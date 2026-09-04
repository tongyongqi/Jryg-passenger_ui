# -*- coding: utf-8 -*-
# 这个文件的功能是大陆直连接口发券专属的日志单例输出的代码
"""
大陆直连接口发券专属的日志单例 (send_coupon_direct_logger.py)
无冗余代码，直接调用通用日志底层生成专属日志。
"""
from logger.logger import get_logger

send_coupon_direct_logger = get_logger("send_coupon_direct.log", "send_coupon_direct_system")
