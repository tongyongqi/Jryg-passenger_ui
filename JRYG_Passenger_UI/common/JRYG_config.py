import os
import yaml

# 项目根目录 JRYG_Passenger_UI
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 各核心目录路径
COMMON_DIR = os.path.join(BASE_DIR, "common")
CONFIG_DIR = os.path.join(BASE_DIR, "config")
CASES_DIR = os.path.join(BASE_DIR, "cases")
DATA_DIR = os.path.join(BASE_DIR, "data")
REPORT_DIR = os.path.join(BASE_DIR, "report")
LOGS_DIR = os.path.join(BASE_DIR, "logs")
SCREENSHOTS_DIR = os.path.join(BASE_DIR, "screenshots")

# 各全局配置文件、测试数据与日志文件路径
SETTINGS_FILE = os.path.join(CONFIG_DIR, "JRYG_settings.yaml")
TEST_DATA_FILE = os.path.join(DATA_DIR, "JRYG_test_data.json")
LOG_FILE = os.path.join(LOGS_DIR, "JRYG_run.log")

def load_settings():
    """动态加载全局 JRYG_settings.yaml 配置文件"""
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    return {}

SETTINGS = load_settings()
