import os
from jryg_android.JRYG_config import (
    REPORT_DIR, LOGS_DIR, SCREENSHOTS_DIR, DATA_DIR, CONFIG_DIR
)

def init_all_dirs():
    """初始化并确保运行所需的全部文件夹目录均已创建"""
    for directory in (REPORT_DIR, LOGS_DIR, SCREENSHOTS_DIR, DATA_DIR, CONFIG_DIR):
        os.makedirs(directory, exist_ok=True)
