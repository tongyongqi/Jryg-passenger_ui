"""
JRYG 港版 iOS E2E 下单全流程自动化测试运行入口
==============================================================================
功能：
  一键运行 iOS E2E 下单全流程用例
  执行顺序：打开App → 登录 → 包车价下单(Alipay HK+银行卡) → 打表下单(后付→现金)

运行方式：
  方式 1（Shell 脚本）:
    bash JRYG_run_e2e_order_ios.sh

  方式 2（Python 直接运行）:
    python3 JRYG_run_e2e_order_ios.py
    python3 JRYG_run_e2e_order_ios.py --collect-only   # 仅收集用例不执行
    python3 JRYG_run_e2e_order_ios.py -k test_e2e       # 按关键字筛选

  方式 3（PyCharm）:
    右键本文件 → Run
==============================================================================
"""

import os
import sys
import pytest

# 添加框架根路径
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from jryg_hk_ios.JRYG_dir_init import init_all_dirs
from jryg_hk_ios.JRYG_config import REPORT_DIR


def run_tests(argv=None):
    """JRYG 港版 iOS E2E 下单全流程测试执行引擎"""
    print("\n" + "=" * 60)
    print("   JRYG 港版阳光出行 iOS E2E 下单全流程测试引擎 (Start)")
    print("   流程: 打开App → 登录 → 包车价下单 → 打表下单(后付+现金)")
    print("=" * 60)

    # 初始化必需文件夹
    init_all_dirs()

    report_file = os.path.join(REPORT_DIR, "JRYG_test_report_e2e_order_ios.html")

    extra_args = list(argv or [])

    # E2E 下单全流程用例文件
    e2e_test_files = [
        os.path.join(BASE_DIR, "cases", "JRYG_test_ios_e2e_order.py"),
    ]

    # 过滤出实际存在的文件
    existing_files = [f for f in e2e_test_files if os.path.exists(f)]
    if not existing_files:
        print("[错误] 未找到 E2E 下单测试文件！")
        return 1

    # 检查文件是否存在
    for f in e2e_test_files:
        if not os.path.exists(f):
            print(f"[警告] 测试文件不存在: {f}")

    pytest_args = [
        "-c", os.path.join(BASE_DIR, "pytest.ini"),
        "-v", "-s",
    ] + existing_files

    # 非 collect-only 模式时生成 HTML 报告
    if not any(arg in ("--collect-only", "--co") for arg in extra_args):
        pytest_args.extend([f"--html={report_file}", "--self-contained-html"])
        print(f"  >> 测试报告将输出至: {report_file}")

    # 打印运行信息
    print(f"  >> 测试文件: {existing_files}")
    print(f"  >> 额外参数: {extra_args or '(无)'}")
    print("-" * 60)

    from jryg_hk_ios.JRYG_run_result import E2EResult
    result = E2EResult()
    exit_code = pytest.main(pytest_args + extra_args, plugins=[result])
    collect_only = any(arg in ("--collect-only", "--co") for arg in extra_args)
    exit_code, message = result.outcome(exit_code, collect_only)

    print("=" * 60)
    print(f"   JRYG 港版 iOS E2E → {message} (exit_code={exit_code})")
    print("=" * 60 + "\n")

    # 报告路径提示
    if not collect_only and os.path.exists(report_file):
        print(f"[报告] file://{report_file}")

    return exit_code


if __name__ == "__main__":
    sys.exit(run_tests(sys.argv[1:]))
