#!/usr/bin/env python3
"""国内环境部署：通过 Jenkins API 将所有或指定 k8s 服务部署到指定环境和分支。

不带参数运行时，在终端选择环境、多个服务和共同分支；--gui 才打开窗口。
命令行参数模式默认仅预检；交互模式展示计划并明确确认后才会触发构建。
密码只从环境变量或交互输入读取，不写入代码、日志或命令输出。
"""

import argparse
import getpass
import os
import queue
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError, as_completed
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import quote
from xml.etree import ElementTree as ET

import requests

DEFAULT_URL = "http://jk-tx.jryghq.com"
DEFAULT_USERNAME = "dongyongqi"
DEFAULT_BRANCH = "origin/master"
DEFAULT_VERSION = "master"
ENV_CHOICES = (
    "dev", "test", "test1", "test2", "test3", "test4", "test5",
    "test6", "test7", "test8", "test9", "test10", "pre", "pre-robotaxi",
)


@dataclass(frozen=True)
class JenkinsJob:
    name: str
    url: str
    parameters: Dict[str, str]
    choices: Dict[str, Tuple[str, ...]]


class JenkinsError(RuntimeError):
    pass


class SelectionCancelled(Exception):
    pass


def normalize_branch(value: str) -> str:
    branch = value.strip()
    if not branch or any(char.isspace() for char in branch):
        raise ValueError("--branch 不能为空或包含空白字符")
    if branch.startswith(("origin/", "*/")):
        return branch
    return "origin/" + branch


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="国内环境部署（无参数默认终端选择；参数模式默认只预检）")
    parser.add_argument("--url", default=DEFAULT_URL, help="Jenkins 地址")
    parser.add_argument("--username", default=os.getenv("JRYG_JENKINS_USER", DEFAULT_USERNAME))
    parser.add_argument("--password", default=os.getenv("JRYG_JENKINS_PASSWORD"),
                        help="不建议直接传入；优先使用 JRYG_JENKINS_PASSWORD")
    parser.add_argument("--env", choices=ENV_CHOICES, help="目标部署环境；交互模式可在终端选择")
    parser.add_argument("--branch", default=DEFAULT_BRANCH,
                        help="目标Git分支，如 master、release/x 或 origin/release/x")
    parser.add_argument("--version", default=DEFAULT_VERSION,
                        help="部署版本VER；非多版本部署通常保持master")
    parser.add_argument("--include", default=r"^k8s_",
                        help="服务名包含规则（正则）；可用于只部署特定服务")
    parser.add_argument("--exclude", help="服务名排除规则（正则）")
    parser.add_argument("--limit", type=int, help="仅处理前 N 个服务，用于调试")
    parser.add_argument("--delay", type=float, default=0.5, help="触发服务之间的间隔秒数")
    parser.add_argument("--execute", action="store_true", help="真正触发部署；缺省仅预检")
    parser.add_argument("--yes", action="store_true", help="跳过交互确认，适用于受控 CI")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--gui", action="store_true", help="显式打开图形界面")
    modes.add_argument("--interactive", action="store_true", help="在终端选择环境、多个服务和共同分支")
    return parser.parse_args(argv)


