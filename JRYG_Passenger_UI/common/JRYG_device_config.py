"""
Android 真机 UI 自动化配置文件（已迁入 JRYG_Passenger_UI 项目结构）
"""

from JRYG_Passenger_UI.common.JRYG_config import SETTINGS

DEVICE_UDID = SETTINGS["device"]["udid"]
DEVICE_NAME = SETTINGS["device"].get("name", "")
PLATFORM_VERSION = SETTINGS["device"].get("platform_version", "")
APP_PACKAGE = SETTINGS["packages"]["passenger"]
APP_ACTIVITY = SETTINGS["packages"]["passenger_activity"]
APP_PATH = SETTINGS["packages"].get("app_path", "")
APPIUM_HOST = SETTINGS["device"]["appium_host"]
APPIUM_PORT = SETTINGS["device"]["appium_port"]
SYSTEM_PORT = SETTINGS["device"]["system_port"]
