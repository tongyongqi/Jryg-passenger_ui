"""全局配置：目录路径与 JRYG_settings.yaml 配置加载。

所有路径都以项目根目录（JRYG_Passenger_UI_HK-ios）为基准，
保证在不同机器上执行时路径一致。
"""

import os
import yaml

# 项目根目录 JRYG_Passenger_UI_HK-ios
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 各核心目录路径
COMMON_DIR = os.path.dirname(os.path.abspath(__file__))  # 本包所在目录（jryg_hk_ios）
CONFIG_DIR = os.path.join(BASE_DIR, "config")            # 配置文件目录
CASES_DIR = os.path.join(BASE_DIR, "cases")              # 用例目录
REPORT_DIR = os.path.join(BASE_DIR, "report")            # 报告/页面树/截图输出目录
LOGS_DIR = os.path.join(BASE_DIR, "logs")                # 运行日志目录
SCREENSHOTS_DIR = os.path.join(BASE_DIR, "screenshots")  # 独立截图目录

# 全局配置文件路径
SETTINGS_FILE = os.path.join(CONFIG_DIR, "JRYG_settings.yaml")
LOG_FILE = os.path.join(LOGS_DIR, "JRYG_run.log")


def load_settings():
    """动态加载全局 JRYG_settings.yaml 配置文件。

    配置文件不存在时返回空字典，让调用方使用默认值，
    避免因缺少配置直接中断整个测试导入。
    """
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            # safe_load 只支持 YAML 基础类型，不执行任意对象构造
            return yaml.safe_load(f)
    return {}


# 全局配置对象，导入时一次性加载
SETTINGS = load_settings()