def saved_password(base_url: str, username: str) -> Optional[str]:
    environment_password = os.getenv("JRYG_JENKINS_PASSWORD")
    if environment_password:
        return environment_password
    if sys.platform != "darwin":
        return None
    service = "jryg-deploy:" + base_url.rstrip("/")
    try:
        result = subprocess.run(
            ["/usr/bin/security", "find-generic-password", "-a", username,
             "-s", service, "-w"],
            capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise JenkinsError("无法读取macOS钥匙串，请检查钥匙串是否已解锁") from None
    if result.returncode == 44:
        return None
    if result.returncode != 0:
        raise JenkinsError("钥匙串访问未获授权，请在系统提示中允许读取部署凭据")
    return result.stdout.removesuffix("\n") or None


def login_password(base_url: str, username: str, explicit: Optional[str] = None) -> str:
    password = explicit or saved_password(base_url, username)
    if not password:
        password = getpass.getpass("Jenkins密码（隐藏输入）：")
    if not password:
        raise JenkinsError("Jenkins密码不能为空")
    return password


def build_session(base_url: str, username: str, password: str) -> requests.Session:
    session = requests.Session()
    session.auth = (username, password)
    session.headers.update({"Accept": "application/json", "User-Agent": "jryg-master-deployer/1.0"})
    response = session.get(base_url.rstrip("/") + "/api/json",
                           params={"tree": "mode"}, timeout=(5, 15))
    if response.status_code == 401 or "/login" in response.url:
        session.close()
        raise JenkinsError("Jenkins 账号或密码错误")
    if response.status_code == 403:
        session.close()
        raise JenkinsError("当前Jenkins账号无读取权限")
    response.raise_for_status()
    response.json()
    return session


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parameter_definitions(config_xml: bytes) -> Tuple[Dict[str, str], Dict[str, Tuple[str, ...]]]:
    root = ET.fromstring(config_xml)
    parameters: Dict[str, str] = {}
    parameter_choices: Dict[str, Tuple[str, ...]] = {}
    for node in root.iter():
        if not local_name(node.tag).endswith("ParameterDefinition"):
            continue
        children = {local_name(child.tag): (child.text or "").strip() for child in node}
        name = children.get("name")
        if not name:
            continue
        choices = tuple((choice.text or "").strip() for choice in node.findall(".//string")
                        if (choice.text or "").strip())
        default = children.get("defaultValue", "")
        if not default and choices:
            default = choices[0]
        parameters[name] = default
        if choices:
            parameter_choices[name] = choices
    return parameters, parameter_choices


def discover_jobs(session: requests.Session, base_url: str, include: str,
                  exclude: Optional[str], limit: Optional[int],
                  progress: Optional[Callable[[str], None]] = None,
                  on_job: Optional[Callable[[JenkinsJob], None]] = None,
                  on_error: Optional[Callable[[str], None]] = None) -> List[JenkinsJob]:
    response = session.get(
        base_url.rstrip("/") + "/api/json",
        params={"tree": "jobs[name,url,buildable]"},
        timeout=(5, 15),
    )
    response.raise_for_status()
    include_re = re.compile(include)
    exclude_re = re.compile(exclude) if exclude else None
    selected = [job for job in response.json().get("jobs", [])
                if job.get("buildable", True)
                and include_re.search(job["name"])
                and not (exclude_re and exclude_re.search(job["name"]))]
    selected.sort(key=lambda item: item["name"])
    if limit is not None:
        if limit <= 0:
            raise ValueError("--limit 必须为正整数")
        selected = selected[:limit]
    if not selected:
        raise JenkinsError("没有匹配到可构建服务")
    if progress:
        progress(f"已发现 {len(selected)} 个作业，开始并发读取配置：0/{len(selected)}")

    def read_config(item: Dict[str, str]) -> JenkinsJob:
        with requests.Session() as client:
            client.auth = session.auth
            client.headers.update(session.headers)
            client.cookies.update(session.cookies)
            client.proxies.update(session.proxies)
            client.verify = session.verify
            client.cert = session.cert
            client.trust_env = session.trust_env
            config = client.get(item["url"] + "config.xml", timeout=(5, 15))
            config.raise_for_status()
            parameters, choices = parameter_definitions(config.content)
            return JenkinsJob(item["name"], item["url"], parameters, choices)

    jobs: List[JenkinsJob] = []
    errors: List[str] = []
    pool = ThreadPoolExecutor(max_workers=6)
    futures = {pool.submit(read_config, item): item["name"] for item in selected}
    try:
        for completed, future in enumerate(as_completed(futures, timeout=90), 1):
            name = futures[future]
            try:
                job = future.result()
            except (requests.RequestException, ET.ParseError, ValueError) as exc:
                reason = f"{name} 配置读取失败：{exc}"
                errors.append(reason)
                if on_error:
                    on_error(reason)
            else:
                jobs.append(job)
                if on_job:
                    on_job(job)
            if progress:
                progress(f"读取配置 {completed}/{len(selected)}：{name}")
    except FutureTimeoutError:
        reason = "服务配置加载超过90秒，未完成的作业不可选择；请检查网络后重新加载"
        errors.append(reason)
        if on_error:
            on_error(reason)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    if errors and on_error is None:
        raise JenkinsError("\n".join(errors))
    if not jobs:
        raise JenkinsError("没有读取到可用服务配置，请检查网络和账号权限")
    return sorted(jobs, key=lambda job: job.name)


def deployment_parameters(job: JenkinsJob, environment: str, branch: str,
                          version: str) -> Dict[str, str]:
    params = dict(job.parameters)
    missing = [name for name in ("ENV", "BRANCH") if name not in params]
    if missing:
        raise JenkinsError(f"{job.name} 缺少参数 {missing}，不是标准分支部署服务")
    allowed_environments = job.choices.get("ENV", ())
    if allowed_environments and environment not in allowed_environments:
        raise JenkinsError(
            f"{job.name} 不支持环境 {environment}，允许值={','.join(allowed_environments)}")
    params["ENV"] = environment
    params["BRANCH"] = branch
    if "VER" in params:
        params["VER"] = version
    if "multiVersion" in params:
        params["multiVersion"] = "no"
    return params


def add_crumb(session: requests.Session, base_url: str) -> None:
    response = session.get(base_url.rstrip("/") + "/crumbIssuer/api/json", timeout=20)
    if response.status_code == 404:
        return
    response.raise_for_status()
    data = response.json()
    session.headers[data["crumbRequestField"]] = data["crumb"]


def trigger(session: requests.Session, job: JenkinsJob, params: Dict[str, str]) -> Optional[str]:
    response = session.post(job.url + "buildWithParameters", data=params,
                            allow_redirects=False, timeout=30)
    if response.status_code not in (201, 202, 302):
        raise JenkinsError(f"{job.name} 触发失败：HTTP {response.status_code} {response.text[:200]}")
    return response.headers.get("Location")


def fetch_job_branches(session: requests.Session, job: JenkinsJob) -> Tuple[str, ...]:
    endpoint = (job.url + "descriptorByName/net.uaznia.lukanus.hudson.plugins.gitparameter."
                "GitParameterDefinition/fillValueItems")
    response = session.post(endpoint, params={"param": "BRANCH"}, timeout=30)
    response.raise_for_status()
    values = response.json().get("values", [])
    branches = {str(item.get("value") or item.get("name") or "").strip() for item in values}
    branches.discard("")
    if not branches:
        raise JenkinsError(f"{job.name} 没有返回可选分支")
    return tuple(sorted(branches, key=lambda value: (value != DEFAULT_BRANCH, value.lower())))


def common_job_branches(session: requests.Session, jobs: Sequence[JenkinsJob],
                        progress: Optional[Callable[[str], None]] = None) -> Tuple[str, ...]:
    common: Optional[set] = None
    for index, job in enumerate(jobs, 1):
        if progress:
            progress(f"读取分支 {index}/{len(jobs)}：{job.name}")
        branches = set(fetch_job_branches(session, job))
        common = branches if common is None else common.intersection(branches)
        if not common:
            break
    if not common:
        raise JenkinsError("所选服务没有共同分支，请减少服务或重新选择")
    return tuple(sorted(common, key=lambda value: (value != DEFAULT_BRANCH, value.lower())))


def print_plan(plan: Iterable[Tuple[JenkinsJob, Dict[str, str]]]) -> None:
    for index, (job, params) in enumerate(plan, 1):
        version = params.get("VER", "<作业无VER参数>")
        print(f"{index:03d}. {job.name}: ENV={params['ENV']} BRANCH={params['BRANCH']} VER={version}")


def confirm(environment: str, branch: str, count: int) -> bool:
    print(f"\n即将部署 {count} 个服务：ENV={environment} BRANCH={branch}")
    return input("执行部署？[y/N]：").strip().lower() in ("y", "yes")


class DeploymentApp:
    def __init__(self, base_url: str, username: str, initial_env: Optional[str] = None):
        os.environ.setdefault("TK_SILENCE_DEPRECATION", "1")
        import tkinter as tk
        from tkinter import messagebox, simpledialog, ttk

        self.tk = tk
        self.ttk = ttk
        self.messagebox = messagebox
        self.simpledialog = simpledialog
        self.base_url = base_url.rstrip("/")
        self.session: Optional[requests.Session] = None
        self.jobs: List[JenkinsJob] = []
        self.visible_jobs: List[JenkinsJob] = []
        self.busy = False
        self._events = queue.SimpleQueue()
        self._closed = False
        self._generation = 0

        self.root = tk.Tk()
        self.root.title("国内环境部署")
        self.root.geometry("960x720")
        self.root.minsize(820, 620)
        self.root.configure(bg="#f4f6fa")

        self.username = tk.StringVar(value=username)
        self.password = tk.StringVar(value=os.getenv("JRYG_JENKINS_PASSWORD", ""))
        self.environment = tk.StringVar(value=initial_env or ENV_CHOICES[0])
        self.branch = tk.StringVar(value="")
        self.service_filter = tk.StringVar(value="")
        self.status = tk.StringVar(value="请先选择环境并加载服务")
        self._configure_style()
        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        self.root.after(100, self._poll_events)

    def _configure_style(self) -> None:
        style = self.ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("Title.TLabel", background="#f4f6fa", foreground="#172033",
                        font=("PingFang SC", 22, "bold"))
        style.configure("Sub.TLabel", background="#f4f6fa", foreground="#697386",
                        font=("PingFang SC", 11))
        style.configure("Card.TFrame", background="#ffffff")
        style.configure("Card.TLabel", background="#ffffff", foreground="#263043")
        style.configure("Primary.TButton", foreground="#ffffff", background="#315efb",
                        font=("PingFang SC", 11, "bold"), padding=(16, 9))
        style.map("Primary.TButton", background=[("active", "#244bd7"), ("disabled", "#9ba9d0")])
        style.configure("Action.TButton", padding=(12, 7))

    def _build_ui(self) -> None:
        tk, ttk = self.tk, self.ttk
        outer = ttk.Frame(self.root, padding=24)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="国内环境部署", style="Title.TLabel").pack(anchor="w")
        ttk.Label(outer, text="选择多个服务后，从弹窗选择一个共同分支进行部署。",
                  style="Sub.TLabel").pack(anchor="w", pady=(3, 18))

        card = ttk.Frame(outer, style="Card.TFrame", padding=18)
        card.pack(fill="both", expand=True)
        for column in (1, 3, 5):
            card.columnconfigure(column, weight=1)
        card.rowconfigure(3, weight=1)

        ttk.Label(card, text="账号", style="Card.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Entry(card, textvariable=self.username, width=18).grid(row=0, column=1, sticky="ew", padx=(8, 18))
        ttk.Label(card, text="密码", style="Card.TLabel").grid(row=0, column=2, sticky="w")
        ttk.Entry(card, textvariable=self.password, show="●", width=18).grid(row=0, column=3, sticky="ew", padx=(8, 18))
        ttk.Label(card, text="环境", style="Card.TLabel").grid(row=0, column=4, sticky="w")
        env = ttk.Combobox(card, textvariable=self.environment, values=ENV_CHOICES,
                           state="readonly", width=14)
        env.grid(row=0, column=5, sticky="ew", padx=(8, 0))
        env.bind("<<ComboboxSelected>>", lambda _event: self._environment_changed())

        controls = ttk.Frame(card, style="Card.TFrame")
        controls.grid(row=1, column=0, columnspan=6, sticky="ew", pady=(16, 10))
        ttk.Button(controls, text="加载服务", style="Primary.TButton",
                   command=self.load_services).pack(side="left")
        ttk.Button(controls, text="全选", style="Action.TButton",
                   command=self.select_all).pack(side="left", padx=(10, 0))
        ttk.Button(controls, text="清空", style="Action.TButton",
                   command=self.clear_selection).pack(side="left", padx=(8, 0))
        ttk.Label(controls, text="搜索服务", style="Card.TLabel").pack(side="left", padx=(22, 8))
        search = ttk.Entry(controls, textvariable=self.service_filter, width=28)
        search.pack(side="left", fill="x", expand=True)
        search.bind("<KeyRelease>", lambda _event: self._refresh_services())

        ttk.Label(card, text="服务（可按 Command/Shift 多选）", style="Card.TLabel").grid(
            row=2, column=0, columnspan=3, sticky="w")
        ttk.Label(card, text="统一部署分支", style="Card.TLabel").grid(
            row=2, column=3, columnspan=3, sticky="w", padx=(18, 0))

        service_frame = ttk.Frame(card, style="Card.TFrame")
        service_frame.grid(row=3, column=0, columnspan=3, sticky="nsew", pady=(8, 0))
        service_frame.rowconfigure(0, weight=1)
        service_frame.columnconfigure(0, weight=1)
        self.service_list = tk.Listbox(service_frame, selectmode=tk.EXTENDED, exportselection=False,
                                       activestyle="none", font=("Menlo", 11), borderwidth=1,
                                       relief="solid", selectbackground="#315efb")
        self.service_list.grid(row=0, column=0, sticky="nsew")
        service_scroll = ttk.Scrollbar(service_frame, orient="vertical", command=self.service_list.yview)
        service_scroll.grid(row=0, column=1, sticky="ns")
        self.service_list.configure(yscrollcommand=service_scroll.set)

        right = ttk.Frame(card, style="Card.TFrame")
        right.grid(row=3, column=3, columnspan=3, sticky="nsew", padx=(18, 0), pady=(8, 0))
        right.columnconfigure(0, weight=1)
        branch_row = ttk.Frame(right, style="Card.TFrame")
        branch_row.pack(fill="x")
        ttk.Entry(branch_row, textvariable=self.branch, state="readonly").pack(side="left", fill="x", expand=True)
        ttk.Button(branch_row, text="弹出分支", style="Primary.TButton",
                   command=self.choose_branch).pack(side="left", padx=(10, 0))

        ttk.Label(right, text="部署计划", style="Card.TLabel").pack(anchor="w", pady=(18, 7))
        self.plan_text = tk.Text(right, height=14, wrap="none", state="disabled",
                                 font=("Menlo", 10), bg="#f8fafc", fg="#263043",
                                 borderwidth=1, relief="solid")
        self.plan_text.pack(fill="both", expand=True)
        actions = ttk.Frame(right, style="Card.TFrame")
        actions.pack(fill="x", pady=(12, 0))
        ttk.Button(actions, text="生成预检计划", style="Action.TButton",
                   command=self.preview).pack(side="left")
        self.deploy_button = ttk.Button(actions, text="确认部署", style="Primary.TButton",
                                        command=self.deploy)
        self.deploy_button.pack(side="right")

        footer = ttk.Frame(outer)
        footer.pack(fill="x", pady=(12, 0))
        self.load_progress = ttk.Progressbar(footer, mode="indeterminate")
        self.load_progress.pack(fill="x", pady=(0, 6))
        ttk.Label(footer, textvariable=self.status, style="Sub.TLabel").pack(side="left")
        ttk.Label(footer, text="只有点击“确认部署”并二次确认后才会触发 Jenkins",
                  style="Sub.TLabel").pack(side="right")

    def _post(self, callback: Callable[[], None], generation: int) -> None:
        self._events.put((generation, callback))

    def _poll_events(self) -> None:
        if self._closed:
            return
        try:
            for _index in range(200):
                generation, callback = self._events.get_nowait()
                if generation == self._generation:
                    callback()
        except queue.Empty:
            pass
        if not self._closed:
            self.root.after(100, self._poll_events)

    def _close(self) -> None:
        self._closed = True
        self._generation += 1
        self.root.destroy()

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        pending = [self.root]
        while pending:
            widget = pending.pop()
            pending.extend(widget.winfo_children())
            if isinstance(widget, (self.ttk.Button, self.ttk.Entry, self.ttk.Combobox)):
                widget.state(["disabled" if busy else "!disabled"])
        self.service_list.configure(state="disabled" if busy else "normal")
        if busy:
            self.load_progress.start(15)
        else:
            self.load_progress.stop()

    def _run_background(self, work: Callable[[], object], done: Callable[[object], None]) -> None:
        if self.busy or self._closed:
            return
        generation = self._generation
        self._set_busy(True)

        def runner() -> None:
            try:
                result = work()
            except Exception as exc:
                self._post(lambda error=exc: self._background_failed(error), generation)
            else:
                self._post(lambda value=result: self._background_done(value, done), generation)

        threading.Thread(target=runner, daemon=True).start()

    def _background_done(self, result: object, done: Callable[[object], None]) -> None:
        self._set_busy(False)
        done(result)

    def _background_failed(self, exc: Exception) -> None:
        self._set_busy(False)
        self.status.set("操作失败，可重新加载")
        self._set_plan(str(exc))
        self.messagebox.showerror("操作失败", str(exc), parent=self.root)

    def _credentials(self) -> Tuple[str, str]:
        username = self.username.get().strip()
        if not username:
            raise JenkinsError("请输入Jenkins账号")
        password = self.password.get() or saved_password(self.base_url, username)
        if not password:
            raise JenkinsError("没有已保存凭据，请输入Jenkins密码")
        self.password.set(password)
        return username, password

    def load_services(self) -> None:
        if self.busy:
            return
        try:
            username, password = self._credentials()
        except JenkinsError as exc:
            self.messagebox.showwarning("缺少登录信息", str(exc), parent=self.root)
            return
        environment = self.environment.get()
        self._generation += 1
        generation = self._generation
        self.session = None
        self.jobs = []
        self.branch.set("")
        self._refresh_services()
        self._set_plan("")
        self.status.set("正在验证Jenkins账号…")
        started = time.monotonic()

        def progress(text: str) -> None:
            self._post(lambda value=text: self.status.set(value), generation)

        def on_job(job: JenkinsJob) -> None:
            try:
                deployment_parameters(job, environment, DEFAULT_BRANCH, DEFAULT_VERSION)
            except JenkinsError:
                return

            def display() -> None:
                self.jobs.append(job)
                self.jobs.sort(key=lambda item: item.name)
                self._refresh_services()

            self._post(display, generation)

        def work() -> object:
            session = build_session(self.base_url, username, password)
            errors: List[str] = []
            try:
                jobs = discover_jobs(session, self.base_url, r"^(k8s_|test_h5_dcms$)",
                                     None, None, progress, on_job, errors.append)
            except Exception:
                session.close()
                raise
            available = []
            for job in jobs:
                try:
                    deployment_parameters(job, environment, DEFAULT_BRANCH, DEFAULT_VERSION)
                except JenkinsError:
                    continue
                available.append(job)
            return session, available, errors

        def done(result: object) -> None:
            session, jobs, errors = result
            self.session = session
            self.jobs = jobs
            self._refresh_services()
            elapsed = time.monotonic() - started
            self.status.set(f"已加载 {len(jobs)} 个支持 {environment} 的服务，用时 {elapsed:.1f} 秒")
            if errors:
                self._set_plan("以下配置未加载，相关服务不可选择：\n" + "\n".join(errors))
            elif not jobs:
                self._set_plan(f"没有支持 {environment} 的服务，请更换环境")

        self._run_background(work, done)

    def _environment_changed(self) -> None:
        self._generation += 1
        self._set_busy(False)
        self.session = None
        self.jobs = []
        self.visible_jobs = []
        self.branch.set("")
        self.service_list.delete(0, self.tk.END)
        self._set_plan("")
        self.status.set("环境已变更，请重新加载服务")

    def _refresh_services(self) -> None:
        query = self.service_filter.get().strip().lower()
        self.visible_jobs = [job for job in self.jobs if query in job.name.lower()]
        self.service_list.delete(0, self.tk.END)
        for job in self.visible_jobs:
            self.service_list.insert(self.tk.END, job.name)

    def select_all(self) -> None:
        self.service_list.selection_set(0, self.tk.END)

    def clear_selection(self) -> None:
        self.service_list.selection_clear(0, self.tk.END)
        self.branch.set("")
        self._set_plan("")

    def _selected_jobs(self) -> List[JenkinsJob]:
        return [self.visible_jobs[index] for index in self.service_list.curselection()]

    def choose_branch(self) -> None:
        if self.busy:
            return
        jobs = self._selected_jobs()
        if not jobs:
            self.messagebox.showwarning("未选择服务", "请先选择一个或多个服务", parent=self.root)
            return
        if self.session is None:
            self.messagebox.showwarning("服务未加载", "请先点击“加载服务”", parent=self.root)
            return
        self.status.set(f"正在读取 {len(jobs)} 个服务的共同分支…")
        generation = self._generation
        session = self.session

        def progress(text: str) -> None:
            self._post(lambda value=text: self.status.set(value), generation)

        def work() -> object:
            add_crumb(session, self.base_url)
            return common_job_branches(session, jobs, progress)

        def done(result: object) -> None:
            branches = result
            self.status.set(f"找到 {len(branches)} 个共同分支")
            self._show_branch_dialog(branches)

        self._run_background(work, done)

    def _show_branch_dialog(self, branches: Sequence[str]) -> None:
        tk, ttk = self.tk, self.ttk
        dialog = tk.Toplevel(self.root)
        dialog.title("选择共同分支")
        dialog.geometry("620x520")
        dialog.transient(self.root)
        dialog.grab_set()
        frame = ttk.Frame(dialog, padding=18)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="选择一个分支用于全部已选服务",
                  font=("PingFang SC", 15, "bold")).pack(anchor="w")
        query = tk.StringVar()
        search = ttk.Entry(frame, textvariable=query)
        search.pack(fill="x", pady=(12, 8))
        listbox = tk.Listbox(frame, selectmode=tk.SINGLE, exportselection=False,
                             font=("Menlo", 11), activestyle="none",
                             selectbackground="#315efb")
        listbox.pack(fill="both", expand=True)

        def refresh(*_args: object) -> None:
            keyword = query.get().strip().lower()
            listbox.delete(0, tk.END)
            for branch in branches:
                if keyword in branch.lower():
                    listbox.insert(tk.END, branch)
            if listbox.size():
                listbox.selection_set(0)

        def apply(*_args: object) -> None:
            selected = listbox.curselection()
            if not selected:
                return
            self.branch.set(listbox.get(selected[0]))
            dialog.destroy()
            self.preview()

        query.trace_add("write", refresh)
        listbox.bind("<Double-Button-1>", apply)
        search.bind("<Return>", apply)
        ttk.Button(frame, text="使用此分支", style="Primary.TButton",
                   command=apply).pack(anchor="e", pady=(12, 0))
        refresh()
        search.focus_set()

    def _build_selected_plan(self) -> List[Tuple[JenkinsJob, Dict[str, str]]]:
        jobs = self._selected_jobs()
        branch = self.branch.get().strip()
        if not jobs:
            raise JenkinsError("请至少选择一个服务")
        if not branch:
            raise JenkinsError("请点击“弹出分支”选择一个共同分支")
        return [(job, deployment_parameters(job, self.environment.get(), branch, DEFAULT_VERSION))
                for job in jobs]

    def _set_plan(self, content: str) -> None:
        self.plan_text.configure(state="normal")
        self.plan_text.delete("1.0", self.tk.END)
        self.plan_text.insert("1.0", content)
        self.plan_text.configure(state="disabled")

    def preview(self) -> None:
        try:
            plan = self._build_selected_plan()
        except JenkinsError as exc:
            self.messagebox.showwarning("无法生成计划", str(exc), parent=self.root)
            return
        lines = [f"环境：{self.environment.get()}", f"分支：{self.branch.get()}",
                 f"服务数：{len(plan)}", "", "服务列表："]
        lines.extend(f"{index:03d}. {job.name}" for index, (job, _params) in enumerate(plan, 1))
        self._set_plan("\n".join(lines))
        self.status.set("预检计划已生成，尚未触发部署")

    def deploy(self) -> None:
        if self.busy:
            return
        if self.session is None:
            self.messagebox.showwarning("服务未加载", "请先加载服务", parent=self.root)
            return
        try:
            plan = self._build_selected_plan()
        except JenkinsError as exc:
            self.messagebox.showwarning("无法部署", str(exc), parent=self.root)
            return
        environment, branch = self.environment.get(), self.branch.get()
        if not self.messagebox.askyesno(
                "确认部署",
                f"即将把 {len(plan)} 个服务部署到：\n\n环境：{environment}\n分支：{branch}\n\n是否继续？",
                icon="warning", parent=self.root):
            return
        expected = f"{environment} {branch}"
        actual = self.simpledialog.askstring(
            "二次确认", f"请输入以下内容确认：\n{expected}", parent=self.root)
        if actual != expected:
            self.messagebox.showinfo("已取消", "确认内容不匹配，未触发任何部署", parent=self.root)
            return
        self.status.set("正在触发Jenkins部署…")
        session = self.session

        def work() -> object:
            add_crumb(session, self.base_url)
            successes, failures = [], []
            for job, params in plan:
                try:
                    successes.append((job.name, trigger(session, job, params)))
                except Exception as exc:
                    failures.append((job.name, str(exc)))
                time.sleep(0.5)
            return successes, failures

        def done(result: object) -> None:
            successes, failures = result
            lines = [f"已触发：{len(successes)}", f"失败：{len(failures)}", ""]
            lines.extend(f"成功  {name}" for name, _queue in successes)
            lines.extend(f"失败  {name}: {reason}" for name, reason in failures)
            self._set_plan("\n".join(lines))
            self.status.set(f"部署触发完成：成功 {len(successes)}，失败 {len(failures)}")
            if failures:
                self.messagebox.showwarning("部分服务失败", "请查看部署结果中的失败服务", parent=self.root)
            else:
                self.messagebox.showinfo("部署已触发", f"已触发 {len(successes)} 个服务", parent=self.root)

        self._run_background(work, done)

    def run(self) -> None:
        self.root.mainloop()


