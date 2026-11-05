"""JRYG_Passenger_UI_HK-ios 自动化模块 —— JRYG_run_main_ios.py
==============================================================================
港版阳光出行 iOS 乘客端 UI 自动化测试主运行入口。

功能：
  1. 初始化运行所需目录（报告、日志、截图、配置）
  2. 收集所有 iOS 专用测试文件（cases/ 目录下 JRYG_test_ios_*.py）
  3. 通过 pytest 执行测试，生成 HTML 报告
  4. --batch依次执行包车两例、打表四例；每例完成并清理后间隔10秒，失败停止
  5. 单例报告及批次结果保存到report/batches/时间戳，不覆盖每日历史；批次禁止重叠

测试用例组合（车型 × 支付方式）：
  - 打錶的士：現金(cash) / 電子支付后付（银行卡、Alipay HK独立文件）/ 直接Alipay HK
  - 旧电子支付银行卡文件保留显式入口，默认运行器不重复提交同一场景
  - 包車價的士：Alipay HK(alipay) / 信用卡(bankcard)
==============================================================================
"""

import argparse
from datetime import datetime
import fcntl
import json
import os
from pathlib import Path
import signal
import sys
import time
import pytest

# 从runners目录定位项目根，直接运行与python -m运行使用相同配置和用例路径。
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# 导入目录初始化函数，确保运行前报告/日志/截图/配置目录已存在
from ui_framework.JRYG_dir_init import init_all_dirs
# 导入报告输出目录路径
from ui_framework.JRYG_config import REPORT_DIR


class CompletedOrderGate:
    """批量子任务只接受一个已核验完成且已支付的订单，不把跳过或仅接单算成功。"""

    def __init__(self):
        self.completed_orders = []

    def pytest_collection_finish(self, session):
        if len(session.items) != 1:
            raise pytest.UsageError("批量每轮必须执行恰好一个订单用例，禁止空选择或多用例混跑")

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_call(self, item):
        outcome = yield
        if outcome.excinfo is not None:
            return
        instance = item.instance
        driver = getattr(instance, "driver_ui", None)
        order_no = getattr(instance, "completed_order_no", None)
        if (not order_no or driver is None or driver.last_phase != "complete"
                or order_no != driver.order_no or driver.awaiting_new_order
                or order_no in driver.completed_before_run):
            outcome.force_exception(AssertionError("当前订单未通过完成且已支付核验，停止批量后续用例"))
            return
        self.completed_orders.append({"nodeid": item.nodeid, "order_no": order_no})


