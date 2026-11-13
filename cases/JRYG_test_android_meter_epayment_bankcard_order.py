"""打錶的士＋電子支付下单，行程结束后银行卡及OTP后付。"""

from pathlib import Path
import sys

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from jryg_hk_android.JRYG_android_order import AndroidOrderBase


class TestMeterEpaymentBankcardAndroid(AndroidOrderBase):
    __test__ = True
    CAR_TYPE = "meter"
    PAYMENT = "epayment"
    FINAL_PAYMENT = "bankcard"
    android_scenario_name = "TestMeterEpaymentBankcard"

    def test_order_flow(self):
        """电子支付下单→司机账单→卡表单→OTP→同订单到账核验。"""
        self._run_order_flow()


if __name__ == "__main__":
    from JRYG_run_main import run_tests
    sys.exit(run_tests(["--case", str(Path(__file__).resolve()), *sys.argv[1:]]))