def run_gui(base_url: str = DEFAULT_URL, username: str = DEFAULT_USERNAME,
            initial_env: Optional[str] = None) -> None:
    DeploymentApp(base_url, username, initial_env).run()


def parse_terminal_selection(text: str, values: Sequence[str], multiple: bool = False,
                             kind: str = "") -> List[str]:
    tokens = re.split(r"[,，、\s]+", text.strip())
    if not text.strip():
        raise ValueError("请选择，不能留空")
    if text.strip().lower() == "all" and multiple:
        return list(values)
    selected: List[str] = []
    aliases = {"passenger-api": "k8s_passenger", "dcms": "test_h5_dcms"}
    for token in tokens:
        if not token:
            continue
        if token.isdigit():
            indexes = [int(token)]
        elif multiple and re.fullmatch(r"\d+-\d+", token):
            start, end = map(int, token.split("-"))
            if not 1 <= start <= end <= len(values):
                raise ValueError(f"编号范围无效：{token}")
            indexes = list(range(start, end + 1))
        else:
            candidate = token
            if kind == "service" and candidate not in values:
                candidate = aliases.get(token, "k8s_" + token)
            elif kind == "branch" and candidate not in values:
                candidate = normalize_branch(token)
            if candidate not in values:
                raise ValueError(f"不在可选列表中：{token}")
            indexes = [values.index(candidate) + 1]
        for index in indexes:
            if not 1 <= index <= len(values):
                raise ValueError(f"编号超出范围：{index}")
            if values[index - 1] not in selected:
                selected.append(values[index - 1])
    if not selected or (not multiple and len(selected) != 1):
        raise ValueError("请选择一个选项" if not multiple else "请至少选择一个服务")
    return selected


