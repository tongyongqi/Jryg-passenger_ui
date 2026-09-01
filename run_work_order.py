# -*- coding: utf-8 -*-
# 这个文件的功能是全自动调度和一键集中管理及执行控制台的代码

import asyncio
import os
import sys

# 1. 统一构建最高级别的 Python 搜索路径，确保彻底兼容任何物理目录、工作空间运行场景
root_dir = os.path.abspath(os.path.dirname(__file__))
sys.path.append(root_dir)

# 统一导入项目内的所有核心功能模块
from WorkOrder.order import run_create_flow as run_work_order_create_flow
from WorkOrder.accept_order import run_accept_flow as run_work_order_accept_flow
from WorkOrder.settle_order import run_settle_flow as run_work_order_settle_flow
from create_coupon.run_create import main as run_create_coupon_flow
import send_coupon as mainland_coupon_module
import send_hk_coupon as hk_coupon_module
from logger.logger import sys_logger

if __name__ == "__main__":
    # ==========================================================================
    # 🚦 极简一键功能选择控制台 (在 PyCharm 中修改此数字运行不同功能)
    # ==========================================================================
    # 1 - 工单全自动创建流程 (直连订单 -> 导航到工单页签 -> 创建工单 -> 勾选投诉/四级级联 -> 保存并关闭)
    # 2 - 创建优惠券流程 (启动后台 -> 创建优惠券表单并自动填入、强力注入 -> 自动通过流程审批)
    # 3 - 发放大陆优惠券 (自动登录截取 API Token -> 发送大陆发券 POST 接口请求发放优惠券)
    # 4 - 发放香港优惠券 (直连香港发券 API 接口发放香港测试优惠券)
    # 5 - 工单处理录入流转 (导航至工单列表 -> 自动获取最新工单并点击受理 -> 填写投诉结果“有效”/责任方及双文本 -> 截图保存，不执行最终提交)
    # 6 - 工单退款结算流转 (导航至工单列表 -> 自动获取最新工单并点击处理 -> 点击退款&结算配置乘客全额、司机正常并保存 -> 强力抹除校验并点击“受理完成”提交)
    RUN_MODE = 1

    # ==========================================================================
    # ⚙️ 共享控制参数 (修改以下参数可灵活控制各功能模块运行)
    # ==========================================================================
    # 鉴权登录配置：True 代表开启静默无头模式，False 代表真实弹出浏览器界面方便观察
    HEADLESS = True

    # ------------------ 1. 工单配置 ------------------
    # 待流转创建并受理的订单号列表 (支持配置单个或多个)
    ORDER_IDS = [
        "7359060558"
    ]

    # ------------------ 2. 大陆优惠券发放配置 ------------------
    # 大陆发券的目标接收手机号 (多个手机号可以用英文逗号隔开)
    MAINLAND_MOBILES = "11000000001"
    # 大陆发券的单次发放数量 (张数)
    MAINLAND_SEND_NUM = 10

    # ------------------ 3. 香港优惠券发放配置 ------------------
    # 香港发券的目标接收手机号 (多个手机号可以用英文逗号隔开)
    HK_MOBILES = "11000000001"
    # 香港发券的单次发放数量 (张数)
    HK_SEND_NUM = 1

    # ==========================================================================
    # 🚀 自动化启动中心：根据 RUN_MODE 执行对应的核心流转逻辑
    # ==========================================================================
    sys_logger.info("="*70)
    sys_logger.info(f"启动 优惠券与工单自动化调度系统 (RUN_MODE: {RUN_MODE})")
    sys_logger.info(f"当前浏览器静默模式 HEADLESS: {HEADLESS}")
    sys_logger.info("="*70)

    if RUN_MODE == 1:
        sys_logger.info("正在执行工单全自动创建流转程序...")
        sys_logger.info(f"待处理的订单号列表 ORDER_IDS: {ORDER_IDS}")
        asyncio.run(run_work_order_create_flow(headless=HEADLESS, order_ids=ORDER_IDS))

    elif RUN_MODE == 2:
        sys_logger.info("正在执行优惠券自动化创建与自动审核流转...")
        asyncio.run(run_create_coupon_flow(headless=HEADLESS))

    elif RUN_MODE == 3:
        sys_logger.info(f"正在执行大陆优惠券接口发放流程... 手机号: {MAINLAND_MOBILES} | 数量: {MAINLAND_SEND_NUM}")
        asyncio.run(mainland_coupon_module.run_flow(headless=HEADLESS, mobiles=MAINLAND_MOBILES, send_num=MAINLAND_SEND_NUM))

    elif RUN_MODE == 4:
        sys_logger.info(f"正在执行香港优惠券接口发放流程... 手机号: {HK_MOBILES} | 数量: {HK_SEND_NUM}")
        hk_coupon_module.send_hk_coupon(mobiles=HK_MOBILES, send_num=HK_SEND_NUM)

    elif RUN_MODE == 5:
        sys_logger.info("正在执行工单基础受理与填写流程...")
        asyncio.run(run_work_order_accept_flow(headless=HEADLESS))

    elif RUN_MODE == 6:
        sys_logger.info("正在执行工单退款结算与最终受理完成流程...")
        asyncio.run(run_work_order_settle_flow(headless=HEADLESS))

    else:
        sys_logger.error(f"未知运行模式 RUN_MODE: {RUN_MODE}，请将其设置为 1, 2, 3, 4, 5 或 6 中的一个！")
