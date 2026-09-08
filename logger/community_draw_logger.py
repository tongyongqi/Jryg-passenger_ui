# -*- coding: utf-8 -*-
# 这个文件的功能是社群抽奖专属的日志单例输出的代码
"""
社群抽奖功能专属的日志单例 (community_draw_logger.py)
无冗余代码，直接调用通用日志底层生成专属日志。
"""
from logger.logger import get_logger

community_draw_logger = get_logger("community_draw.log", "community_draw_system")
