"""港版阳光出行 iOS 真机连接。"""

from appium import webdriver
from appium.options.ios import XCUITestOptions

from .JRYG_config import SETTINGS
from .JRYG_logger import logger


class JRYG_HKDevice:
    """通过独立 iOS 配置连接 Appium / WDA。"""

    def __init__(self):
        self.driver = None
        self.device_cfg = SETTINGS.get("device", {})
        self.pkg_cfg = SETTINGS.get("packages", {})
        self.platform = self.device_cfg.get("platform_name", "iOS").upper()
        self.udid = self.device_cfg["udid"]
        self.app_pkg = self.pkg_cfg["passenger_hk"]

    def connect(self):
        if self.platform != "IOS":
            raise ValueError("iOS 目录只能使用 iOS 设备配置")
        host = self.device_cfg.get("appium_host", "127.0.0.1")
        port = self.device_cfg.get("appium_port", 4723)
        return self._connect_ios(f"http://{host}:{port}")

    def _connect_ios(self, appium_url):
        options = XCUITestOptions()
        options.platform_name = "iOS"
        options.udid = self.udid
        options.device_name = self.device_cfg.get("device_name", "iPhone 15")
        options.platform_version = self.device_cfg["platform_version"]
        options.automation_name = "XCUITest"
        options.web_driver_agent_url = self.device_cfg.get("wda_url", "http://127.0.0.1:8100")
        options.bundle_id = self.app_pkg
        options.no_reset = True
        options.new_command_timeout = 600
        logger.info(f"【iOS】连接 {appium_url}，启动 {self.app_pkg}")
        self.driver = webdriver.Remote(appium_url, options=options)
        return self.driver

    def disconnect(self):
        if self.driver:
            self.driver.quit()
            self.driver = None
            logger.info("【iOS】Session 通道已释放")
