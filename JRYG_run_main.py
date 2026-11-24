"""HK Android runner: sequential scenarios, batch completion receipts, stop-on-failure."""

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
    """Run one scenario in a subprocess; ensure cleanup before starting the next."""
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
    """Validate final collected items before any setup; reject extra files or methods."""

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
                raise pytest.UsageError("Six-scenario entry only allows selected cases/main_flow_cases items")
            seen.add(key)


def _validate_main_flow_pytest_args(args):
    """Dedicated entry accepts only display, filter and collect-only arguments."""
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
        print("[Error] --batch and --case cannot be used together.")
        return 2
    if options.batch_result and not options.case:
        print("[Error] Batch completion receipt is only produced by a single scenario subprocess.")
        return 2
    nodes = scenario_nodes()
    if options.case:
        matches = [node for node in nodes if options.case in (
            node, node.split("::")[1], node.split("::")[0],
            Path(node.split("::")[0]).name, "cases/" + Path(node.split("::")[0]).name,
            str(Path(node.split("::")[0]).relative_to(BASE_DIR)),
            str(Path(node.split("::")[0]).relative_to(BASE_DIR)) + "::" + node.split("::", 1)[1])]
        if not matches or (options.main_flow_only and len(matches) != 1):
            scope = "a unique registered main-flow item in cases/main_flow_cases" if options.main_flow_only else "a scenario file, class name or full node id"
            print(f"[Error] --case must specify {scope}.")
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
        pytest_args.extend(["-o", "addopts=", "--import-mode=importlib"])
        inherited_addopts = os.environ.pop("PYTEST_ADDOPTS", None)
        if inherited_addopts:
            print("[Scope] Ignoring PYTEST_ADDOPTS; only selected main-flow nodes are collected.")
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
