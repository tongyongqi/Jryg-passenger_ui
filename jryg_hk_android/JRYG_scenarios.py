"""安卓独立订单场景清单，顺序与已验证iOS默认清单一致。

V1.5.0 新增预约用车、安全中心、邮箱收据、收银台真机调试场景，
不参与六场景默认批量运行，仅在 --case 或 include_optional 时可选。
"""

import importlib.util
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
SCENARIOS = (
    ("JRYG_test_android_meter_cash_order.py", "TestMeterCashAndroid"),
    ("JRYG_test_android_meter_epayment_bankcard_order.py", "TestMeterEpaymentBankcardAndroid"),
    ("JRYG_test_android_meter_epayment_alipay_order.py", "TestMeterEpaymentAlipayAndroid"),
    ("JRYG_test_android_meter_alipay_order.py", "TestMeterAlipayAndroid"),
    ("JRYG_test_android_charter_alipay_order.py", "TestCharterAlipayAndroid"),
    ("JRYG_test_android_charter_bankcard_order.py", "TestCharterBankcardAndroid"),
)
OPTIONAL_SCENARIOS = (
    ("JRYG_test_android_meter_epayment_target_order.py", "TestMeterEpaymentTargetOrderAndroid"),
)
# V1.5.0 真机调试场景：方法名非 test_order_flow，需单独指定
V150_DEVICE_SCENARIOS = (
    ("JRYG_test_android_v150_booking.py", "TestV150BookingDevice", "test_booking_entry_and_time_selection"),
    ("JRYG_test_android_v150_safety.py", "TestV150SafetyDevice", "test_safety_center_entry_and_contacts"),
    ("JRYG_test_android_v150_email.py", "TestV150EmailDevice", "test_email_native_input_replaces_exactly_once"),
    ("JRYG_test_android_v150_email.py", "TestV150EmailDevice", "test_email_settings_entry_open_management_page"),
    ("JRYG_test_android_v150_email.py", "TestV150EmailDevice", "test_email_save_format_validation_rules"),
    ("JRYG_test_android_v150_email.py", "TestV150EmailDevice", "test_email_save_with_surrounding_spaces_trims_value"),
    ("JRYG_test_android_v150_email.py", "TestV150EmailDevice", "test_email_invalid_format_toast_and_not_saved"),
    ("JRYG_test_android_v150_email.py", "TestV150EmailDevice", "test_email_empty_value_deletes_and_toast_success"),
    ("JRYG_test_android_v150_receipt.py", "TestV150ReceiptDevice", "test_receipt_order_detail_shows_prompt_and_button"),
    ("JRYG_test_android_v150_receipt.py", "TestV150ReceiptDevice", "test_receipt_dialog_content_and_initial_state"),
    ("JRYG_test_android_v150_receipt.py", "TestV150ReceiptDevice", "test_receipt_saved_email_entry_sends_directly_without_dialog"),
    ("JRYG_test_android_v150_receipt.py", "TestV150ReceiptDevice", "test_receipt_unset_email_entry_shows_set_and_send_dialog"),
    ("JRYG_test_android_v150_receipt.py", "TestV150ReceiptDevice", "test_receipt_empty_email_save_restores_set_and_send_entry"),
    ("JRYG_test_android_v150_receipt.py", "TestV150ReceiptDevice", "test_receipt_modify_enables_editing_and_keyboard"),
    ("JRYG_test_android_v150_receipt.py", "TestV150ReceiptDevice", "test_receipt_input_toggles_send_button"),
    ("JRYG_test_android_v150_receipt.py", "TestV150ReceiptDevice", "test_receipt_send_with_valid_email_toast_success"),
    ("JRYG_test_android_v150_receipt.py", "TestV150ReceiptDevice", "test_receipt_saved_email_direct_send_succeeds"),
    ("JRYG_test_android_v150_receipt.py", "TestV150ReceiptDevice", "test_receipt_empty_or_invalid_email_blocks_submit"),
    ("JRYG_test_android_v150_receipt.py", "TestV150ReceiptDevice", "test_receipt_send_rate_limit_two_per_minute"),
    ("JRYG_test_android_v150_receipt.py", "TestV150ReceiptDevice", "test_receipt_close_dialog_does_not_save_draft"),
    ("JRYG_test_android_v150_cashier.py", "TestV150CashierDevice", "test_cashier_payment_order"),
    ("JRYG_test_android_v150_cashier.py", "TestV150CashierDevice", "test_cashier_wechat_uninstalled_prompt"),
)


def scenario_nodes(*, include_optional=False):
    nodes = []
    scenarios = SCENARIOS + OPTIONAL_SCENARIOS if include_optional else SCENARIOS
    for filename, class_name in scenarios:
        path = BASE_DIR / "cases" / filename
        if not path.is_file():
            raise RuntimeError(f"安卓独立订单场景缺失：{filename}")
        nodes.append(f"{path}::{class_name}::test_order_flow")
    if include_optional:
        for filename, class_name, method_name in V150_DEVICE_SCENARIOS:
            path = BASE_DIR / "cases" / filename
            if not path.is_file():
                raise RuntimeError(f"V1.5.0 真机调试场景缺失：{filename}")
            nodes.append(f"{path}::{class_name}::{method_name}")
    return nodes


def android_scenarios():
    for filename, class_name in SCENARIOS:
        path = BASE_DIR / "cases" / filename
        spec = importlib.util.spec_from_file_location("hk_android_" + path.stem, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        yield getattr(module, class_name)
