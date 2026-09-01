import asyncio
import os
import sys

# 1. 确保将项目根目录添加到 python path 使得模块 and 配置能被正常载入
sys.path.append(os.path.abspath(os.path.dirname(__file__)))

# 统一导入项目内的所有核心功能模块
from WorkOrder.order import run_flow as run_work_order_flow
from create_coupon.run_create import main as run_create_coupon_flow
import send_coupon as mainland_coupon_module
import send_hk_coupon as hk_coupon_module

if __name__ == "__main__":
    # ==========================================================================
    # 🚦 极简一键功能选择控制台 (在 PyCharm 中修改此数字运行不同功能)
    # ==========================================================================
    # 1 - 工单创建以及工单受理闭环流转 (直连订单 -> 切换工单页签 -> 创建工单 -> 首行受理 -> 填写处理及退款结算 -> 保存并受理完成)
    # 2 - 创建优惠券流程 (启动后台 -> 创建优惠券表单并自动填入、强力注入 -> 自动通过流程审批)
    # 3 - 发放大陆优惠券 (自动登录截取 API Token -> 发送大陆发券 POST 接口请求发放优惠券)
    # 4 - 发放香港优惠券 (直连香港发券 API 接口发放香港测试优惠券)
    RUN_MODE = 1

    # ==========================================================================
    # ⚙️ 共享控制参数 (修改以下参数可灵活控制各功能模块运行)
    # ==========================================================================
    # 鉴权登录配置：True 代表开启静默无头模式，False 代表真实弹出浏览器界面方便观察
    HEADLESS = False

    # ------------------ 1. 工单配置 ------------------
    # 待流转创建并受理的订单号列表 (支持配置单个或多个)
    ORDER_IDS = [
        "7358984980"
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
    print("\n" + "="*70)
    print(f"[*] 🌟 正在启动 优惠券与工单自动化调度系统 (RUN_MODE: {RUN_MODE})")
    print(f"[*] 当前浏览器静默模式 HEADLESS: {HEADLESS}")
    print("="*70)

    if RUN_MODE == 1:
        print(f"[*] 🚀 [ACTION] 正在执行工单创建以及工单受理闭环流转程序...")
        print(f"[*] 待处理的订单号列表 ORDER_IDS: {ORDER_IDS}")
        asyncio.run(run_work_order_flow(headless=HEADLESS, order_ids=ORDER_IDS))

    elif RUN_MODE == 2:
        print(f"[*] 🚀 [ACTION] 正在执行优惠券自动化创建与自动审核流转...")
        asyncio.run(run_create_coupon_flow(headless=HEADLESS))

    elif RUN_MODE == 3:
        print(f"[*] 🚀 [ACTION] 正在执行大陆优惠券接口发放流程...")
        print(f"[*] 目标手机号: {MAINLAND_MOBILES} | 发放数量: {MAINLAND_SEND_NUM} 张")
        asyncio.run(mainland_coupon_module.run_flow(headless=HEADLESS, mobiles=MAINLAND_MOBILES, send_num=MAINLAND_SEND_NUM))

    elif RUN_MODE == 4:
        print(f"[*] 🚀 [ACTION] 正在执行香港优惠券接口发放流程...")
        print(f"[*] 目标手机号: {HK_MOBILES} | 发放数量: {HK_SEND_NUM} 张")
        hk_coupon_module.send_hk_coupon(mobiles=HK_MOBILES, send_num=HK_SEND_NUM)

    else:
        print(f"[❌ ERROR] 未知运行模式 RUN_MODE: {RUN_MODE}，请将其设置为 1, 2, 3 或 4 中的一个！")
