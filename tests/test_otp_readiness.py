from types import SimpleNamespace
from unittest.mock import Mock
import xml.etree.ElementTree as ET

import pytest

from ui_framework.JRYG_ios_ui_base import iOSBase
from ui_framework import JRYG_ios_ui_elements as E


OTP = f'''<XCUIElementTypeApplication bundleId="{E.PASSENGER_BUNDLE_ID}">
<XCUIElementTypeOther visible="true">
<XCUIElementTypeStaticText label="安全結帳" visible="true" />
<XCUIElementTypeStaticText label="Sandbox Test Page" visible="true" />
<XCUIElementTypeStaticText label="One-Time Password (OTP)" visible="true" />
<XCUIElementTypeTextField placeholderValue="e.g. 123456" visible="true" enabled="true" />
<XCUIElementTypeButton label="Verify &amp; Proceed" visible="true" enabled="true" />
</XCUIElementTypeOther></XCUIElementTypeApplication>'''
BLANK = f'''<XCUIElementTypeApplication bundleId="{E.PASSENGER_BUNDLE_ID}">
<XCUIElementTypeStaticText label="安全結帳" visible="true" />
<XCUIElementTypeWebView visible="true" enabled="true" />
</XCUIElementTypeApplication>'''
SUCCESS = f'''<XCUIElementTypeApplication bundleId="{E.PASSENGER_BUNDLE_ID}">
<XCUIElementTypeStaticText label="SUCCESS" visible="true" />
</XCUIElementTypeApplication>'''


@pytest.fixture
def setup(monkeypatch):
    clock = SimpleNamespace(now=0)
    monkeypatch.setattr("ui_framework.JRYG_ios_ui_base.ensure_unlocked", Mock(return_value=False))
    monkeypatch.setattr("ui_framework.JRYG_ios_ui_base.time.monotonic", lambda: clock.now)
    monkeypatch.setattr("ui_framework.JRYG_ios_ui_base.time.sleep", lambda seconds: setattr(clock, "now", clock.now + seconds))
    flow = iOSBase()
    flow.client = Mock()
    flow.field = Mock(displayed=True, enabled=True, value="")
    flow.button = Mock(displayed=True, enabled=True)
    flow.client.http.get.return_value = SimpleNamespace(value=OTP)
    flow.client.source.return_value = OTP
    flow.client.return_value.find_elements.return_value = [flow.field]
    flow._ios_get_all_texts = Mock(return_value=["SUCCESS"])
    return flow, clock


def assert_no_actions(flow):
    flow.field.tap.assert_not_called()
    flow.field.clear_text.assert_not_called()
    flow.field.set_text.assert_not_called()
    flow.button.tap.assert_not_called()
    flow.client.click.assert_not_called()
    flow.client.send_keys.assert_not_called()
    flow.client.app_activate.assert_not_called()


def test_blank_checkout_timeout_is_distinct_and_waits_90_seconds(setup, caplog):
    flow, clock = setup
    flow.client.http.get.return_value = SimpleNamespace(value=BLANK)
    with caplog.at_level("INFO"), pytest.raises(TimeoutError, match="安全結帳内容未加载") as caught:
        flow._ios_handle_otp_page("sandbox")
    assert clock.now == 90
    assert "支付请求已发出但结果未确认" in str(caught.value)
    assert "不要直接重付" in str(caught.value)
    assert "安全結帳内容未加载" in caplog.text
    assert_no_actions(flow)


def test_blank_checkout_can_load_after_previous_30_second_limit(setup):
    flow, clock = setup
    flow.client.http.get.side_effect = lambda *args, **kwargs: SimpleNamespace(value=BLANK if clock.now < 40 else OTP)
    field, verify, placeholder = flow._ios_wait_otp_ready("sandbox")
    assert clock.now == 40
    assert field is flow.field
    assert "Verify & Proceed" in verify
    assert placeholder == "e.g. 123456"
    assert_no_actions(flow)


def test_source_requests_share_remaining_budget(setup):
    flow, clock = setup
    timeouts = []

    def read(_endpoint, timeout):
        timeouts.append(timeout)
        clock.now += timeout
        return SimpleNamespace(value=BLANK)

    flow.client.http.get.side_effect = read
    with pytest.raises(TimeoutError):
        flow._ios_wait_otp_ready("sandbox", wait_seconds=7)
    assert timeouts == [5, 1.5]
    assert clock.now == 7
    assert_no_actions(flow)


@pytest.mark.parametrize("seconds", [0, -1, 181, float("nan"), float("inf"), "bad"])
def test_invalid_wait_does_not_request_device(setup, seconds):
    flow, _clock = setup
    with pytest.raises(ValueError):
        flow._ios_wait_otp_ready("sandbox", wait_seconds=seconds)
    flow.client.http.get.assert_not_called()
    assert_no_actions(flow)


@pytest.mark.parametrize("label", ["Payment Failed", "Authentication Failed", "Incorrect OTP", "支付失敗"])
def test_payment_failure_stops_immediately(setup, label):
    flow, clock = setup
    root = ET.fromstring(BLANK)
    ET.SubElement(root, "XCUIElementTypeStaticText", label=label, visible="true")
    flow.client.http.get.return_value = SimpleNamespace(value=ET.tostring(root, encoding="unicode"))
    with pytest.raises(RuntimeError, match="支付或验证失败"):
        flow._ios_wait_otp_ready("sandbox")
    assert clock.now == 0
    flow.client.http.get.assert_called_once()
    assert_no_actions(flow)


