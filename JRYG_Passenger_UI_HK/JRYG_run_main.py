import os
import sys
import pytest

# 添加框架根路径与父目录至 sys.path，支持相对导入和全局引用
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(BASE_DIR)
sys.path.append(os.path.dirname(BASE_DIR))

from JRYG_Passenger_UI_HK.common.JRYG_dir_init import init_all_dirs
from JRYG_Passenger_UI_HK.common.JRYG_config import REPORT_DIR

def run_tests():
    """JRYG 港版 UI 自动化测试执行引擎入口"""
    print("\n" + "="*50)
    print("      JRYG 港版阳光出行测试执行引擎 (Start)")
    print("="*50)
    
    # 初始化必需文件夹
    init_all_dirs()
    
    report_file = os.path.join(REPORT_DIR, "JRYG_test_report_hk.html")
    
    # 动态匹配 JRYG_*.py 规格
    pytest_args = [
        "-v", "-s",
        os.path.join(BASE_DIR, "cases"),
        "-o", "python_files=JRYG_*.py",
        "-o", "python_classes=TestJRYG*",
        "-o", "python_functions=test_*",
        f"--html={report_file}",
        "--self-contained-html"
    ]
    
    print(f"执行港版用例检测，正在输出 HTML 测试报告: {report_file}")
    exit_code = pytest.main(pytest_args)
    
    print("="*50)
    print("      JRYG 港版阳光出行测试执行引擎 (Completed)")
    print("="*50 + "\n")
    return exit_code

if __name__ == "__main__":
    run_tests()