def run_batch(case_files, extra_args, *, run_case=None, report_dir=None, platform="ios"):
    """共享批次门禁；平台桥接独立准备/清理设备，完成凭据通过后等待10秒。"""
    if run_case is None:
        from runners.JRYG_run_case_ios import run_case

    if os.environ.get("HK_DRIVER_UI_STOP_AFTER", "submitted") != "submitted":
        print("[错误] 批量不能使用仅接单模式，必须完成行程及同订单支付核验。")
        return 2
    if any(arg == "--html" or arg.startswith("--html=") for arg in extra_args):
        print("[错误] 批量自动保存独立报告，请勿用--html覆盖所有用例的报告。")
        return 2
    report_root = Path(REPORT_DIR if report_dir is None else report_dir)
    report_root.mkdir(parents=True, exist_ok=True)
    with (report_root / f".{platform}-batch.lock").open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("[错误] 已有iOS批次运行，拒绝重叠执行。")
            return 2
        batch_dir = report_root / "batches" / datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        batch_dir.mkdir(parents=True, exist_ok=False)
        rows = [{"sequence": index, "case": Path(path).name, "status": "not_run"}
                for index, path in enumerate(case_files, 1)]
        exit_code = 1
        completed_orders = set()
        interrupted_code = 130

        def interrupt(signum, frame):
            nonlocal interrupted_code
            interrupted_code = 128 + signum
            raise KeyboardInterrupt

        previous = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGTSTP)}
        try:
            for sig in previous:
                signal.signal(sig, interrupt)
            for index, (case_file, row) in enumerate(zip(case_files, rows), 1):
                row["status"] = "running"
                row["started_at"] = datetime.now().isoformat(timespec="seconds")
                result_file = batch_dir / f"{index:02d}_result.json"
                case_report = batch_dir / f"{index:02d}_{Path(case_file).stem}.html"
                row["report"] = str(case_report)
                print(f"[批量 {index}/{len(case_files)}] 执行 {Path(case_file).name}", flush=True)
                exit_code = run_case(case_file, [*extra_args, f"--batch-result={result_file}", f"--report-file={case_report}"])
                row["exit_code"] = exit_code
                row["finished_at"] = datetime.now().isoformat(timespec="seconds")
                row["status"] = "failed"
                if exit_code != 0:
                    print(f"[停止] 当前用例或设备准备失败，退出码{exit_code}；不启动后续用例。", flush=True)
                    break
                result = json.loads(result_file.read_text(encoding="utf-8"))
                records = result.get("completed_orders", [])
                if result.get("exit_code") != 0 or len(records) != 1:
                    exit_code = 1
                    row["reason"] = "没有唯一的已完成且已支付订单凭据"
                    break
                order_no = records[0]["order_no"]
                if order_no in completed_orders:
                    exit_code = 1
                    row["reason"] = "订单号已被此前用例使用，不能冒充本次新结果"
                    break
                completed_orders.add(order_no)
                row.update(status="passed", order_no=order_no)
                print(f"[完成] 订单{order_no}已完成且已支付，本轮进程已清理。", flush=True)
                if index < len(case_files):
                    print("[等待] 用例间隔10秒，之后才启动下一例。", flush=True)
                    time.sleep(10)
            else:
                exit_code = 0
        except KeyboardInterrupt:
            exit_code = interrupted_code
            print("[停止] 批量已中断，不继续后续用例。", flush=True)
        except Exception as exc:
            exit_code = 1
            print(f"[停止] 批量结果核验失败：{exc}；不继续后续用例。", flush=True)
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)
            for row in rows:
                if row["status"] == "running":
                    row["status"] = "interrupted" if exit_code >= 128 else "failed"
                if row["status"] in ("failed", "interrupted"):
                    row["exit_code"] = exit_code
            summary = {"exit_code": exit_code, "interval_seconds": 10, "cases": rows}
            summary_file = batch_dir / "batch_result.json"
            summary_file.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"[批量报告] {summary_file}", flush=True)
            if platform == "ios":
                try:
                    from ui_framework.JRYG_dingtalk_report import notify_batch
                    notify_batch(summary_file)
                except (Exception, KeyboardInterrupt) as exc:
                    print(f"[钉钉报告] 通知异常（{type(exc).__name__}），不影响测试退出码，不自动重发。", flush=True)
        return exit_code


def batch_order(case_files):
    """双端使用同一批次顺序：包车两例在前，打表四例在后。"""
    return case_files[4:] + case_files[:4]


