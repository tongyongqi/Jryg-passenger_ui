"""港版阳光出行 iOS 真机连接。

通过独立的 iOS 设备配置连接 Appium / WDA，
只允许连接测试环境指定的本地或内网 Appium 通道。
"""

from appium import webdriver
from appium.options.ios import XCUITestOptions

from .JRYG_config import SETTINGS
from .JRYG_logger import logger


class JRYG_HKDevice:
    """通过独立 iOS 配置连接 Appium / WDA。"""

    def __init__(self):
        """读取设备与包名配置，初始化连接所需的全部基础参数。"""
        # Appium 会话对象，未连接时为 None
        self.driver = None
        # 设备相关配置（udid、版本、Appium 地址等）
        self.device_cfg = SETTINGS.get("device", {})
        # 包名配置（乘客端 bundleId 等）
        self.pkg_cfg = SETTINGS.get("packages", {})
        # 平台名统一大写比较
        self.platform = self.device_cfg.get("platform_name", "iOS").upper()
        # 真机唯一标识
        self.udid = self.device_cfg["udid"]
        # 乘客端 App 包名
        self.app_pkg = self.pkg_cfg["passenger_hk"]

    def connect(self):
        """建立 Appium 连接，返回 webdriver 会话。

        非 iOS 配置直接报错，避免误用安卓设备配置。
        """
        if self.platform != "IOS":
            raise ValueError("iOS 目录只能使用 iOS 设备配置")
        # Appium 服务地址，默认本机 4723 端口
        host = self.device_cfg.get("appium_host", "127.0.0.1")
        port = self.device_cfg.get("appium_port", 4723)
        return self._connect_ios(f"http://{host}:{port}")

    def _connect_ios(self, appium_url):
        """按 XCUITest 能力创建 iOS 会话。

        no_reset=True 保留 App 登录态，new_command_timeout 放宽空闲回收时间。
        """
        options = XCUITestOptions()
        options.platform_name = "iOS"
        options.udid = self.udid
        options.device_name = self.device_cfg.get("device_name", "iPhone 15")
        options.platform_version = self.device_cfg["platform_version"]
        options.automation_name = "XCUITest"
        # 复用已启动的 WebDriverAgent，避免每次重新安装
        options.web_driver_agent_url = self.device_cfg.get("wda_url", "http://127.0.0.1:8100")
        options.bundle_id = self.app_pkg
        # 不重置 App，保留登录态与历史数据
        options.no_reset = True
        # 命令空闲超时 600 秒，防止长时间等待时被断开
        options.new_command_timeout = 600
        logger.info(f"【iOS】连接 {appium_url}，启动 {self.app_pkg}")
        self.driver = webdriver.Remote(appium_url, options=options)
        return self.driver

    def disconnect(self):
        """释放 Appium 会话，避免占用真机通道。"""
        if self.driver:
            self.driver.quit()
            self.driver = None
            logger.info("【iOS】Session 通道已释放")
