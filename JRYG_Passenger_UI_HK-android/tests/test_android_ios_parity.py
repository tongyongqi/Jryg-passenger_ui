"""六例业务合同及Android原生OTP门禁的离线验证，不连接手机或支付服务。"""

from copy import deepcopy
from unittest.mock import Mock
import xml.etree.ElementTree as ET

import pytest

import JRYG_run_main as runner
from jryg_hk_android.JRYG_android_order import AndroidOrderMixin
from jryg_hk_android.JRYG_android_payment import AndroidPaymentBase, AndroidPaymentMixin
from jryg_hk_android.JRYG_shared_ios import ios_scenarios, shared_settings
from ui_framework import JRYG_ios_ui_elements as E
from ui_framework.JRYG_ios_ui_base import iOSBase


SCENARIO_CONTRACTS = [
    ("TestCharterAlipayAndroid", "charter", "alipay", ""),
    ("TestCharterBankcardAndroid", "charter", "bankcard", ""),
    ("TestMeterCashAndroid", "meter", "cash", ""),
    ("TestMeterEpaymentBankcardAndroid", "meter", "epayment", "bankcard"),
    ("TestMeterEpaymentAlipayAndroid", "meter", "epayment", "alipay"),
    ("TestMeterAlipayAndroid", "meter", "alipay", ""),
]


def test_six_scenarios_match_ios_contract_and_batch_sequence():
    cases = {case.__name__ + "Android": case for case in ios_scenarios()}
    ordered = runner.batch_order(runner.scenario_nodes())
    assert [node.split("::")[1] for node in ordered] == [row[0] for row in SCENARIO_CONTRACTS]
    assert len(cases) == len(SCENARIO_CONTRACTS) == 6
    for name, car, payment, final in SCENARIO_CONTRACTS:
        case = type(name, (AndroidOrderMixin, cases[name]), {"__test__": False})
        assert (case.CAR_TYPE, case.PAYMENT, case.FINAL_PAYMENT) == (car, payment, final)
        assert case.test_order_flow is cases[name].test_order_flow
        assert case._ios_pay is cases[name]._ios_pay
        assert case._ios_otp_value_confirmed is iOSBase._ios_otp_value_confirmed


def node(class_name, text="", **attributes):
    return ET.Element(class_name, {"class": class_name, "text": text, "enabled": "true",
                                  "displayed": "true", "bounds": "[10,10][300,100]", **attributes})


def otp_page():
    root = ET.Element("hierarchy")
    web = ET.SubElement(root, "android.webkit.WebView", {"class": "android.webkit.WebView"})
    form = ET.SubElement(web, "android.view.View", {"class": "android.view.View"})
    form.append(node("android.widget.TextView", "Sandbox Test Page", displayed="false"))
    form.append(node("android.widget.TextView", "One-Time Password (OTP)"))
    field = node("android.widget.EditText", "e.g. 123456", hint="e.g. 123456")
    button = node("android.widget.Button", "Verify & Proceed")
    form.extend([field, button])
    return root, form, field, button


@pytest.fixture
def payment(monkeypatch):
    monkeypatch.setattr(E, "OTP_DEFAULT_CODE", "unit-only-value")
    order = AndroidPaymentBase()
    order.android_settings = shared_settings()
    root, form, field_node, button_node = otp_page()
    field = Mock(id="otp-input", text="e.g. 123456")
    field.is_displayed.return_value = field.is_enabled.return_value = True
    field.get_attribute.return_value = "e.g. 123456"
    button = Mock(id="verify-button", text="Verify & Proceed")
    button.is_displayed.return_value = button.is_enabled.return_value = True
    driver = Mock(current_package=order.order_settings["packages"]["passenger_hk"])
    order.client = Mock(driver=driver)

    def refresh(value):
        field.text = value
        field_node.set("text", value or "")
        driver.page_source = ET.tostring(root, encoding="unicode")

    refresh("e.g. 123456")
    field.clear.side_effect = lambda: refresh("")
    field.send_keys.side_effect = refresh
    field_path, button_path, _ = order._android_otp_form(root)
    driver.find_elements.side_effect = lambda by, path: [field] if path == field_path else [button] if path == button_path else []
    budgets = []

    def wait(predicate, message, timeout=30):
        budgets.append(timeout)
        result = predicate()
        if not result:
            raise TimeoutError(message)
        return result

    order._wait = wait
    order._wait_payment_exit = Mock()
    return order, field, button, root, form, refresh, budgets


def test_native_otp_title_offscreen_and_single_submit(payment):
    order, field, button, _, _, _, budgets = payment
    order._ios_handle_otp_page("offline")
    field.click.assert_called_once()
    field.clear.assert_called_once()
    field.send_keys.assert_called_once_with("unit-only-value")
    button.click.assert_called_once()
    assert budgets == [30, 5, 5, 5, 5]
    order.client.dismiss_keyboard.assert_called_once_with()
    order._wait_payment_exit.assert_called_once_with(E.OTP_PAGE_KEYWORDS, require_success=False)


