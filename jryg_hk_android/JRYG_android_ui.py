"""Appium Android 原生设备适配，供香港双端公共订单流程使用。"""

from dataclasses import dataclass
import json
import re
import shutil
import subprocess
import warnings
from types import SimpleNamespace
import xml.etree.ElementTree as ET

from selenium.common.exceptions import StaleElementReferenceException

from .JRYG_android_session import AndroidSessionLease

CLASS_MAP = {
    "XCUIElementTypeTextField": "android.widget.EditText",
    "XCUIElementTypeSecureTextField": "android.widget.EditText",
    "XCUIElementTypeButton": "android.widget.Button",
    "XCUIElementTypeImage": "android.widget.ImageView",
}
FIELD_HINTS = {
    "et_input_fee": "請輸入車費",
    "et_input_other_fee": "請輸入附加費",
    "et_input_extra_fee": "請輸入附加費",
    "phone_num": "請輸入手機號碼",
}


def xpath_string(value):
    """将文本转换为 XPath 字符串字面量，混合引号时使用 concat 拼接。"""
    if "'" not in value:
        return "'" + value + "'"
    if '"' not in value:
        return '"' + value + '"'
    return "concat(" + ', "\'", '.join("'" + part + "'" for part in value.split("'")) + ")"


def ensure_device(udid, packages):
    """通过 ADB 检查指定设备已授权且安装了所需包，不自动改用其他设备。"""
    if not shutil.which("adb"):
        raise RuntimeError("未检测到 adb，请配置 Android SDK")
    result = subprocess.run(["adb", "devices"], capture_output=True, text=True, timeout=10, check=True)
    devices = dict(line.split()[:2] for line in result.stdout.splitlines()[1:] if len(line.split()) >= 2)
    if devices.get(udid) != "device":
        raise RuntimeError(f"Android 设备 {udid} 未连接或未授权；不会切换到其他手机")
    for package in packages:
        result = subprocess.run(["adb", "-s", udid, "shell", "pm", "path", package],
                                capture_output=True, text=True, timeout=10, check=True)
        if not result.stdout.strip().startswith("package:"):
            raise RuntimeError(f"测试手机未安装 App：{package}")


def normalized_tree(source, package):
    """将 Android 原生 XML 转为共享状态机使用的类 iOS 控件树，不连接 WDA。"""
    native = ET.fromstring(source)
    root = ET.Element("XCUIElementTypeApplication", bundleId=package, visible="true")

    def convert(node, parent):
        """递归映射原生节点的类型、文字、占位符及边界，并据显示属性与面积标记可见性。"""
        class_name = node.get("class", node.tag)
        tag = next((tag for tag, name in CLASS_MAP.items() if name == class_name), "XCUIElementTypeOther")
        if class_name.endswith("TextView"):
            tag = "XCUIElementTypeButton" if node.get("clickable") == "true" else "XCUIElementTypeStaticText"
        if class_name.endswith("Dialog") or node.get("resource-id") == "android:id/parentPanel":
            tag = "XCUIElementTypeAlert"
        bounds = re.fullmatch(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]", node.get("bounds", ""))
        x1, y1, x2, y2 = map(int, bounds.groups()) if bounds else (0, 0, 0, 0)
        resource = node.get("resource-id", "")
        text = node.get("text", "")
        hint = node.get("hint") or FIELD_HINTS.get(resource.split("/")[-1], "")
        if "EditText" in class_name and not hint and ("請輸入" in text or "请输入" in text):
            hint = text
        visible = node.get("displayed", "true") == "true" and x2 > x1 and y2 > y1
        element = ET.SubElement(parent, tag, {
            "label": text or node.get("content-desc", ""), "name": resource,
            "value": text, "placeholderValue": hint, "resource-id": resource,
            "visible": str(visible).lower(), "enabled": node.get("enabled", "true"),
            "x": str(x1), "y": str(y1), "width": str(x2 - x1), "height": str(y2 - y1),
        })
        for child in node:
            convert(child, element)
    for node in native:
        convert(node, root)
    return root


