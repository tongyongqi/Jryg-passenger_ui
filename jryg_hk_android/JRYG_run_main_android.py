"""JRYG_Passenger_UI_HK-android 自动化模块 —— JRYG_run_main_android.py

港版阳光出行 Android 乘客端 UI 自动化测试批次运行入口。
提供 CompletedOrderGate、batch_order、run_batch，不依赖任何 Android 代码。
"""

from datetime import datetime
import fcntl
import json
import os
from pathlib import Path
import signal
import sys
import time
import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)


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


def run_batch(case_files, extra_args, *, run_case=None, report_dir=None, platform="android"):
    """Android 批次门禁；完成凭据通过后等待10秒。"""
    if run_case is None:
        from .JRYG_run_case_android import run_case

    if os.environ.get("HK_DRIVER_UI_STOP_AFTER", "submitted") != "submitted":
        print("[错误] 批量不能使用仅接单模式，必须完成行程及同订单支付核验。")
        return 2
    if any(arg == "--html" or arg.startswith("--html=") for arg in extra_args):
        print("[错误] 批量自动保存独立报告，请勿用--html覆盖所有用例的报告。")
        return 2
    from .JRYG_config import REPORT_DIR as ANDROID_REPORT_DIR
    report_root = Path(ANDROID_REPORT_DIR if report_dir is None else report_dir)
    report_root.mkdir(parents=True, exist_ok=True)
    with (report_root / f".{platform}-batch.lock").open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("[错误] 已有Android批次运行，拒绝重叠执行。")
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
        return exit_code


def batch_order(case_files):
    """双端使用同一批次顺序：包车两例在前，打表四例在后。"""
    return case_files[4:] + case_files[:4]
