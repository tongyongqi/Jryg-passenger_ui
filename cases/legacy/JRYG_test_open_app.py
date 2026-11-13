# 编写时间：2026-09-20
# 本期功能：香港 Android 早期场景 — 优惠券规则用例
"""香港 Android 优惠券规则用例，公共设备、登录、路线与券操作均由框架提供。"""

import time

import pytest

from jryg_hk_android.JRYG_config import SETTINGS
from jryg_hk_android.JRYG_android_coupon import AndroidCouponBase
from jryg_hk_android.JRYG_android_order import AndroidDriverUIFlow
from jryg_hk_android.JRYG_android_ui import resolve_runtime
from jryg_hk_android import JRYG_android_ui_elements as E
from jryg_hk_android.JRYG_driver_ui import parser


@pytest.mark.skipif(
    SETTINGS["device"].get("platform_name", "Android").upper() != "ANDROID",
    reason="当前不是 Android 自动化环境",
)
class TestJRYGHKAndroidOrder(AndroidCouponBase):
    """优惠券时效和选择保留规则；历史直接下单及司机入口保持跳过。"""

    @pytest.mark.skip(reason="只进行乘客端优惠券场景校验，跳过直接呼叫下单")
    def test_android_launch_to_order(self):
        """历史入口检查已有订单或准备路线，不作为当前完整订单验证。"""
        self._android_prepare_passenger_app("legacy_order")
        if self.client(textContains="取消訂單").exists:
            self._android_screenshot("JRYG_android_06_order_submitted.png")
            return
        self.prepare_passenger_route("legacy_order", start=E.BOOKING_START_ADDRESS)

    @pytest.mark.skip(reason="只进行乘客端优惠券场景校验，跳过司机端流程")
    def test_android_driver_order_flow(self):
        """已跳过的历史司机调试入口，目标仅到bill阶段，不包含最终付款核验。"""
        runtime = resolve_runtime(self.order_settings)
        args = parser(wda_url=runtime.wda_url).parse_args(["--stop-after", "bill"])
        AndroidDriverUIFlow(args, client=self.clients[runtime.udid]).run()

    def test_android_coupon_expiry_verification(self):
        """选择优惠券后等待310秒并触发估价校验，断言刷新后原选择仍保留。

        本用例未直接断言过期提示一定出现，弹窗文案仅用于可选关闭。
        """
        self.prepare_passenger_route("coupon_expiry", start=E.BOOKING_START_ADDRESS, verify_login=True)
        self._android_select_car_type("coupon_expiry", "charter")
        self._android_screenshot("JRYG_coupon_check_01_quote.png")
        selected = self.select_coupons(policy="all")
        assert selected, "未选择任何优惠券"
        time.sleep(310)
        self._android_click_confirm_call("coupon_expiry")
        time.sleep(4)
        self._android_screenshot("JRYG_coupon_check_03_expired_prompt.png")
        self._android_click_dialog_button([
            "確定", "确定", "確認", "确认", "我知道了", "同意", "重新估價", "重新估价"], wait_after=4)
        self.open_coupon_list()
        self._android_screenshot("JRYG_coupon_check_04_post_verification.png")
        assert self.selected_coupons_retained(selected), "估价刷新后原选券未保留选择状态"
        self.return_to_quote()
        self._android_back_to_home("coupon_expiry")
        self._android_screenshot("JRYG_coupon_check_05_finished.png")

    def test_android_coupon_rules_scenarios(self):
        """核验初始无错误、App恢复及收银台退出后优惠券保留，最后真实确认下单。

        结束只确认乘客下单结果，不包含司机行程与最终同订单到账验证。
        """
        self.prepare_passenger_route("coupon_rules", start=E.BOOKING_START_ADDRESS, verify_login=True)
        time.sleep(5)
        prompt = self.client(textMatches=".*预估信息已更新.*|.*请重新选择.*|.*失效.*")
        assert not prompt.exists, "初始进入选择车型页面不应有刷新提示或报错"

        self._android_select_car_type("coupon_rules", "charter")
        selected = self.select_coupons(policy="all")
        assert selected, "目标优惠券未选择"
        self._android_screenshot("JRYG_scenario_A_selected.png")
        self.resume_passenger_app()
        self._android_screenshot("JRYG_scenario_A_foreground.png")
        self.open_coupon_list()
        self._android_screenshot("JRYG_scenario_A_retained_check.png")
        assert self.selected_coupons_retained(selected), "应用从后台切回前台后，目标优惠券未被保留"
        self.return_to_quote()

        self.open_prepaid_cashier("coupon_rules")
        self._android_screenshot("JRYG_scenario_C_cashier.png")
        self.close_prepaid_cashier()
        self._android_screenshot("JRYG_scenario_C_back_to_quote.png")
        self.open_coupon_list()
        self._android_screenshot("JRYG_scenario_C_retained_check.png")
        assert self.selected_coupons_retained(selected), "收银台关闭并刷新估价后，目标优惠券未被保留"
        self.return_to_quote()

        self.open_prepaid_cashier("coupon_rules")
        self._android_screenshot("JRYG_prepaid_cashier_order.png")
        self._android_click_confirm_pay("coupon_rules")
        assert self._android_wait_order_result("coupon_rules") == "success", "优惠券支付下单结果未确认"
        self._android_screenshot("JRYG_order_submitted_with_coupon.png")