def select_in_terminal(title: str, values: Sequence[str], multiple: bool = False,
                       kind: str = "") -> List[str]:
    if not values:
        raise JenkinsError(f"{title}没有可选项")
    keyword = ""
    while True:
        print(f"\n{title}")
        for index, value in enumerate(values, 1):
            if keyword.lower() in value.lower():
                print(f"{index:03d}. {value}")
        extra = "，可输入多个编号/名称、1-3或all全选" if multiple else ""
        print(f"输入编号或名称{extra}；/关键词筛选，/恢复全部，q退出")
        text = input("请选择：").strip()
        if text.lower() == "q":
            raise SelectionCancelled()
        if text.startswith("/"):
            keyword = text[1:]
            continue
        try:
            return parse_terminal_selection(text, values, multiple, kind)
        except ValueError as exc:
            print(f"选择无效：{exc}")


def select_services_in_terminal(values: Sequence[str],
                                initial: Sequence[str] = ()) -> List[str]:
    if not values:
        raise JenkinsError("当前环境没有可选服务")
    selected = [value for value in dict.fromkeys(initial) if value in values]
    keyword = ""
    while True:
        visible = [value for value in values if keyword.lower() in value.lower()]
        heading = f"搜索结果：{keyword}" if keyword else "全部服务列表"
        print(f"\n{heading}（{len(visible)} 个；编号始终对应完整列表）")
        for index, value in enumerate(values, 1):
            if value in visible:
                mark = "已选" if value in selected else "    "
                print(f"{index:03d}. [{mark}] {value}")
        print(f"已选 {len(selected)} 个：{', '.join(selected) or '无'}")
        print("输入关键词搜索，如 passenger；编号/完整名称多选，如 1,3 或 1-3；all选当前列表")
        print("选中后自动返回全部列表；done或回车完成；remove 编号移除；clear清空；/返回全部；q退出")
        text = input("选择服务：").strip()
        command = text.lower()
        if command == "q":
            raise SelectionCancelled()
        if command in ("", "done"):
            if selected:
                return selected
            print("请至少选择一个服务后再继续")
            continue
        if command == "clear":
            selected.clear()
            keyword = ""
            continue
        if command in ("/", "back", "b"):
            keyword = ""
            continue
        if command.startswith("remove "):
            try:
                removed = parse_terminal_selection(text[7:], values, True, "service")
            except ValueError as exc:
                print(f"移除无效：{exc}")
                continue
            selected = [value for value in selected if value not in removed]
            keyword = ""
            continue
        if text.startswith("/"):
            keyword = text[1:]
            continue
        tokens = [token for token in re.split(r"[,，、\s]+", text) if token]
        if (len(tokens) == 1 and command != "all" and text not in values
                and re.fullmatch(r"\d+(?:-\d+)?", text) is None):
            keyword = text
            if not any(keyword.lower() in value.lower() for value in values):
                print(f"没有匹配“{keyword}”的服务，请重新搜索或输入 / 返回全部")
            continue
        try:
            additions = list(visible) if command == "all" else parse_terminal_selection(
                text, values, True, "service")
            if not additions:
                raise ValueError("当前搜索结果为空")
            if any(value not in visible for value in additions):
                raise ValueError("请输入当前搜索结果中显示的编号，或输入 / 返回全部列表")
        except ValueError as exc:
            print(f"选择无效：{exc}")
            continue
        for value in additions:
            if value not in selected:
                selected.append(value)
        print(f"已添加 {len(additions)} 个服务，返回全部列表；输入 done 继续选择分支")
        keyword = ""


