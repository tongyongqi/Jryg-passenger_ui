"""打錶的士电子支付后付－银行卡，独立于Alipay HK和现金用例。

下单选電子支付；司机全UI接单、状态与账单不变。行程结束通过公共支付入口
选择信用卡或扣帳卡，提交卡表单/OTP后核验司机同订单已完成且已支付。
此文件只声明车型、下单方式和FINAL_PAYMENT，不复制App准备、地址或支付代码；
公共支付来自iOSBase._ios_pay，司机编排来自TestOrderBase.test_order_flow。
"""

import os
import sys

import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from ui_framework.JRYG_config import SETTINGS
from ui_framework.JRYG_order_flow import TestOrderBase


@pytest.mark.skipif(
    SETTINGS["device"].get("platform_name", "Android").upper() == "ANDROID",
    reason="当前配置为Android环境，跳过iOS测试",
)
class TestMeterEpaymentBankcard(TestOrderBase):
    """电子支付下单＋银行卡后付，复用统一订单编排和支付方法。"""

    __test__ = True
    CAR_TYPE = "meter"
    PAYMENT = "epayment"
    FINAL_PAYMENT = "bankcard"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "-s", *sys.argv[1:]]))
