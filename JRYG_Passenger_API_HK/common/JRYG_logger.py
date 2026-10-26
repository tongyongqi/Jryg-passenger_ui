"""香港接口自动化专用日志。"""

import logging
from logging.handlers import RotatingFileHandler

from JRYG_Passenger_API_HK.common.JRYG_config import LOG_FILE


def get_logger(name="JRYG_HK_API"):
    logger = logging.getLogger(name)
    if not logger.handlers:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        logger.setLevel(logging.INFO)
        formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        console = logging.StreamHandler()
        console.setFormatter(formatter)
        file_handler = RotatingFileHandler(
            LOG_FILE, maxBytes=10 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(console)
        logger.addHandler(file_handler)
        logger.propagate = False
    return logger


logger = get_logger()
