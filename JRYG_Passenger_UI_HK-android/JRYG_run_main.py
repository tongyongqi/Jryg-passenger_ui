"""香港Android运行器，共享iOS场景顺序、批次完成凭据及失败即停规则。"""

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

from jryg_hk_android.JRYG_dir_init import init_all_dirs
from jryg_hk_android.JRYG_config import REPORT_DIR
from jryg_hk_android import JRYG_shared_ios
from jryg_hk_android.JRYG_scenarios import scenario_nodes
from runners.JRYG_run_main_ios import CompletedOrderGate, batch_order, run_batch


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


def _run_tests(argv=None):
    init_all_dirs()
    parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    parser.add_argument("--case")
    parser.add_argument("--batch", action="store_true")
    parser.add_argument("--report-file")
    parser.add_argument("--batch-result", help=argparse.SUPPRESS)
    options, extra_args = parser.parse_known_args(list(argv or []))
    if options.batch and options.case:
        print("[错误] --batch与--case不能同时使用。")
        return 2
    if options.batch_result and not options.case:
        print("[错误] 批量完成凭据只能由独立场景输出。")
        return 2
    nodes = scenario_nodes(include_optional=True) if options.case else scenario_nodes()
    if options.case:
        matches = [node for node in nodes if options.case in (
            node, node.split("::")[1], node.split("::")[0],
            Path(node.split("::")[0]).name, "cases/" + Path(node.split("::")[0]).name)]
        if len(matches) != 1:
            print("[错误] --case必须指定安卓独立场景文件、类名或完整节点。")
            return 2
        selected = matches
    else:
        selected = batch_order(nodes) if options.batch else nodes
    read_only = any(arg in ("--collect-only", "--co", "--help", "-h") for arg in extra_args)
    if options.batch and not read_only:
        return run_batch(selected, extra_args, run_case=run_case, report_dir=REPORT_DIR, platform="android")
    report_file = str(Path(options.report_file).resolve()) if options.report_file else str(
        Path(REPORT_DIR) / "JRYG_test_report_hk.html")
    pytest_args = ["-c", str(BASE_DIR / "pytest.ini"), "-v", "-s", "-x", *selected]
    if not read_only:
        pytest_args.extend([f"--html={report_file}", "--self-contained-html"])
    gate = CompletedOrderGate() if options.batch_result and not read_only else None
    exit_code = pytest.main(pytest_args + extra_args, plugins=[gate] if gate is not None else [])
    if gate is not None:
        if exit_code == 0 and len(gate.completed_orders) != 1:
            exit_code = 1
        Path(options.batch_result).write_text(json.dumps(
            {"exit_code": int(exit_code), "completed_orders": gate.completed_orders},
            ensure_ascii=False, indent=2), encoding="utf-8")
    return exit_code


if __name__ == "__main__":
    sys.exit(run_tests(sys.argv[1:]))