def run_tests(argv=None):
    """JRYG 港版 iOS UI 自动化测试执行引擎入口。

    流程：
    1. 初始化必需文件夹
    2. 收集所有 iOS 测试文件
    3. 组装 pytest 参数（-v -s --html 报告）
    4. 执行 pytest 并返回退出码

    :param argv: --batch顺序执行六例、逐例清理和等待10秒；--case保留独立场景入口。
    无--batch时兼容原pytest会话；--batch的收集/帮助不启动设备，不等待。
    每个批量场景通过Shell准备WDA，仅--case运行pytest，不递归进入批量。
    :return: pytest 退出码（0=成功，非 0=有失败或错误）。
    """
    print("\n" + "="*50)
    print("      JRYG 港版阳光出行 iOS 测试执行引擎 -ios (Start)")
    print("="*50)

    # 初始化必需文件夹（报告、日志、截图、配置）
    init_all_dirs()

    # HTML 测试报告输出路径
    report_file = os.path.join(REPORT_DIR, "JRYG_test_report_hk_ios.html")

    # --case由直接Python入口指定；其余选项保留原样交给pytest。
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
    if options.report_file:
        report_file = str(Path(options.report_file).resolve())

    # 收集所有 iOS 专用测试文件（cases/ 目录下 JRYG_test_ios_*.py）
    # 参数化下单用例（车型 × 支付方式组合）
    ios_test_files = [
        # 打錶的士：現金 / 電子支付后付（银行卡、Alipay HK）/ 直接Alipay HK
        os.path.join(BASE_DIR, "cases", "JRYG_test_ios_meter_cash_order.py"),
        os.path.join(BASE_DIR, "cases", "JRYG_test_ios_meter_epayment_bankcard_order.py"),
        os.path.join(BASE_DIR, "cases", "JRYG_test_ios_meter_epayment_alipay_order.py"),
        os.path.join(BASE_DIR, "cases", "JRYG_test_ios_meter_alipay_order.py"),
        # 包車價的士：Alipay HK / 信用卡/扣帳卡
        os.path.join(BASE_DIR, "cases", "JRYG_test_ios_charter_alipay_order.py"),
        os.path.join(BASE_DIR, "cases", "JRYG_test_ios_charter_bankcard_order.py"),
    ]

    if options.case:
        case_path = Path(options.case)
        if not case_path.is_absolute():
            case_path = Path(BASE_DIR) / case_path
        case_path = case_path.resolve()
        if case_path.parent != Path(BASE_DIR) / "cases" or not case_path.name.startswith("JRYG_test_ios_") or case_path.suffix != ".py" or not case_path.is_file():
            print("[错误 -ios] --case必须指定本项目cases内存在的iOS场景文件！")
            return 2

    # 共享基线不变；iOS批量按包车两例→打表四例顺序运行。
    batch_files = batch_order(ios_test_files)
    selected_files = [str(case_path)] if options.case else batch_files if options.batch else ios_test_files
    missing = [path for path in selected_files if not Path(path).is_file()]
    if missing:
        print(f"[错误 -ios] 用例文件缺失，不能缩减批次冒充全部执行：{missing}")
        return 2
    existing_files = selected_files
    read_only = any(arg in ("--collect-only", "--co", "--help", "-h") for arg in extra_args)
    if options.batch:
        print("[顺序] 包车Alipay → 包车银行卡 → 打表现金 → 电子支付后付银行卡 → 电子支付后付Alipay → 直接Alipay", flush=True)
        if not read_only:
            return run_batch(existing_files, extra_args)

    # 组装 pytest 参数
    pytest_args = [
        "-c", os.path.join(BASE_DIR, "pytest.ini"),  # 指定 pytest 配置文件
        "-v", "-s",                                   # 详细输出 + 不捕获 print
    ] + existing_files

    # 非 collect-only 模式时生成 HTML 报告
    if not any(arg in ("--collect-only", "--co") for arg in extra_args):
        pytest_args.extend([f"--html={report_file}", "--self-contained-html"])
        print(f"输出香港 iOS UI 测试报告: {report_file}")

    gate = CompletedOrderGate() if options.batch_result and not read_only else None
    exit_code = pytest.main(pytest_args + extra_args, plugins=[gate] if gate is not None else [])
    if gate is not None:
        if exit_code == 0 and len(gate.completed_orders) != 1:
            exit_code = 1
            print("[停止] 用例被跳过或没有完成订单，不能放行下一例。")
        result_file = Path(options.batch_result)
        result_file.write_text(json.dumps({"exit_code": int(exit_code), "completed_orders": gate.completed_orders},
                                          ensure_ascii=False, indent=2), encoding="utf-8")

    print("="*50)
    print("      JRYG 港版阳光出行 iOS 测试执行引擎 -ios (Completed)")
    print("="*50 + "\n")
    return exit_code

if __name__ == "__main__":
    # 直接运行此文件时，透传命令行参数给 run_tests
    sys.exit(run_tests(sys.argv[1:]))