@pytest.mark.parametrize("fault", ["duplicate", "hidden", "disabled", "missing_title", "wrong_button", "outside_webview"])
def test_unready_or_wrong_native_form_cannot_submit(fault):
    root, form, field, button = otp_page()
    if fault == "duplicate":
        form.append(deepcopy(field))
    elif fault == "hidden":
        field.set("displayed", "false")
    elif fault == "disabled":
        field.set("enabled", "false")
    elif fault == "missing_title":
        form.remove(form[0])
    elif fault == "wrong_button":
        button.set("text", "Verify")
    else:
        root.remove(root[0])
        root.append(form)
    with pytest.raises(RuntimeError):
        AndroidPaymentMixin._android_otp_form(root)


def test_loading_page_waits_without_input(payment):
    order, field, button, _, _, refresh, _ = payment
    order.client.driver.page_source = "<hierarchy/>"

    def wait(predicate, message, timeout=30):
        assert timeout == 30
        assert predicate() is False
        field.click.assert_not_called()
        field.clear.assert_not_called()
        field.send_keys.assert_not_called()
        button.click.assert_not_called()
        refresh("e.g. 123456")
        return predicate()

    order._wait = wait
    assert order._android_wait_otp_ready("offline")[0] is field
    field.click.assert_not_called()


@pytest.mark.parametrize("value", ["", None, "e.g. 123456", "***************", "wrong-same-size"])
def test_unconfirmed_native_otp_value_never_submits(payment, value):
    order, field, button, _, _, refresh, _ = payment
    field.send_keys.side_effect = lambda code: refresh(value)
    with pytest.raises(TimeoutError, match="回读"):
        order._ios_handle_otp_page("offline")
    field.send_keys.assert_called_once()
    button.click.assert_not_called()
    order._wait_payment_exit.assert_not_called()


def test_ineffective_clear_stops_before_input(payment):
    order, field, button, _, _, refresh, _ = payment
    refresh("residual-value")
    field.clear.side_effect = None
    with pytest.raises(TimeoutError, match="回读"):
        order._ios_handle_otp_page("offline")
    field.send_keys.assert_not_called()
    button.click.assert_not_called()


def test_pre_submit_value_change_blocks_verify(payment):
    order, field, button, _, _, refresh, _ = payment
    button.is_enabled.side_effect = lambda: refresh("changed-before-submit") or True
    with pytest.raises(RuntimeError, match="提交前"):
        order._ios_handle_otp_page("offline")
    button.click.assert_not_called()


@pytest.mark.parametrize("uncertain", ["input", "verify"])
def test_response_uncertain_is_not_repeated(payment, uncertain):
    order, field, button, _, _, _, _ = payment
    target = field.send_keys if uncertain == "input" else button.click
    target.side_effect = TimeoutError("unit-response-lost")
    with pytest.raises(RuntimeError, match="不重复"):
        order._ios_handle_otp_page("offline")
    target.assert_called_once()
    if uncertain == "input":
        button.click.assert_not_called()
    order._wait_payment_exit.assert_not_called()


@pytest.mark.parametrize("fault", ["foreign_app", "alert", "failure", "duplicate_button", "changed_id", "wrong_hint"])
def test_native_otp_guards_block_submission(payment, fault):
    order, field, button, root, form, refresh, _ = payment
    if fault == "foreign_app":
        order.client.driver.current_package = "com.sunlightmobility.driver"
    elif fault == "alert":
        form.append(node("android.app.Dialog"))
    elif fault == "failure":
        form.append(node("android.widget.TextView", "Authentication Failed"))
    elif fault == "duplicate_button":
        form.append(deepcopy(form[-1]))
    elif fault == "wrong_hint":
        field.get_attribute.return_value = "other-placeholder"
    else:
        replacement = Mock(id="different-input")
        replacement.is_displayed.return_value = replacement.is_enabled.return_value = True
        replacement.get_attribute.return_value = "e.g. 123456"
        order.client.driver.find_elements.side_effect = lambda *args: [replacement]
    refresh("e.g. 123456")
    with pytest.raises((RuntimeError, TimeoutError)):
        if fault == "changed_id":
            order._android_otp_controls(field)
        else:
            order._ios_handle_otp_page("offline")
    field.send_keys.assert_not_called()
    button.click.assert_not_called()


def test_keyboard_can_hide_verify_during_input_but_must_restore_before_submit(payment):
    order, field, button, root, form, refresh, _ = payment
    button_node = form[-1]

    def focus():
        button_node.set("displayed", "false")
        button_node.set("bounds", "[0,0][0,0]")
        refresh(field.text)

    def dismiss():
        button_node.set("displayed", "true")
        button_node.set("bounds", "[10,10][300,100]")
        refresh(field.text)

    field.click.side_effect = focus
    order.client.dismiss_keyboard.side_effect = dismiss
    order._ios_handle_otp_page("keyboard")
    field.click.assert_called_once()
    field.clear.assert_called_once()
    field.send_keys.assert_called_once()
    button.click.assert_called_once()


