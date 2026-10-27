import subprocess
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

    def press_key(self, keycode):
        """触发特定的物理按键值事件"""
        self.run_cmd(["input", "keyevent", str(keycode)])

    def back(self):
        """执行硬件返回键"""
        self.press_key(4)

    # ==================== 代理检测与清除 ====================

    def get_http_proxy(self):
        """读取设备当前 HTTP 代理设置（settings global http_proxy）。

        :return: 代理地址字符串，无代理时返回空字符串
        """
        return self.run_cmd(["settings", "get", "global", "http_proxy"])

    def get_global_http_proxy(self):
        """读取设备 global_http_proxy 设置（部分系统用此 key 存储代理）。

        :return: 代理地址字符串，无代理时返回空字符串
        """
        return self.run_cmd(["settings", "get", "global", "global_http_proxy"])

    def has_proxy(self):
        """检测设备是否设置了 HTTP 代理。

        同时检查 http_proxy 和 global_http_proxy 两个 key，
        任一非空且非 ":0"/"null"/"None" 即判定存在代理。

        :return: (has_proxy: bool, proxy_value: str) — 是否有代理、代理值
        """
        # 无效值列表：空、":0"、"null"（settings get 未设置时返回 null）
        invalid = {"", ":0", "null", "None"}
        proxy = self.get_http_proxy()
        if proxy and proxy not in invalid:
            return True, proxy
        proxy = self.get_global_http_proxy()
        if proxy and proxy not in invalid:
            return True, proxy
        return False, ""

    def clear_http_proxy(self):
        """清除设备 HTTP 代理设置。

        删除 http_proxy 和 global_http_proxy 两个 key，
        并发送 PROXY_CHANGE 广播让系统立即生效。
        """
        self.run_cmd(["settings", "delete", "global", "http_proxy"])
        self.run_cmd(["settings", "delete", "global", "global_http_proxy"])
        # 发送广播触发系统重新加载代理设置，使清除立即生效
        # 注意：部分设备广播命令返回非零退出码但实际已生效，不强制 check
        full_cmd = ["adb", "-s", self.udid, "shell", "am", "broadcast",
                     "-a", "android.intent.action.PROXY_CHANGE"]
        subprocess.run(full_cmd, capture_output=True, text=True, timeout=15)
        logger.info(f"已清除设备 {self.udid} 的 HTTP 代理设置")

    def check_and_clear_proxy(self):
        """检测设备是否存在代理，存在则自动清除。

        典型用法：测试启动前调用，确保设备无代理干扰接口请求。

        :return: True 表示已清除代理（原本存在代理），False 表示无需清除（原本无代理）
        """
        has, proxy = self.has_proxy()
        if has:
            logger.warning(f"检测到设备 {self.udid} 存在代理: {proxy}，正在清除...")
            self.clear_http_proxy()
            # 清除后二次确认
            still_has, _ = self.has_proxy()
            if still_has:
                logger.error(f"代理清除失败，设备 {self.udid} 仍存在代理")
                return False
            logger.info(f"设备 {self.udid} 代理已成功清除")
            return True
        else:
            logger.info(f"设备 {self.udid} 未检测到代理，无需清除")
            return False
