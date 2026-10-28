import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from .JRYG_config import LOG_FILE

def get_logger(name="JRYG_HK_android"):
    """创建并配置旋转式日志记录器，支持控制台和文件同步双向输出"""
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        
        # 控制台输出
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
        
        # 日志文件记录 (最大10MB，自动保存3个备份)
        Path(LOG_FILE).parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(LOG_FILE, maxBytes=10*1024*1024, backupCount=3, encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        
    return logger

logger = get_logger()