@pytest.mark.parametrize("kind", ["other_app", "alert"])
def test_foreground_or_alert_blocks_otp(setup, kind):
    flow, _clock = setup
    root = ET.fromstring(OTP)
    if kind == "other_app":
        root.set("bundleId", "com.apple.Preferences")
    else:
        ET.SubElement(root, "XCUIElementTypeAlert", visible="true")
    flow.client.http.get.return_value = SimpleNamespace(value=ET.tostring(root, encoding="unicode"))
    with pytest.raises(RuntimeError):
        flow._ios_wait_otp_ready("sandbox")
    assert_no_actions(flow)


@pytest.mark.parametrize("kind", ["duplicate", "hidden", "disabled", "placeholder", "title", "secure"])
def test_incomplete_or_ambiguous_form_never_selected(setup, kind):
    flow, _clock = setup
    root = ET.fromstring(OTP)
    parent = root.find("XCUIElementTypeOther")
    field = parent.find("XCUIElementTypeTextField")
    if kind == "duplicate":
        parent.append(ET.fromstring(ET.tostring(field)))
    elif kind == "hidden":
        field.set("visible", "false")
    elif kind == "disabled":
        field.set("enabled", "false")
    elif kind == "placeholder":
        field.set("placeholderValue", "Another input")
    elif kind == "title":
        parent.remove(parent.findall("XCUIElementTypeStaticText")[1])
    else:
        field.tag = "XCUIElementTypeSecureTextField"
    assert flow._ios_otp_readiness(root) is None
    flow.client.http.get.return_value = SimpleNamespace(value=ET.tostring(root, encoding="unicode"))
    with pytest.raises(TimeoutError):
        flow._ios_wait_otp_ready("sandbox", wait_seconds=1)
    flow.client.assert_not_called()
    assert_no_actions(flow)


def test_transport_failure_logged_without_sensitive_exception_details(setup, caplog):
    flow, clock = setup
    secret = "private-payment-reference"
    flow.client.http.get.side_effect = OSError(secret)
    with caplog.at_level("INFO"), pytest.raises(TimeoutError) as caught:
        flow._ios_wait_otp_ready("sandbox", wait_seconds=1)
    assert clock.now == 1
    assert "WDA页面读取失败（OSError）" in str(caught.value)
    assert secret not in str(caught.value) + caplog.text
    assert_no_actions(flow)


def test_incomplete_xml_only_waits_without_actions(setup):
    flow, _clock = setup
    flow.client.http.get.side_effect = [SimpleNamespace(value="<broken"), SimpleNamespace(value=OTP)]
    field, _verify, _placeholder = flow._ios_wait_otp_ready("sandbox", wait_seconds=1)
    assert field is flow.field
    assert_no_actions(flow)


def ready_flow(flow, monkeypatch):
    monkeypatch.setattr(E, "OTP_DEFAULT_CODE", "654321")

    def select(xpath):
        target = flow.button if "/XCUIElementTypeButton[" in xpath else flow.field
        return Mock(find_elements=Mock(return_value=[target]))

    flow.client.side_effect = select
    flow.field.clear_text.side_effect = lambda: setattr(flow.field, "value", "")
    flow.field.set_text.side_effect = lambda value: setattr(flow.field, "value", value)
    flow.button.tap.side_effect = lambda: setattr(flow.client.source, "return_value", SUCCESS)


def test_verified_otp_submitted_once_no_coordinate_or_global_input(setup, monkeypatch, caplog):
    flow, _clock = setup
    ready_flow(flow, monkeypatch)
    with caplog.at_level("INFO"):
        flow._ios_handle_otp_page("sandbox")
    flow.field.tap.assert_called_once()
    flow.field.clear_text.assert_called_once()
    flow.field.set_text.assert_called_once_with("654321")
    flow.button.tap.assert_called_once()
    flow.client.click.assert_not_called()
    flow.client.send_keys.assert_not_called()
    assert "654321" not in caplog.text


@pytest.mark.parametrize("failure", ["clear", "input", "submit"])
def test_uncertain_action_response_never_retried(setup, monkeypatch, failure):
    flow, _clock = setup
    ready_flow(flow, monkeypatch)
    method = {"clear": flow.field.clear_text, "input": flow.field.set_text, "submit": flow.button.tap}[failure]
    method.side_effect = OSError("response lost")
    with pytest.raises(RuntimeError):
        flow._ios_handle_otp_page("sandbox")
    method.assert_called_once()
    if failure != "submit":
        flow.button.tap.assert_not_called()
    if failure == "clear":
        flow.field.set_text.assert_not_called()


def test_wrong_value_readback_prevents_verify(setup, monkeypatch):
    flow, _clock = setup
    ready_flow(flow, monkeypatch)
    flow.field.set_text.side_effect = lambda _value: setattr(flow.field, "value", "******")
    with pytest.raises(RuntimeError, match="输入未通过回读核验"):
        flow._ios_handle_otp_page("sandbox")
    flow.field.set_text.assert_called_once()
    flow.button.tap.assert_not_called()
