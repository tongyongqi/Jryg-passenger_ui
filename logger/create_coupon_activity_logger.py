# -*- coding: utf-8 -*-
# 这个文件的功能是领券活动专属的日志单例输出的代码
"""
领券活动功能专属的日志单例 (create_coupon_activity_logger.py)
无冗余代码，直接调用通用日志底层生成专属日志。
"""
from logger.logger import get_logger

create_coupon_activity_logger = get_logger("create_coupon_activity.log", "create_coupon_activity_system")
