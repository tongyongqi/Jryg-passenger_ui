"""iOS独立用例启动桥接：复用Shell准备WDA，再只执行当前场景。

保留当前Python解释器、命令行参数和退出码。仅收集/帮助由Shell直接透传，
不连接设备；正式运行失败时不会降级为静默跳过，也不启动其他订单场景。
"""

import os
from pathlib import Path
import signal
import subprocess
import sys
import time


BASE_DIR = Path(__file__).resolve().parents[1]


def run_case(case_file, argv=None):
    """验证自有case路径，委托唯一WDA启动脚本；中断后等待其清理所建子进程。"""
    path = Path(case_file).resolve()
    if path.parent != BASE_DIR / "cases" or not path.name.startswith("JRYG_test_ios_") or path.suffix != ".py" or not path.is_file():
        raise ValueError("直接入口只能执行本项目cases内的iOS场景文件")
    args = list(sys.argv[1:] if argv is None else argv)
    env = os.environ.copy()
    env["HK_IOS_PYTHON"] = sys.executable
    command = ["bash", str(BASE_DIR / "runners/JRYG_run_hk_ios.sh"), "--case", str(path), *args]
    process = None
    interrupted_code = 0
    cleanup_deadline = None

    def stop_run(signum, frame):
        nonlocal interrupted_code, cleanup_deadline
        interrupted_code = 128 + signum
        if cleanup_deadline is None:
            cleanup_deadline = time.monotonic() + 15
            print("[清理] 收到中断或暂停请求，结束本次运行，不保留暂停的订单任务。", flush=True)
        if process is not None and process.poll() is None:
            try:
                process.terminate()
            except ProcessLookupError:
                pass

    previous_handlers = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGTSTP)}
    try:
        for sig in previous_handlers:
            signal.signal(sig, stop_run)
        process = subprocess.Popen(command, cwd=BASE_DIR, env=env, start_new_session=True)
        if interrupted_code:
            stop_run(interrupted_code - 128, None)
        while True:
            try:
                exit_code = process.wait(timeout=0.5)
                return interrupted_code or exit_code
            except subprocess.TimeoutExpired:
                if cleanup_deadline is not None and time.monotonic() >= cleanup_deadline:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.wait()
                    return interrupted_code
    finally:
        if process is not None and process.poll() is None:
            try:
                process.terminate()
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
        for sig, handler in previous_handlers.items():
            signal.signal(sig, handler)
