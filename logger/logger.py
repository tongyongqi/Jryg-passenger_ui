# -*- coding: utf-8 -*-
"""
统一的日志管理模块，提供控制台与本地文件（logs/running_flow.log）双重持久化输出
"""
import os
import sys
import logging

# 确保 logs 目录存在
os.makedirs("logs", exist_ok=True)
LOG_FILE_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "logs", "running_flow.log"))

class UniversalLogger:
    """
    通用、自适应的日志记录器
    """
    def __init__(self, name="flow_system"):
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.INFO)
        
        # 避免 Handler 重复添加
        if not self.logger.handlers:
            # 1. 创建控制台 Handler
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setLevel(logging.INFO)
            
            # 2. 创建文件 Handler (追加写模式，支持 utf-8 编码)
            file_handler = logging.FileHandler(LOG_FILE_PATH, mode="a", encoding="utf-8")
            file_handler.setLevel(logging.INFO)
            
            # 3. 定义统一的日志输出格式
            formatter = logging.Formatter(
                fmt="[%(asctime)s] [%(levelname)s] %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S"
            )
            console_handler.setFormatter(formatter)
            file_handler.setFormatter(formatter)
            
            # 4. 将 Handler 注册进 Logger
            self.logger.addHandler(console_handler)
            self.logger.addHandler(file_handler)

    def info(self, msg):
        self.logger.info(msg)

    def warn(self, msg):
        self.logger.warning(msg)

    def error(self, msg):
        self.logger.error(msg)

# 全局单例 Logger，供所有模块导入直接使用
sys_logger = UniversalLogger()
