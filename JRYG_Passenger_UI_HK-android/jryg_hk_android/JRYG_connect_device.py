"""港版阳光出行 Android 真机连接。"""

import time
import subprocess

from appium import webdriver

from .JRYG_config import SETTINGS
from .JRYG_logger import logger


class JRYG_HKDevice:
    """Android 真机 App 唤起与连接。"""

    def __init__(self):
        self.driver: webdriver.Remote = None
        self.device_cfg = SETTINGS.get("device", {})
        self.pkg_cfg = SETTINGS.get("packages", {})
        
        self.platform = self.device_cfg.get("platform_name", "Android").upper()
        self.udid = self.device_cfg["udid"]
        self.app_pkg = self.pkg_cfg["passenger_hk"]
        self.app_activity = self.pkg_cfg["passenger_hk_activity"]

    def connect(self) -> webdriver.Remote:
        """读取本目录的 Android 配置并建立连接。"""
        if self.platform != "ANDROID":
            raise ValueError("Android 目录只能使用 Android 设备配置")
        appium_url = f"http://{self.device_cfg.get('appium_host', '127.0.0.1')}:{self.device_cfg.get('appium_port', 4723)}"
        logger.info(f"【港版连接】启动 Appium 自动化 Session. URL: {appium_url} | 平台: {self.platform}")
        return self._connect_android(appium_url)

    def _connect_android(self, appium_url: str) -> webdriver.Remote:
        """Android 平台专属 Appium (UiAutomator2) 连接策略"""
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
        """清理 Android 设备上可能与 Appium 冲突的 UiAutomator2/Poco 自动化进程"""
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
        """安全释放 Session 通道"""
        if self.driver:
            self.driver.quit()
            logger.info("【港版连接】Session 通道已安全断开并释放")
