"""包車價的士＋银行卡及OTP预付，行程结束后不重复支付。"""

from pathlib import Path
import sys

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from jryg_hk_android.JRYG_android_order import AndroidOrderBase


class TestCharterBankcardAndroid(AndroidOrderBase):
    __test__ = True
    CAR_TYPE = "charter"
    PAYMENT = "bankcard"
    FINAL_PAYMENT = ""
    ios_scenario_name = "TestCharterBankcard"

    def test_order_flow(self):
        """卡表单及OTP预付→司机行程及只读账单→同订单到账核验。"""
        self._run_order_flow()


if __name__ == "__main__":
    from JRYG_run_main import run_tests
    sys.exit(run_tests(["--case", str(Path(__file__).resolve()), *sys.argv[1:]]))