@dataclass
class AndroidRuntime:
    """保存司机设备标识及已校验的共机或双机运行模式。"""

    udid: str
    device_mode: str

    @property
    def wda_url(self):
        """返回兼容共享接口的 Android 伪地址，仅作设备标识而非真实 WDA 地址。"""
        return "android://" + self.udid

    @property
    def shared_device(self):
        """判断司机与乘客是否使用同一台设备。"""
        return self.device_mode == "shared"


def resolve_runtime(settings):
    """优先读取环境配置，推导 auto 模式并验证 shared/dual 与设备是否相同一致。"""
    import os
    passenger = settings["device"]["udid"]
    driver = os.environ.get("HK_DRIVER_ANDROID_UDID") or settings["driver"].get("udid") or passenger
    mode = os.environ.get("HK_DRIVER_DEVICE_MODE") or settings["driver"].get("device_mode", "auto")
    same = driver == passenger
    if mode == "auto":
        mode = "shared" if same else "dual"
    if mode not in ("shared", "dual") or (mode == "shared") != same:
        raise RuntimeError("Android shared 必须共用 UDID，dual 必须配置独立司机 UDID")
    return AndroidRuntime(driver, mode)


class AndroidElement:
    """包装 Appium 原生控件，提供共享流程所需的属性与输入操作。"""

    def __init__(self, client, native):
        """保存所属客户端和原生控件引用。"""
        self.client = client
        self.native = native

    @property
    def label(self):
        """优先返回控件文字，无文字时返回无障碍描述。"""
        return self.native.text or self.native.get_attribute("content-desc") or ""

    @property
    def bounds(self):
        """将原生控件矩形转换为可按属性读取的边界对象。"""
        return SimpleNamespace(**self.native.rect)

    def click(self):
        """点击已定位的原生控件。"""
        self.native.click()

    def clear_text(self):
        """清空原生输入控件的已有文字。"""
        self.native.clear()

    def set_text(self, value):
        """先聚焦并清空控件，再输入新值。"""
        self.native.click()
        self.native.clear()
        self.native.send_keys(value)


class AndroidSelector:
    """将共享查询条件适配为 Android 控件查找，点击时要求唯一命中。"""

    def __init__(self, client, **query):
        """保存客户端及本次定位条件，不立即执行查找。"""
        self.client = client
        self.query = query

    def find_elements(self):
        """优先原生ID和类定位；文字/描述分支合并后保持可见、可用及唯一性合同。"""
        query = self.query
        class_name = CLASS_MAP.get(query.get("className"), query.get("className"))
        if "resourceId" in query:
            locators = [("id", query["resourceId"])]
        elif "className" in query:
            locators = [("class name", class_name)]
        else:
            if "text" in query:
                methods, value = ("text", "description"), query["text"]
            elif "textContains" in query:
                methods, value = ("textContains", "descriptionContains"), query["textContains"]
            elif "textMatches" in query:
                methods, value = ("textMatches", "descriptionMatches"), "(?s).+"
            else:
                methods, value = (), None
            locators = [("-android uiautomator", f"new UiSelector().{method}({json.dumps(value, ensure_ascii=False)})")
                        for method in methods] or [("-android uiautomator", "new UiSelector()")]
        candidates = []
        previous_ids = set()
        for by, locator in locators:
            elements = self.client.driver.find_elements(by, locator)
            candidates.extend(native for native in elements if native.id not in previous_ids)
            previous_ids.update(native.id for native in elements)
        result = []
        for native in candidates:
            if not native.is_displayed() or not native.is_enabled():
                continue
            if "className" in query and native.get_attribute("class") != class_name:
                continue
            element = AndroidElement(self.client, native)
            if any(key in query for key in ("text", "textContains", "textMatches")):
                text, description = native.text or "", native.get_attribute("content-desc") or ""
                if "text" in query and query["text"] not in (text, description):
                    continue
                if "textContains" in query and not any(query["textContains"] in value for value in (text, description)):
                    continue
                if "textMatches" in query and (not (text or description) or not re.fullmatch(query["textMatches"], text or description)):
                    continue
            result.append(element)
        return result

    @property
    def exists(self):
        """判断是否存在可见可用控件；查询期间引用过期表示该旧控件已离开当前页面。"""
        try:
            return bool(self.find_elements())
        except StaleElementReferenceException:
            return False

    def unique(self):
        """仅返回恰好一个匹配控件，缺失或多匹配均报错，避免误操作。"""
        elements = self.find_elements()
        if len(elements) != 1:
            raise RuntimeError(f"Android 控件缺失或不唯一：{self.query}")
        return elements[0]

    def click(self):
        """先验证匹配结果唯一，再点击该控件。"""
        self.unique().click()


