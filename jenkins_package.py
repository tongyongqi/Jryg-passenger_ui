#!/usr/bin/env python3
"""Jenkins 客户端打包工具。

默认以交互方式选择客户端、Git 分支和打包环境，确认后触发 Jenkins
参数化构建。密码优先从环境变量或 macOS 钥匙串读取，不会写入源码。
可使用 ``--dry-run`` 只检查参数，避免误触发真实构建。
"""

import argparse
import getpass
import os
import subprocess
import sys
import warnings
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple
from urllib.parse import quote, urljoin, urlsplit
from xml.etree import ElementTree as ET

warnings.filterwarnings("ignore", message=r"urllib3 v2 only supports OpenSSL 1\.1\.1\+.*")

import requests

# Jenkins 连接配置。密码不设置默认明文值，只允许通过环境变量或钥匙串获取。
DEFAULT_URL = "http://192.168.70.51:8080"
DEFAULT_USERNAME = "tongyongqi"
PASSWORD_ENV = "JRYG_PACKAGE_JENKINS_PASSWORD"
KEYCHAIN_SERVICE = "JRYG Jenkins Package"

# 交互菜单中的任务顺序；只展示 Jenkins 中实际存在且可构建的任务。
JOB_ORDER = (
    "Android-Driver-Dev",
    "Android-Driver-Intl-Dev",
    "Android-Passenger-Dev",
    "Android-Passenger-Intl-Dev",
    "iOS-Driver-dev",
    "iOS-Driver-HQ-Dev",
    "iOS-Passenger-dev",
    "iOS-Passenger-HQ-Dev",
    "Robotaxi-Control-Dev",
    "Robotaxi-Groundcrew-Dev",
)
# 兼容不同 Jenkins 任务可能使用的分支、环境参数名。
BRANCH_PARAMETER_NAMES = ("GIT_BRANCH", "BRANCH", "GITBRANCH")
ENV_PARAMETER_NAMES = ("BUILD_TYPE", "ENV", "ENVIRONMENT", "BUILD_ENV")

# Jenkins API 未返回选项时使用的环境兜底列表。
BUILD_TYPE_CHOICES = (
    "releaseOffline",
    "releaseOnline",
    "releasePre",
    "releasePreRobotaxi",
    "releaseTest1",
    "releaseTest2",
    "releaseTest3",
    "releaseTest4",
    "releaseTest5",
    "releaseTest6",
    "releaseTest7",
    "releaseTest8",
    "releaseTest9",
    "releaseTest10",
    "releaseTest11",
)
BUILD_TYPE_LABELS = {
    "releaseoffline": "开发",
    "releaseonline": "线上",
    "releasepre": "阿里预发",
    "releaseprerobotaxi": "智驾预发",
}


class JenkinsError(RuntimeError):
    """表示可预期且适合直接展示给用户的 Jenkins 操作错误。"""


@dataclass
class ParameterDefinition:
    """Jenkins 单个构建参数的定义。"""

    name: str  # 参数名，例如 GIT_BRANCH、BUILD_TYPE。
    default: str = ""  # Jenkins 配置的默认值。
    choices: List[str] = field(default_factory=list)  # Choice 参数的可选值。
    kind: str = ""  # Jenkins 返回的参数类型。


@dataclass(frozen=True)
class JenkinsJob:
    """可供用户选择的 Jenkins 打包任务。"""

    name: str  # Jenkins 任务名称。
    url: str  # 已修正为真实服务器主机的任务地址。


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    """解析命令行参数；未传入的任务、分支和环境将在运行时交互选择。"""
    parser = argparse.ArgumentParser(description="选择端、分支和环境，触发 Jenkins 打包")
    parser.add_argument("--url", default=DEFAULT_URL, help="Jenkins 地址")
    parser.add_argument(
        "--username",
        default=os.getenv("JRYG_PACKAGE_JENKINS_USER", DEFAULT_USERNAME),
        help="Jenkins 用户名",
    )
    parser.add_argument(
        "--password",
        default=os.getenv(PASSWORD_ENV),
        help=f"Jenkins 密码；建议使用环境变量 {PASSWORD_ENV}",
    )
    parser.add_argument("--job", help="Jenkins 任务名；不传则交互选择")
    parser.add_argument("--branch", help="Git 分支；不传则交互选择")
    parser.add_argument("--build-type", help="构建环境/BUILD_TYPE；不传则交互选择")
    parser.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="参数=值",
        help="覆盖其他 Jenkins 参数，可重复传入",
    )
    parser.add_argument("--list", action="store_true", help="只列出可用的打包任务")
    parser.add_argument("--dry-run", action="store_true", help="只显示打包参数，不触发构建")
    parser.add_argument("--yes", action="store_true", help="跳过触发前确认")
    return parser.parse_args(argv)


