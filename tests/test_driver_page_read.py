from types import SimpleNamespace
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET

import pytest
from wda.usbmux.exceptions import HTTPError

from ui_framework.JRYG_driver_ui import (
    BUNDLE_ID,
    DriverAppNotForegroundError,
    DriverPageReadError,
    DriverUIFlow,
    parser,
)


DRIVER_XML = f'<AppiumAUT><XCUIElementTypeApplication bundleId="{BUNDLE_ID}" /></AppiumAUT>'


def response(value):
    return SimpleNamespace(value=value)


@pytest.fixture
def flow(monkeypatch):
    monkeypatch.setattr("ui_framework.JRYG_driver_ui.ensure_unlocked", Mock(return_value=False))
    args = parser(wda_url="http://example.invalid").parse_args([])
    client = Mock()
    result = DriverUIFlow(args, client)
    result.deadline = 1000
    return result


def test_stale_settings_foreground_does_not_request_xml(flow):
    flow.client.http.get.return_value = response({"bundleId": "com.apple.Preferences"})
    with patch("ui_framework.JRYG_driver_ui.time.monotonic", return_value=10):
        with pytest.raises(DriverAppNotForegroundError):
            flow.root()
    flow.client.http.get.assert_called_once_with("/wda/activeAppInfo", timeout=20)
    flow.client.source.assert_not_called()
    flow.client.click.assert_not_called()
    flow.client.swipe.assert_not_called()


def test_driver_foreground_still_checks_xml_bundle(flow):
    flow.client.http.get.side_effect = [
        response({"bundleId": BUNDLE_ID}),
        response('<XCUIElementTypeApplication bundleId="com.apple.Preferences" />'),
    ]
    with patch("ui_framework.JRYG_driver_ui.time.monotonic", return_value=10):
        with pytest.raises(DriverAppNotForegroundError):
            flow.root()
    assert flow.client.http.get.call_count == 2


def test_activation_once_waits_before_reading_driver_xml(flow):
    flow.client.http.get.side_effect = [
        response({"bundleId": "com.apple.Preferences"}),
        response({"bundleId": BUNDLE_ID}),
        response(DRIVER_XML),
    ]
    with patch("ui_framework.JRYG_driver_ui.time.monotonic", return_value=10), patch(
        "ui_framework.JRYG_driver_ui.time.sleep"
    ) as sleep:
        flow._activate_driver_app()
    flow.client.app_activate.assert_called_once_with(BUNDLE_ID)
    assert [call.args[0] for call in flow.client.http.get.call_args_list] == [
        "/wda/activeAppInfo", "/wda/activeAppInfo", "/source?format=xml"
    ]
    sleep.assert_called_once()
    flow.client.click.assert_not_called()
    flow.client.swipe.assert_not_called()
    flow.client.session.assert_not_called()


def test_request_budget_shared_between_foreground_and_xml(flow):
    flow.client.http.get.side_effect = [response({"bundleId": BUNDLE_ID}), response(DRIVER_XML)]
    with patch("ui_framework.JRYG_driver_ui.time.monotonic", side_effect=[10, 11, 13]):
        assert flow.root(read_deadline=15).tag == "AppiumAUT"
    assert [call.kwargs["timeout"] for call in flow.client.http.get.call_args_list] == [4, 2]


def test_expired_budget_never_requests_device(flow):
    with patch("ui_framework.JRYG_driver_ui.time.monotonic", return_value=10):
        with pytest.raises(DriverPageReadError):
            flow.root(read_deadline=9)
    flow.client.http.get.assert_not_called()


@pytest.mark.parametrize("error", [HTTPError("timed out"), OSError("connection lost")])
def test_source_transport_failure_is_not_business_timeout(flow, error):
    flow.client.http.get.side_effect = [response({"bundleId": BUNDLE_ID}), error]
    with patch("ui_framework.JRYG_driver_ui.time.monotonic", return_value=10):
        with pytest.raises(DriverPageReadError) as caught:
            flow._activate_driver_app()
    assert not isinstance(caught.value, TimeoutError)
    assert caught.value.__cause__ is error
    assert flow.client.http.get.call_count == 2
    flow.client.app_activate.assert_called_once_with(BUNDLE_ID)
    flow.client.click.assert_not_called()
    flow.client.swipe.assert_not_called()
    flow.client.session.assert_not_called()


def test_malformed_xml_remains_parse_error(flow):
    flow.client.http.get.side_effect = [response({"bundleId": BUNDLE_ID}), response("<broken")]
    with patch("ui_framework.JRYG_driver_ui.time.monotonic", return_value=10):
        with pytest.raises(ET.ParseError):
            flow.root()


def test_foreground_transport_failure_never_fetches_source(flow):
    flow.client.http.get.side_effect = HTTPError("timed out")
    with patch("ui_framework.JRYG_driver_ui.time.monotonic", return_value=10):
        with pytest.raises(DriverPageReadError):
            flow.root()
    flow.client.http.get.assert_called_once()


def test_page_error_after_action_does_not_retry_action(flow):
    flow.args.stop_after = "submitted"
    flow._activate_driver_app = Mock()
    flow.wait_for = Mock(side_effect=[(ET.fromstring(DRIVER_XML), "destination"), DriverPageReadError("source blocked")])
    flow.act = Mock()
    with patch("ui_framework.JRYG_driver_ui.time.monotonic", return_value=10):
        with pytest.raises(DriverPageReadError):
            flow.run()
    flow.act.assert_called_once()
    assert flow.wait_for.call_count == 2


def test_inspect_performs_no_business_actions(flow):
    flow.args.inspect = True
    flow._activate_driver_app = Mock()
    flow.wait_for = Mock(return_value=(ET.fromstring(DRIVER_XML), "online"))
    flow.act = Mock()
    flow.submit_bill = Mock()
    flow.run()
    flow._activate_driver_app.assert_called_once()
    flow.act.assert_not_called()
    flow.submit_bill.assert_not_called()
    flow.client.click.assert_not_called()
    flow.client.swipe.assert_not_called()


def test_registration_home_detected_as_logged_out(flow):
    page = ET.fromstring(
        f'<XCUIElementTypeApplication bundleId="{BUNDLE_ID}">'
        '<XCUIElementTypeStaticText label="登錄/註冊" visible="true" />'
        '<XCUIElementTypeStaticText label="註冊需要材料" visible="true" />'
        '</XCUIElementTypeApplication>'
    )
    assert flow.detect_phase(page) == "login"
    flow._activate_driver_app = Mock()
    flow.wait_for_entry_page = Mock(return_value=(page, "login"))
    flow.act = Mock()
    flow.args.mobile = None
    with pytest.raises(RuntimeError, match="HK_DRIVER_MOBILE"):
        flow.ensure_online(resume_existing=True)
    flow.act.assert_not_called()
    flow.client.click.assert_not_called()
    flow.client.swipe.assert_not_called()


def test_hidden_registration_text_not_login(flow):
    page = ET.fromstring(
        '<root><XCUIElementTypeStaticText label="登錄/註冊" visible="false" />'
        '<XCUIElementTypeStaticText label="註冊需要材料" visible="false" /></root>'
    )
    assert flow.detect_phase(page) == "unknown"
