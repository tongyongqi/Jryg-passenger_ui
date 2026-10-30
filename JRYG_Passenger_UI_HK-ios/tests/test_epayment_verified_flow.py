"""已走通电子支付路径的金额、输入顺序、3DS结果与最终同单核验回归。

银行卡与Alipay HK仅改变后付渠道，电子支付下单方式不变；金额不符、OTP输入
失败、支付失败或SUCCESS未确认时必须停止。页面提交不替代司机同订单到账。
"""

import logging
from unittest.mock import Mock
import xml.etree.ElementTree as ET

import pytest

from tests.test_driver_readiness import OrderBase, order_module
from ui_framework import JRYG_ios_ui_elements as E


@pytest.fixture
def case(monkeypatch):
    """构造电子支付订单并模拟设备/截图，固定费用5+0、不产生真实付款。"""
    instance = OrderBase()
    instance.CAR_TYPE = "meter"
    instance.PAYMENT = "epayment"
    instance.client = Mock()
    instance.poco = Mock()
    instance._ios_screenshot = Mock()
    instance._ios_back_to_home = Mock()
    monkeypatch.setenv("HK_ORDER_AMOUNT", "5")
    monkeypatch.setenv("HK_OTHER_AMOUNT", "0")
    monkeypatch.setattr(order_module.time, "sleep", lambda seconds: None)
    return instance


def test_payment_waits_for_real_amount_page_before_submit(case):
    case._ios_get_all_texts = Mock(side_effect=[["行程結束"], ["確認支付5HKD"]])
    case._ios_wait_current_payment("test")
    assert case._ios_get_all_texts.call_count == 2
    case.client.click.assert_not_called()


def test_wrong_payment_amount_never_gets_submitted(case):
    case._ios_get_all_texts = Mock(return_value=["確認支付9HKD"])
    with pytest.raises(AssertionError, match="金额与司机账单不一致"):
        case._ios_wait_current_payment("test")
    case.client.click.assert_not_called()


def test_payment_page_timeout_is_not_skipped(case, monkeypatch):
    monkeypatch.setattr(order_module, "SETTINGS", {"order_validation": {"completion_timeout": 1}})
    monkeypatch.setattr(order_module.time, "monotonic", Mock(side_effect=[0, 0, 2]))
    case._ios_get_all_texts = Mock(return_value=["主頁"])
    with pytest.raises(TimeoutError, match="不跳过支付"):
        case._ios_wait_current_payment("test")


def test_failed_payment_message_stops_before_click(case):
    case._ios_get_all_texts = Mock(return_value=["支付失敗"])
    with pytest.raises(RuntimeError, match="支付失败或取消"):
        case._ios_wait_current_payment("test")
    case.client.click.assert_not_called()


def test_missing_card_page_does_not_return_home_as_success(case):
    case._ios_get_all_texts = Mock(return_value=["信用卡或扣帳卡", "確認支付5HKD"])
    case._ios_fill_bank_card_form = Mock(return_value=False)
    with pytest.raises(RuntimeError, match="表单未提交"):
        case._ios_complete_payment("test")
    case._ios_back_to_home.assert_not_called()


def test_card_and_3ds_submission_still_requires_driver_final_verification(case, caplog):
    case._ios_get_all_texts = Mock(return_value=["信用卡或扣帳卡", "確認支付5HKD"])
    case._ios_fill_bank_card_form = Mock(return_value=True)
    with caplog.at_level(logging.INFO):
        case._ios_complete_payment("test")
    assert "最终到账待司机同订单核验" in caplog.text
    assert "银行卡支付完成" not in caplog.text
    case._ios_back_to_home.assert_called_once()


def bank_source():
    root = ET.Element("root")
    for i, value in enumerate(("卡號", "月 / 年", "CVV", "持卡人姓名")):
        ET.SubElement(root, "XCUIElementTypeTextField", visible="true", value=value,
                      x="10", y=str(100 + i * 50), width="200", height="40")
    return ET.tostring(root, encoding="unicode")


