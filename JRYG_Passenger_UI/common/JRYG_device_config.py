"""
Android 真机 UI 自动化配置文件（已迁入 JRYG_Passenger_UI 项目结构）
"""

from JRYG_Passenger_UI.common.JRYG_config import SETTINGS

DEVICE_UDID = SETTINGS["device"]["udid"]               # 设备唯一标识
DEVICE_NAME = SETTINGS["device"].get("name", "")       # 设备名称（可选）
PLATFORM_VERSION = SETTINGS["device"].get("platform_version", "")  # Android 系统版本
APP_PACKAGE = SETTINGS["packages"]["passenger"]        # 乘客端包名
APP_ACTIVITY = SETTINGS["packages"]["passenger_activity"]  # 乘客端启动 Activity
APP_PATH = SETTINGS["packages"].get("app_path", "")    # APK 安装包路径（可选）
APPIUM_HOST = SETTINGS["device"]["appium_host"]        # Appium Server 主机地址
APPIUM_PORT = SETTINGS["device"]["appium_port"]        # Appium Server 监听端口
SYSTEM_PORT = SETTINGS["device"]["system_port"]        # UiAutomator2 系统端口