def keychain_password(username: str) -> Optional[str]:
    """从当前用户的 macOS 钥匙串读取 Jenkins 密码。"""
    if sys.platform != "darwin":
        return None
    result = subprocess.run(
        [
            "security",
            "find-generic-password",
            "-a",
            username,
            "-s",
            KEYCHAIN_SERVICE,
            "-w",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    password = result.stdout.strip()
    return password if result.returncode == 0 and password else None


def save_keychain_password(username: str, password: str) -> None:
    """将验证成功的 Jenkins 密码更新到 macOS 钥匙串。"""
    if sys.platform != "darwin":
        return
    result = subprocess.run(
        [
            "security",
            "add-generic-password",
            "-U",
            "-a",
            username,
            "-s",
            KEYCHAIN_SERVICE,
            "-w",
            password,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise JenkinsError("密码已验证，但保存到 macOS 钥匙串失败")


def normalize_jenkins_url(base_url: str, url: str) -> str:
    """保留任务路径，并把 Jenkins 返回的 localhost 主机替换为真实地址。"""
    path = urlsplit(url).path
    if not path:
        return base_url.rstrip("/") + "/"
    return base_url.rstrip("/") + "/" + path.lstrip("/")


def build_session(base_url: str, username: str, password: str) -> requests.Session:
    """创建带 Basic Auth 的会话，并通过 Jenkins 根 API 验证登录状态。"""
    session = requests.Session()
    session.auth = (username, password)
    session.headers.update(
        {"Accept": "application/json", "User-Agent": "jryg-package-trigger/1.0"}
    )

    # 立即验证凭据，避免用户完成选择后才发现账号或权限异常。
    response = session.get(base_url.rstrip("/") + "/api/json", timeout=20)
    if response.status_code in (401, 403) or "/login" in response.url:
        raise JenkinsError("Jenkins 账号或密码错误，或当前账号没有访问权限")
    response.raise_for_status()
    return session


def discover_jobs(session: requests.Session, base_url: str) -> List[JenkinsJob]:
    """发现当前账号可见且可构建的客户端任务，并按预设顺序返回。"""
    response = session.get(
        base_url.rstrip("/") + "/api/json",
        params={"tree": "jobs[name,url,buildable]"},
        timeout=20,
    )
    response.raise_for_status()

    # 过滤被 Jenkins 禁用的任务，避免菜单中出现无法触发的选项。
    raw_jobs = {
        item["name"]: item
        for item in response.json().get("jobs", [])
        if item.get("buildable", True)
    }
    jobs = [
        JenkinsJob(name, normalize_jenkins_url(base_url, raw_jobs[name]["url"]))
        for name in JOB_ORDER
        if name in raw_jobs
    ]
    if jobs:
        return jobs

    package_names = [
        name
        for name in raw_jobs
        if any(token in name.lower() for token in ("android", "ios", "robotaxi"))
    ]
    return [
        JenkinsJob(name, normalize_jenkins_url(base_url, raw_jobs[name]["url"]))
        for name in sorted(package_names)
    ]


def job_by_name(
    session: requests.Session, base_url: str, jobs: List[JenkinsJob], name: str
) -> JenkinsJob:
    """按名称查找任务；菜单中不存在时再调用 API 验证用户指定的任务。"""
    for job in jobs:
        if job.name == name:
            return job
    url = base_url.rstrip("/") + "/job/" + quote(name, safe="") + "/"
    response = session.get(url + "api/json", timeout=20)
    if response.status_code == 404:
        raise JenkinsError(f"Jenkins 任务不存在：{name}")
    response.raise_for_status()
    return JenkinsJob(name, url)


def choose(title: str, values: Sequence[str], default: Optional[str] = None) -> str:
    """显示带序号的通用菜单，循环等待用户输入有效序号或选项原值。"""
    if not values:
        raise JenkinsError(f"{title}没有可选项")
    print(f"\n{title}：")

    # 环境项附加中文含义；任务名和分支名保持原样显示。
    for index, value in enumerate(values, 1):
        marker = "（默认）" if value == default else ""
        lower_value = value.lower()
        label = BUILD_TYPE_LABELS.get(lower_value)
        if not label and lower_value.startswith("releasetest"):
            label = "测试环境 " + value[len("releaseTest"):]
        description = f" - {label}" if label else ""
        print(f"  {index}. {value}{description}{marker}")
    while True:
        suffix = f"，回车默认 {default}" if default else ""
        raw = input(f"请输入序号{suffix}：").strip()
        if not raw and default:
            return default
        if raw.isdigit() and 1 <= int(raw) <= len(values):
            return values[int(raw) - 1]
        if raw in values:
            return raw
        print("输入无效，请重新输入。")


def choose_job(jobs: List[JenkinsJob]) -> JenkinsJob:
    """让用户从已发现的任务中选择需要打包的客户端。"""
    name = choose("请选择需要打包的端", [job.name for job in jobs])
    return next(job for job in jobs if job.name == name)


def local_name(tag: str) -> str:
    """移除 XML 命名空间，只保留标签本地名称。"""
    return tag.rsplit("}", 1)[-1]


def parameter_definitions_from_xml(config_xml: bytes) -> Dict[str, ParameterDefinition]:
    """从 Jenkins config.xml 提取参数名、默认值、选项及参数类型。"""
    root = ET.fromstring(config_xml)
    definitions: Dict[str, ParameterDefinition] = {}
    for node in root.iter():
        kind = local_name(node.tag)
        if not kind.endswith("ParameterDefinition"):
            continue
        direct_children = {local_name(child.tag): child for child in node}
        name_node = direct_children.get("name")
        if name_node is None or not (name_node.text or "").strip():
            continue
        name = (name_node.text or "").strip()
        default_node = direct_children.get("defaultValue")
        default = (default_node.text or "").strip() if default_node is not None else ""
        choices_node = direct_children.get("choices")
        choices: List[str] = []
        if choices_node is not None:
            choices = [
                (item.text or "").strip()
                for item in choices_node.iter()
                if local_name(item.tag) == "string" and (item.text or "").strip()
            ]
        if not default and choices:
            default = choices[0]
        definitions[name] = ParameterDefinition(name, default, choices, kind)
    return definitions


def merge_json_definitions(
    definitions: Dict[str, ParameterDefinition], payload: Dict[str, object]
) -> None:
    """把 Jenkins JSON API 返回的参数信息合并到已有 XML 参数定义。"""
    for action in payload.get("actions", []):
        if not isinstance(action, dict):
            continue
        for item in action.get("parameterDefinitions", []):
            if not isinstance(item, dict) or not item.get("name"):
                continue
            name = str(item["name"])
            definition = definitions.setdefault(name, ParameterDefinition(name))
            default_value = item.get("defaultParameterValue")
            if isinstance(default_value, dict) and "value" in default_value:
                value = default_value["value"]
                definition.default = str(value).lower() if isinstance(value, bool) else str(value)
            choices = item.get("choices")
            if isinstance(choices, list) and choices:
                definition.choices = [str(value) for value in choices]
            definition.kind = str(item.get("type", definition.kind))


def dynamic_git_choices(
    session: requests.Session, job: JenkinsJob, parameter_name: str
) -> List[str]:
    """调用 Git Parameter 插件接口，获取任务当前可用的远程分支。"""
    descriptor = (
        "descriptorByName/net.uaznia.lukanus.hudson.plugins.gitparameter."
        "GitParameterDefinition/fillValueItems"
    )
    response = session.get(
        job.url + descriptor,
        params={"param": parameter_name},
        timeout=30,
    )
    if not response.ok:
        return []
    try:
        values = response.json().get("values", [])
    except (ValueError, AttributeError):
        return []
    result: List[str] = []
    for item in values:
        if isinstance(item, dict):
            value = item.get("value") or item.get("name")
        else:
            value = item
        if value is not None and str(value) not in result:
            result.append(str(value))
    return result


def load_parameters(
    session: requests.Session, job: JenkinsJob
) -> Dict[str, ParameterDefinition]:
    """读取参数名称、默认值和选项，并补充分支插件的动态选项。"""
    definitions: Dict[str, ParameterDefinition] = {}

    # 部分账号无 config.xml 权限（403），此时继续使用下方的只读 JSON API。
    config_response = session.get(job.url + "config.xml", timeout=20)
    if config_response.ok:
        definitions = parameter_definitions_from_xml(config_response.content)
    elif config_response.status_code not in (403, 404):
        config_response.raise_for_status()

    api_response = session.get(
        job.url + "api/json",
        params={"tree": "actions[parameterDefinitions[name,type,defaultParameterValue[value],choices]]"},
        timeout=20,
    )
    api_response.raise_for_status()
    merge_json_definitions(definitions, api_response.json())

    for name, definition in definitions.items():
        if name.upper() in BRANCH_PARAMETER_NAMES and not definition.choices:
            definition.choices = dynamic_git_choices(session, job, name)
    if not definitions:
        raise JenkinsError(f"{job.name} 不是参数化构建任务")
    return definitions


def find_parameter(
    definitions: Dict[str, ParameterDefinition], candidates: Sequence[str]
) -> Optional[ParameterDefinition]:
    """忽略大小写，从多个兼容名称中找到任务实际使用的参数。"""
    names = {name.upper(): definition for name, definition in definitions.items()}
    for candidate in candidates:
        if candidate in names:
            return names[candidate]
    return None


def resolve_branch(value: str, choices: Sequence[str]) -> str:
    """校验分支，并支持把 master 等短名称自动规范化为 origin/master。"""
    branch = value.strip()
    if not branch or any(character.isspace() for character in branch):
        raise JenkinsError("Git 分支不能为空或包含空白字符")
    if not choices or branch in choices:
        return branch

    # Jenkins Git Parameter 插件通常以 origin/ 开头返回远程分支。
    normalized = branch if branch.startswith("origin/") else "origin/" + branch
    if normalized in choices:
        return normalized
    raise JenkinsError(f"分支不存在：{branch}")


def choose_branch(definition: ParameterDefinition) -> str:
    """要求用户明确选择分支；支持全名、短名称和关键字模糊匹配。"""
    choices = definition.choices
    if not choices:
        # 插件未返回分支时允许手工输入，但不允许直接回车跳过。
        while True:
            raw = input("\n请输入需要打包的 Git 分支：").strip()
            if raw:
                return resolve_branch(raw, ())
            print("必须由用户选择或输入 Git 分支。")

    print(f"\nJenkins 共返回 {len(choices)} 个分支。")
    while True:
        raw = input("请输入需要打包的分支全名或关键字：").strip()
        if not raw:
            print("必须由用户选择 Git 分支。")
            continue
        try:
            return resolve_branch(raw, choices)
        except JenkinsError:
            matches = [choice for choice in choices if raw.lower() in choice.lower()]
            if len(matches) == 1:
                return matches[0]
            if matches:
                visible = matches[:30]
                selected = choose("匹配到以下分支", visible)
                return selected
            print("没有匹配的分支，请重新输入。")


def parse_overrides(values: Sequence[str]) -> Dict[str, str]:
    """解析可重复传入的 ``--set 参数=值``，用于覆盖其他构建参数。"""
    overrides: Dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise JenkinsError(f"--set 格式错误：{value}，应为 参数=值")
        name, parameter_value = value.split("=", 1)
        if not name.strip():
            raise JenkinsError("--set 的参数名不能为空")
        overrides[name.strip()] = parameter_value
    return overrides


def build_parameters(
    definitions: Dict[str, ParameterDefinition],
    branch_value: Optional[str],
    build_type_value: Optional[str],
    overrides: Dict[str, str],
) -> Tuple[Dict[str, str], str, str]:
    """保留 Jenkins 默认参数，并覆盖用户选择的分支、环境及 --set 参数。"""
    branch_definition = find_parameter(definitions, BRANCH_PARAMETER_NAMES)
    env_definition = find_parameter(definitions, ENV_PARAMETER_NAMES)
    if branch_definition is None:
        raise JenkinsError("该任务缺少 Git 分支参数（GIT_BRANCH/BRANCH）")
    if env_definition is None:
        raise JenkinsError("该任务缺少环境参数（BUILD_TYPE/ENV）")

    if branch_value:
        branch = resolve_branch(branch_value, branch_definition.choices)
    else:
        branch = choose_branch(branch_definition)

    # 优先使用任务实时返回的环境列表；读取不到时使用脚本内置兜底值。
    environment_choices = env_definition.choices or list(BUILD_TYPE_CHOICES)
    if build_type_value:
        build_type = build_type_value.strip()
        if build_type not in environment_choices:
            allowed = ", ".join(environment_choices)
            raise JenkinsError(f"构建环境不存在：{build_type}；可选值：{allowed}")
    else:
        build_type = choose("请选择打包环境", environment_choices)

    unknown = sorted(set(overrides) - set(definitions))
    if unknown:
        raise JenkinsError("任务不存在以下参数：" + ", ".join(unknown))

    parameters = {name: definition.default for name, definition in definitions.items()}
    parameters[branch_definition.name] = branch
    parameters[env_definition.name] = build_type
    parameters.update(overrides)
    return parameters, branch, build_type


def add_crumb(session: requests.Session, base_url: str) -> None:
    """获取 Jenkins CSRF crumb；未启用该机制时无需添加请求头。"""
    response = session.get(base_url.rstrip("/") + "/crumbIssuer/api/json", timeout=20)
    if response.status_code == 404:
        return
    response.raise_for_status()
    data = response.json()
    session.headers[data["crumbRequestField"]] = data["crumb"]


def trigger(
    session: requests.Session, job: JenkinsJob, parameters: Dict[str, str]
) -> Optional[str]:
    """触发参数化构建，成功时尽量返回可访问的 Jenkins 队列地址。"""
    response = session.post(
        job.url + "buildWithParameters",
        data=parameters,
        allow_redirects=False,
        timeout=30,
    )
    if response.status_code not in (201, 202, 302):
        detail = " ".join(response.text[:300].split())
        raise JenkinsError(f"触发失败：HTTP {response.status_code} {detail}")
    location = response.headers.get("Location")
    if not location:
        return None
    queue_url = urljoin(job.url, location)
    job_server = urlsplit(job.url)
    base_url = f"{job_server.scheme}://{job_server.netloc}"
    return normalize_jenkins_url(base_url, queue_url)


def confirm(job: JenkinsJob, branch: str, build_type: str) -> None:
    """展示最终选择，并要求输入固定文本，防止误触发真实打包。"""
    print("\n即将触发 Jenkins 打包：")
    print(f"  端/任务：{job.name}")
    print(f"  Git 分支：{branch}")
    print(f"  打包环境：{build_type}")
    actual = input("请输入 BUILD 确认，其他输入取消：").strip()
    if actual != "BUILD":
        raise JenkinsError("用户取消打包")


def main(argv: Optional[Sequence[str]] = None) -> int:
    """完成登录、任务选择、参数预览、确认和触发构建的主流程。"""
    args = parse_args(argv)

    # 优先级：命令行/环境变量密码 > macOS 钥匙串 > 隐藏式交互输入。
    stored_password = keychain_password(args.username)
    password = args.password or stored_password or getpass.getpass("Jenkins 密码：")
    if not password:
        raise JenkinsError("Jenkins 密码不能为空")

    # 只有登录验证通过后，才把新密码写入钥匙串，避免保存错误凭据。
    base_url = args.url.rstrip("/")
    session = build_session(base_url, args.username, password)
    if password != stored_password:
        save_keychain_password(args.username, password)
        print("Jenkins 密码已安全保存到 macOS 钥匙串，下次无需输入。")

    # 先发现任务；--list 到此即可返回，保证不会读取参数或触发构建。
    jobs = discover_jobs(session, base_url)
    if args.list:
        if not jobs:
            raise JenkinsError("未发现可用的客户端打包任务")
        print("可用的 Jenkins 打包任务：")
        for job in jobs:
            print("- " + job.name)
        return 0

    if args.job:
        job = job_by_name(session, base_url, jobs, args.job)
    else:
        if not jobs:
            raise JenkinsError("未发现可用的客户端打包任务")
        job = choose_job(jobs)

    # 读取该任务的实时参数，再合并用户选择和可选的 --set 覆盖项。
    definitions = load_parameters(session, job)
    parameters, branch, build_type = build_parameters(
        definitions,
        args.branch,
        args.build_type,
        parse_overrides(args.set),
    )

    # 打印所有最终参数，便于在真正触发前检查布尔参数和渠道等默认值。
    print("\n打包参数预览：")
    for name, value in parameters.items():
        print(f"  {name}={value}")
    if args.dry_run:
        print("\n预检完成，未触发 Jenkins 构建。")
        return 0

    if not args.yes:
        confirm(job, branch, build_type)
    add_crumb(session, base_url)
    queue_url = trigger(session, job, parameters)
    print(f"\n已触发 {job.name} 打包。")
    if queue_url:
        print(f"Jenkins 队列：{queue_url}")
    else:
        print(f"任务地址：{job.url}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (JenkinsError, requests.RequestException, ET.ParseError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        raise SystemExit(2)
