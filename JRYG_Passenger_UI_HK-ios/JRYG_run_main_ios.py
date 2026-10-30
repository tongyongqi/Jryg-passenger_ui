"""JRYG_Passenger_UI_HK-ios 自动化模块 —— JRYG_run_main_ios.py
==============================================================================
港版阳光出行 iOS 乘客端 UI 自动化测试主运行入口。

功能：
  1. 初始化运行所需目录（报告、日志、截图、配置）
  2. 收集所有 iOS 专用测试文件（cases/ 目录下 JRYG_test_ios_*.py）
  3. 通过 pytest 执行测试，生成 HTML 报告
  4. 支持命令行参数透传（如 --collect-only）

测试用例组合（车型 × 支付方式）：
  - 打錶的士：現金(cash) / 電子支付(epayment) / Alipay HK(alipay)
  - 包車價的士：Alipay HK(alipay) / 信用卡(bankcard) / 八達通(octopus, 暂不执行)
==============================================================================
"""

import os
import sys
import pytest

# 添加框架根路径与父目录至 sys.path，支持相对导入和全局引用
# BASE_DIR = JRYG_Passenger_UI_HK-ios（本文件所在目录）
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# 将框架根路径加入 sys.path，确保能 import jryg_hk_ios 包
sys.path.append(BASE_DIR)
# 将项目根路径（JRYG_PassengerIUi）加入 sys.path，支持跨项目导入 API 层
sys.path.append(os.path.dirname(BASE_DIR))

# 导入目录初始化函数，确保运行前报告/日志/截图/配置目录已存在
from jryg_hk_ios.JRYG_dir_init import init_all_dirs
# 导入报告输出目录路径
from jryg_hk_ios.JRYG_config import REPORT_DIR

def run_tests(argv=None):
    """JRYG 港版 iOS UI 自动化测试执行引擎入口。

    流程：
    1. 初始化必需文件夹
    2. 收集所有 iOS 测试文件
    3. 组装 pytest 参数（-v -s --html 报告）
    4. 执行 pytest 并返回退出码

    :param argv: 额外的命令行参数列表（透传给 pytest）。
    :return: pytest 退出码（0=成功，非 0=有失败或错误）。
    """
    print("\n" + "="*50)
    print("      JRYG 港版阳光出行 iOS 测试执行引擎 -ios (Start)")
    print("="*50)

    # 初始化必需文件夹（报告、日志、截图、配置）
    init_all_dirs()

    # HTML 测试报告输出路径
    report_file = os.path.join(REPORT_DIR, "JRYG_test_report_hk_ios.html")

    # 透传的命令行参数
    extra_args = list(argv or [])

    # 收集所有 iOS 专用测试文件（cases/ 目录下 JRYG_test_ios_*.py）
    # 参数化下单用例（车型 × 支付方式组合）
    ios_test_files = [
        # 打錶的士：現金 / 電子支付（信用卡路径）/ Alipay HK
        os.path.join(BASE_DIR, "cases", "JRYG_test_ios_meter_cash_order.py"),
        os.path.join(BASE_DIR, "cases", "JRYG_test_ios_meter_epayment_order.py"),
        os.path.join(BASE_DIR, "cases", "JRYG_test_ios_meter_alipay_order.py"),
        # 包車價的士：Alipay HK / 信用卡/扣帳卡 / 八達通（八達通暂不执行）
        os.path.join(BASE_DIR, "cases", "JRYG_test_ios_charter_alipay_order.py"),
        os.path.join(BASE_DIR, "cases", "JRYG_test_ios_charter_bankcard_order.py"),
        os.path.join(BASE_DIR, "cases", "JRYG_test_ios_charter_octopus_order.py"),
    ]

    # 过滤出实际存在的文件（避免文件缺失导致 pytest 报错）
    existing_files = [f for f in ios_test_files if os.path.exists(f)]
    if not existing_files:
        print("[错误 -ios] 未找到任何 iOS 测试文件！")
        return 1

    # 组装 pytest 参数
    pytest_args = [
        "-c", os.path.join(BASE_DIR, "pytest.ini"),  # 指定 pytest 配置文件
        "-v", "-s",                                   # 详细输出 + 不捕获 print
    ] + existing_files

    # 非 collect-only 模式时生成 HTML 报告
    if not any(arg in ("--collect-only", "--co") for arg in extra_args):
        pytest_args.extend([f"--html={report_file}", "--self-contained-html"])
        print(f"输出香港 iOS UI 测试报告: {report_file}")

    # 执行 pytest 并获取退出码
    exit_code = pytest.main(pytest_args + extra_args)

    print("="*50)
    print("      JRYG 港版阳光出行 iOS 测试执行引擎 -ios (Completed)")
    print("="*50 + "\n")
    return exit_code

if __name__ == "__main__":
    # 直接运行此文件时，透传命令行参数给 run_tests
    sys.exit(run_tests(sys.argv[1:]))
