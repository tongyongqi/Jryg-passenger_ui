# -*- coding: utf-8 -*-
# 这个文件的功能是接口创建优惠券专属的日志单例输出的代码
"""
接口创建优惠券功能专属的日志单例 (create_coupon_api_logger.py)
无冗余代码，直接调用通用日志底层生成专属日志。
"""
from logger.logger import get_logger

create_coupon_api_logger = get_logger("create_coupon_api.log", "create_coupon_api_system")
