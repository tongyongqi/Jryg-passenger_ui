import subprocess
import time
from JRYG_Passenger_UI.common.JRYG_logger import logger
from JRYG_Passenger_UI.common.JRYG_config import SETTINGS

class JRYG_ADBTools:
    """ADB 移动端命令交互基础工具封装"""
    def __init__(self, udid=None):
        self.udid = udid or SETTINGS["device"]["udid"]

    def run_cmd(self, cmd):
        """执行有超时和退出码检查的 ADB Shell 命令。"""
        full_cmd = ["adb", "-s", self.udid, "shell"] + cmd
        res = subprocess.run(full_cmd, capture_output=True, text=True, timeout=15, check=True)
        if res.stderr.strip().startswith("Error"):
            raise RuntimeError(res.stderr.strip())
        return res.stdout.strip()

    def get_top_activity(self):
        """实时获取设备顶层活跃的 Activity 栈信息"""
        out = self.run_cmd(["dumpsys", "activity", "activities"])
        for marker in ("topResumedActivity", "mResumedActivity", "ResumedActivity"):
            for line in out.splitlines():
                if marker in line:
                    return line.strip()
        return "unknown"

    def force_stop(self, package):
        """强制杀死指定的 Android App 进程"""
        logger.info(f"强制终止 App 进程: {package}")
        self.run_cmd(["am", "force-stop", package])

    def start_app(self, package, activity):
        """根据包名与核心入口 Activity 启动 App"""
        logger.info(f"拉起 Android App: {package}/{activity}")
        self.run_cmd(["am", "start", "-n", f"{package}/{activity}"])

    def tap(self, x, y):
        """通过物理像素坐标执行点击"""
        logger.info(f"坐标点击操作: ({x}, {y})")
        self.run_cmd(["input", "tap", str(x), str(y)])

    def input_text(self, text):
        """通过第三方剪贴板工具安全键入字符串文本（规避原生 adb 输入中文乱码）"""
        escaped = text.replace("'", "'\\''")
        self.run_cmd(["am", "broadcast", "-a", "clipper.set", "-e", "text", f"'{escaped}'"])
        time.sleep(0.5)
        self.run_cmd(["input", "keyevent", "KEYCODE_PASTE"])
        logger.info(f"剪贴板文本写入: {text}")

    def press_key(self, keycode):
        """触发特定的物理按键值事件"""
        self.run_cmd(["input", "keyevent", str(keycode)])

    def back(self):
        """执行硬件返回键"""
        self.press_key(4)
