"""运行目录初始化：确保报告、日志、截图、配置目录在运行前已存在。

被导入时自动执行一次，保证后续写文件（截图、页面树、日志）不会因目录缺失失败。
"""

import os
from .JRYG_config import (
    REPORT_DIR, LOGS_DIR, SCREENSHOTS_DIR, CONFIG_DIR
)


def init_all_dirs():
    """初始化并确保运行所需的全部文件夹目录均已创建。

    只创建缺失的目录，已存在的目录保持不动，避免误删历史报告。
    """
    # 需要保证存在的四个目录：报告、日志、截图、配置
    dirs = [REPORT_DIR, LOGS_DIR, SCREENSHOTS_DIR, CONFIG_DIR]
    for d in dirs:
        if not os.path.exists(d):
            # 递归创建父目录，一次建全
            os.makedirs(d)
            print(f"[初始化] 创建必需文件夹: {d}")


# 模块导入时自动执行
init_all_dirs()
