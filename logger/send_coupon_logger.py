# -*- coding: utf-8 -*-
"""
大陆优惠券接口发放功能专属日志管理组件 (send_coupon_logger.py)
日志存储路径：根目录/logs/send_coupon.log
"""

import os
import sys
import logging

os.makedirs("logs", exist_ok=True)
LOG_FILE_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "logs", "send_coupon.log"))

class SendCouponLogger:
    def __init__(self, name="send_coupon_system"):
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.INFO)
        
        if not self.logger.handlers:
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setLevel(logging.INFO)
            
            file_handler = logging.FileHandler(LOG_FILE_PATH, mode="a", encoding="utf-8")
            file_handler.setLevel(logging.INFO)
            
            formatter = logging.Formatter(
                fmt="[%(asctime)s] [%(levelname)s] %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S"
            )
            console_handler.setFormatter(formatter)
            file_handler.setFormatter(formatter)
            
            self.logger.addHandler(console_handler)
            self.logger.addHandler(file_handler)

    def info(self, msg):
        self.logger.info(msg)

    def warn(self, msg):
        self.logger.warning(msg)

    def error(self, msg):
        self.logger.error(msg)

send_coupon_logger = SendCouponLogger()
