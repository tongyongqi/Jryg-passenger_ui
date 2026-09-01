# -*- coding: utf-8 -*-
"""
香港发券功能专属的日志单例 (send_hk_coupon_logger.py)
无冗余代码，直接调用通用日志底层生成专属日志。
"""
from logger.logger import get_logger

send_hk_coupon_logger = get_logger("send_hk_coupon.log", "send_hk_coupon_system")
