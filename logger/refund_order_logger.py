# -*- coding: utf-8 -*-
# 这个文件的功能是退款接口专属的日志单例输出的代码
"""
退款接口专属的日志单例 (refund_order_logger.py)
无冗余代码，直接调用通用日志底层生成专属日志。
"""
from logger.logger import get_logger

refund_order_logger = get_logger("refund_order.log", "refund_order_system")
