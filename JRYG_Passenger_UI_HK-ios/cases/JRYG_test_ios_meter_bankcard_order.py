"""
港版 iOS 测试场景：打錶的士 + 信用卡/扣帳卡支付
==============================================================================
车型：打錶的士（meter）
支付：信用卡/扣帳卡（bankcard）
==============================================================================
"""

import os
import sys
import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from jryg_hk_ios.JRYG_config import SETTINGS
from cases.JRYG_test_ios_order_base import TestOrderBase


@pytest.mark.skipif(
    SETTINGS["device"].get("platform_name", "Android").upper() == "ANDROID",
    reason="当前配置为 Android 自动化环境，跳过 iOS 测试"
)
class TestMeterBankcard(TestOrderBase):
    """打錶的士 + 信用卡/扣帳卡支付"""

    __test__ = True
    CAR_TYPE = "meter"
    PAYMENT = "bankcard"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "-s", *sys.argv[1:]]))
