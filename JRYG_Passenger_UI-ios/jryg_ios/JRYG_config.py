import os
import yaml

# 项目根目录 JRYG_Passenger_UI-ios
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 各核心目录路径
COMMON_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_DIR = os.path.join(BASE_DIR, "config")
CASES_DIR = os.path.join(BASE_DIR, "cases")
DATA_DIR = os.path.join(BASE_DIR, "data")
REPORT_DIR = os.path.join(BASE_DIR, "report")
LOGS_DIR = os.path.join(BASE_DIR, "logs")
SCREENSHOTS_DIR = os.path.join(BASE_DIR, "screenshots")

# 各全局配置文件、测试数据与日志文件路径
SETTINGS_FILE = os.path.join(CONFIG_DIR, "JRYG_settings.yaml")
TEST_DATA_FILE = os.path.join(DATA_DIR, "JRYG_test_data.json")
LOG_FILE = os.path.join(LOGS_DIR, "JRYG_run_ios.log")

def load_settings():
    """动态加载全局 JRYG_settings.yaml 配置文件（iOS 版）"""
    with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
        settings = yaml.safe_load(f)
    required = {
        "device": ("udid", "appium_host", "appium_port", "platform_version", "device_name"),
        "packages": ("passenger",),
    }
    if not isinstance(settings, dict):
        raise ValueError(f"配置必须为映射结构: {SETTINGS_FILE}")
    for section, keys in required.items():
        values = settings.get(section)
        if not isinstance(values, dict):
            raise ValueError(f"配置缺少 {section}: {SETTINGS_FILE}")
        for key in keys:
            if values.get(key) in (None, ""):
                raise ValueError(f"配置缺少 {section}.{key}: {SETTINGS_FILE}")
    return settings

# 模块导入时即加载全局配置
SETTINGS = load_settings()
