"""大陆 iOS 真机连接与基础操作封装。

通过 Appium XCUITest 驱动连接 iPhone 真机，提供与安卓端 AndroidDevice 对应的基础能力。
"""

import time
from pathlib import Path

from appium import webdriver
from appium.options.ios import XCUITestOptions
from appium.webdriver.common.appiumby import AppiumBy
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException

from .JRYG_config import SETTINGS, SCREENSHOTS_DIR
from .JRYG_logger import logger


class IOSDevice:
    """iOS 真机连接与操作封装"""

    def __init__(self):
        """IOSDevice.__init__ —— 内部辅助方法：init  。

        :return: None"""
        self.driver: webdriver.Remote = None
        self.device_cfg = SETTINGS["device"]
        self.pkg_cfg = SETTINGS["packages"]
        self.udid = self.device_cfg["udid"]
        self.app_bundle = self.pkg_cfg["passenger"]

    def connect(self) -> webdriver.Remote:
        """连接 iOS 真机并启动 App"""
        options = XCUITestOptions()
        options.platform_name = "iOS"
        options.udid = self.udid
        options.device_name = self.device_cfg.get("device_name", "iPhone 15")
        options.platform_version = self.device_cfg["platform_version"]
        options.automation_name = "XCUITest"

        wda_url = self.device_cfg.get("wda_url", "http://127.0.0.1:8100")
        options.web_driver_agent_url = wda_url

        options.bundle_id = self.app_bundle
        options.no_reset = True
        options.new_command_timeout = 600

        appium_url = f"http://{self.device_cfg.get('appium_host', '127.0.0.1')}:{self.device_cfg.get('appium_port', 4723)}"
        logger.info(f"【iOS 连接】Appium Server: {appium_url} | 设备 UDID: {self.udid}")
        logger.info(f"【iOS 连接】正在启动 session，请稍候...")

        self.driver = webdriver.Remote(appium_url, options=options)
        logger.info(f"【iOS 连接】成功！Session ID: {self.driver.session_id}")

        self._wait_for_home()
        return self.driver

    def _wait_for_home(self, ad_timeout: int = 3):
        """等待广告/闪屏结束后进入首页"""
        logger.info(f"【广告】等待 {ad_timeout} 秒后进入首页...")
        time.sleep(ad_timeout)

        # 尝试关闭广告弹窗
        skip_keywords = ["跳过", "跳过广告", "我知道了"]
        for keyword in skip_keywords:
            try:
                el = self.driver.find_element(*self.by_text(keyword))
                el.click()
                logger.info(f"【广告】已点击'{keyword}'")
                time.sleep(1)
                break
            except (NoSuchElementException, Exception):
                continue

        logger.info("【广告】弹窗检查完成")

    def disconnect(self):
        """断开连接"""
        if self.driver:
            try:
                self.driver.quit()
            finally:
                self.driver = None
            logger.info("【iOS 断开】Session 已关闭")

    def tap(self, x: int, y: int):
        """通过物理像素坐标执行单击操作"""
        self.driver.tap([(x, y)], duration=100)

    def click(self, x_ratio: float, y_ratio: float):
        """通过屏幕比例坐标执行单击操作"""
        size = self.driver.get_window_size()
        self.tap(int(size["width"] * x_ratio), int(size["height"] * y_ratio))

    def swipe(self, start_x: int, start_y: int, end_x: int, end_y: int, duration: int = 500):
        """通过起点和终点坐标执行滑动手势"""
        self.driver.swipe(start_x, start_y, end_x, end_y, duration)

    def swipe_up(self, duration: int = 500):
        """从屏幕底部 80% 滑动至顶部 20%，模拟上划手势"""
        size = self.driver.get_window_size()
        start_x = size["width"] // 2
        start_y = int(size["height"] * 0.8)
        end_y = int(size["height"] * 0.2)
        self.swipe(start_x, start_y, start_x, end_y, duration)

    def swipe_down(self, duration: int = 500):
        """从屏幕顶部 20% 滑动至底部 80%，模拟下划手势"""
        size = self.driver.get_window_size()
        start_x = size["width"] // 2
        start_y = int(size["height"] * 0.2)
        end_y = int(size["height"] * 0.8)
        self.swipe(start_x, start_y, start_x, end_y, duration)

    def screenshot(self, filename: str = None):
        """截取当前屏幕并保存至 screenshots 目录，返回文件路径"""
        if filename is None:
            filename = f"screenshot_ios_{int(time.time())}.png"
        path = Path(filename)
        if not path.is_absolute():
            path = Path(SCREENSHOTS_DIR) / path
        path.parent.mkdir(parents=True, exist_ok=True)
        if not self.driver.save_screenshot(str(path)):
            raise RuntimeError(f"截图保存失败: {path}")
        logger.info(f"【iOS 截图】已保存: {path}")
        return str(path)

    def find_element(self, locator: tuple, timeout: int = 10, retries: int = 2):
        """在指定超时内查找并返回元素对象，超时抛出异常"""
        for attempt in range(retries + 1):
            try:
                return WebDriverWait(self.driver, timeout).until(
                    EC.presence_of_element_located(locator)
                )
            except Exception as exc:
                retryable = any(text in str(exc) for text in (
                    "socket hang up", "Connection reset", "Broken pipe"
                ))
                if not retryable or attempt == retries:
                    raise
                logger.info(f"【iOS 重试】XCUITest 连接中断 ({attempt + 1}/{retries})")
                time.sleep(3)

    def is_element_present(self, locator: tuple, timeout: int = 3) -> bool:
        """判断元素是否在指定超时内出现，返回布尔值"""
        try:
            WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located(locator)
            )
            return True
        except TimeoutException:
            return False

    def input_text(self, locator: tuple, text: str, timeout: int = 10):
        """定位元素后清空内容并输入文本"""
        element = self.find_element(locator, timeout)
        element.clear()
        element.send_keys(text)

    # ==================== 快捷定位方法 ====================

    @staticmethod
    def by_id(resource_id: str):
        """通过 accessibility id 构建定位器元组"""
        return AppiumBy.ACCESSIBILITY_ID, resource_id

    @staticmethod
    def by_text(text: str):
        """通过精确文本构建定位器元组（使用 iOS predicate）"""
        return AppiumBy.IOS_PREDICATE, f'label == "{text}"'

    @staticmethod
    def by_text_contains(text: str):
        """通过包含文本构建定位器元组"""
        return AppiumBy.IOS_PREDICATE, f'label CONTAINS "{text}"'

    @staticmethod
    def by_class_chain(chain: str):
        """通过 class chain 构建定位器元组"""
        return AppiumBy.IOS_CLASS_CHAIN, chain
