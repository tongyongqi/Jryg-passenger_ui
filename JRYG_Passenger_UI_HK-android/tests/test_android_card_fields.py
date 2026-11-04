"""安卓信用卡字段读取与配置复用回归，不提交真实支付。"""

from unittest.mock import Mock
import xml.etree.ElementTree as ET

import pytest

from jryg_hk_android.JRYG_android_payment import AndroidPaymentBase
from ui_framework import JRYG_ios_ui_elements as E


@pytest.fixture
def card():
    instance = AndroidPaymentBase()
    instance.client = Mock()
    instance._android_payment_guard = Mock(return_value=ET.fromstring(
        '<android.webkit.WebView class="android.webkit.WebView"><android.widget.TextView text="銀行卡"/></android.webkit.WebView>'))
    field = Mock()
    field.text = ""
    field.get_attribute.side_effect = lambda name: {"class": "android.widget.EditText", "hint": "", "content-desc": ""}.get(name)
    field.is_displayed.return_value = True
    field.is_enabled.return_value = True
    instance.client.return_value.find_elements.return_value = []
    instance.client.driver.find_elements.return_value = [field]
    return instance, field


def test_cvv_without_hint_uses_same_label_container_and_webview(card):
    instance, field = card
    instance._fill_payment_field(["CVV"], E.TEST_CARD_CVV)
    method, path = instance.client.driver.find_elements.call_args.args
    assert method == "xpath"
    assert "android.webkit.WebView" in path
    assert "@text='CVV 碼'" in path
    assert "parent::*[count(*[@class='android.widget.EditText'])=1]" in path
    field.click.assert_called_once_with()
    field.clear.assert_called_once_with()
    field.send_keys.assert_called_once_with(E.TEST_CARD_CVV)
    instance.client.dismiss_keyboard.assert_called_once_with()


@pytest.mark.parametrize("problem", ["duplicate", "hidden", "disabled", "wrong_class"])
def test_ambiguous_cvv_fields_are_not_filled(card, problem):
    instance, field = card
    if problem == "duplicate":
        instance.client.driver.find_elements.return_value = [field, Mock()]
    elif problem == "hidden":
        field.is_displayed.return_value = False
    elif problem == "disabled":
        field.is_enabled.return_value = False
    else:
        field.get_attribute.side_effect = lambda _: "android.widget.TextView"
    with pytest.raises(RuntimeError, match="CVV同容器"):
        instance._fill_payment_field(["CVV"], E.TEST_CARD_CVV)
    field.send_keys.assert_not_called()
    field.click.assert_not_called()


def test_cvv_does_not_use_arbitrary_field_when_no_label_exists(card):
    instance, field = card
    instance.client.driver.find_elements.return_value = []
    assert instance._android_cvv_field() == []
    field.send_keys.assert_not_called()


def test_cvv_requires_card_form_page(card):
    instance, field = card
    instance._android_payment_guard.return_value = ET.fromstring('<android.widget.TextView text="登入"/>')
    with pytest.raises(RuntimeError, match="不是信用卡表单"):
        instance._android_cvv_field()
    instance.client.driver.find_elements.assert_not_called()
    field.send_keys.assert_not_called()


def test_cvv_with_hint_keeps_original_field_match(card):
    instance, _ = card
    hinted = Mock()
    hinted.label = ""
    hinted.native.get_attribute.return_value = "CVV"
    instance.client.return_value.find_elements.return_value = [hinted]
    instance._fill_payment_field(["CVV"], E.TEST_CARD_CVV)
    hinted.set_text.assert_called_once_with(E.TEST_CARD_CVV)
    instance._android_payment_guard.assert_not_called()
    instance.client.driver.find_elements.assert_not_called()


def test_card_form_uses_ios_values_before_single_submit_and_otp(card):
    instance, _ = card
    instance._ios_get_all_texts = Mock(return_value=["銀行卡"])
    instance._fill_payment_field = Mock()
    instance._click_text = Mock()
    instance._ios_handle_otp_page = Mock()
    assert instance._ios_fill_bank_card_form("charter-bankcard")
    values = [call.args[1] for call in instance._fill_payment_field.call_args_list]
    assert values == [E.TEST_CARD_NUMBER, E.TEST_CARD_EXPIRY, E.TEST_CARD_CVV, E.TEST_CARD_HOLDER]
    instance._click_text.assert_called_once_with(["請支付"])
    instance._ios_handle_otp_page.assert_called_once_with("charter-bankcard")