def test_verified_card_input_sequence_and_one_otp_submission(case, caplog):
    """核验卡表单输入顺序、一次OTP提交及日志正文不含卡数据。

    日志泄露检查不包含pytest附加的源码行号，避免行号恰好等于测试CVV时误报。
    """
    case._ios_get_all_texts = Mock(return_value=[E.BANK_PAGE_KEYWORDS[0]])
    case.client.source.return_value = bank_source()
    actions = []
    case.client.send_keys.side_effect = lambda value: actions.append(value)
    case._ios_handle_otp_page = Mock(side_effect=lambda tag: actions.append("3DS"))
    with caplog.at_level(logging.INFO):
        assert case._ios_fill_bank_card_form("test") is True
    assert actions == [E.TEST_CARD_NUMBER, E.TEST_CARD_EXPIRY, E.TEST_CARD_CVV, E.TEST_CARD_HOLDER, "3DS"]
    for value in (E.TEST_CARD_NUMBER, E.TEST_CARD_CVV, E.TEST_CARD_HOLDER):
        assert all(value not in message for message in caplog.messages)
    case._ios_handle_otp_page.assert_called_once()


def test_missing_required_card_field_stops_before_payment(case):
    case._ios_get_all_texts = Mock(return_value=[E.BANK_PAGE_KEYWORDS[0]])
    case.client.return_value = Mock(exists=False)
    case.client.source.return_value = "<root />"
    case._ios_handle_otp_page = Mock()
    with pytest.raises(RuntimeError, match="卡号未填写"):
        case._ios_fill_bank_card_form("test")
    case.client.send_keys.assert_not_called()
    case._ios_handle_otp_page.assert_not_called()


@pytest.fixture
def otp_case(case):
    case._ios_click_element_by_label = Mock(return_value=True)
    return case


def test_otp_uses_clear_input_verify_order_without_logging_code(otp_case, caplog):
    otp_case._ios_get_all_texts = Mock(side_effect=[["One-Time Password"], ["SUCCESS"], ["主頁"]])
    with caplog.at_level(logging.INFO):
        otp_case._ios_handle_otp_page("test")
    assert [c.args[0] for c in otp_case.client.send_keys.call_args_list] == ["\b"] * E.OTP_CLEAR_TIMES + [E.OTP_DEFAULT_CODE]
    assert [c.args[0] for c in otp_case._ios_click_element_by_label.call_args_list] == ["", "Verify"]
    assert E.OTP_DEFAULT_CODE not in caplog.text
    assert "待司机同订单支付状态核验" in caplog.text


def test_otp_failure_does_not_count_as_success(otp_case):
    otp_case._ios_get_all_texts = Mock(side_effect=[["One-Time Password"], ["Authentication Failed"]])
    with pytest.raises(RuntimeError, match="3DS支付验证失败"):
        otp_case._ios_handle_otp_page("test")


def test_otp_never_closes_is_a_failure(otp_case):
    otp_case._ios_get_all_texts = Mock(return_value=["One-Time Password"])
    with pytest.raises(TimeoutError, match="3DS弹层未关闭"):
        otp_case._ios_handle_otp_page("test")


def test_webview_click_uses_finite_elements(case):
    selector = Mock()
    selector.find_elements.return_value = [Mock(label="Verify & Proceed")]
    case.client.return_value = selector
    assert case._ios_click_element_by_label("Verify") is True
    selector.find_elements.assert_called_once()
    selector.find_elements.return_value[0].click.assert_called_once()


@pytest.mark.parametrize("stage", ["focus", "clear", "input"])
def test_otp_input_failure_never_clicks_verify(otp_case, stage):
    otp_case._ios_get_all_texts = Mock(return_value=["One-Time Password"])
    if stage == "focus":
        otp_case._ios_click_element_by_label.side_effect = RuntimeError("focus failed")
    elif stage == "clear":
        otp_case.client.send_keys.side_effect = RuntimeError("clear failed")
    else:
        otp_case.client.send_keys.side_effect = [None] * E.OTP_CLEAR_TIMES + [RuntimeError("input failed")]
    with pytest.raises(RuntimeError, match="停止验证"):
        otp_case._ios_handle_otp_page("test")
    assert not any(c.args[0] == "Verify" for c in otp_case._ios_click_element_by_label.call_args_list)


