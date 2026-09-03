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
import config_business
from logger.logger import sys_logger
from refund_order.refund_order import apply_refund

if __name__ == "__main__":
    # ==========================================================================
    # 🚦 极简一键功能选择控制台 (在 PyCharm 中修改此数字运行不同功能)
    # ==========================================================================
    # 1 - 工单全自动创建流程 (直连订单 -> 导航到工单页签 -> 创建工单 -> 勾选投诉/四级级联 -> 保存并关闭)
    # 2 - 创建优惠券流程 (启动后台 -> 创建优惠券表单并自动填入、强力注入 -> 自动通过流程审批)
    # 3 - 发放大陆优惠券 (自动登录截取 API Token -> 发送大陆发券 POST 接口请求发放优惠券)
    # 4 - 发放香港优惠券 (直连香港发券 API 接口发放香港测试优惠券)
    # 5 - 工单受理流程 (导航至工单列表 -> 按订单号搜索并点击受理 -> 填写投诉结果/责任方 -> 自动检测页面按钮三分支: 取消订单/改价免单/退款&结算 -> 执行对应分支 -> 受理完成提交)
    # 6 - 工单退款结算流程 (导航至工单列表 -> 按订单号搜索并点击处理 -> 点击退款&结算配置乘客全额退款、司机正常结算并保存 -> 清除Vue校验 -> 点击受理完成提交)
    # 7 - 接口退款 (直接调用退款接口，对指定订单发起退款申请，无需浏览器自动化)
    RUN_MODE = 3

    # ==========================================================================
    # ⚙️ 共享控制参数 (修改以下参数可灵活控制各功能模块运行)
    # ==========================================================================
    # 鉴权登录配置：True 代表开启静默无头模式，False 代表真实弹出浏览器界面方便观察
    HEADLESS = True

    # ------------------ MODE 1. 工单创建配置 ------------------
    # 待创建工单的订单号列表 (支持配置单个或多个)
    ORDER_IDS_1 = [
        "7358984706"
    ]
    # 工单类型选择 (如投诉、建议等)
    WORK_ORDER_TYPE_1 = "投诉"
    # 工单内容/受理备注说明
    WORK_ORDER_REMARK_1 = "自动创建工单"
    # 默认关联的 meta_id 属性
    META_ID_1 = "113491"
    # 默认关联的 order_type 属性
    ORDER_TYPE_1 = "5"

    # ------------------ MODE 5. 工单受理配置 ------------------
    # 待受理的订单号列表 (支持配置单个或多个)
    ORDER_IDS_5 = [
        "7358984706"
    ]

    # ------------------ MODE 6. 工单退款结算配置 ------------------
    # 待结算的订单号列表 (支持配置单个或多个)
    ORDER_IDS_6 = [
        "7358984706"
    ]

    # ------------------ MODE 2. 创建优惠券配置 ------------------
    # 拟创建的优惠券名称
    COUPON_NAME = "自动化创建优惠卷1000元"
    # 优惠券面值金额 (元)
    FACE_VALUE = "1000"
    # 使用门槛：满多少元可用 (元)
    USE_RULE = "1"
    # 最高抵扣比例百分比 (100 代表 100%)
    MAX_DISCOUNT = "100"
    # 优惠券发行量 (张)
    COUPON_QTY = "100000"

    # ------------------ MODE 3. 大陆优惠券发放配置 ------------------
    # 大陆发券的目标接收手机号 (多个手机号可以用英文逗号隔开)
    MAINLAND_MOBILES = "18618251727"
    # 大陆发券的单次发放数量 (张数)
    MAINLAND_SEND_NUM = 20

    # ------------------ MODE 4. 香港优惠券发放配置 ------------------
    # 香港发券的目标接收手机号 (多个手机号可以用英文逗号隔开)
    HK_MOBILES = "11000006910"
    # 香港发券的单次发放数量 (张数)
    HK_SEND_NUM = 20

    # ------------------ MODE 7. 接口退款配置 ------------------
    # 退款参数 (每次运行 RUN_MODE=7 前修改此处即可)
    REFUND = {
        "order_id": 7359087690,               # 订单号 (int 类型)
        "order_no": "2693DPESEIWX4ER",         # 订单编号
        "refund_amount": 380,                 # 退款金额 (分)
        "refund_reason": "测试",                # 退款原因
        "work_id": 2                           # 工单ID
    }

    # ==========================================================================
    # 🚀 自动化启动中心：根据 RUN_MODE 执行对应的核心流转逻辑
    # ==========================================================================
    sys_logger.info("="*70)
    sys_logger.info(f"启动 优惠券与工单自动化调度系统 (RUN_MODE: {RUN_MODE})")
    sys_logger.info(f"当前浏览器静默模式 HEADLESS: {HEADLESS}")
    sys_logger.info("="*70)

    if RUN_MODE == 1:
        sys_logger.info("正在执行工单全自动创建流转程序...")
        sys_logger.info(f"待处理的订单号列表 ORDER_IDS: {ORDER_IDS_1}")
        sys_logger.info(f"工单类型: {WORK_ORDER_TYPE_1} | 备注: {WORK_ORDER_REMARK_1}")
        # 将运行脚本内的工单配置同步到 config_business 模块
        config_business.TARGET_ORDER_ID_1 = ORDER_IDS_1[0] if ORDER_IDS_1 else ""
        config_business.TARGET_ORDER_ID = ORDER_IDS_1[0] if ORDER_IDS_1 else ""
        config_business.WORK_ORDER_TYPE_1 = WORK_ORDER_TYPE_1
        config_business.WORK_ORDER_TYPE = WORK_ORDER_TYPE_1
        config_business.WORK_ORDER_REMARK_1 = WORK_ORDER_REMARK_1
        config_business.WORK_ORDER_REMARK = WORK_ORDER_REMARK_1
        config_business.META_ID_1 = META_ID_1
        config_business.META_ID = META_ID_1
        config_business.ORDER_TYPE_1 = ORDER_TYPE_1
        config_business.ORDER_TYPE = ORDER_TYPE_1
        asyncio.run(run_work_order_create_flow(headless=HEADLESS, order_ids=ORDER_IDS_1))

    elif RUN_MODE == 2:
        sys_logger.info("正在执行优惠券自动化创建与自动审核流转...")
        # 将运行脚本内的优惠券配置同步到 config_business 模块
        config_business.COUPON_NAME = COUPON_NAME
        config_business.FACE_VALUE = FACE_VALUE
        config_business.USE_RULE = USE_RULE
        config_business.MAX_DISCOUNT = MAX_DISCOUNT
        config_business.COUPON_QTY = COUPON_QTY
        asyncio.run(run_create_coupon_flow(headless=HEADLESS))

    elif RUN_MODE == 3:
        sys_logger.info(f"正在执行大陆优惠券接口发放流程... 手机号: {MAINLAND_MOBILES} | 数量: {MAINLAND_SEND_NUM}")
        asyncio.run(mainland_coupon_module.run_flow(headless=HEADLESS, mobiles=MAINLAND_MOBILES, send_num=MAINLAND_SEND_NUM))

    elif RUN_MODE == 4:
        sys_logger.info(f"正在执行香港优惠券接口发放流程... 手机号: {HK_MOBILES} | 数量: {HK_SEND_NUM}")
        hk_coupon_module.send_hk_coupon(mobiles=HK_MOBILES, send_num=HK_SEND_NUM)

    elif RUN_MODE == 5:
        sys_logger.info("正在执行工单受理流程（三分支自动检测+受理完成提交）...")
        config_business.TARGET_ORDER_ID_5 = ORDER_IDS_5[0] if ORDER_IDS_5 else ""
        config_business.TARGET_ORDER_ID = ORDER_IDS_5[0] if ORDER_IDS_5 else ""
        sys_logger.info(f"待受理的订单号: {config_business.TARGET_ORDER_ID}")
        asyncio.run(run_work_order_accept_flow(headless=HEADLESS))

    elif RUN_MODE == 6:
        sys_logger.info("正在执行工单退款结算与受理完成流程...")
        config_business.TARGET_ORDER_ID_6 = ORDER_IDS_6[0] if ORDER_IDS_6 else ""
        config_business.TARGET_ORDER_ID = ORDER_IDS_6[0] if ORDER_IDS_6 else ""
        sys_logger.info(f"待结算的订单号: {config_business.TARGET_ORDER_ID}")
        asyncio.run(run_work_order_settle_flow(headless=HEADLESS))

    elif RUN_MODE == 7:
        sys_logger.info("正在执行接口退款流程...")
        sys_logger.info(f"退款参数: {REFUND}")
        apply_refund(refund_config=REFUND)

    else:
        sys_logger.error(f"未知运行模式 RUN_MODE: {RUN_MODE}，请将其设置为 1, 2, 3, 4, 5, 6 或 7 中的一个！")
