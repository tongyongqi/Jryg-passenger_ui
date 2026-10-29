"""
港版 iOS 测试场景：包車價的士 + 電子支付
==============================================================================
车型：包車價的士（charter）
支付：電子支付（epayment）
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
class TestCharterEpayment(TestOrderBase):
    """包車價的士 + 電子支付"""

    __test__ = True
    CAR_TYPE = "charter"
    PAYMENT = "epayment"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "-s", *sys.argv[1:]]))
