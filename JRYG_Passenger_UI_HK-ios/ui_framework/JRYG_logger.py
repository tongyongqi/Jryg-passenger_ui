"""统一日志记录器：控制台与文件双输出，文件按大小滚动。

模块级 logger 供其它模块直接导入使用，避免多处重复配置。
司机与乘客共用日志文件；调用方只记录操作阶段，不应记录卡号、OTP或会话凭据。
"""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from .JRYG_config import LOG_FILE


def get_logger(name="JRYG_HK_ios"):
    """创建并配置旋转式日志记录器，支持控制台和文件同步双向输出。

    重复调用时复用同名 logger，避免日志被重复打印多份。
    """
    logger = logging.getLogger(name)
    # 已有 handler 说明已配置过，直接复用，避免重复输出
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

        # 控制台输出
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

        # 日志文件记录 (最大10MB，自动保存3个备份)
        # 先确保日志目录存在，避免 RotatingFileHandler 因目录缺失报错
        Path(LOG_FILE).parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(LOG_FILE, maxBytes=10*1024*1024, backupCount=3, encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


# 模块级默认日志实例
logger = get_logger()
