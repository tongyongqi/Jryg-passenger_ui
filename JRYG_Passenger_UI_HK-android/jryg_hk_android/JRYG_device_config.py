"""
港版 Android 真机 UI 自动化设备配置
==============================================================================
从 jryg_hk_android.JRYG_config 的全局配置中提取 Appium 连接所需的设备参数，
统一在此暴露，避免各用例直接拼装 capability。
==============================================================================
"""

from jryg_hk_android.JRYG_config import SETTINGS

# ---- 设备标识 ----
DEVICE_UDID = SETTINGS["device"]["udid"]                       # 设备唯一标识
DEVICE_NAME = SETTINGS["device"].get("device_name", "")         # 设备名称（可选）
PLATFORM_VERSION = SETTINGS["device"].get("platform_version", "")  # Android 系统版本

# ---- 港版 App 包名 ----
APP_PACKAGE = SETTINGS["packages"]["passenger_hk"]             # 乘客端包名
APP_ACTIVITY = SETTINGS["packages"].get("passenger_hk_activity", "")  # 乘客端启动 Activity
APP_PATH = SETTINGS["packages"].get("app_path", "")             # APK 安装包路径（可选）

# ---- Appium Server ----
APPIUM_HOST = SETTINGS["device"].get("appium_host", "127.0.0.1")  # Appium Server 主机地址
APPIUM_PORT = SETTINGS["device"].get("appium_port", 4723)        # Appium Server 监听端口
SYSTEM_PORT = SETTINGS["device"].get("system_port", 8201)        # UiAutomator2 系统端口
