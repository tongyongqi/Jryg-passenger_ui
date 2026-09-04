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
from send_coupon.send_coupon_direct import send_coupon_direct
from create_coupon.create_coupon_direct import create_coupon_direct
import config_business
from logger.logger import sys_logger
from refund_order.refund_order import apply_refund
from database.mysql_client import run_interactive_console


# ==========================================================================
# 🚦 主执行调度引擎 (置于最上方：一键导航、极速选择、随时跳转修改各模块参数)
# ==========================================================================

def run_scheduler():
    """
    调度启动中心：处理用户菜单输入，并动态路由启动对应时机模块。
    """
    # ==========================================================================
    # 🚦 极简一键功能选择控制台 (👉 提示：请按住 Ctrl/Cmd 点击右侧蓝色函数名，直接自动导航跳转！)
    # ==========================================================================
    一键高亮导航 = {
        "1-[工单自动创建]": run_mode_1_工单全自动创建,
        "2-[创建优惠券]": run_mode_2_创建优惠券流程,
        "3-[发放大陆券]": run_mode_3_发放大陆优惠券,
        "4-[发放香港券]": run_mode_4_发放香港优惠券,
        "5-[工单受理流程]": run_mode_5_工单受理流程,
        "6-[工单退款结算]": run_mode_6_工单退款结算流程,
        "7-[极速接口退款]": run_mode_7_接口退款,
        "8-[数据库控制台]": run_mode_8_数据库控制台,
        "9-[直连发券]": run_mode_9_直连接口发券,
        "10-[接口创建券]": run_mode_10_直连接口创建优惠券,
    }
    # --------------------------------------------------------------------------
    # 💡 优化体验：如果保持默认变量 (默认为 None)，将自动弹出交互菜单让您输入数字执行！
    RUN_MODE = None

    # ==========================================================================
    # ⚙️ 共享控制参数 (修改以下参数可灵活控制各功能模块运行)
    # ==========================================================================
    # 鉴权登录配置：True 代表开启静默无头模式，False 代表真实弹出浏览器界面方便观察
    HEADLESS = True

    # 🚀 自动化启动中心：根据 RUN_MODE 执行对应的核心流转逻辑
    if RUN_MODE is None:
        print("\n" + "=" * 70)
        print("  🎫 优惠券与工单自动化调度系统 - 功能选择控制台")
        print("=" * 70)
        print("  [1] 🛠️ 工单全自动创建流程")
        print("  [2] 🎫 创建优惠券流程（并自动审批）")
        print("  [3] 🚀 发放大陆优惠券（接口发放）")
        print("  [4] 🚀 发放香港优惠券（接口发放）")
        print("  [5] 🛠️ 工单受理流程（自动检测三分支）")
        print("  [6] 🛠️ 工单退款结算流程")
        print("  [7] 💰 接口一键退款（极速接口，无需浏览器）")
        print("  [8] 🗄️ 数据库交互调试控制台（联表查券、清券、微信/芝麻绑定）")
        print("  [9] 🚀 直连接口发券（不经过扶摇，纯接口发放）")
        print("  [10] 🎫 直连接口创建优惠券（不启动浏览器，纯接口创建）")
        print("  [0] 🚪 退出程序")
        print("=" * 70)
        user_input = input("👉 请选择您想运行的功能编号 [1-8, 0退出]: ").strip()
        if user_input == "0" or not user_input:
            print("👋 运行已退出。")
            sys.exit(0)
        if user_input.isdigit() and 1 <= int(user_input) <= 10:
            RUN_MODE = int(user_input)
        else:
            print("⚠️ 输入错误，自动退出！")
            sys.exit(1)

    sys_logger.info("="*70)
    sys_logger.info(f"启动 优惠券与工单自动化调度系统 (RUN_MODE: {RUN_MODE})")
    sys_logger.info(f"当前浏览器静默模式 HEADLESS: {HEADLESS}")
    sys_logger.info("="*70)

    # 映射路由并启动对应模块
    if RUN_MODE == 1:
        run_mode_1_工单全自动创建(headless=HEADLESS)
    elif RUN_MODE == 2:
        run_mode_2_创建优惠券流程(headless=HEADLESS)
    elif RUN_MODE == 3:
        run_mode_3_发放大陆优惠券(headless=HEADLESS)
    elif RUN_MODE == 4:
        run_mode_4_发放香港优惠券(headless=HEADLESS)
    elif RUN_MODE == 5:
        run_mode_5_工单受理流程(headless=HEADLESS)
    elif RUN_MODE == 6:
        run_mode_6_工单退款结算流程(headless=HEADLESS)
    elif RUN_MODE == 7:
        run_mode_7_接口退款(headless=HEADLESS)
    elif RUN_MODE == 8:
        run_mode_8_数据库控制台(headless=HEADLESS)
    elif RUN_MODE == 9:
        run_mode_9_直连接口发券(headless=HEADLESS)
    elif RUN_MODE == 10:
        run_mode_10_直连接口创建优惠券(headless=HEADLESS)
    else:
        sys_logger.error(f"未知运行模式 RUN_MODE: {RUN_MODE}，请将其设置为 1-10 中的数字！")


