# -*- coding: utf-8 -*-
# 这个文件的功能是创建数据库连接和操作专属的日志单例输出的代码
"""
数据库专属的日志单例 (database_logger.py)
无冗余代码，直接调用通用日志底层生成专属日志。
"""
from logger.logger import get_logger

database_logger = get_logger("database.log", "database_system")
