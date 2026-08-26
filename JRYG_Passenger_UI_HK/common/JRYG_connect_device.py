"""
港版阳光出行——真机设备物理通道连接与交互二次封装（自适应 Android/iOS 双端）
"""

import time
import os
import sys
import subprocess

from appium import webdriver
from appium.webdriver.common.appiumby import AppiumBy
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# 支持导入同层级公共模块
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from JRYG_Passenger_UI_HK.common.JRYG_config import SETTINGS
from JRYG_Passenger_UI_HK.common.JRYG_logger import logger


class JRYG_HKDevice:
    """自适应 Android 和 iOS 双平台的一键真机 App 唤起与连接类"""

    def __init__(self):
        self.driver: webdriver.Remote = None
        self.device_cfg = SETTINGS.get("device", {})
        self.pkg_cfg = SETTINGS.get("packages", {})
        
        self.platform = self.device_cfg.get("platform_name", "iOS").upper()
        self.udid = self.device_cfg.get("udid", "00008120-000E79E03472201E")
        self.app_pkg = self.pkg_cfg.get("passenger_hk", "com.jryg.client.hk")
        self.app_activity = self.pkg_cfg.get("passenger_hk_activity", "")

    def connect(self) -> webdriver.Remote:
        """
        核心连接入口：根据 settings.yaml 配置自动调度 Android/iOS 连接策略
        """
        appium_url = f"http://{self.device_cfg.get('appium_host', '127.0.0.1')}:{self.device_cfg.get('appium_port', 4723)}"
        logger.info(f"【港版连接】启动 Appium 自动化 Session. URL: {appium_url} | 平台: {self.platform}")

        if self.platform == "IOS":
            return self._connect_ios(appium_url)
        else:
            return self._connect_android(appium_url)

    def _connect_ios(self, appium_url: str) -> webdriver.Remote:
        """iOS 平台专属 Appium (XCUITest) 连接策略"""
        from appium.options.ios import XCUITestOptions
        
        options = XCUITestOptions()
        options.platform_name = "iOS"
        options.udid = self.udid
        options.device_name = self.device_cfg.get("device_name", "iPhone111111")
        options.platform_version = self.device_cfg.get("platform_version", "26.5")
        options.automation_name = "XCUITest"
        
        # 强制配置免安装 WDA，指向本地转发的 8100 端口，实现毫秒级快速启动
        wda_url = self.device_cfg.get("wda_url", "http://127.0.0.1:8100")
        options.web_driver_agent_url = wda_url
        
        options.bundle_id = self.app_pkg
        options.no_reset = True
        options.auto_grant_permissions = True
        options.new_command_timeout = 600

        logger.info(f"【iOS】正在通过 WDA 快速拉起港版 App '{self.app_pkg}'...")
        self.driver = webdriver.Remote(appium_url, options=options)
        logger.info(f"【iOS】拉起成功！Session ID: {self.driver.session_id}")
        return self.driver

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

    # ==================== 跨平台快捷定位方法封装 ====================

    def find_element(self, locator: tuple, timeout: int = 15):
        """高容错显式等待查找元素"""
        return WebDriverWait(self.driver, timeout).until(
            EC.presence_of_element_located(locator)
        )

    def click_element(self, locator: tuple, timeout: int = 15):
        """高容错显式等待并点击元素"""
        element = WebDriverWait(self.driver, timeout).until(
            EC.element_to_be_clickable(locator)
        )
        element.click()

    def is_element_present(self, locator: tuple, timeout: int = 4) -> bool:
        """判定元素当前是否存在"""
        try:
            WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located(locator)
            )
            return True
        except Exception:
            return False

    @staticmethod
    def by_id(resource_id: str):
        return AppiumBy.ID, resource_id

    @staticmethod
    def by_text(text: str, platform="iOS"):
        if platform.upper() == "IOS":
            # iOS 采用更加稳定高效的 Class Chain 定位文本
            return AppiumBy.iOS_CLASS_CHAIN, f'**/XCUIElementTypeAny[`label == "{text}"`]'
        else:
            return AppiumBy.ANDROID_UIAUTOMATOR, f'new UiSelector().text("{text}")'

    @staticmethod
    def by_xpath(xpath: str):
        return AppiumBy.XPATH, xpath
