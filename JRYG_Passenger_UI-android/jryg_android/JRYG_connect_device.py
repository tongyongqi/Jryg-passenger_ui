"""
Android 真机连接与基础操作封装（已迁入 JRYG_Passenger_UI-android 结构）
"""

import time
import subprocess
from pathlib import Path

from appium import webdriver
from appium.options.android import UiAutomator2Options
from appium.webdriver.common.appiumby import AppiumBy
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from . import JRYG_device_config as config
from .JRYG_config import SCREENSHOTS_DIR
from selenium.common.exceptions import NoSuchElementException, TimeoutException


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
        options.uiautomator2_server_launch_timeout = 60_000    
        options.adb_exec_timeout = 60_000            

        appium_url = f"http://{config.APPIUM_HOST}:{config.APPIUM_PORT}"
        print(f"[连接] Appium Server: {appium_url}")
        print(f"[连接] 设备 UDID: {config.DEVICE_UDID}")
        print("[连接] 正在启动 session，请稍候...")

        self.driver = webdriver.Remote(appium_url, options=options)
        print(f"[连接] 成功！Session ID: {self.driver.session_id}")

        # 用 ADB 显式 Intent 启动 App，避免 activate_app 触发系统"打开方式"弹框
        self._start_app_via_adb(config.APP_PACKAGE, config.APP_ACTIVITY)
        time.sleep(1)

        # 关闭可能出现的"打开方式"弹框（ResolverActivity）
        self._dismiss_resolver_if_present()

        self._wait_for_home()
        return self.driver

    def _start_app_via_adb(self, package, activity):
        """通过 ADB am start 显式启动指定 App 的 Activity，避免隐式 Intent 触发选择器。"""
        udid = config.DEVICE_UDID
        subprocess.run(
            ["adb", "-s", udid, "shell", "am", "start", "-n", f"{package}/{activity}"],
            capture_output=True, timeout=10
        )
        print(f"[连接] 已通过 ADB 启动 {package}/{activity}")

    def _dismiss_resolver_if_present(self):
        """检测并关闭系统'打开方式'弹框（ResolverActivity），避免遮挡 App 界面。"""
        udid = config.DEVICE_UDID
        try:
            result = subprocess.run(
                ["adb", "-s", udid, "shell", "dumpsys", "window"],
                capture_output=True, text=True, timeout=5
            )
            if "ResolverActivity" not in result.stdout:
                return
            print("[连接] 检测到'打开方式'弹框，正在关闭...")
            # 按返回键关闭弹框
            subprocess.run(
                ["adb", "-s", udid, "shell", "input", "keyevent", "4"],
                capture_output=True, timeout=5
            )
            time.sleep(1)
            # 再次确认弹框是否已关闭
            result2 = subprocess.run(
                ["adb", "-s", udid, "shell", "dumpsys", "window"],
                capture_output=True, text=True, timeout=5
            )
            if "ResolverActivity" in result2.stdout:
                print("[连接] 返回键未能关闭弹框，尝试用 am start 重新启动 App")
                subprocess.run(
                    ["adb", "-s", udid, "shell", "am", "start", "-n",
                     f"{config.APP_PACKAGE}/{config.APP_ACTIVITY}"],
                    capture_output=True, timeout=10
                )
                time.sleep(2)
        except Exception as e:
            print(f"[连接] 关闭弹框异常: {e}")

    def _clean_uiautomator2(self):
        """只清理本设备的 Appium 服务及本会话端口。"""
        prefix = ["adb", "-s", config.DEVICE_UDID]
        for package in ("io.appium.uiautomator2.server", "io.appium.uiautomator2.server.test"):
            subprocess.run(prefix + ["shell", "am", "force-stop", package],
                           capture_output=True, timeout=5, check=True)
        subprocess.run(prefix + ["forward", "--remove", f"tcp:{self.system_port}"],
                       capture_output=True, timeout=5)

    def _wait_for_home(self, ad_timeout: int = 3):
        """等待广告/闪屏结束后进入首页。

        先用 ADB uiautomator dump 定位并关闭广告弹窗（避免 UiAutomator2 server 在广告遮挡时崩溃），
        再用 Appium find_element 做补充检查。
        """
        print(f"[广告] 等待 {ad_timeout} 秒后进入首页...")
        time.sleep(ad_timeout)

        # 先用 ADB 后备方案关闭广告弹窗
        self._close_ad_via_adb()
        time.sleep(1)

        # 再用 Appium 补充检查跳过广告和关闭弹窗
        skip_keywords = ["跳过", "跳过广告", "我知道了"]
        for keyword in skip_keywords:
            try:
                el = self.driver.find_element(*self.by_text(keyword))
                el.click()
                print(f"[广告] 已点击'{keyword}'")
                time.sleep(1)
                break
            except (NoSuchElementException, Exception):
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
            except (NoSuchElementException, Exception):
                pass

        print("[广告] 弹窗检查完成")

    def _close_ad_via_adb(self):
        """通过 ADB uiautomator dump 定位广告关闭按钮并点击坐标。"""
        import xml.etree.ElementTree as ET
        udid = config.DEVICE_UDID
        dump_cmd = ["adb", "-s", udid, "shell", "uiautomator", "dump", "/sdcard/ui_dump.xml"]
        cat_cmd = ["adb", "-s", udid, "shell", "cat", "/sdcard/ui_dump.xml"]
        try:
            subprocess.run(dump_cmd, capture_output=True, text=True, timeout=10)
            result = subprocess.run(cat_cmd, capture_output=True, text=True, timeout=10)
            root = ET.fromstring(result.stdout)
            for node in root.iter("node"):
                rid = node.get("resource-id", "")
                if "iv_cancel" in rid or "iv_close" in rid:
                    bounds = node.get("bounds", "")
                    import re
                    m = re.findall(r"\d+", bounds)
                    if len(m) >= 4:
                        cx = (int(m[0]) + int(m[2])) // 2
                        cy = (int(m[1]) + int(m[3])) // 2
                        subprocess.run(["adb", "-s", udid, "shell", "input", "tap", str(cx), str(cy)],
                                     capture_output=True, timeout=5)
                        print(f"[广告] ADB 后备关闭广告弹窗 ({cx},{cy})")
                        time.sleep(1)
                        return
        except Exception as e:
            print(f"[广告] ADB 后备关闭失败: {e}")

    def disconnect(self):
        """断开连接"""
        if self.driver:
            try:
                self.driver.quit()
            finally:
                self.driver = None
            print("[断开] Session 已关闭")

    def tap(self, x: int, y: int):
        """通过物理像素坐标执行单击操作。"""
        self.driver.tap([(x, y)], duration=100)

    def swipe(self, start_x: int, start_y: int, end_x: int, end_y: int, duration: int = 500):
        """通过起点和终点坐标执行滑动手势。"""
        self.driver.swipe(start_x, start_y, end_x, end_y, duration)

    def swipe_up(self, duration: int = 500):
        """从屏幕底部 80% 滑动至顶部 20%，模拟上划手势。"""
        size = self.driver.get_window_size()
        start_x = size["width"] // 2
        start_y = int(size["height"] * 0.8)
        end_y = int(size["height"] * 0.2)
        self.swipe(start_x, start_y, start_x, end_y, duration)

    def swipe_down(self, duration: int = 500):
        """从屏幕顶部 20% 滑动至底部 80%，模拟下划手势。"""
        size = self.driver.get_window_size()
        start_x = size["width"] // 2
        start_y = int(size["height"] * 0.2)
        end_y = int(size["height"] * 0.8)
        self.swipe(start_x, start_y, start_x, end_y, duration)

    def screenshot(self, filename: str = None):
        """截取当前屏幕并保存至 screenshots 目录，返回文件路径。"""
        if filename is None:
            filename = f"screenshot_{int(time.time())}.png"
        path = Path(filename)
        if not path.is_absolute():
            path = Path(SCREENSHOTS_DIR) / path
        path.parent.mkdir(parents=True, exist_ok=True)
        if not self.driver.save_screenshot(str(path)):
            raise RuntimeError(f"截图保存失败: {path}")
        print(f"[截图] 已保存: {path}")
        return str(path)

    def _wait_for_element(self, condition, timeout, retries):
        if retries < 0:
            raise ValueError("retries 不能小于0")
        for attempt in range(retries + 1):
            try:
                return WebDriverWait(self.driver, timeout).until(condition)
            except Exception as exc:
                retryable = any(text in str(exc) for text in (
                    "socket hang up", "Connection reset", "Broken pipe"
                ))
                if not retryable or attempt == retries:
                    raise
                print(f"[重试] UiAutomator2 连接中断 ({attempt + 1}/{retries})")
                time.sleep(3)

    def find_element(self, locator: tuple, timeout: int = 10, retries: int = 2):
        """在指定超时内查找并返回元素对象，超时抛出异常。"""
        return self._wait_for_element(EC.presence_of_element_located(locator), timeout, retries)

    def is_element_present(self, locator: tuple, timeout: int = 3) -> bool:
        """判断元素是否在指定超时内出现，返回布尔值。"""
        try:
            WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located(locator)
            )
            return True
        except TimeoutException:
            return False

    def input_text(self, locator: tuple, text: str, timeout: int = 10):
        """定位元素后清空内容并输入文本。"""
        element = self.find_element(locator, timeout)
        element.clear()
        element.send_keys(text)

    # ==================== 快捷定位方法 ====================

    @staticmethod
    def by_id(resource_id: str):
        """通过 resource_id 构建定位器元组。"""
        return AppiumBy.ID, resource_id

    @staticmethod
    def by_text(text: str):
        """通过精确文本构建 UiSelector 定位器元组。"""
        return AppiumBy.ANDROID_UIAUTOMATOR, f'new UiSelector().text("{text}")'
