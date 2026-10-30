"""打錶的士线上后付Alipay HK：下单仍选電子支付，只改变行程结束后的支付渠道。

复用已验证双端UI顺序：司机出车 → 乘客下单 → 司机接单/滑动状态/账单
→ 乘客选择Alipay HK → Safari Pay Now/SUCCESS → 返回乘客首页
→ 司机到账详情核验同订单已完成且已支付。无需司机业务接口或token。
本文件仅配置FINAL_PAYMENT="alipay"，启动、地址、状态与费用等待全部继承；
付款通过iOSBase._ios_pay复用Safari实现，不在本用例重复写Pay Now动作。
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
class TestMeterEpaymentAlipay(TestOrderBase):
    """电子支付下单＋Alipay HK后付，不修改车型、司机流程、账单和最终同订单核验。"""

    __test__ = True
    CAR_TYPE = "meter"
    PAYMENT = "epayment"
    FINAL_PAYMENT = "alipay"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "-s", *sys.argv[1:]]))
