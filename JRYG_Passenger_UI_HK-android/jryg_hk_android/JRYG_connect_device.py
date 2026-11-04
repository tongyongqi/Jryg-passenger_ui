"""港版阳光出行 Android 真机连接。"""

import time
import subprocess

from appium import webdriver

from .JRYG_config import SETTINGS
from .JRYG_logger import logger


class JRYG_HKDevice:
    """管理港版乘客 App 的真机配置、UiAutomator2 会话建立与释放。"""

    def __init__(self):
        """读取设备、包名和启动页配置，初始化未连接的驱动引用。"""
        self.driver: webdriver.Remote = None
        self.device_cfg = SETTINGS.get("device", {})
        self.pkg_cfg = SETTINGS.get("packages", {})
        
        self.platform = self.device_cfg.get("platform_name", "Android").upper()
        self.udid = self.device_cfg["udid"]
        self.app_pkg = self.pkg_cfg["passenger_hk"]
        self.app_activity = self.pkg_cfg["passenger_hk_activity"]

    def connect(self) -> webdriver.Remote:
        """拒绝非 Android 配置，按配置拼接 Appium 地址并建立真机会话。"""
        if self.platform != "ANDROID":
            raise ValueError("Android 目录只能使用 Android 设备配置")
        appium_url = f"http://{self.device_cfg.get('appium_host', '127.0.0.1')}:{self.device_cfg.get('appium_port', 4723)}"
        logger.info(f"【港版连接】启动 Appium 自动化 Session. URL: {appium_url} | 平台: {self.platform}")
        return self._connect_android(appium_url)

    def _connect_android(self, appium_url: str) -> webdriver.Remote:
        """先清理自动化资源，再保留应用数据、配置自动授权并建立启动乘客 App 的会话。"""
        from appium.options.android import UiAutomator2Options
        
        self._clean_android_uia2()
        
        options = UiAutomator2Options()
        options.platform_name = "Android"
        options.udid = self.udid
        options.automation_name = "UiAutomator2"
        options.device_name = self.device_cfg.get("device_name", "Android_Device")
        options.system_port = self.device_cfg.get("system_port", 8201)
        
        options.app_package = self.app_pkg
        options.app_activity = self.app_activity if self.app_activity else "com.jryg.client.activity.loading.YGALoadingActivity"
        
        options.no_reset = True
        options.auto_grant_permissions = True
        options.new_command_timeout = 600
        options.set_capability("appium:adbExecTimeout", 60000)
        options.set_capability("appium:uiautomator2ServerInstallTimeout", 60000)
        options.set_capability("appium:uiautomator2ServerLaunchTimeout", 60000)
        options.set_capability("appium:disableWindowAnimation", True)

        logger.info(f"【Android】正在启动并拉起港版 App '{self.app_pkg}'...")
        self.driver = webdriver.Remote(appium_url, options=options)
        logger.info(f"【Android】拉起成功！Session ID: {self.driver.session_id}")
        return self.driver

    def _clean_android_uia2(self):
        """尽力停止自动化进程并清除 ADB 转发，可能中断已有自动化会话。

        强停固定的 UiAutomator2/Poco 包，杀掉匹配进程，并调用 forward --remove-all；
        各命令不校验退出码，发生异常时记录警告后继续连接，并不保证清理成功。
        """
        try:
            automation_packages = (
                "io.appium.uiautomator2.server",
                "io.appium.uiautomator2.server.test",
                "com.netease.open.pocoservice",
                "com.netease.open.pocoservice.test",
            )
            for package in automation_packages:
                subprocess.run(
                    ["adb", "-s", self.udid, "shell", "am", "force-stop", package],
                    capture_output=True,
                    timeout=5,
                )
            subprocess.run(
                ["adb", "-s", self.udid, "shell", "pkill", "-f", "uiautomator"],
                capture_output=True,
                timeout=5,
            )
            subprocess.run(
                ["adb", "-s", self.udid, "forward", "--remove-all"],
                capture_output=True,
                timeout=5,
            )
            time.sleep(1)
            logger.info("【Android】已清理 UiAutomator2/Poco 残留进程并重置 ADB 端口转发")
        except Exception as exc:
            logger.warning(f"【Android】自动化残留进程清理未完全执行: {exc}")

    def disconnect(self):
        """驱动存在时结束 Appium 会话并记录断开结果，不捕获退出异常或清空引用。"""
        if self.driver:
            self.driver.quit()
            logger.info("【港版连接】Session 通道已安全断开并释放")
