# -*- coding: utf-8 -*-
# 这个文件的功能是登录系统专属的日志单例输出的代码
"""
登录功能专属的日志单例 (login_logger.py)
无冗余代码，直接调用通用日志底层生成专属日志。
"""
from logger.logger import get_logger

login_logger = get_logger("login.log", "login_system")