def execute_plan(session: requests.Session, base_url: str,
                 plan: Sequence[Tuple[JenkinsJob, Dict[str, str]]], delay: float) -> int:
    add_crumb(session, base_url)
    failures: List[str] = []
    for index, (job, params) in enumerate(plan, 1):
        try:
            queue_url = trigger(session, job, params)
            suffix = f"，队列={queue_url}" if queue_url else ""
            print(f"[{index}/{len(plan)}] 已触发 {job.name}{suffix}")
        except Exception as exc:
            failures.append(f"{job.name}: {exc}")
            print(f"[{index}/{len(plan)}] 失败 {job.name}: {exc}", file=sys.stderr)
        if index < len(plan) and delay > 0:
            time.sleep(delay)
    if failures:
        print("\n以下服务触发失败：", file=sys.stderr)
        for failure in failures:
            print("- " + failure, file=sys.stderr)
        return 1
    print(f"\n已触发 {len(plan)} 个服务部署。请在 Jenkins 中检查各构建结果。")
    return 0


def run_terminal(args: argparse.Namespace) -> int:
    print("国内环境部署 · 终端选择（不会打开窗口）")
    environment = args.env or select_in_terminal("选择部署环境", ENV_CHOICES)[0]
    username = args.username
    base_url = args.url.rstrip("/")
    password = login_password(base_url, username, args.password)
    print(f"使用Jenkins账号：{username}（更换账号可使用 --username）")
    with build_session(base_url, username, password) as session:
        print(f"\n正在加载支持 {environment} 的服务…", flush=True)

        def progress(text: str) -> None:
            print("\r" + text.ljust(110), end="", flush=True)

        errors: List[str] = []
        include = r"^(k8s_|test_h5_dcms$)" if args.include == r"^k8s_" else args.include
        jobs = discover_jobs(session, base_url, include, args.exclude, args.limit,
                             progress=progress, on_error=errors.append)
        print()
        available: Dict[str, JenkinsJob] = {}
        for job in jobs:
            try:
                deployment_parameters(job, environment, DEFAULT_BRANCH, args.version)
            except JenkinsError:
                continue
            available[job.name] = job
        print(f"已加载 {len(available)} 个支持 {environment} 的服务")
        for reason in errors:
            print("未加载：" + reason)
        names: List[str] = []
        while True:
            names = select_services_in_terminal(tuple(available), names)
            selected_jobs = [available[name] for name in names]
            add_crumb(session, base_url)
            try:
                branches = common_job_branches(session, selected_jobs, print)
            except JenkinsError as exc:
                print(f"无法选择共同分支：{exc}；请重新选择服务")
                continue
            break
        branch = select_in_terminal("选择全部已选服务的共同分支", branches, kind="branch")[0]
        plan = [(job, deployment_parameters(job, environment, branch, args.version))
                for job in selected_jobs]
        print("\n部署计划（尚未触发部署）：")
        print_plan(plan)
        if not confirm(environment, branch, len(plan)):
            print("预检结束，未触发任何部署。")
            return 0
        return execute_plan(session, base_url, plan, args.delay)


