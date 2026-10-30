"""司机全 UI 运行配置：仅解析设备地址及单/双设备模式，不读取接口会话。"""

from dataclasses import dataclass
import os
from urllib.parse import urlsplit


def settings_or_default(settings=None):
    """仅未传入配置时加载项目设置，显式空配置不被默认值覆盖。"""
    if settings is None:
        from .JRYG_config import SETTINGS
        settings = SETTINGS
    return settings or {}


def normalized_wda(url):
    """校验无凭据的WDA根地址并归一化localhost，用于比较是否共用设备。"""
    parsed = urlsplit(url)
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError:
        raise RuntimeError("WDA 端口无效") from None
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ("", "/"):
        raise RuntimeError("WDA 地址必须是无凭据的 HTTP/HTTPS 服务根地址")
    host = "127.0.0.1" if parsed.hostname == "localhost" else parsed.hostname
    return parsed.scheme, host, port


@dataclass(frozen=True)
class DriverRuntime:
    """不可变的司机WDA与设备模式，避免运行中静默切换设备。"""

    wda_url: str
    device_mode: str

    @property
    def shared_device(self):
        """标记司机与乘客是否必须顺序切换同一设备。"""
        return self.device_mode == "shared"


def resolve_runtime(settings=None):
    """auto：未配置独立 WDA 时顺序共用设备；dual：必须提供不同 WDA。"""
    settings = settings_or_default(settings)
    driver = settings.get("driver") or {}
    passenger = (settings.get("device") or {}).get("wda_url", "http://127.0.0.1:8100")
    wda_url = os.environ.get("HK_DRIVER_WDA_URL") or driver.get("wda_url") or passenger
    mode = os.environ.get("HK_DRIVER_DEVICE_MODE") or driver.get("device_mode", "auto")
    same_device = normalized_wda(wda_url) == normalized_wda(passenger)
    if mode not in ("auto", "shared", "dual"):
        raise RuntimeError("司机 device_mode 必须为 auto、shared 或 dual")
    if mode == "auto":
        mode = "shared" if same_device else "dual"
    if (mode == "dual" and same_device) or (mode == "shared" and not same_device):
        raise RuntimeError("dual 需要独立 WDA；shared 必须与乘客使用同一 WDA")
    return DriverRuntime(wda_url.rstrip("/"), mode)
