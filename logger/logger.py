# -*- coding: utf-8 -*-
"""
==========================================================================
🌐 优惠券与工单自动化调度系统 - 通用日志底层模块 (logger.py)
==========================================================================
本模块提供统一的日志引擎构造器，避免各功能模块重复编写/复制相同的 Logger 初始化代码。
各功能的专属日志模块只需调用 get_logger() 传入各自的日志名称即可。
"""

import os
import sys
import logging

# 确保 logs 目录存在
os.makedirs("logs", exist_ok=True)

def get_logger(filename, name):
    """
    自适应创建、配置并返回一个控制台与本地文件双重输出的 Logger 实例。
    
    参数:
      filename (str): 本地保存的日志文件名 (例如: "work_order.log")
      name (str): 日志记录器系统名称 (例如: "work_order_system")
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    
    # 防止 Handler 重复挂载
    if not logger.handlers:
        # 计算 logs 下该日志的绝对路径
        log_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "logs", filename))
        
        # 1. 终端流处理器
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        
        # 2. 文件持久化处理器
        file_handler = logging.FileHandler(log_path, mode="a", encoding="utf-8")
        file_handler.setLevel(logging.INFO)
        
        # 3. 统一美观的格式化规范
        formatter = logging.Formatter(
            fmt="[%(asctime)s] [%(levelname)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        console_handler.setFormatter(formatter)
        file_handler.setFormatter(formatter)
        
        # 4. 挂载管道
        logger.addHandler(console_handler)
        logger.addHandler(file_handler)
        
    return logger

# 全局备用的默认单例 Logger
sys_logger = get_logger("running_flow.log", "default_flow_system")
