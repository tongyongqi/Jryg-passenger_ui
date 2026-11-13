# 编写时间：2026-10-15
# 本期功能：打錶的士＋現金下单，司机填写 5 HKD 车费及 0 附加费，同订单完成核验
"""打錶的士＋現金：司机填写5 HKD车费及0附加费，同订单完成核验。"""

from pathlib import Path
import sys

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from jryg_hk_android.JRYG_android_order import AndroidOrderBase


class TestMeterCashAndroid(AndroidOrderBase):
    __test__ = True
    CAR_TYPE = "meter"
    PAYMENT = "cash"
    FINAL_PAYMENT = ""
    android_scenario_name = "TestMeterCash"

    def test_order_flow(self):
        """北角A1→香港大学，现金下单→司机收款，不提交线上支付。"""
        self._run_order_flow()


if __name__ == "__main__":
    from JRYG_run_main import run_tests
    sys.exit(run_tests(["--case", str(Path(__file__).resolve()), *sys.argv[1:]]))