def main(argv: Optional[Sequence[str]] = None) -> int:
    raw_args = list(sys.argv[1:] if argv is None else argv)
    args = parse_args(raw_args)
    if args.gui:
        run_gui(args.url, args.username, args.env)
        return 0
    if args.interactive or not raw_args:
        return run_terminal(args)
    if not args.env:
        raise JenkinsError("参数模式必须提供 --env；不带参数运行或加 --interactive 可在终端选择")
    args.branch = normalize_branch(args.branch)
    base_url = args.url.rstrip("/")
    password = login_password(base_url, args.username, args.password)
    session = build_session(base_url, args.username, password)
    jobs = discover_jobs(session, base_url, args.include, args.exclude, args.limit)
    plan: List[Tuple[JenkinsJob, Dict[str, str]]] = []
    skipped: List[str] = []
    for job in jobs:
        try:
            plan.append((job, deployment_parameters(job, args.env, args.branch, args.version)))
        except JenkinsError as exc:
            skipped.append(str(exc))
    if not plan:
        raise JenkinsError("没有可按指定环境和分支部署的标准服务")
    print_plan(plan)
    if skipped:
        print("\n跳过以下非标准任务：")
        for reason in skipped:
            print("- " + reason)

    if not args.execute:
        print(f"\n预检完成：可部署 {len(plan)} 个服务，跳过 {len(skipped)} 个非标准任务。"
              "未触发任何部署；加 --execute 才会执行。")
        return 0

    if not args.yes and not confirm(args.env, args.branch, len(plan)):
        print("已取消部署，未触发任何构建。")
        return 0
    return execute_plan(session, base_url, plan, args.delay)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (SelectionCancelled, KeyboardInterrupt, EOFError):
        print("\n已退出终端选择；已触发的构建不会自动撤销。")
        raise SystemExit(0)
    except (JenkinsError, requests.RequestException, ValueError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        raise SystemExit(2)
