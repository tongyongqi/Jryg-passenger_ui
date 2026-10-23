import os
import sys
import pytest

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from JRYG_Passenger_UI.common.JRYG_dir_init import init_all_dirs
from JRYG_Passenger_UI.common.JRYG_config import REPORT_DIR

def run_tests(extra_args=None):
    """JRYG UI 自动化测试执行引擎入口，自动生成测试报告。

    :param extra_args: 可选的 pytest 命令行参数列表，格式为 list[str]，
                       例如 ['-k', 'test_login'] 用于筛选用例，默认为 None 即执行全部用例。
    """
    print("\n" + "="*50)
    print("      JRYG 阳光出行测试执行引擎 (Start)")
    print("="*50)
    
    # 初始化必需文件夹
    init_all_dirs()
    
    report_file = os.path.join(REPORT_DIR, "JRYG_test_report.html")
    
    pytest_args = [
        "-v", "-s",
        os.path.join(BASE_DIR, "cases"),
        "-o", "python_files=JRYG_test_*.py",
        "-o", "python_classes=TestJRYG*",
        "-o", "python_functions=test_*",
        f"--html={report_file}",
        "--self-contained-html"
    ]
    
    pytest_args.extend(extra_args or [])
    print(f"执行用例检测，正在输出 HTML 测试报告: {report_file}")
    exit_code = pytest.main(pytest_args)
    print(f"JRYG 测试执行结束，退出码: {exit_code}")
    return exit_code

if __name__ == "__main__":
    sys.exit(run_tests(sys.argv[1:]))
