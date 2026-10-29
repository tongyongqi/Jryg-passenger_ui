"""JRYG_Passenger_UI_HK-ios 自动化模块 —— JRYG_run_main_ios.py
==============================================================================
"""

import os
import sys
import pytest

# 添加框架根路径与父目录至 sys.path，支持相对导入和全局引用
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(BASE_DIR)
sys.path.append(os.path.dirname(BASE_DIR))

from jryg_hk_ios.JRYG_dir_init import init_all_dirs
from jryg_hk_ios.JRYG_config import REPORT_DIR

def run_tests(argv=None):
    """JRYG 港版 iOS UI 自动化测试执行引擎入口 -ios"""
    print("\n" + "="*50)
    print("      JRYG 港版阳光出行 iOS 测试执行引擎 -ios (Start)")
    print("="*50)

    # 初始化必需文件夹
    init_all_dirs()

    report_file = os.path.join(REPORT_DIR, "JRYG_test_report_hk_ios.html")

    extra_args = list(argv or [])

    # 收集所有 iOS 专用测试文件（cases/ 目录下 JRYG_test_ios_*.py）
    ios_test_files = [
        # 基础流程用例
        os.path.join(BASE_DIR, "cases", "JRYG_test_ios_open_and_login.py"),
        os.path.join(BASE_DIR, "cases", "JRYG_test_ios_open_and_route.py"),
        os.path.join(BASE_DIR, "cases", "JRYG_test_ios_booking_flow.py"),
        # E2E 全流程（重构版）
        os.path.join(BASE_DIR, "cases", "JRYG_test_ios_e2e_order.py"),
        # 参数化下单用例（车型 × 支付方式，8 种组合）
        os.path.join(BASE_DIR, "cases", "JRYG_test_ios_meter_cash_order.py"),
        os.path.join(BASE_DIR, "cases", "JRYG_test_ios_meter_epayment_order.py"),
        os.path.join(BASE_DIR, "cases", "JRYG_test_ios_meter_alipay_order.py"),
        os.path.join(BASE_DIR, "cases", "JRYG_test_ios_meter_bankcard_order.py"),
        os.path.join(BASE_DIR, "cases", "JRYG_test_ios_charter_cash_order.py"),
        os.path.join(BASE_DIR, "cases", "JRYG_test_ios_charter_epayment_order.py"),
        os.path.join(BASE_DIR, "cases", "JRYG_test_ios_charter_alipay_order.py"),
        os.path.join(BASE_DIR, "cases", "JRYG_test_ios_charter_bankcard_order.py"),
    ]

    # 过滤出实际存在的文件
    existing_files = [f for f in ios_test_files if os.path.exists(f)]
    if not existing_files:
        print("[错误 -ios] 未找到任何 iOS 测试文件！")
        return 1

    pytest_args = [
        "-c", os.path.join(BASE_DIR, "pytest.ini"),
        "-v", "-s",
    ] + existing_files

    if not any(arg in ("--collect-only", "--co") for arg in extra_args):
        pytest_args.extend([f"--html={report_file}", "--self-contained-html"])
        print(f"输出香港 iOS UI 测试报告: {report_file}")
    exit_code = pytest.main(pytest_args + extra_args)

    print("="*50)
    print("      JRYG 港版阳光出行 iOS 测试执行引擎 -ios (Completed)")
    print("="*50 + "\n")
    return exit_code

if __name__ == "__main__":
    sys.exit(run_tests(sys.argv[1:]))
