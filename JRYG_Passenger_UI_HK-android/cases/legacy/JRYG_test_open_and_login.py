"""香港 Android 独立登录与优惠券下单用例，复用公共乘客及优惠券步骤。"""

import pytest

from jryg_hk_android.JRYG_config import SETTINGS
from jryg_hk_android.JRYG_android_coupon import AndroidCouponBase
from ui_framework import JRYG_ios_ui_elements as E


@pytest.mark.skipif(
    SETTINGS["device"].get("platform_name", "Android").upper() != "ANDROID",
    reason="当前不是 Android 自动化环境",
)
class TestJRYGHKOneKeyLogin(AndroidCouponBase):
    """独立登录与指定优惠券下单场景，复用公共设备连接和乘客步骤。"""

    def test_passenger_hk_login_flow(self):
        """启动后从个人中心核验登录态，并确认乘客前台及保存截图。"""
        assert self.ensure_passenger_login("login"), "乘客登录状态未确认"
        self._assert_passenger_foreground()
        self._ios_screenshot("JRYG_login_completed.png")

    def test_passenger_hk_booking_flow(self):
        """从指定预约起点选择目标优惠券并真实呼叫，仅核验乘客下单成功。

        未在此用例验证司机接单、行程完成或最终同单到账。
        """
        self.prepare_passenger_route("booking", start=E.BOOKING_START_ADDRESS, verify_login=True)
        selected = self.select_coupons(policy="target", target_keywords=E.COUPON_TARGET_TEXTS)
        assert selected, "目标优惠券未选择"
        self._ios_click_confirm_call("booking")
        assert self._ios_wait_order_result("booking") == "success", "乘客 UI 下单未成功"
        self._ios_screenshot("JRYG_booking_submitted.png")
