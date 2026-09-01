# -*- coding: utf-8 -*-
"""
==========================================================================
🌐 优惠券与工单自动化调度系统 - 日志管理组件 (logger.py)
==========================================================================
本模块提供了一种高内聚、自适应的双重持久化日志记录机制 (UniversalLogger)。
支持同时将运行时的标准输出（控制台）及离线本地文件（追加写入模式）进行持久化归档。

日志存储路径：根目录/logs/running_flow.log
"""

import os
import sys
import logging

# ----------------- 确保 logs 存储目录的存在性 -----------------
os.makedirs("logs", exist_ok=True)
# 计算全局绝对路径，确保从任何工作目录（CWD）调用该脚本时均能正确指向 logs 文件夹
LOG_FILE_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "logs", "running_flow.log"))


class UniversalLogger:
    """
    通用持久化日志记录器类，实现了 Stream 和 File 两种处理器（Handler）的单例式加载。
    """
    def __init__(self, name="flow_system"):
        # 获取底层原生 logging 记录器实例
        self.logger = logging.getLogger(name)
        # 设置全局捕获过滤的最低级别为 INFO（忽略调试 debug 级别）
        self.logger.setLevel(logging.INFO)
        
        # 稳健的双重保障：防止由于多次初始化或模块重载导致 StreamHandler/FileHandler 被重复添加而打印双份日志
        if not self.logger.handlers:
            
            # 1. 构造标准控制台（终端）输出处理器
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setLevel(logging.INFO)
            
            # 2. 构造本地文件持久化处理器（采用追加写入模式，硬性指定使用 utf-8 编码，防止中文乱码）
            file_handler = logging.FileHandler(LOG_FILE_PATH, mode="a", encoding="utf-8")
            file_handler.setLevel(logging.INFO)
            
            # 3. 订制高规范性的日志标准打印格式 (精确记录 [时间戳] [日志等级] 内容)
            formatter = logging.Formatter(
                fmt="[%(asctime)s] [%(levelname)s] %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S"
            )
            console_handler.setFormatter(formatter)
            file_handler.setFormatter(formatter)
            
            # 4. 将两种管道处理器正式关联并装载至核心 logger 引擎
            self.logger.addHandler(console_handler)
            self.logger.addHandler(file_handler)

    def info(self, msg):
        """记录常规业务流程、关键动作及成功状态等正常日志"""
        self.logger.info(msg)

    def warn(self, msg):
        """记录网络延迟、断线重试、元素未立刻捕获等自愈性质的可忽略预警日志"""
        self.logger.warning(msg)

    def error(self, msg):
        """记录系统阻断性崩溃、API接口异常、断言失败等核心报错日志"""
        self.logger.error(msg)


# ==========================================================================
# 🌟 全局单例 Logger，供整个项目下的所有子模块、配置和执行流直接导入复用
# ==========================================================================
sys_logger = UniversalLogger()
