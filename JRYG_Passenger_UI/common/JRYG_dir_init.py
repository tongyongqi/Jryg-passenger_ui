import os
from JRYG_Passenger_UI.common.JRYG_config import (
    REPORT_DIR, LOGS_DIR, SCREENSHOTS_DIR, DATA_DIR, CONFIG_DIR
)

def init_all_dirs():
    """初始化并确保运行所需的全部文件夹目录均已创建"""
    dirs = [REPORT_DIR, LOGS_DIR, SCREENSHOTS_DIR, DATA_DIR, CONFIG_DIR]
    for d in dirs:
        if not os.path.exists(d):
            os.makedirs(d)
            print(f"[初始化] 创建必需文件夹: {d}")

# 模块导入时自动执行
init_all_dirs()
