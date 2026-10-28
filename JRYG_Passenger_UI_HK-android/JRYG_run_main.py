import os
import sys
import pytest

# 添加框架根路径与父目录至 sys.path，支持相对导入和全局引用
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(BASE_DIR)
sys.path.append(os.path.dirname(BASE_DIR))

from jryg_hk_android.JRYG_dir_init import init_all_dirs
from jryg_hk_android.JRYG_config import REPORT_DIR

def run_tests(argv=None):
    """JRYG 港版 UI 自动化测试执行引擎入口"""
    print("\n" + "="*50)
    print("      JRYG 港版阳光出行测试执行引擎 (Start)")
    print("="*50)
    
    # 初始化必需文件夹
    init_all_dirs()
    
    report_file = os.path.join(REPORT_DIR, "JRYG_test_report_hk.html")
    
    extra_args = list(argv or [])
    pytest_args = [
        "-c", os.path.join(BASE_DIR, "pytest.ini"),
        "-v", "-s",
        os.path.join(BASE_DIR, "cases", "JRYG_test_open_app.py"),
    ]
    if not any(arg in ("--collect-only", "--co") for arg in extra_args):
        pytest_args.extend([f"--html={report_file}", "--self-contained-html"])
        print(f"输出香港 UI 测试报告: {report_file}")
    exit_code = pytest.main(pytest_args + extra_args)
    
    print("="*50)
    print("      JRYG 港版阳光出行测试执行引擎 (Completed)")
    print("="*50 + "\n")
    return exit_code

if __name__ == "__main__":
    sys.exit(run_tests(sys.argv[1:]))
