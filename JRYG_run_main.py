"""香港Android运行器，独立场景顺序、批次完成凭据及失败即停规则。"""

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys

import pytest

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from passenger_android_core.JRYG_dir_init import init_all_dirs
from passenger_android_core.JRYG_config import REPORT_DIR
from passenger_android_core import JRYG_shared
from passenger_android_core.JRYG_scenarios import scenario_nodes
from passenger_android_core.JRYG_run_main_android import CompletedOrderGate, batch_order, run_batch


def run_case(nodeid, extra_args):
    """每轮独立进程创建/释放Appium会话，中断时等待清理，不启动下一例。"""
    process = subprocess.Popen([sys.executable, str(BASE_DIR / "JRYG_run_main.py"),
                                "--case", nodeid, *extra_args], cwd=BASE_DIR, start_new_session=True)
    try:
        return process.wait()
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()


def run_tests(argv=None):
    interrupted_code = None

    def interrupt(signum, frame):
        nonlocal interrupted_code
        interrupted_code = 128 + signum
        raise KeyboardInterrupt

    previous = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGHUP, signal.SIGTSTP)}
    try:
        for sig in previous:
            signal.signal(sig, interrupt)
        exit_code = _run_tests(argv)
        return interrupted_code if interrupted_code is not None else exit_code
    except KeyboardInterrupt:
        return interrupted_code if interrupted_code is not None else 130
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


class MainFlowCollectionGate:
    """在任何用例 setup 前检查最终收集结果，禁止追加其他文件或方法。"""

    def __init__(self, selected):
        self.selected = {
            (Path(node.split("::", 1)[0]).resolve(), node.split("::", 1)[1])
            for node in selected
        }

    def pytest_collection_finish(self, session):
        seen = set()
        main_dir = (BASE_DIR / "cases" / "main_flow_cases").resolve()
        for item in session.items:
            path = Path(item.path).resolve()
            method = item.nodeid.partition("::")[2]
            key = (path, method)
            if path.parent != main_dir or key not in self.selected or key in seen:
                raise pytest.UsageError("六场景入口只允许执行选定的 cases/main_flow_cases 主流程，拒绝越界或重复用例")
            seen.add(key)


def _validate_main_flow_pytest_args(args):
    """专用入口只接受展示、过滤与只收集参数，不接受额外测试路径或配置覆盖。"""
    parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    parser.add_argument("--collect-only", "--co", action="store_true")
    parser.add_argument("--help", "-h", action="store_true")
    parser.add_argument("-q", "--quiet", action="count")
    parser.add_argument("-v", "--verbose", action="count")
    parser.add_argument("-s", action="store_true")
    parser.add_argument("-x", "--exitfirst", action="store_true")
    parser.add_argument("-k")
    parser.add_argument("-m")
    parser.add_argument("--maxfail", type=int)
    parser.add_argument("--tb", choices=("auto", "long", "short", "line", "native", "no"))
    parser.add_argument("--disable-warnings", action="store_true")
    parser.parse_args(args)


def _run_tests(argv=None):
    init_all_dirs()
    parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    parser.add_argument("--case")
    parser.add_argument("--batch", action="store_true")
    parser.add_argument("--report-file")
    parser.add_argument("--batch-result", help=argparse.SUPPRESS)
    parser.add_argument("--main-flow-only", action="store_true")
    options, extra_args = parser.parse_known_args(list(argv or []))
    if options.main_flow_only:
        _validate_main_flow_pytest_args(extra_args)
    if options.batch and options.case:
        print("[错误] --batch与--case不能同时使用。")
        return 2
    if options.batch_result and not options.case:
        print("[错误] 批量完成凭据只能由独立场景输出。")
        return 2
    nodes = scenario_nodes(include_optional=bool(options.case), main_flow_only=options.main_flow_only)
    if options.case:
        matches = [node for node in nodes if options.case in (
            node, node.split("::")[1], node.split("::")[0],
            Path(node.split("::")[0]).name, "cases/" + Path(node.split("::")[0]).name,
            str(Path(node.split("::")[0]).relative_to(BASE_DIR)),
            str(Path(node.split("::")[0]).relative_to(BASE_DIR)) + "::" + node.split("::", 1)[1])]
        if not matches or (options.main_flow_only and len(matches) != 1):
            scope = "cases/main_flow_cases 内唯一已注册主流程" if options.main_flow_only else "安卓独立场景文件、类名或完整节点"
            print(f"[错误] --case必须指定{scope}。")
            return 2
        selected = matches
    else:
        selected = batch_order(nodes) if options.batch else nodes
    read_only = any(arg in ("--collect-only", "--co", "--help", "-h") for arg in extra_args)
    if options.batch and not read_only:
        batch_args = ["--main-flow-only", *extra_args] if options.main_flow_only else extra_args
        return run_batch(selected, batch_args, run_case=run_case, report_dir=REPORT_DIR, platform="android")
    report_file = str(Path(options.report_file).resolve()) if options.report_file else str(
        Path(REPORT_DIR) / "JRYG_test_report_hk.html")
    pytest_args = ["-c", str(BASE_DIR / "pytest.ini"), "-v", "-s", *selected]
    if not read_only:
        pytest_args.extend([f"--html={report_file}", "--self-contained-html"])
    gate = CompletedOrderGate() if options.batch_result and not read_only else None
    plugins = [gate] if gate is not None else []
    if options.main_flow_only:
        plugins.append(MainFlowCollectionGate(selected))
        # 专用入口的范围不能被外部 PYTEST_ADDOPTS 或配置 addopts 追加测试路径扩大。
        # 不改配置文件；仍明确使用项目现有的 importlib 收集方式。
        pytest_args.extend(["-o", "addopts=", "--import-mode=importlib"])
        inherited_addopts = os.environ.pop("PYTEST_ADDOPTS", None)
        if inherited_addopts:
            print("[范围限制] 本入口忽略 PYTEST_ADDOPTS，仅读取指定主流程节点。")
        try:
            exit_code = pytest.main(pytest_args + extra_args, plugins=plugins)
        finally:
            if inherited_addopts is not None:
                os.environ["PYTEST_ADDOPTS"] = inherited_addopts
    else:
        exit_code = pytest.main(pytest_args + extra_args, plugins=plugins)
    if gate is not None:
        if exit_code == 0 and len(gate.completed_orders) != 1:
            exit_code = 1
        Path(options.batch_result).write_text(json.dumps(
            {"exit_code": int(exit_code), "completed_orders": gate.completed_orders},
            ensure_ascii=False, indent=2), encoding="utf-8")
    return exit_code


if __name__ == "__main__":
    sys.exit(run_tests(sys.argv[1:]))
