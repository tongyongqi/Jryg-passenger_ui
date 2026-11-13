# 编写时间：2026-10-15
# 本期功能：非目标订单结束后继续接目标单，目标采用电子支付银行卡后付
"""安卓：非目标订单结束后继续接本次乘客目标单，目标采用电子支付银行卡后付。"""

from pathlib import Path
import sys

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from jryg_hk_android.JRYG_android_target_order import AndroidTargetOrderBase


class TestMeterEpaymentTargetOrderAndroid(AndroidTargetOrderBase):
    __test__ = True
    CAR_TYPE = "meter"
    PAYMENT = "epayment"
    FINAL_PAYMENT = "bankcard"

    def test_order_flow(self):
        """逐单核对订单号，非目标单结束后继续听单，最终核验目标单已完成且已支付。"""
        self._run_order_flow()


if __name__ == "__main__":
    from JRYG_run_main import run_tests

    sys.exit(run_tests(["--case", str(Path(__file__).resolve()), *sys.argv[1:]]))