def test_card_field_failure_does_not_submit_or_enter_otp(card):
    instance, _ = card
    instance._ios_get_all_texts = Mock(return_value=["銀行卡"])
    instance._fill_payment_field = Mock(side_effect=RuntimeError("field missing"))
    instance._click_text = Mock()
    instance._ios_handle_otp_page = Mock()
    with pytest.raises(RuntimeError, match="field missing"):
        instance._ios_fill_bank_card_form("charter-bankcard")
    instance._click_text.assert_not_called()
    instance._ios_handle_otp_page.assert_not_called()


@pytest.mark.parametrize("placeholders,label,value", [
    (["卡號", "卡号", "Card Number"], "卡號", E.TEST_CARD_NUMBER),
    (["月 / 年", "月/年", "MM/YY", "Expiry"], "有效期", E.TEST_CARD_EXPIRY),
    (["持卡人姓名", "Name"], "持卡人姓名", E.TEST_CARD_HOLDER),
])
def test_floating_labels_keep_fields_bound_to_their_own_container(card, placeholders, label, value):
    instance, field = card
    instance._fill_payment_field(placeholders, value)
    assert f"@text='{label}'" in instance.client.driver.find_elements.call_args.args[1]
    field.send_keys.assert_called_once_with(value)


def test_unknown_payment_label_does_not_select_arbitrary_input(card):
    instance, field = card
    assert instance._android_labelled_card_field(["Unknown"]) == []
    instance.client.driver.find_elements.assert_not_called()
    field.send_keys.assert_not_called()


def test_pay_button_reflow_waits_read_only_before_single_payment(card):
    instance, _ = card
    instance._ios_get_all_texts = Mock(return_value=["銀行卡"])
    instance._fill_payment_field = Mock()
    instance._click_text = Mock()
    instance._ios_handle_otp_page = Mock()
    instance.client.return_value.exists = False

    def wait(predicate, message, timeout=30):
        if "支付按钮" in message:
            assert timeout == 5
            assert predicate() is False
            instance._click_text.assert_not_called()
            instance._ios_handle_otp_page.assert_not_called()
            instance.client.return_value.exists = True
        assert predicate()
        return True

    instance._wait = wait
    assert instance._ios_fill_bank_card_form("reflow")
    instance._click_text.assert_called_once_with(["請支付"])
    instance._ios_handle_otp_page.assert_called_once_with("reflow")


def test_uncertain_card_payment_click_is_never_repeated(card):
    instance, _ = card
    instance._ios_get_all_texts = Mock(return_value=["銀行卡"])
    instance._fill_payment_field = Mock()
    failure = TimeoutError("unit response lost")
    instance._click_text = Mock(side_effect=failure)
    instance._ios_handle_otp_page = Mock()
    with pytest.raises(RuntimeError, match="禁止重复提交") as error:
        instance._ios_fill_bank_card_form("uncertain")
    assert error.value.__cause__ is failure
    instance._click_text.assert_called_once()
    instance._ios_handle_otp_page.assert_not_called()


@pytest.mark.parametrize("loading", ["查詢結果中", "查询结果中", "spinner-only"])
def test_post_otp_cashier_query_is_read_only_and_not_completion(card, loading):
    instance, _ = card
    instance._android_payment_guard = Mock()
    instance._click_text = Mock()
    root = ET.Element("hierarchy")
    ET.SubElement(root, "android.widget.TextView", text="預付車費", displayed="true")
    ET.SubElement(root, "android.widget.TextView", text=loading,
                  **{"resource-id": "com.sunlightmobility.client:id/tip_loading", "displayed": "true"})
    ready = ET.fromstring('<hierarchy><android.widget.TextView text="溫馨提示" displayed="true"/></hierarchy>')
    instance._android_payment_guard.side_effect = [root, ready]

    def wait(predicate, message, timeout=30):
        assert timeout == 45
        assert predicate() is False
        instance._click_text.assert_not_called()
        assert predicate() is True
        return True

    instance._wait = wait
    instance._wait_payment_exit(E.OTP_PAGE_KEYWORDS, require_success=False)
    instance._click_text.assert_called_once_with(["打開", "打开"], exact=True, required=False)


def test_post_otp_query_with_failure_stops_without_payment_retry(card):
    instance, _ = card
    instance._android_payment_guard.return_value = ET.fromstring(
        '<hierarchy><android.widget.TextView text="查詢結果中"/><android.widget.TextView text="Payment Failed"/></hierarchy>')
    instance._click_text = Mock()
    with pytest.raises(RuntimeError, match="支付失败"):
        instance._wait_payment_exit(E.OTP_PAGE_KEYWORDS, require_success=False)
    instance._click_text.assert_not_called()
