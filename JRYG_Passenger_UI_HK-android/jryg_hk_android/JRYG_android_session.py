"""安卓会话互斥与端口预检，不终止外部会话或删除ADB转发。"""

import fcntl
import hashlib
from pathlib import Path
import socket
import subprocess

BASE_DIR = Path(__file__).resolve().parents[1]


class AndroidSessionLease:
    def __init__(self, udid, system_port, *, directory=None):
        if isinstance(system_port, bool) or not isinstance(system_port, int) or not 1024 <= system_port <= 65535:
            raise ValueError("Android system_port必须是1024至65535之间的整数")
        self.udid = udid
        self.system_port = system_port
        self.directory = Path(directory) if directory is not None else BASE_DIR / "logs/.android-sessions"
        self.handles = []

    def acquire(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        device_key = hashlib.sha256(self.udid.encode("utf-8")).hexdigest()[:16]
        try:
            for key, message in (
                ("device-" + device_key, f"Android设备{self.udid}已有本项目测试运行，禁止重叠会话"),
                (f"port-{self.system_port}", f"Android system_port {self.system_port}已被本项目会话占用"),
            ):
                handle = (self.directory / (key + ".lock")).open("a+")
                try:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    handle.close()
                    raise RuntimeError(message) from None
                self.handles.append(handle)
            self.check_available()
            return self
        except BaseException:
            self.release()
            raise

    def check_available(self):
        result = subprocess.run(["adb", "forward", "--list"], capture_output=True,
                                text=True, timeout=10, check=True)
        for line in result.stdout.splitlines():
            values = line.split()
            if len(values) != 3:
                continue
            serial, local, remote = values
            if serial == self.udid and remote == "tcp:6790":
                raise RuntimeError(
                    f"Android设备{self.udid}已有UiAutomator2转发{local}，可能存在活跃或残留会话；"
                    "请先结束原会话，未自动关闭其他测试或删除转发")
            if local == f"tcp:{self.system_port}":
                raise RuntimeError(
                    f"Android system_port {self.system_port}被ADB转发占用；请先结束占用端口的原会话，"
                    "未自动删除转发")
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                probe.bind(("127.0.0.1", self.system_port))
        except OSError as exc:
            raise RuntimeError(
                f"Android system_port {self.system_port}不可用：请先结束占用端口的原会话；"
                "未自动杀进程、切换设备或重复建连") from exc

    def release(self):
        handles, self.handles = self.handles, []
        for handle in reversed(handles):
            try:
                fcntl.flock(handle, fcntl.LOCK_UN)
            finally:
                handle.close()
