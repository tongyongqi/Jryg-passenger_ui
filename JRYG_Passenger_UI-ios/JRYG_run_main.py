"""JRYG_Passenger_UI-ios 自动化模块 —— JRYG_run_main.py
==============================================================================
"""

import os
import sys
import pytest

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# 用例目录
CASES_DIR = os.path.join(BASE_DIR, "cases")
REPORT_DIR = os.path.join(BASE_DIR, "report")
LOGS_DIR = os.path.join(BASE_DIR, "logs")
SCREENSHOTS_DIR = os.path.join(BASE_DIR, "screenshots")

for d in (REPORT_DIR, LOGS_DIR, SCREENSHOTS_DIR):
    os.makedirs(d, exist_ok=True)


def run_tests(extra_args=None):
    """JRYG 大陆 iOS UI 自动化测试执行引擎入口

    :param extra_args: 可选的 pytest 命令行参数列表，例如 ['-k', 'login'] 筛选用例。
    """
    print("\n" + "=" * 50)
    print("      JRYG 大陆 iOS 测试执行引擎 (Start)")
    print("=" * 50)

    report_file = os.path.join(REPORT_DIR, "JRYG_test_report.html")

    if not os.path.isdir(CASES_DIR):
        print(f"[错误] 用例目录不存在: {CASES_DIR}")
        return 1

    # 检查是否有 .py 用例文件
    py_files = [f for f in os.listdir(CASES_DIR) if f.endswith(".py") and not f.startswith("_")]
    if not py_files:
        print(f"[提示] 用例目录 {CASES_DIR} 中暂无用例文件。")
        print("       请按「一个场景一个 .py 文件」的方式添加 iOS 用例后再执行。")
        return 0

    pytest_args = [
        "-v", "-s",
        CASES_DIR,
        "-o", "python_files=test_*.py",
        "-o", "python_classes=Test*",
        "-o", "python_functions=test_*",
        f"--html={report_file}",
        "--self-contained-html"
    ]
    pytest_args.extend(extra_args or [])

    print(f"执行大陆 iOS 用例，目录: {CASES_DIR}")
    print(f"正在输出 HTML 测试报告: {report_file}")
    exit_code = pytest.main(pytest_args)
    print(f"JRYG 大陆 iOS 测试执行结束，退出码: {exit_code}")
    return exit_code


if __name__ == "__main__":
    sys.exit(run_tests(sys.argv[1:]))