@pytest.mark.parametrize("final_payment", ["", "bankcard", "alipay"])
def test_epayment_keeps_order_choice_independent_from_final_channel(case, final_payment):
    case.FINAL_PAYMENT = final_payment
    assert case.PAYMENT == "epayment"
    assert case.final_payment == (final_payment or "bankcard")


def test_new_alipay_case_only_changes_postpayment_channel():
    from cases.JRYG_test_ios_meter_epayment_alipay_order import TestMeterEpaymentAlipay
    from cases.JRYG_test_ios_meter_epayment_order import TestMeterEpayment

    case = TestMeterEpaymentAlipay()
    assert case.CAR_TYPE == TestMeterEpayment.CAR_TYPE == "meter"
    assert case.PAYMENT == TestMeterEpayment.PAYMENT == "epayment"
    assert case.final_payment == "alipay"
    assert TestMeterEpaymentAlipay.test_order_flow is TestMeterEpayment.test_order_flow
    assert TestMeterEpaymentAlipay._driver_ui_grab_and_flow is TestMeterEpayment._driver_ui_grab_and_flow


@pytest.mark.parametrize("final_payment", ["bankcard", "alipay"])
def test_final_channel_routes_to_only_its_existing_payment_flow(case, final_payment):
    case.FINAL_PAYMENT = final_payment
    case._ios_get_all_texts = Mock(return_value=["信用卡或扣帳卡", "Alipay HK", "確認支付5HKD"])
    case._ios_fill_bank_card_form = Mock(return_value=True)
    case._ios_complete_alipay_payment = Mock()
    case._ios_complete_payment("test")
    chosen = case.client.call_args_list[0].kwargs["textContains"]
    if final_payment == "alipay":
        assert chosen == "Alipay HK"
        case._ios_complete_alipay_payment.assert_called_once_with("test")
        case._ios_fill_bank_card_form.assert_not_called()
    else:
        assert chosen == "信用卡或扣帳卡"
        case._ios_fill_bank_card_form.assert_called_once_with("test")
        case._ios_complete_alipay_payment.assert_not_called()


def test_missing_alipay_option_never_falls_back_to_bankcard(case):
    case.FINAL_PAYMENT = "alipay"
    case._ios_get_all_texts = Mock(return_value=["信用卡或扣帳卡", "確認支付5HKD"])
    case._ios_fill_bank_card_form = Mock()
    with pytest.raises(RuntimeError, match="未找到Alipay HK"):
        case._ios_complete_payment("test")
    case.client.assert_not_called()
    case._ios_fill_bank_card_form.assert_not_called()


def test_missing_alipay_control_never_clicks_confirm_payment(case):
    case.FINAL_PAYMENT = "alipay"
    case._ios_get_all_texts = Mock(return_value=["Alipay HK", "確認支付5HKD"])
    case.client.return_value = Mock(exists=False)
    case.poco.return_value.exists.return_value = False
    with pytest.raises(RuntimeError, match="控件不可用"):
        case._ios_complete_payment("test")
    case.client.return_value.click.assert_not_called()
    assert len(case.poco.call_args_list) == 1


@pytest.fixture
def alipay_case(case):
    case.FINAL_PAYMENT = "alipay"
    case._ios_wait_and_close_safari_alert = Mock()
    case._ios_safari_click_by_text = Mock(return_value=True)
    return case


