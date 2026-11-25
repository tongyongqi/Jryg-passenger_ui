"""JRYG_Passenger_UI_HK-ios 自动化模块 —— JRYG_run_main_ios.py
==============================================================================
港版阳光出行 iOS 乘客端 UI 自动化测试主运行入口。

功能：
  1. 初始化运行所需目录（报告、日志、截图、配置）
  2. 收集所有 iOS 专用测试文件（cases/ 目录下 JRYG_test_ios_*.py）
  3. 通过 pytest 执行测试，生成 HTML 报告
  4. --batch依次执行六例；下单前安全失败清理后等5秒重试一次，最终失败记录后继续
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
from ui_framework.JRYG_config import REPORT_DIR, SETTINGS


FAILURE_REASONS = {
    "TimeoutError": "页面或业务步骤等待超时",
    "AssertionError": "用例断言未通过",
    "DriverAppNotForegroundError": "司机App未处于前台，禁止继续操作",
    "DriverPageReadError": "司机页面读取失败，禁止重滑或重提交",
    "DeviceUnlockError": "设备解锁失败",
    "RuntimeError": "UI流程或订单状态核验失败",
    "OSError": "设备连接、进程启动或文件操作失败",
    "Exception": "用例执行异常，详情见本例HTML及现场",
    "completion_gate": "当前订单未通过完成且已支付核验",
    "skipped": "用例被跳过，不能计为订单完成",
    "collection": "用例收集失败或未选中恰好一个订单用例",
    "result_missing": "未生成单例结果，可能在设备准备或启动阶段失败",
    "result_invalid": "单例结果文件损坏或结构不合法",
    "missing_order": "没有唯一的已完成且已支付订单凭据",
    "duplicate_order": "订单号已被此前用例使用，不能冒充本次新结果",
    "child_failed": "用例或设备准备失败，详情见本例报告及终端日志",
    "runner_error": "单例启动或结果核验异常",
    "interrupted": "用户或系统中断，停止后续用例",
}
FAILURE_PHASES = {"setup": "准备阶段", "call": "执行阶段", "teardown": "清理阶段",
                  "collection": "收集阶段", "runner": "子任务阶段"}
DRIVER_PHASES = {"login", "code", "offline", "online", "offer", "departure", "pickup",
                 "onboard", "tail", "destination", "bill", "unpaid", "complete",
                 "cancelled", "network_location_error", "unknown"}


def failure_detail(phase, error_type="Exception", *, reason_code=None, driver_phase=None):
    """仅保存白名单分类和阶段，不将异常正文、输入或外部结果原文写入汇总。"""
    phase = phase if isinstance(phase, str) and phase in FAILURE_PHASES else "runner"
    error_type = error_type if isinstance(error_type, str) and error_type in FAILURE_REASONS else "Exception"
    code = reason_code if isinstance(reason_code, str) and reason_code in FAILURE_REASONS else error_type
    detail = {"phase": phase, "error_type": error_type, "reason_code": code,
              "reason": f"{FAILURE_PHASES[phase]}：{FAILURE_REASONS[code]}"}
    if isinstance(driver_phase, str) and driver_phase in DRIVER_PHASES:
        detail["driver_phase"] = driver_phase
    return detail


def check_batch_result(row, result_file, completed_orders):
    """核验单例文件和唯一完成凭据；失败原因分类重建，不透传异常或子例原文。"""
    try:
        result = json.loads(result_file.read_text(encoding="utf-8"))
    except FileNotFoundError:
        row["reason_code"] = "result_missing"
    except (OSError, ValueError):
        row["reason_code"] = "result_invalid"
    else:
        if (not isinstance(result, dict) or type(result.get("exit_code")) is not int
                or not isinstance(result.get("completed_orders"), list)
                or not isinstance(result.get("failures", []), list)
                or any(not isinstance(detail, dict)
                       or not all(isinstance(detail.get(key), str) for key in ("phase", "error_type", "reason_code"))
                       for detail in result.get("failures", []))):
            row["reason_code"] = "result_invalid"
        else:
            failures = []
            for detail in result.get("failures", []):
                if isinstance(detail, dict):
                    failures.append(failure_detail(detail.get("phase"), detail.get("error_type"),
                                                   reason_code=detail.get("reason_code"),
                                                   driver_phase=detail.get("driver_phase")))
            if failures:
                row["failures"] = failures
            records = result["completed_orders"]
            row["retry_safe"] = (result.get("retry_safe") is True and not records and bool(failures)
                                 and row["exit_code"] == result["exit_code"] == 1
                                 and all(detail["phase"] == "call" and detail.get("driver_phase") == "online"
                                         and detail["reason_code"] in ("RuntimeError", "TimeoutError", "AssertionError",
                                                                       "DriverAppNotForegroundError", "DriverPageReadError",
                                                                       "DeviceUnlockError", "OSError")
                                         for detail in failures))
            if row["exit_code"] != 0 or result["exit_code"] != 0 or failures:
                row["exit_code"] = row["exit_code"] or result["exit_code"] or 1
                row["reason_code"] = failures[0]["reason_code"] if failures else "child_failed"
            elif (len(records) != 1 or not isinstance(records[0], dict)
                  or not isinstance(records[0].get("order_no"), str) or not records[0]["order_no"].strip()):
                row["reason_code"] = "missing_order"
            elif records[0]["order_no"] in completed_orders:
                row["reason_code"] = "duplicate_order"
            else:
                order_no = records[0]["order_no"]
                completed_orders.add(order_no)
                row.update(status="passed", order_no=order_no)
                return
    row["status"] = "failed"
    row["exit_code"] = row["exit_code"] or 1
    row["reason"] = "; ".join(detail["reason"] for detail in row.get("failures", [])) or FAILURE_REASONS[row["reason_code"]]


class CompletedOrderGate:
    """批量子任务只接受一个已核验完成且已支付的订单，不把跳过或仅接单算成功。"""

    def __init__(self, *, retry_reopen_app=False):
        self.completed_orders = []
        self.failures = []
        self.interrupted = False
        self.retry_safe = False
        self.retry_reopen_app = retry_reopen_app

    def pytest_keyboard_interrupt(self, excinfo):
        from _pytest.main import Interrupted

        if issubclass(excinfo.type, KeyboardInterrupt) and not issubclass(excinfo.type, Interrupted):
            self.interrupted = True
            self.failures.append(failure_detail("runner", reason_code="interrupted"))

    def pytest_collection_finish(self, session):
        if len(session.items) != 1:
            self.failures.append(failure_detail("collection", reason_code="collection"))
            raise pytest.UsageError("批量每轮必须执行恰好一个订单用例，禁止空选择或多用例混跑")

    def pytest_collectreport(self, report):
        if report.failed:
            self.failures.append(failure_detail("collection", reason_code="collection"))

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_makereport(self, item, call):
        outcome = yield
        report = outcome.get_result()
        if report.when == "call":
            instance = item.instance
            driver = getattr(instance, "driver_ui", None)
            self.retry_safe = (getattr(instance, "retry_safe", False) is True
                               and getattr(driver, "last_phase", None) == "online"
                               and getattr(driver, "awaiting_new_order", False) is True
                               and not getattr(instance, "completed_order_no", None)
                               and not getattr(instance, "resuming_order", False))
        if report.failed or report.skipped:
            if report.when == "call" and any(detail["reason_code"] == "completion_gate" for detail in self.failures):
                return
            driver = getattr(item.instance, "driver_ui", None)
            error_type = call.excinfo.typename if call.excinfo is not None else "Exception"
            self.failures.append(failure_detail(report.when, error_type,
                                               reason_code="skipped" if report.skipped else None,
                                               driver_phase=getattr(driver, "last_phase", None)))

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_call(self, item):
        if item.instance is not None:
            item.instance.batch_new_order_only = True
            item.instance.batch_retry = self.retry_reopen_app
        outcome = yield
        if outcome.excinfo is not None:
            return
        instance = item.instance
        driver = getattr(instance, "driver_ui", None)
        order_no = getattr(instance, "completed_order_no", None)
        if (not order_no or driver is None or driver.last_phase != "complete"
                or order_no != driver.order_no or driver.awaiting_new_order
                or order_no in driver.completed_before_run):
            self.failures.append(failure_detail("call", "AssertionError", reason_code="completion_gate",
                                               driver_phase=getattr(driver, "last_phase", None)))
            outcome.force_exception(AssertionError("当前订单未通过完成且已支付核验，本用例失败并记录原因"))
            return
        self.completed_orders.append({"nodeid": item.nodeid, "order_no": order_no})


def run_batch(case_files, extra_args, *, run_case=None, report_dir=None, platform="ios", api_config=None):
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
        exit_code = 0
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
                row["attempts"] = []
                row["retry_count"] = 0
                print(f"[批量 {index}/{len(case_files)}] 执行 {Path(case_file).name}", flush=True)
                for attempt_number in (1, 2):
                    prefix = f"{index:02d}" if attempt_number == 1 else f"{index:02d}_retry1"
                    result_file = batch_dir / f"{prefix}_result.json"
                    case_report = batch_dir / f"{prefix}_{Path(case_file).stem}.html"
                    attempt = {"attempt": attempt_number, "status": "running", "retry_safe": False,
                               "started_at": datetime.now().isoformat(timespec="seconds"),
                               "result": str(result_file), "report": str(case_report)}
                    row["attempts"].append(attempt)
                    row["retry_count"] = attempt_number - 1
                    row.update(result=str(result_file), report=str(case_report))
                    capture_args = []
                    if api_config is not None and platform == "ios":
                        if api_config.get("enabled"):
                            api_dir = batch_dir / f"{prefix}_api"
                            attempt["api_report"] = row["api_report"] = str(api_dir / "接口清单.txt")
                            capture_args = [f"--api-output={api_dir}", f"--api-namespace={api_config['namespace']}"]
                        else:
                            capture_args = ["--no-api-catalog"]
                    retry_args = ["--retry-reopen-app"] if attempt_number == 2 else []
                    try:
                        case_exit = int(run_case(case_file, [*extra_args, *capture_args, *retry_args,
                                                           f"--batch-result={result_file}", f"--report-file={case_report}"]))
                        attempt["exit_code"] = attempt["process_exit_code"] = case_exit
                        if case_exit >= 128 or case_exit < 0:
                            interrupted_code = case_exit if case_exit >= 128 else 128 - case_exit
                            raise KeyboardInterrupt
                        check_batch_result(attempt, result_file, completed_orders)
                    except Exception as exc:
                        detail = failure_detail("runner", type(exc).__name__, reason_code="runner_error")
                        attempt.update(status="failed", exit_code=attempt.get("exit_code") or 1,
                                       reason_code="runner_error", reason=detail["reason"], failures=[detail], retry_safe=False)
                    attempt["finished_at"] = datetime.now().isoformat(timespec="seconds")
                    if (attempt["status"] == "failed" and attempt_number == 1
                            and platform == "ios" and attempt["retry_safe"]):
                        print(f"[重试] {attempt['reason']}；本轮已清理，等待5秒后重新打开App，重试当前用例1/1。", flush=True)
                        time.sleep(5)
                        continue
                    row.update({key: value for key, value in attempt.items() if key not in ("attempt", "started_at")})
                    break
                if row["status"] == "passed":
                    print(f"[完成] 订单{row['order_no']}已完成且已支付，本轮进程已清理。", flush=True)
                else:
                    if exit_code == 0:
                        exit_code = row["exit_code"]
                    if row["retry_count"]:
                        row["retry_note"] = "重试1次仍失败，不再重试"
                    else:
                        row["retry_note"] = "未证明为下单前安全失败，不整例重试，避免重复下单或付款"
                    print(f"[失败] {row['reason']}；退出码{row['exit_code']}。{row['retry_note']}；已记录，继续后续用例。", flush=True)
                if index < len(case_files):
                    print("[等待] 用例间隔10秒，之后才启动下一例。", flush=True)
                    time.sleep(10)
                    if platform == "ios":
                        print("[唤醒] 下一例先唤醒电脑；WDA就绪后自动唤醒并核验手机，不向已清理的WDA发送解锁请求。", flush=True)
        except KeyboardInterrupt:
            exit_code = interrupted_code
            print("[停止] 批量已中断，不继续后续用例。", flush=True)
        except Exception as exc:
            exit_code = exit_code or 1
            print(f"[停止] 批量调度异常（{type(exc).__name__}），不继续后续用例。", flush=True)
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)
            for row in rows:
                if row["status"] == "running":
                    code = "interrupted" if exit_code >= 128 else "runner_error"
                    row.update(status="interrupted" if exit_code >= 128 else "failed",
                               exit_code=exit_code, reason_code=code, reason=FAILURE_REASONS[code],
                               finished_at=datetime.now().isoformat(timespec="seconds"))
                    for attempt in row.get("attempts", []):
                        if attempt["status"] == "running":
                            attempt.update(status=row["status"], exit_code=exit_code,
                                           reason_code=code, reason=FAILURE_REASONS[code],
                                           finished_at=row["finished_at"], retry_safe=False)
            summary = {"exit_code": exit_code, "interval_seconds": 10, "retry_delay_seconds": 5,
                       "max_retries": 1 if platform == "ios" else 0, "cases": rows}
            summary_file = batch_dir / "batch_result.json"
            summary_file.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"[批量报告] {summary_file}", flush=True)
            if platform == "ios" and api_config is not None and api_config.get("enabled"):
                try:
                    from ui_framework.JRYG_api_catalog import merge_catalogs
                    print(f"[批次接口清单] {merge_catalogs(batch_dir, api_config)}", flush=True)
                except (Exception, KeyboardInterrupt) as exc:
                    print(f"[接口报告] 汇总失败（{type(exc).__name__}），不影响 UI 测试退出码。", flush=True)
            if platform == "ios":
                try:
                    from ui_framework.JRYG_dingtalk_report import notify_batch
                    notify_batch(summary_file)
                except (Exception, KeyboardInterrupt) as exc:
                    print(f"[钉钉报告] 通知异常（{type(exc).__name__}），不影响测试退出码，不自动重发。", flush=True)
        return exit_code


def batch_order(case_files):
    """包车两渠道在前，打表线上支付在后，现金最后；保留全部已有场景。"""
    names = (
        "JRYG_test_ios_charter_alipay_order.py",
        "JRYG_test_ios_charter_bankcard_order.py",
        "JRYG_test_ios_meter_epayment_alipay_order.py",
        "JRYG_test_ios_meter_alipay_order.py",
        "JRYG_test_ios_meter_epayment_bankcard_order.py",
        "JRYG_test_ios_meter_cash_order.py",
    )
    ranks = {name: index for index, name in enumerate(names)}
    return sorted(case_files, key=lambda path: ranks.get(Path(path).name, len(ranks)))


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
    parser.add_argument("--retry-reopen-app", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--api-namespace", choices=("test", "dev"))
    parser.add_argument("--api-output")
    parser.add_argument("--no-api-catalog", action="store_true")
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
    api_config = None
    if not read_only:
        api_config = {"enabled": False}
        if not options.no_api_catalog:
            try:
                from ui_framework.JRYG_api_catalog import load_config
                api_config = load_config(options.api_namespace)
            except Exception as exc:
                print(f"[接口采集] 配置加载失败（{type(exc).__name__}），本轮禁用采集，不影响 UI 测试。", flush=True)
    if options.batch:
        print("[顺序] 包车Alipay HK → 包车银行卡 → 打表电子支付Alipay HK → 打表直接Alipay HK → 打表电子支付银行卡 → 打表现金", flush=True)
        if not read_only:
            return run_batch(existing_files, extra_args, report_dir=options.api_output, api_config=api_config)

    # 组装 pytest 参数
    pytest_args = [
        "-c", os.path.join(BASE_DIR, "pytest.ini"),  # 指定 pytest 配置文件
        "-v", "-s",                                   # 详细输出 + 不捕获 print
    ] + existing_files

    # 非 collect-only 模式时生成 HTML 报告
    if not any(arg in ("--collect-only", "--co") for arg in extra_args):
        pytest_args.extend([f"--html={report_file}", "--self-contained-html"])
        print(f"输出香港 iOS UI 测试报告: {report_file}")

    gate = CompletedOrderGate(retry_reopen_app=options.retry_reopen_app) if options.batch_result and not read_only else None
    capture = None
    plugins = [gate] if gate is not None else []
    if api_config is not None and api_config.get("enabled"):
        from ui_framework.JRYG_ui_trace import UITracePlugin
        api_dir = Path(options.api_output) if options.api_output else Path(REPORT_DIR) / "api_runs" / datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        capture = UITracePlugin(api_dir)
        plugins.append(capture)
        print(f"[接口采集] 香港 {api_config['namespace']}，报告目录：{api_dir}")
    try:
        exit_code = pytest.main(pytest_args + extra_args, plugins=plugins)
    finally:
        if capture is not None:
            try:
                from ui_framework.JRYG_api_catalog import finish_capture
                print(f"[接口清单] {finish_capture(capture, api_config)}", flush=True)
            except (Exception, KeyboardInterrupt) as exc:
                print(f"[接口报告] 生成失败（{type(exc).__name__}），不影响 UI 测试退出码，不重跑订单。", flush=True)
    if gate is not None:
        if gate.interrupted:
            exit_code = 130
        if exit_code == 0 and (len(gate.completed_orders) != 1 or gate.failures):
            exit_code = 1
            print("[失败] 用例被跳过、存在阶段失败或没有完成订单，记录后继续批次下一例。")
        if exit_code != 0 and not gate.failures:
            gate.failures.append(failure_detail("runner", reason_code="child_failed"))
        result_file = Path(options.batch_result)
        result_file.write_text(json.dumps({"exit_code": int(exit_code), "completed_orders": gate.completed_orders,
                                          "failures": gate.failures,
                                          "retry_safe": gate.retry_safe and not gate.completed_orders and not gate.interrupted,
                                          "reason": "; ".join(detail["reason"] for detail in gate.failures)},
                                          ensure_ascii=False, indent=2), encoding="utf-8")

    print("="*50)
    print("      JRYG 港版阳光出行 iOS 测试执行引擎 -ios (Completed)")
    print("="*50 + "\n")
    return exit_code

if __name__ == "__main__":
    # 直接运行此文件时，透传命令行参数给 run_tests
    sys.exit(run_tests(sys.argv[1:]))
