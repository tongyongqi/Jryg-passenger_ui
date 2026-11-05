"""每天10:45执行香港iOS批次；系统须提前唤醒，不解锁Mac或保存电脑密码。"""

import argparse
from contextlib import contextmanager
from datetime import datetime, time as clock_time
import fcntl
import json
import os
from pathlib import Path
import plistlib
import signal
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
PROJECT = ROOT / "JRYG_Passenger_UI_HK-ios"
LABEL = "com.jryg.hk-ios.daily"
REPORT_DIR = PROJECT / "report"
LOG_DIR = PROJECT / "logs" / "scheduled"
PYTHON = ROOT / ".venv" / "bin" / "python"
ENTRY = ROOT / "香港乘客iOS包车打表六场景.py"
WINDOW_START = clock_time(10, 45)
WINDOW_END = clock_time(10, 55)


def log(message):
    print(f"[{datetime.now().isoformat(timespec='seconds')}] {message}", flush=True)


def in_schedule_window(now):
    return WINDOW_START <= now.time() < WINDOW_END


def mac_state():
    result = subprocess.run(
        ["/usr/sbin/ioreg", "-n", "Root", "-d", "1", "-a"],
        capture_output=True, check=True, timeout=5,
    )
    value = plistlib.loads(result.stdout)
    roots = value if isinstance(value, list) else [value]
    uid = os.getuid()
    console_uid = Path("/dev/console").stat().st_uid
    sessions = [user for root in roots if isinstance(root, dict)
                for user in root.get("IOConsoleUsers", []) if isinstance(user, dict)]
    logged_in = console_uid == uid and any(
        user.get("kCGSSessionUserIDKey") == uid
        and user.get("kCGSSessionOnConsoleKey") is True
        and user.get("kCGSessionLoginDoneKey") is True for user in sessions
    )
    locked = next((root.get("IOConsoleLocked") for root in roots if isinstance(root, dict)
                   and isinstance(root.get("IOConsoleLocked"), bool)), None)
    power = subprocess.run(["/usr/bin/pmset", "-g", "batt"], capture_output=True,
                           text=True, check=True, timeout=5)
    return {"logged_in": logged_in, "locked": locked, "ac_power": "'AC Power'" in power.stdout}


@contextmanager
def awake_for_run():
    hold = subprocess.Popen(["/usr/bin/caffeinate", "-i", "-s", "-w", str(os.getpid())])
    try:
        subprocess.run(["/usr/bin/caffeinate", "-u", "-t", "5"], check=True, timeout=8)
        if hold.poll() is not None:
            raise RuntimeError("防休眠进程未保持运行，停止任务")
        yield
    finally:
        if hold.poll() is None:
            hold.terminate()
        try:
            hold.wait(timeout=5)
        except subprocess.TimeoutExpired:
            hold.kill()
            hold.wait(timeout=5)


def execute_batch():
    environment = os.environ.copy()
    environment["PATH"] = ":".join(dict.fromkeys([
        str(PYTHON.parent), "/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin",
        "/usr/sbin", "/sbin", *environment.get("PATH", "").split(":"),
    ]))
    child = subprocess.Popen([str(PYTHON), str(ENTRY)], cwd=str(ROOT), env=environment,
                             start_new_session=True)
    previous = {}

    def forward(signum, _frame):
        if child.poll() is None:
            try:
                os.killpg(child.pid, signum)
            except ProcessLookupError:
                pass

    try:
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            previous[sig] = signal.signal(sig, forward)
        return child.wait()
    finally:
        if child.poll() is None:
            forward(signal.SIGTERM, None)
            child.wait()
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def run_scheduled():
    now = datetime.now()
    if not in_schedule_window(now):
        log("不在10:45—10:55启动窗口；跳过睡眠后迟到补跑，不下单或付款")
        return 0
    if not PYTHON.is_file() or not os.access(PYTHON, os.X_OK) or not ENTRY.is_file():
        log("项目Python或六场景入口不存在，停止任务")
        return 2
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    with (REPORT_DIR / ".ios-scheduled.lock").open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            log("已有定时任务执行中，跳过重复触发")
            return 0
        state_file = REPORT_DIR / "ios_schedule_result.json"
        previous = json.loads(state_file.read_text(encoding="utf-8")) if state_file.exists() else {}
        if previous.get("date") == now.date().isoformat():
            log("当天已启动过定时批次，不因失败或重新唤醒自动重跑")
            return 0
        state = mac_state()
        log("Mac系统已运行；锁屏状态：" + {True: "已锁屏", False: "未锁屏", None: "无法确认"}[state["locked"]])
        if not state["logged_in"]:
            log("未确认当前用户已登录控制台；需先登录Mac，不能自动越过登录或FileVault")
            return 2
        if not state["ac_power"]:
            log("Mac未接电，跳过定时批次；防系统休眠保护需要AC供电")
            return 2
        with awake_for_run():
            state = mac_state()
            if not state["logged_in"] or not state["ac_power"]:
                log("唤醒准备期间用户会话或供电发生变化，停止，不启动订单")
                return 2
            now = datetime.now()
            if not in_schedule_window(now):
                log("准备完成时已超过启动窗口，跳过，不补跑")
                return 0
            record = {"date": now.date().isoformat(), "started_at": now.isoformat(timespec="seconds"),
                      "status": "started", "mac_locked": state["locked"]}
            state_file.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
            log("已申请点亮显示器及运行期防休眠；不输入电脑密码、不解除屏幕锁定")
            log("启动香港iOS六场景；沿用批次锁、iPhone解锁、失败停止与钉钉报告")
            try:
                exit_code = execute_batch()
            except Exception as exc:
                exit_code = 2
                log(f"任务启动异常（{type(exc).__name__}），不自动重试")
            record.update(status="completed" if exit_code == 0 else "failed", exit_code=exit_code,
                          finished_at=datetime.now().isoformat(timespec="seconds"))
            state_file.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
            return exit_code


def main(argv=None):
    parser = argparse.ArgumentParser(description="Mac先由pmset提前唤醒，10:45启动UI自动化；默认仅检查")
    parser.add_argument("--run", action="store_true", help="在早晨窗口真实执行订单和付款，不自动重试")
    args = parser.parse_args(argv)
    if sys.platform != "darwin" or os.getuid() == 0:
        log("必须由已登录的普通macOS用户运行，不以root执行订单")
        return 2
    try:
        if args.run:
            return run_scheduled()
        state = mac_state()
        log("只读检查：" + json.dumps(state, ensure_ascii=False))
        log("休眠中的电脑无法执行此脚本；需提前设置每日10:40的pmset唤醒")
        log("未执行订单，未唤醒显示器，未启用定时任务")
        return 0
    except Exception as exc:
        log(f"定时入口失败（{type(exc).__name__}），停止，不重跑订单")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