def test_alipay_success_then_open_then_home_uses_existing_sequence(alipay_case):
    alipay_case._ios_get_all_texts = Mock(side_effect=[["SUCCESS"], ["打開"], ["主頁"], ["主頁"]])
    actions = []
    alipay_case._ios_safari_click_by_text.side_effect = lambda label, *args, **kwargs: actions.append(label) or True
    alipay_case._ios_back_to_home.side_effect = lambda tag: actions.append("passenger_home")
    alipay_case._ios_complete_alipay_payment("test")
    assert actions == ["Pay Now", "打開", "passenger_home"]
    assert alipay_case._ios_safari_click_by_text.call_args_list[0].kwargs == {"allow_fallback": False}
    alipay_case.client.click.assert_not_called()


def test_alipay_success_merchant_return_before_open_and_home(alipay_case):
    alipay_case._ios_get_all_texts = Mock(side_effect=[["SUCCESS"], ["SUCCESS"], ["Return to Merchant"], ["打开"]])
    alipay_case._ios_complete_alipay_payment("test")
    assert [c.args[0] for c in alipay_case._ios_safari_click_by_text.call_args_list] == ["Pay Now", "Return to Merchant", "打开"]
    alipay_case._ios_back_to_home.assert_called_once_with("test")


@pytest.mark.parametrize("texts", [["FAILED"], ["支付失敗"], ["UNSUCCESSFUL"], ["SUCCESS", "FAILED"]])
def test_alipay_failure_never_returns_home_as_success(alipay_case, texts):
    alipay_case._ios_get_all_texts = Mock(return_value=texts)
    with pytest.raises(RuntimeError, match="支付失败或取消"):
        alipay_case._ios_complete_alipay_payment("test")
    alipay_case._ios_back_to_home.assert_not_called()


def test_alipay_unconfirmed_payment_is_timeout_not_success(alipay_case):
    alipay_case._ios_get_all_texts = Mock(return_value=["WAITING"])
    with pytest.raises(TimeoutError, match="未确认SUCCESS"):
        alipay_case._ios_complete_alipay_payment("test")
    alipay_case._ios_back_to_home.assert_not_called()
    assert alipay_case._ios_safari_click_by_text.call_count == 1


def test_alipay_missing_pay_now_stops_without_duplicate_click(alipay_case):
    alipay_case._ios_safari_click_by_text.return_value = False
    with pytest.raises(RuntimeError, match="未定位到Alipay HK Pay Now"):
        alipay_case._ios_complete_alipay_payment("test")
    alipay_case.client.click.assert_not_called()
    alipay_case._ios_safari_click_by_text.assert_called_once()
    alipay_case._ios_back_to_home.assert_not_called()


def test_alipay_pay_now_missing_locator_never_uses_blind_coordinate(case):
    case._ios_get_source_xml = Mock(return_value="<root />")
    assert case._ios_safari_click_by_text("Pay Now", 196, 460, allow_fallback=False) is False
    case.client.click.assert_not_called()


def test_alipay_pay_now_reuses_safari_visible_element_coordinate(case):
    case._ios_get_source_xml = Mock(return_value='<XCUIElementTypeButton visible="true" label="Pay Now" x="40" y="400" width="160" height="50" />')
    assert case._ios_safari_click_by_text("Pay Now", 196, 460, allow_fallback=False) is True
    case.client.click.assert_called_once_with(120, 425)


