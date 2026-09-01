# -*- coding: utf-8 -*-
"""
优惠券自动创建功能专属的日志单例 (create_coupon_logger.py)
无冗余代码，直接调用通用日志底层生成专属日志。
"""
from logger.logger import get_logger

create_coupon_logger = get_logger("create_coupon.log", "create_coupon_system")