# ==========================================================================
# ⚙️ 模块化功能定义区域 (Ctrl+Click/Cmd+Click 右侧函数名可一键导航至此修改参数)
# ==========================================================================

def run_mode_1_工单全自动创建(headless=True):
    """
    ========================================================================
    🛠️ MODE 1. 工单全自动创建配置
    ========================================================================
    """
    # ------------------ 配置参数区 ------------------
    # 待创建工单的订单号列表 (支持配置单个或多个)
    ORDER_IDS_1 = [
        "7359089825"
    ]
    # 工单类型选择 (如投诉、建议等)
    WORK_ORDER_TYPE_1 = "投诉"
    # 工单内容/受理备注说明
    WORK_ORDER_REMARK_1 = "自动创建工单"
    # 默认关联的 meta_id 属性
    META_ID_1 = "113491"
    # 默认关联的 order_type 属性
    ORDER_TYPE_1 = "5"
    # -----------------------------------------------

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
    
    asyncio.run(run_work_order_create_flow(headless=headless, order_ids=ORDER_IDS_1))


def run_mode_2_创建优惠券流程(headless=True):
    """
    ========================================================================
    🎫 MODE 2. 创建优惠券与提审流转配置
    ========================================================================
    """
    # ------------------ 配置参数区 ------------------
    # 优惠券类型: "满减券" 或 "折扣券"
    COUPON_TYPE = "折扣券"
    # 拟创建的优惠券名称 (设置为 "自动生成" 或留空，系统将自动根据金额/折扣生成，例如“100元优惠券”或“8.5折优惠券”)
    COUPON_NAME = "自动生成"
    # 优惠券面值金额 (元) (仅在 COUPON_TYPE="满减券" 时生效)
    FACE_VALUE = "200"
    # 折扣数值 (例如 8.5 代表 8.5折, 仅在 COUPON_TYPE="折扣券" 时生效)
    DISCOUNT_VALUE = "8.5"
    # 使用门槛：满多少元可用 (元)
    USE_RULE = "1"
    # 最高抵扣比例百分比 (100 代表 100%)
    MAX_DISCOUNT = "100"
    # 优惠券发行量 (张)
    COUPON_QTY = "100000"
    # -----------------------------------------------

    sys_logger.info("正在执行优惠券自动化创建与自动审核流转...")
    
    # 智能自愈：如果设置为 "自动生成" 或留空，则根据数值智能自动拼装优惠券名称
    final_coupon_name = COUPON_NAME
    if final_coupon_name == "自动生成" or not final_coupon_name.strip():
        if COUPON_TYPE == "折扣券":
            final_coupon_name = f"{DISCOUNT_VALUE}折优惠券"
        else:
            final_coupon_name = f"{FACE_VALUE}元优惠券"
    sys_logger.info(f"✨ 智能生成的优惠券名称为: {final_coupon_name}")

    # 将运行脚本内的优惠券配置同步到 config_business 模块
    config_business.COUPON_TYPE = COUPON_TYPE
    config_business.COUPON_NAME = final_coupon_name
    config_business.FACE_VALUE = FACE_VALUE
    config_business.DISCOUNT_VALUE = DISCOUNT_VALUE
    config_business.USE_RULE = USE_RULE
    config_business.MAX_DISCOUNT = MAX_DISCOUNT
    config_business.COUPON_QTY = COUPON_QTY
    
    asyncio.run(run_create_coupon_flow(headless=headless))


def run_mode_3_发放大陆优惠券(headless=True):
    """
    ========================================================================
    🚀 MODE 3. 大陆优惠券接口一键发放配置
    ========================================================================
    """
    # ------------------ 配置参数区 ------------------
    # 大陆发券的目标接收手机号 (多个手机号可以用英文逗号隔开)
    MAINLAND_MOBILES = "13521098140"
    # 大陆发券的单次发放数量 (张数)
    MAINLAND_SEND_NUM = 20
    # -----------------------------------------------

    sys_logger.info(f"正在执行大陆优惠券接口发放流程... 手机号: {MAINLAND_MOBILES} | 数量: {MAINLAND_SEND_NUM}")
    asyncio.run(mainland_coupon_module.run_flow(headless=headless, mobiles=MAINLAND_MOBILES, send_num=MAINLAND_SEND_NUM))


def run_mode_4_发放香港优惠券(headless=True):
    """
    ========================================================================
    🚀 MODE 4. 香港优惠券接口一键发放配置
    ========================================================================
    """
    # ------------------ 配置参数区 ------------------
    # 香港发券的目标接收手机号 (多个手机号可以用英文逗号隔开)
    HK_MOBILES = "11000006910"
    # 香港发券的单次发放数量 (张数)
    HK_SEND_NUM = 20
    # -----------------------------------------------

    sys_logger.info(f"正在执行香港优惠券接口发放流程... 手机号: {HK_MOBILES} | 数量: {HK_SEND_NUM}")
    hk_coupon_module.send_hk_coupon(mobiles=HK_MOBILES, send_num=HK_SEND_NUM)