class AndroidClient:
    """以 Appium 驱动实现共享流程的设备接口，统一控件查询、页面与手势操作。"""

    def __init__(self, driver, lease=None):
        """保存已建立的Appium驱动及设备锁，直到退出会话后才释放锁。"""
        self.driver = driver
        self.lease = lease
        self._closed = False
        self._udid = None  # 由 connect 设置，供熄屏检测使用

    @classmethod
    def connect(cls, settings, udid, system_port, *, packages=None):
        """校验设备和所需包，保留应用数据并建立不自动启动 App 的 UiAutomator2 会话。"""
        from appium import webdriver
        from appium.options.android import UiAutomator2Options
        if packages is None:
            packages = (settings["packages"]["passenger_hk"], "com.sunlightmobility.driver")
        ensure_device(udid, packages)
        config = settings["device"]
        idle_timeout = config.get("wait_for_idle_timeout", 0)
        if isinstance(idle_timeout, bool) or not isinstance(idle_timeout, int) or idle_timeout < 0:
            raise ValueError("Android wait_for_idle_timeout必须为非负整数毫秒")
        selector_timeout = config.get("wait_for_selector_timeout", 0)
        if isinstance(selector_timeout, bool) or not isinstance(selector_timeout, int) or selector_timeout < 0:
            raise ValueError("Android wait_for_selector_timeout必须为非负整数毫秒")
        request_timeout = config.get("request_timeout", 20)
        if isinstance(request_timeout, bool) or not isinstance(request_timeout, (int, float)) or request_timeout <= 0:
            raise ValueError("Android request_timeout必须为正数秒")
        server_timeout = config.get("uiautomator2_server_read_timeout", max(1, int((request_timeout - 5) * 1000)))
        if (isinstance(server_timeout, bool) or not isinstance(server_timeout, int) or server_timeout <= 0
                or server_timeout >= request_timeout * 1000):
            raise ValueError("Android uiautomator2_server_read_timeout必须为正整数毫秒且小于request_timeout")
        source_settings = {
            "waitForIdleTimeout": idle_timeout,
            "waitForSelectorTimeout": selector_timeout,
            "enableTopmostWindowFromActivePackage": False,
        }
        options = UiAutomator2Options().load_capabilities({
            "platformName": "Android", "appium:automationName": "UiAutomator2",
            "appium:udid": udid, "appium:deviceName": config.get("device_name", "Android_Device"),
            "appium:systemPort": system_port, "appium:noReset": True,
            "appium:autoLaunch": False, "appium:newCommandTimeout": 900,
            "appium:adbExecTimeout": 20000,
            "appium:uiautomator2ServerReadTimeout": server_timeout,
            "appium:disableWindowAnimation": config.get("disable_window_animation", True),
            **{f"appium:settings[{key}]": value for key, value in source_settings.items()},
        })
        url = f"http://{config.get('appium_host', '127.0.0.1')}:{config.get('appium_port', 4723)}"
        from appium.webdriver.client_config import AppiumClientConfig
        client_config = AppiumClientConfig(
            remote_server_addr=url, timeout=config.get("session_create_timeout", 180),
            init_args_for_pool_manager={"init_args_for_pool_manager": {"retries": 0}})
        lease = AndroidSessionLease(udid, system_port).acquire()
        driver = None
        try:
            driver = webdriver.Remote(url, options=options, client_config=client_config)
            client_config.timeout = request_timeout
            driver.update_settings(source_settings)
            driver.implicitly_wait(0)
            instance = cls(driver, lease=lease)
            instance._udid = udid
            return instance
        except BaseException:
            try:
                if driver is not None:
                    driver.quit()
            except Exception:
                warnings.warn("Android会话清理失败，可能残留转发；未覆盖原始建连异常", RuntimeWarning)
            finally:
                lease.release()
            raise

    def __call__(self, **query):
        """根据查询条件创建选择器，供共享流程按调用方式定位控件。"""
        return AndroidSelector(self, **query)

    def is_session_alive(self):
        """检测 UiAutomator2 会话是否健康（instrumentation 进程是否存活）。

        通过执行轻量命令（page_source）并捕获
        "instrumentation process is not running" / "cannot be proxied" 错误判定。
        """
        try:
            self.driver.page_source
            return True
        except Exception as exc:
            msg = str(exc).lower()
            if "instrumentation process is not running" in msg or \
               "cannot be proxied" in msg or \
               "no such session" in msg or \
               "session is closed" in msg:
                return False
            # 其他异常不代表会话崩溃
            return True

    def restart_session(self, settings, udid, system_port, *, packages=None):
        """UiAutomator2 崩溃后重建会话。

        1. 尝试 quit 旧 driver（忽略异常）
        2. 释放旧 lease
        3. 重新 acquire lease 并建立新 driver
        """
        import logging
        log = logging.getLogger("JRYG_HK_android")
        log.warning("【会话恢复】UiAutomator2 会话已崩溃，正在重建")

        # 1. 清理旧 driver
        old_driver = self.driver
        try:
            old_driver.quit()
        except Exception:
            pass

        # 2. 释放旧 lease
        old_lease = getattr(self, "lease", None)
        if old_lease is not None:
            try:
                old_lease.release()
            except Exception:
                pass

        # 3. 清理残留的 ADB 端口转发（旧会话崩溃时可能未清理）
        import subprocess
        try:
            subprocess.run(
                ["adb", "-s", udid, "forward", "--remove", f"tcp:{system_port}"],
                capture_output=True, timeout=10)
        except Exception:
            pass

        # 4. 等待 2 秒让端口释放
        import time
        time.sleep(2)

        # 5. 重新建连
        from appium import webdriver
        from appium.options.android import UiAutomator2Options
        from jryg_hk_android.JRYG_android_session import AndroidSessionLease

        if packages is None:
            packages = (settings["packages"]["passenger_hk"], "com.sunlightmobility.driver")
        config = settings["device"]
        source_settings = {
            "waitForIdleTimeout": config.get("wait_for_idle_timeout", 0),
            "waitForSelectorTimeout": config.get("wait_for_selector_timeout", 0),
            "enableTopmostWindowFromActivePackage": False,
        }
        options = UiAutomator2Options().load_capabilities({
            "platformName": "Android", "appium:automationName": "UiAutomator2",
            "appium:udid": udid, "appium:deviceName": config.get("device_name", "Android_Device"),
            "appium:systemPort": system_port, "appium:noReset": True,
            "appium:autoLaunch": False, "appium:newCommandTimeout": 900,
            "appium:adbExecTimeout": 20000,
            "appium:uiautomator2ServerReadTimeout": config.get(
                "uiautomator2_server_read_timeout", max(1, int((config.get("request_timeout", 20) - 5) * 1000))),
            "appium:disableWindowAnimation": config.get("disable_window_animation", True),
            **{f"appium:settings[{key}]": value for key, value in source_settings.items()},
        })
        url = f"http://{config.get('appium_host', '127.0.0.1')}:{config.get('appium_port', 4723)}"
        from appium.webdriver.client_config import AppiumClientConfig
        client_config = AppiumClientConfig(
            remote_server_addr=url, timeout=config.get("session_create_timeout", 180),
            init_args_for_pool_manager={"init_args_for_pool_manager": {"retries": 0}})
        lease = AndroidSessionLease(udid, system_port).acquire()
        driver = webdriver.Remote(url, options=options, client_config=client_config)
        client_config.timeout = config.get("request_timeout", 20)
        driver.update_settings(source_settings)
        driver.implicitly_wait(0)

        self.driver = driver
        self.lease = lease
        self._udid = udid
        log.info("【会话恢复】UiAutomator2 会话已重建")
        return True

    def source(self, format="xml"):
        """返回当前页面转换后的共享 XML；format 仅兼容调用签名，不改变输出格式。"""
        return ET.tostring(normalized_tree(self.driver.page_source, self.driver.current_package), encoding="unicode")

    def screenshot(self, path):
        """将设备截图保存到指定路径，保存失败时抛出异常。"""
        if not self.driver.save_screenshot(path):
            raise RuntimeError("Android 截图失败")

    def app_activate(self, package):
        """将指定包对应的应用切换到前台。"""
        self.driver.activate_app(package)

    def session(self, package):
        """激活指定应用后返回当前客户端，不另建 Appium 会话。"""
        self.app_activate(package)
        return self

    def home(self):
        """发送 Android Home 键，返回系统桌面。"""
        self.driver.press_keycode(3)

    def back(self):
        """执行 Android 返回操作。"""
        self.driver.back()

    def click(self, x, y):
        """点击指定坐标；仅当两轴均在零到一之间时按窗口比例换算为像素。"""
        width, height = self.window_size()
        if 0 <= x <= 1 and 0 <= y <= 1:
            x, y = round(x * width), round(y * height)
        self.driver.tap([(int(x), int(y))])

    def swipe(self, x1, y1, x2, y2, duration):
        """按给定像素起终点滑动，并将秒数转换为 Appium 使用的毫秒时长。"""
        self.driver.swipe(x1, y1, x2, y2, duration=int(duration * 1000))

    def send_keys(self, value):
        """向当前焦点控件输入内容，单个退格字符改为发送 Android 删除键。"""
        if value == "\b":
            self.driver.press_keycode(67)
        else:
            self.driver.switch_to.active_element.send_keys(value)

    def window_size(self):
        """返回当前窗口的像素宽度与高度。"""
        size = self.driver.get_window_size()
        return size["width"], size["height"]

    def dismiss_keyboard(self):
        """仅在软键盘已显示时请求隐藏键盘。"""
        if self.driver.is_keyboard_shown():
            self.driver.hide_keyboard()

    def quit(self):
        """仅退出本客户端会话，随后释放设备锁；不杀进程或清理其他会话。"""
        if self._closed:
            return
        self._closed = True
        try:
            self.driver.quit()
        finally:
            if self.lease is not None:
                self.lease.release()

    def ensure_unlocked(self):
        """检测设备熄屏并唤醒，不管执行到哪个阶段都唤醒后继续。

        通过 ADB 检测屏幕状态，熄屏时发送 KEYCODE_POWER 唤醒。
        不输入锁屏密码，不中断测试，不直接判定为错误。
        """
        if not self._udid:
            return
        from .JRYG_android_device_guard import ensure_unlocked as _ensure_unlocked
        _ensure_unlocked(self._udid)

    @property
    def udid(self):
        """返回当前设备 UDID，供熄屏检测等使用。"""
        return self._udid
