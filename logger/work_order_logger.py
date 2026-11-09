# -*- coding: utf-8 -*-
# 这个文件的功能是创建工单专属的日志单例输出的代码
"""
工单功能专属的日志单例 (work_order_logger.py)
无冗余代码，直接调用通用日志底层生成专属日志。
"""
from logger.logger import get_logger

work_order_logger = get_logger("work_order.log", "work_order_system")
