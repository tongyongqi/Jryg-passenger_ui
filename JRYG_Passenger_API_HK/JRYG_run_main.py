"""香港接口自动化入口，不启动 App 或检查设备。

--suite all      常规接口回归（默认）
--suite auth     乘客认证接口
--suite order    乘客下单流程
--suite dual     双端接口流程
--suite e2e      Socket 定位、缓存清理、下单至收款
--suite capture  抓包接口断言，输入目录由 HK_CAPTURE_DIR 指定
--collect-only   只收集用例，不请求业务接口或清理缓存
"""

import argparse
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from JRYG_Passenger_API_HK.common.JRYG_config import CASES_DIR, REPORT_DIR, init_all_dirs

SUITES = {
    "all": None,
    "auth": "JRYG_test_hk_api.py",
    "order": "JRYG_test_hk_order_flow.py",
    "dual": "JRYG_test_hk_dual_end_flow.py",
    "e2e": "test_e2e_full_flow.py",
    "capture": "JRYG_test_place_around.py",
}


def run_tests(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--suite", choices=SUITES, default="all", help="选择接口套件")
    args, pytest_args = parser.parse_known_args(argv)

    import pytest

    target = CASES_DIR / SUITES[args.suite] if SUITES[args.suite] else CASES_DIR
    selection = args.suite if args.suite in ("e2e", "capture") else "not capture and not e2e"
    options = ["-c", str(BASE_DIR / "pytest.ini"), str(target), "-m", selection, "-v"]
    if not any(option in ("--collect-only", "--co") for option in pytest_args):
        init_all_dirs()
        report = REPORT_DIR / f"JRYG_api_report_{args.suite}.html"
        options.extend([f"--html={report}", "--self-contained-html"])
    return pytest.main(options + pytest_args)


if __name__ == "__main__":
    sys.exit(run_tests())
