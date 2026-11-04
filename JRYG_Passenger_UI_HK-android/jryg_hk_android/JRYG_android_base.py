"""Android 公共设备生命周期和 UI 操作；不包含测试方法或订单提交。

兼容方法名沿用共享iOS接口，实际动作均由AndroidClient执行，不连接WDA。
"""

from pathlib import Path
import time
import xml.etree.ElementTree as ET

from .JRYG_shared_ios import shared_settings
from .JRYG_android_ui import AndroidClient, resolve_runtime
from ui_framework.JRYG_driver_ui import visible_nodes

BASE_DIR = Path(__file__).resolve().parents[1]


class AndroidUIBase:
    """按需连接乘客及司机设备，提供定位、等待和失败传播的公共基础能力。"""

    DRIVER_REQUIRED = False

    @property
    def order_settings(self):
        """向共享订单编排提供已合并Android设备参数的配置。"""
        return self.android_settings

    @classmethod
    def setup_class(cls):
        """建立必要设备会话；双设备端口冲突或连接失败时释放已建会话。"""
        cls.android_settings = shared_settings()
        cls.clients = {}
        try:
            udid = cls.android_settings["device"]["udid"]
            port = cls.android_settings["device"].get("system_port", 8201)
            packages = (cls.android_settings["packages"]["passenger_hk"],)
            if cls.DRIVER_REQUIRED:
                runtime = resolve_runtime(cls.android_settings)
                if runtime.shared_device:
                    packages += ("com.sunlightmobility.driver",)
                driver_port = cls.android_settings["driver"].get("system_port", port + 1)
                if not runtime.shared_device and driver_port == port:
                    raise RuntimeError("双设备不能共用 Appium system_port")
            cls.clients[udid] = AndroidClient.connect(cls.android_settings, udid, port, packages=packages)
            if cls.DRIVER_REQUIRED and not runtime.shared_device:
                cls.clients[runtime.udid] = AndroidClient.connect(
                    cls.android_settings, runtime.udid, driver_port,
                    packages=("com.sunlightmobility.driver",))
            cls.client = cls.clients[udid]
        except BaseException:
            cls._release_clients()
            raise

    @classmethod
    def _release_clients(cls):
        """先清空引用再逐个释放会话，单个退出异常不阻断剩余资源清理。"""
        clients = list(getattr(cls, "clients", {}).values())
        cls.clients = {}
        cls.client = None
        for client in clients:
            try:
                client.quit()
            except Exception:
                pass

    @classmethod
    def teardown_class(cls):
        """结束时释放设备连接，不重试付款、取消订单或收车。"""
        cls._release_clients()

    def _ios_get_all_texts(self, client):
        """读取指定Android客户端规范化页面树中的可见label。"""
        root = ET.fromstring(client.source())
        return [node.get("label", "") for node in visible_nodes(root) if node.get("label")]

    def _ios_screenshot(self, name):
        """截图写入Android项目screenshots目录；name由调用方指定。"""
        directory = BASE_DIR / "screenshots"
        directory.mkdir(exist_ok=True)
        self.client.screenshot(str(directory / name))

    def _wait(self, predicate, message, timeout=30):
        """轮询谓词到超时，返回真值；谓词异常直接传播，不掩盖页面失败。"""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            value = predicate()
            if value:
                return value
            time.sleep(1)
        raise TimeoutError(message)

    def _click_text(self, keywords, *, exact=False, required=True, client=None):
        """依候选文案顺序定位并点击；必选控件缺失抛错，选择器负责唯一性。"""
        client = client or self.client
        for keyword in keywords:
            selector = client(**{"text" if exact else "textContains": keyword})
            if selector.exists:
                selector.click()
                return True
        if required:
            raise RuntimeError(f"Android 未找到 UI 控件：{keywords}")
        return False

    def _ios_click_dialog_button(self, keywords, *, tag="", fallback_coord=None, wait_after=0, **kwargs):
        """精确点击可选弹窗按钮；兼容fallback_coord参数但不执行坐标兜底。"""
        clicked = self._click_text(keywords, exact=True, required=False)
        if clicked:
            time.sleep(wait_after)
        return clicked

    def _ios_dismiss_dialogs(self, keywords, *, tag="", max_rounds=3, wait_after=1):
        """最多处理指定轮数弹窗，首次未命中即结束，不无限重试。"""
        for _ in range(max_rounds):
            if not self._ios_click_dialog_button(keywords, wait_after=wait_after):
                break

    def _assert_passenger_foreground(self):
        """核对当前包名是配置的乘客App，否则停止以防误触司机或第三方App。"""
        package = self.order_settings["packages"]["passenger_hk"]
        if self.client.driver.current_package != package:
            raise RuntimeError("Android 乘客 App 不在前台，停止操作")