def test_input_checks_do_not_require_offscreen_verify_button(payment):
    order, field, button, _, form, refresh, _ = payment
    form[-1].set("displayed", "false")
    refresh("")
    assert order._android_otp_controls(field)[0] is field
    with pytest.raises(RuntimeError, match="暂未可见"):
        order._android_otp_controls(field, require_button=True)
    button.click.assert_not_called()


@pytest.mark.parametrize("change", ["empty_tree", "missing_title"])
def test_focus_reflow_is_read_only_and_does_not_repeat_actions(payment, change):
    order, field, button, _, _, refresh, _ = payment
    original_wait = order._wait
    transitional = ET.fromstring("<hierarchy/>" if change == "empty_tree" else
        '<hierarchy><android.widget.EditText class="android.widget.EditText" enabled="true" '
        'displayed="true" bounds="[10,10][300,100]"/></hierarchy>')
    field.click.side_effect = lambda: setattr(order.client.driver, "page_source", ET.tostring(transitional, encoding="unicode"))

    def wait(predicate, message, timeout=30):
        if "页面重排" in message and field.send_keys.call_count == 0:
            assert timeout == 5
            assert predicate() is False
            field.click.assert_called_once()
            field.clear.assert_not_called()
            field.send_keys.assert_not_called()
            button.click.assert_not_called()
            refresh(field.text)
        return original_wait(predicate, message, timeout)

    order._wait = wait
    order._ios_handle_otp_page("reflow")
    field.click.assert_called_once()
    field.clear.assert_called_once()
    field.send_keys.assert_called_once()
    button.click.assert_called_once()


def test_permanent_focus_reflow_times_out_without_clearing_or_submitting(payment):
    order, field, button, _, _, _, _ = payment
    field.click.side_effect = lambda: setattr(order.client.driver, "page_source", "<hierarchy/>")
    with pytest.raises(TimeoutError, match="页面重排"):
        order._ios_handle_otp_page("reflow-timeout")
    field.click.assert_called_once()
    field.clear.assert_not_called()
    field.send_keys.assert_not_called()
    button.click.assert_not_called()


@pytest.mark.parametrize("action", ["click", "clear"])
def test_focus_and_clear_failures_preserve_cause_without_retries(payment, action):
    order, field, button, _, _, _, _ = payment
    failure = RuntimeError("unit transport failure")
    getattr(field, action).side_effect = failure
    with pytest.raises(RuntimeError, match="未.*提交") as error:
        order._ios_handle_otp_page("transport")
    assert error.value.__cause__ is failure
    getattr(field, action).assert_called_once()
    field.send_keys.assert_not_called()
    button.click.assert_not_called()


def test_identity_change_after_focus_is_not_treated_as_reflow(payment):
    order, field, button, _, _, _, _ = payment
    replacement = Mock(id="replacement")
    replacement.is_displayed.return_value = replacement.is_enabled.return_value = True
    replacement.get_attribute.return_value = "e.g. 123456"
    field.click.side_effect = lambda: setattr(order.client.driver.find_elements, "side_effect", lambda *_: [replacement])
    with pytest.raises(RuntimeError, match="已变化"):
        order._ios_handle_otp_page("identity-change")
    field.clear.assert_not_called()
    field.send_keys.assert_not_called()
    button.click.assert_not_called()


def test_failure_page_after_focus_is_not_waited_or_submitted(payment):
    order, field, button, _, form, refresh, _ = payment

    def focus():
        form.append(node("android.widget.TextView", "Authentication Failed"))
        refresh(field.text)

    field.click.side_effect = focus
    with pytest.raises(RuntimeError, match="支付失败"):
        order._ios_handle_otp_page("failure")
    field.clear.assert_not_called()
    field.send_keys.assert_not_called()
    button.click.assert_not_called()


def test_otp_locators_do_not_change_when_keyboard_adds_siblings(payment):
    order, field, button, root, form, refresh, _ = payment
    before = order._android_otp_form(root)
    root.insert(0, node("android.inputmethodservice.KeyboardView", "keyboard"))
    form.insert(0, node("android.widget.TextView", "layout loading"))
    after = order._android_otp_form(root)
    assert before == after
    assert "@hint='e.g. 123456'" in after[0]
    assert "android.webkit.WebView" in after[0]
    assert "Verify & Proceed" in after[1]
    assert after[0] == "//*[@class='android.webkit.WebView']//*[@class='android.widget.EditText' and @hint='e.g. 123456']"
    refresh(field.text)
    assert order._android_otp_controls(field)[0] is field
    field.send_keys.assert_not_called()
    button.click.assert_not_called()


def test_temporary_native_input_lookup_is_read_only(payment):
    order, field, button, _, _, _, _ = payment
    from jryg_hk_android.JRYG_android_payment import AndroidOTPNotReadyError
    order.client.driver.find_elements.side_effect = lambda *_: []
    with pytest.raises(AndroidOTPNotReadyError, match="暂未就绪"):
        order._android_otp_controls(field)
    field.click.assert_not_called()
    field.clear.assert_not_called()
    field.send_keys.assert_not_called()
    button.click.assert_not_called()