@pytest.fixture
def safari_clock(monkeypatch):
    """模拟单调时间与等待，让重复弹窗和超时回归不产生实际延迟。"""
    clock = [0.0]
    monkeypatch.setattr(order_module.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(order_module.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    return clock


@pytest.mark.parametrize("count", [1, 2, 4])
def test_safari_closes_every_reappearing_alert_before_pay_now(case, safari_clock, count):
    """网址无效反复出现时逐次点好，无弹窗稳定后才允许一次Pay Now。"""
    frames = iter([["Safari浏览器打不开该网页，因为网址无效。"], ["Pay Now"]] * count)
    case._ios_get_all_texts = Mock(side_effect=lambda client: next(frames, ["Pay Now"]))
    case._ios_safari_click_by_text = Mock(return_value=True)
    assert case._ios_wait_and_close_safari_alert("test") is True
    assert case._ios_safari_click_by_text.call_count == count
    assert all(call.args[0] == "好" and call.kwargs == {"exact": True, "allow_fallback": False}
               for call in case._ios_safari_click_by_text.call_args_list)
    assert safari_clock[0] >= count - 0.5 + 3


@pytest.mark.parametrize("texts", [["Safari浏览器打不开该网页，因为网址无效。"], []])
def test_safari_persistent_alert_or_empty_page_stops_payment(case, safari_clock, texts):
    """持续弹窗或读取为空均不能继续Pay Now，超时保持失败不返回首页。"""
    case._ios_get_all_texts = Mock(return_value=texts)
    case._ios_safari_click_by_text = Mock(return_value=True)
    with pytest.raises(TimeoutError, match="弹窗未稳定消失"):
        case._ios_complete_alipay_payment("test")
    assert all(call.args[0] == "好" for call in case._ios_safari_click_by_text.call_args_list)
    case._ios_back_to_home.assert_not_called()


def test_safari_missing_alert_ok_never_blindly_continues(case, safari_clock):
    """好按钮定位失败立即停止，不能用固定坐标或尝试Pay Now。"""
    case._ios_get_all_texts = Mock(return_value=["网址无效"])
    case._ios_safari_click_by_text = Mock(return_value=False)
    with pytest.raises(RuntimeError, match="好按钮未定位"):
        case._ios_complete_alipay_payment("test")
    case._ios_safari_click_by_text.assert_called_once_with("好", 338, 440, exact=True, allow_fallback=False)
    case._ios_back_to_home.assert_not_called()


def test_safari_ok_uses_changed_alert_coordinates(case):
    """两次好按钮位置不同，必须每次读取新页面而非复用初始坐标。"""
    case._ios_get_source_xml = Mock(side_effect=[
        '<XCUIElementTypeButton visible="true" label="好" x="290" y="430" width="80" height="40" />',
        '<XCUIElementTypeButton visible="true" label="好" x="280" y="380" width="80" height="40" />',
    ])
    for _ in range(2):
        assert case._ios_safari_click_by_text("好", 338, 440, exact=True, allow_fallback=False) is True
    assert [call.args for call in case.client.click.call_args_list] == [(330, 450), (320, 400)]


def test_pay_now_is_blocked_by_new_safari_dialog(case):
    """清理结束后新出现的弹窗在最终页面树中仍必须阻止付款。"""
    case._ios_get_source_xml = Mock(return_value=(
        '<root><XCUIElementTypeOther name="SFDialogView" visible="true" />'
        '<XCUIElementTypeButton visible="true" label="Pay Now" x="40" y="400" width="160" height="50" /></root>'
    ))
    assert case._ios_safari_click_by_text("Pay Now", 196, 460, allow_fallback=False) is False
    case.client.click.assert_not_called()


def test_pay_now_tap_error_never_retries_duplicate_node(case):
    """网络点击结果不明确时只发一次请求，不再点相同文案的另一个节点。"""
    node = '<XCUIElementTypeButton visible="true" label="Pay Now" x="40" y="400" width="160" height="50" />'
    case._ios_get_source_xml = Mock(return_value=f"<root>{node}{node}</root>")
    case.client.click.side_effect = TimeoutError("tap response unavailable")
    assert case._ios_safari_click_by_text("Pay Now", 196, 460, allow_fallback=False) is False
    case.client.click.assert_called_once_with(120, 425)


def test_direct_alipay_case_preserves_original_payment_mapping(case):
    case.PAYMENT = "alipay"
    assert case.final_payment == "alipay"


@pytest.mark.parametrize("order_payment,car,final", [("cash", "meter", "alipay"), ("epayment", "charter", "alipay"), ("epayment", "meter", "unknown")])
def test_invalid_final_payment_is_rejected_before_any_ui(case, order_payment, car, final):
    case.PAYMENT, case.CAR_TYPE, case.FINAL_PAYMENT = order_payment, car, final
    with pytest.raises(ValueError, match="FINAL_PAYMENT"):
        case.test_order_flow()
    case.client.assert_not_called()
