import os
import sys
import pytest

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from jryg_ios.JRYG_dir_init import init_all_dirs
from jryg_ios.JRYG_config import REPORT_DIR

# 大陆 iOS UI 自动化测试执行顺序：
# 1. 登录 → 进入首页
# 2. 首页下单 → 询价 → 收银台 → 呼叫
# 3. 设置页面功能验证
TEST_ORDER = [
    os.path.join(BASE_DIR, "cases", "JRYG_test_ios_login.py"),
    os.path.join(BASE_DIR, "cases", "JRYG_test_ios_order.py"),
    os.path.join(BASE_DIR, "cases", "JRYG_test_ios_settings.py"),
]

def run_tests(extra_args=None):
    """JRYG iOS 自动化测试执行引擎入口，按指定顺序运行测试并生成报告。"""
    print("\n" + "="*50)
    print("      JRYG 阳光出行 iOS 测试执行引擎 (Start)")
    print("="*50)

    init_all_dirs()

    report_file = os.path.join(REPORT_DIR, "JRYG_test_report_ios.html")

    pytest_args = [
        "-v", "-s",
        *TEST_ORDER,
        "-o", "python_files=JRYG_test_ios_*.py",
        "-o", "python_classes=TestJRYG*",
        "-o", "python_functions=test_ios_*",
        f"--html={report_file}",
        "--self-contained-html"
    ]

    pytest_args.extend(extra_args or [])
    print("执行顺序：登录 → 下单 → 设置页面")
    for i, path in enumerate(TEST_ORDER, 1):
        print(f"  {i}. {os.path.basename(path)}")
    print(f"执行用例检测，正在输出 HTML 测试报告: {report_file}")
    exit_code = pytest.main(pytest_args)
    print(f"JRYG iOS 测试执行结束，退出码: {exit_code}")
    return exit_code

if __name__ == "__main__":
    sys.exit(run_tests(sys.argv[1:]))
