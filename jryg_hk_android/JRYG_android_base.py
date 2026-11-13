"""Android 公共设备生命周期和 UI 操作；不包含测试方法或订单提交。

兼容方法名沿用共享iOS接口，实际动作均由AndroidClient执行，不连接WDA。
不管执行到哪个阶段，如果设备熄屏，需要唤醒后继续执行，不能直接判断为错误。
"""

from pathlib import Path
import time
import xml.etree.ElementTree as ET

from .JRYG_shared_ios import shared_settings
from .JRYG_android_ui import AndroidClient, resolve_runtime
from .JRYG_android_device_guard import (
    DeviceUnlockError, ensure_unlocked as _ensure_android_unlocked,
    ensure_mac_awake, mac_prevent_sleep, mac_stop_prevent_sleep,
)
from .JRYG_driver_ui import visible_nodes

BASE_DIR = Path(__file__).resolve().parents[1]


class AndroidUIBase:
    """按需连接乘客及司机设备，提供定位、等待和失败传播的公共基础能力。

    不管执行到哪个阶段，如果设备熄屏，自动唤醒后继续执行，不中断测试。
    Mac 电脑锁屏也检测并尝试点亮显示器，不输入电脑密码。
    """

    DRIVER_REQUIRED = False

    @property
    def order_settings(self):
        """向共享订单编排提供已合并Android设备参数的配置。"""
        return self.android_settings

    @classmethod
    def setup_class(cls):
        """建立必要设备会话；双设备端口冲突或连接失败时释放已建会话。

        连接前先检测 Mac 和 Android 设备熄屏状态，唤醒后继续。
        """
        # Mac 防休眠
        ensure_mac_awake()
        cls.android_settings = shared_settings()
        cls.clients = {}
        cls._client_ports = {}  # udid -> system_port 映射，用于崩溃恢复
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
            # 连接前检测 Android 设备熄屏并唤醒
            _ensure_android_unlocked(udid)
            cls.clients[udid] = AndroidClient.connect(cls.android_settings, udid, port, packages=packages)
            cls._client_ports[udid] = port
            if cls.DRIVER_REQUIRED and not runtime.shared_device:
                _ensure_android_unlocked(runtime.udid)
                cls.clients[runtime.udid] = AndroidClient.connect(
                    cls.android_settings, runtime.udid, driver_port,
                    packages=("com.sunlightmobility.driver",))
                cls._client_ports[runtime.udid] = driver_port
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
        """结束时释放设备连接和 Mac 防休眠，不重试付款、取消订单或收车。"""
        cls._release_clients()
        mac_stop_prevent_sleep()

    def _ensure_devices_awake(self):
        """检测并唤醒所有已连接的 Android 设备和 Mac，不管执行到哪个阶段。

        熄屏时唤醒后继续执行，不中断测试，不直接判定为错误。
        同时检测 UiAutomator2 会话健康，崩溃时自动重建。
        """
        ensure_mac_awake()
        for udid, client in list(getattr(self, "clients", {}).items()):
            try:
                _ensure_android_unlocked(udid)
            except DeviceUnlockError as exc:
                # 不直接判定为错误，记录后等待手动解锁
                import logging
                logging.getLogger("JRYG_HK_android").warning(
                    "[熄屏检查] 设备 %s 唤醒失败：%s；等待手动解锁", udid, exc
                )
            # 检测 UiAutomator2 会话是否崩溃，崩溃时自动重建
            try:
                if hasattr(client, "is_session_alive") and not client.is_session_alive():
                    import logging
                    logging.getLogger("JRYG_HK_android").warning(
                        "[会话检查] 设备 %s 的 UiAutomator2 会话已崩溃，尝试自动重建", udid)
                    settings = getattr(self, "android_settings", None)
                    if settings is not None:
                        system_port = self._client_system_port(udid)
                        client.restart_session(
                            settings, udid, system_port)
                    else:
                        logging.getLogger("JRYG_HK_android").error(
                            "[会话检查] 无法重建会话：缺少 android_settings")
            except Exception as exc:
                import logging
                logging.getLogger("JRYG_HK_android").warning(
                    "[会话检查] 设备 %s 会话健康检测异常：%s", udid, exc)

    def _client_system_port(self, udid):
        """获取客户端对应的 system_port。"""
        # 从 clients 字典的端口映射中查找，默认 8201
        ports = getattr(self, "_client_ports", {})
        return ports.get(udid, 8201)

    def _ios_get_all_texts(self, client):
        """读取指定Android客户端规范化页面树中的可见label。

        读取前先检测设备熄屏并唤醒，不管执行到哪个阶段都唤醒后继续。
        """
        self._ensure_devices_awake()
        root = ET.fromstring(client.source())
        return [node.get("label", "") for node in visible_nodes(root) if node.get("label")]

    def _ios_screenshot(self, name):
        """截图写入Android项目screenshots目录；name由调用方指定。

        截图前先检测设备熄屏并唤醒，不管执行到哪个阶段都唤醒后继续。
        """
        self._ensure_devices_awake()
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
