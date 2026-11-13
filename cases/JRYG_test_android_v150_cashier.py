"""V1.5.0 收银台真机调试场景。

覆盖：
- 收银台支付方式排列顺序（AlipayHK→Octopus→Card）
- 支付方式不重复出现

本场景需要在收银台页面执行，可通过包车预付流程进入，
或由调用方在进入收银台后单独调用验证方法。
不实际支付、不提交订单。
"""

from pathlib import Path
import sys

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from jryg_hk_android.JRYG_v150_device_steps import V150DeviceSteps


class TestV150CashierDevice(V150DeviceSteps):
    __test__ = True
    DRIVER_REQUIRED = False

    def test_cashier_payment_order(self):
        """验证收银台支付方式顺序及不重复。

        前置条件：当前已在收银台页面（通过包车呼叫进入先付後乘页面）。
        如果不在收银台，本测试将跳过并记录。
        """
        tag = "v150_cashier"
        self._ensure_devices_awake()
        self.prepare_passenger_app(tag, launch=True)
        self.ensure_passenger_login(tag)

        # 检测是否已在收银台页面
        page = self._v150_current_page_type()
        if page != "cashier":
            # 尝试通过包车流程进入收银台
            # 设置路线并选择包车 + 预付方式
            from jryg_hk_android import JRYG_android_ui_elements as E
            self.prepare_passenger_route(tag, start=E.DEFAULT_START_ADDRESS, end=E.DEFAULT_END_ADDRESS)
            self._click_text([E.CHARTER_CAR_LABEL], exact=True)
            # 选择预付支付方式（Alipay HK）
            self._android_select_payment(tag, "alipay")
            # 点击确认呼叫进入收银台
            self._android_click_confirm_call(tag)
            # 等待收银台页面
            self._wait(
                lambda: self._v150_current_page_type() == "cashier",
                "V1.5.0 未进入收银台页面",
                timeout=15,
            )
        self.v150_screenshot("cashier_page")

        # 验证支付方式顺序
        result = self.v150_verify_cashier_order(tag)
        assert result["count"] > 0, "收银台未找到任何支付方式"
        self.v150_screenshot("cashier_payment_order")

        # 验证不重复
        dup_result = self.v150_verify_cashier_no_duplicate(tag)
        assert not dup_result["duplicates"], "收银台存在重复支付方式"


if __name__ == "__main__":
    from JRYG_run_main import run_tests
    sys.exit(run_tests(["--case", str(Path(__file__).resolve()), *sys.argv[1:]]))
