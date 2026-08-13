"""
Android 真机连接与基础操作封装（已迁入 JRYG_Passenger_UI 结构）
"""

import time
import os
import sys

from appium import webdriver
from appium.options.android import UiAutomator2Options
from appium.webdriver.common.appiumby import AppiumBy
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# 支持相对导入
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from JRYG_Passenger_UI.common import JRYG_device_config as config


class AndroidDevice:
    """Android 真机连接与操作封装"""

    def __init__(self, system_port: int = None):
        self.driver: webdriver.Remote = None
        self.system_port = system_port or config.SYSTEM_PORT

    def connect(self) -> webdriver.Remote:
        """
        连接 Android 真机
        """
        self._clean_uiautomator2()

        options = UiAutomator2Options()
        options.platform_name = "Android"
        options.udid = config.DEVICE_UDID
        options.automation_name = "UiAutomator2"

        if config.PLATFORM_VERSION:
            options.platform_version = config.PLATFORM_VERSION
        if config.DEVICE_NAME:
            options.device_name = config.DEVICE_NAME

        options.system_port = self.system_port

        if hasattr(config, "APP_PATH") and config.APP_PATH:
            options.app = config.APP_PATH
        elif config.APP_PACKAGE and config.APP_ACTIVITY:
            options.app_package = config.APP_PACKAGE
            options.app_activity = config.APP_ACTIVITY

        options.new_command_timeout = 600
        options.no_reset = True                     
        options.auto_grant_permissions = True       
        options.uiautomator2_server_install_timeout = 120_000  
        options.skip_server_installation = True      
        options.uiautomator2_server_launch_timeout = 60_000    
        options.adb_exec_timeout = 60_000            

        appium_url = f"http://{config.APPIUM_HOST}:{config.APPIUM_PORT}"
        print(f"[连接] Appium Server: {appium_url}")
        print(f"[连接] 设备 UDID: {config.DEVICE_UDID}")
        print(f"[连接] 正在启动 session，请稍候...")

        self.driver = webdriver.Remote(appium_url, options=options)
        print(f"[连接] 成功！Session ID: {self.driver.session_id}")

        self.driver.activate_app(config.APP_PACKAGE)
        time.sleep(1)

        self._wait_for_home()
        return self.driver

    @staticmethod
    def _clean_uiautomator2():
        """清理设备上的 UiAutomator2 残留进程和端口转发"""
        import subprocess
        udid = config.DEVICE_UDID

        try:
            subprocess.run(
                ["adb", "-s", udid, "shell", "pkill", "-f", "uiautomator"],
                capture_output=True, timeout=5
            )
            subprocess.run(
                ["adb", "-s", udid, "forward", "--remove-all"],
                capture_output=True, timeout=5
            )
            print("[清理] 已清理设备 UiAutomator2 残留")
        except Exception:
            pass

    def _wait_for_home(self, ad_timeout: int = 3):
        """等待广告/闪屏结束后进入首页"""
        print(f"[广告] 等待 {ad_timeout} 秒后进入首页...")
        time.sleep(ad_timeout)

        skip_keywords = ["跳过", "跳过广告", "我知道了"]
        for keyword in skip_keywords:
            try:
                el = self.driver.find_element(*self.by_text(keyword))
                el.click()
                print(f"[广告] 已点击'{keyword}'")
                time.sleep(1)
                break
            except Exception:
                continue

        close_ids = [
            f"{config.APP_PACKAGE}:id/iv_close",
            f"{config.APP_PACKAGE}:id/close",
            f"{config.APP_PACKAGE}:id/iv_cancel",
        ]
        for close_id in close_ids:
            try:
                el = self.driver.find_element(*self.by_id(close_id))
                el.click()
                print(f"[广告] 已关闭弹窗 ({close_id})")
                time.sleep(1)
            except Exception:
                pass

        print("[广告] 已进入首页")

    def disconnect(self):
        """断开连接"""
        if self.driver:
            self.driver.quit()
            print("[断开] Session 已关闭")

    def tap(self, x: int, y: int):
        self.driver.tap([(x, y)], duration=100)

    def swipe(self, start_x: int, start_y: int, end_x: int, end_y: int, duration: int = 500):
        self.driver.swipe(start_x, start_y, end_x, end_y, duration)

    def swipe_up(self, duration: int = 500):
        size = self.driver.get_window_size()
        start_x = size["width"] // 2
        start_y = int(size["height"] * 0.8)
        end_y = int(size["height"] * 0.2)
        self.swipe(start_x, start_y, start_x, end_y, duration)

    def swipe_down(self, duration: int = 500):
        size = self.driver.get_window_size()
        start_x = size["width"] // 2
        start_y = int(size["height"] * 0.2)
        end_y = int(size["height"] * 0.8)
        self.swipe(start_x, start_y, start_x, end_y, duration)

    def screenshot(self, filename: str = None):
        if filename is None:
            filename = f"screenshot_{int(time.time())}.png"
        self.driver.save_screenshot(filename)
        print(f"[截图] 已保存: {filename}")
        return filename

    def wait_and_tap(self, locator: tuple, timeout: int = 10, retries: int = 2):
        for attempt in range(retries + 1):
            try:
                element = WebDriverWait(self.driver, timeout).until(
                    EC.element_to_be_clickable(locator)
                )
                element.click()
                return
            except Exception as e:
                msg = str(e)
                if ("socket hang up" in msg or "Connection reset" in msg
                        or "Broken pipe" in msg) and attempt < retries:
                    print(f"[重试] UiAutomator2 连接断开，重试中 ({attempt + 1}/{retries})...")
                    time.sleep(3)
                    continue
                raise

    def find_element(self, locator: tuple, timeout: int = 10, retries: int = 2):
        for attempt in range(retries + 1):
            try:
                return WebDriverWait(self.driver, timeout).until(
                    EC.presence_of_element_located(locator)
                )
            except Exception as e:
                msg = str(e)
                if ("socket hang up" in msg or "Connection reset" in msg
                        or "Broken pipe" in msg) and attempt < retries:
                    print(f"[重试] UiAutomator2 连接断开，重试中 ({attempt + 1}/{retries})...")
                    time.sleep(3)
                    continue
                raise

    def is_element_present(self, locator: tuple, timeout: int = 3) -> bool:
        try:
            WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located(locator)
            )
            return True
        except Exception:
            return False

    def input_text(self, locator: tuple, text: str, timeout: int = 10):
        element = self.find_element(locator, timeout)
        element.clear()
        element.send_keys(text)

    # ==================== 快捷定位方法 ====================

    @staticmethod
    def by_id(resource_id: str):
        return AppiumBy.ID, resource_id

    @staticmethod
    def by_text(text: str):
        return AppiumBy.ANDROID_UIAUTOMATOR, f'new UiSelector().text("{text}")'

    @staticmethod
    def by_text_contains(text: str):
        return AppiumBy.ANDROID_UIAUTOMATOR, f'new UiSelector().textContains("{text}")'

    @staticmethod
    def by_xpath(xpath: str):
        return AppiumBy.XPATH, xpath