def run_mode_5_工单受理流程(headless=True):
    """
    ========================================================================
    🛠️ MODE 5. 工单受理流程（自动检测三分支）配置
    ========================================================================
    """
    # ------------------ 配置参数区 ------------------
    # 待受理的订单号列表 (支持配置单个或多个)
    ORDER_IDS_5 = [
        "7359089825"
    ]
    # -----------------------------------------------

    sys_logger.info("正在执行工单受理流程（三分支自动检测+受理完成提交）...")
    config_business.TARGET_ORDER_ID_5 = ORDER_IDS_5[0] if ORDER_IDS_5 else ""
    config_business.TARGET_ORDER_ID = ORDER_IDS_5[0] if ORDER_IDS_5 else ""
    sys_logger.info(f"待受理的订单号: {config_business.TARGET_ORDER_ID}")
    
    asyncio.run(run_work_order_accept_flow(headless=headless))


def run_mode_6_工单退款结算流程(headless=True):
    """
    ========================================================================
    🛠️ MODE 6. 工单退款结算配置与流程
    ========================================================================
    """
    # ------------------ 配置参数区 ------------------
    # 待结算的订单号列表 (支持配置单个或多个)
    ORDER_IDS_6 = [
        "7359089825"
    ]
    # -----------------------------------------------

    sys_logger.info("正在执行工单退款结算与受理完成流程...")
    config_business.TARGET_ORDER_ID_6 = ORDER_IDS_6[0] if ORDER_IDS_6 else ""
    config_business.TARGET_ORDER_ID = ORDER_IDS_6[0] if ORDER_IDS_6 else ""
    sys_logger.info(f"待结算的订单号: {config_business.TARGET_ORDER_ID}")
    
    asyncio.run(run_work_order_settle_flow(headless=headless))


def run_mode_7_接口退款(headless=True):
    """
    ========================================================================
    💰 MODE 7. 接口一键退款配置与执行 (无浏览器)
    ========================================================================
    """
    # ------------------ 配置参数区 ------------------
    # 退款参数 (每次运行 RUN_MODE=7 前修改此处即可)
    REFUND = {
        "order_id": 7359089847,               # 订单号 (int 类型)
        "order_no": "2693DPEU2FWX4ER",         # 订单编号
        "refund_amount": 30000,                 # 退款金额 (分)
        "refund_reason": "测试",                # 退款原因
        "work_id": 2                           # 工单ID
    }
    # -----------------------------------------------

    sys_logger.info("正在执行接口退款流程...")
    sys_logger.info(f"退款参数: {REFUND}")
    apply_refund(refund_config=REFUND)


def run_mode_8_数据库控制台(headless=True):
    """
    ========================================================================
    🗄️ MODE 8. 数据库交互调试控制台 (联表查券、清券、微信/芝麻绑定)
    ========================================================================
    """
    sys_logger.info("正在启动 数据库交互调试控制台...")
    run_interactive_console()


def run_mode_9_直连接口发券(headless=True):
    """
    ========================================================================
    🚀 MODE 9. 直连接口发券配置 (不经过扶摇，纯接口发放)
    ========================================================================
    """
    # ------------------ 配置参数区 ------------------
    # 优惠券批次ID (int 类型)
    COUPON_ID = 34305
    # 目标接收手机号 (多个手机号可以用英文逗号隔开)
    MOBILES = "18618251727"
    # 发放数量 (张数)
    SEND_NUM = 3
    # -----------------------------------------------

    sys_logger.info(f"正在执行直连接口发券流程（不经过扶摇）...")
    sys_logger.info(f"券ID: {COUPON_ID} | 手机号: {MOBILES} | 数量: {SEND_NUM}")
    send_coupon_direct(mobiles=MOBILES, send_num=SEND_NUM, coupon_id=COUPON_ID)


def run_mode_10_直连接口创建优惠券(headless=True):
    """
    ========================================================================
    🎫 MODE 10. 直连接口创建优惠券配置 (不启动浏览器，纯接口创建)
    ========================================================================
    """
    # ------------------ 配置参数区 ------------------
    # 优惠券面值 (元)
    DENOMINATION = 1000
    # 发行张数
    NUMBER = 1000
    # -----------------------------------------------

    # 优惠券名称根据面值自动生成，不需要手动配置
    auto_name = f"{DENOMINATION}元优惠券"
    sys_logger.info(f"正在执行直连接口创建优惠券流程（不启动浏览器）...")
    sys_logger.info(f"面值: {DENOMINATION}元 | 张数: {NUMBER} | 自动生成名称: {auto_name}")
    create_coupon_direct(coupon_name=auto_name, denomination=DENOMINATION, number=NUMBER)


# ==========================================================================
# 🚀 启动入口：在最底部安全触发调度器 (此时上面所有函数已全部载入，完美防报错)
# ==========================================================================
if __name__ == "__main__":
    run_scheduler()