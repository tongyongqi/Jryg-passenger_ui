from types import SimpleNamespace
from unittest.mock import Mock
import xml.etree.ElementTree as ET

import pytest

from ui_framework import JRYG_device_guard as guard
from ui_framework.JRYG_driver_ui import BUNDLE_ID, DriverUIFlow, parser
from ui_framework.JRYG_ios_ui_base import iOSBase
from ui_framework.JRYG_ios_ui_elements import PASSENGER_BUNDLE_ID
from ui_framework.JRYG_page_monitor import IOSPageMonitor


@pytest.fixture
def clock(monkeypatch):
    state = SimpleNamespace(now=0)
    monkeypatch.setattr(guard.time, "monotonic", lambda: state.now)
    monkeypatch.setattr(guard.time, "sleep", lambda seconds: setattr(state, "now", state.now + seconds))
    return state


def client_with_states(states, source=None, foreground=BUNDLE_ID):
    client = Mock()
    values = iter(states)

    def read(endpoint, **_kwargs):
        if endpoint == "/wda/locked":
            return SimpleNamespace(value=next(values))
        if endpoint == "/wda/activeAppInfo":
            return SimpleNamespace(value={"bundleId": foreground})
        if endpoint == "/source?format=xml":
            return SimpleNamespace(value=source)
        raise AssertionError("unexpected endpoint")

    client.http.get.side_effect = read
    client.http.post.return_value = SimpleNamespace(value=None)
    return client


def assert_no_business(client):
    client.click.assert_not_called()
    client.swipe.assert_not_called()
    client.send_keys.assert_not_called()
    client.app_activate.assert_not_called()
    client.session.assert_not_called()


def test_already_unlocked_no_wake_or_activation(clock):
    client = client_with_states([False])
    assert guard.ensure_unlocked(client, resume_bundle=BUNDLE_ID) is False
    client.http.get.assert_called_once_with("/wda/locked", timeout=3)
    client.http.post.assert_not_called()
    assert_no_business(client)


@pytest.mark.parametrize("bundle", [None, BUNDLE_ID, PASSENGER_BUNDLE_ID, "com.apple.mobilesafari"])
def test_locked_unlock_once_confirm_then_resume(clock, bundle):
    client = client_with_states([True, True, False])
    assert guard.ensure_unlocked(client, resume_bundle=bundle) is True
    posts = client.http.post.call_args_list
    assert [call.args[0] for call in posts] == (["/wda/unlock"] if bundle is None else ["/wda/unlock", "/wda/apps/activate"])
    if bundle:
        assert posts[1].args[1] == {"bundleId": bundle}
    assert clock.now == 0.5
    assert_no_business(client)


def test_password_lock_stops_after_bounded_readonly_wait(clock):
    client = client_with_states([True] * 40)
    with pytest.raises(guard.DeviceUnlockError, match="锁屏密码或Face ID"):
        guard.ensure_unlocked(client, resume_bundle=BUNDLE_ID)
    assert clock.now == 15
    client.http.post.assert_called_once_with("/wda/unlock", timeout=10)
    assert_no_business(client)


@pytest.mark.parametrize("value", [None, "false", 0, 1, {}, []])
def test_invalid_lock_status_does_not_assume_unlocked(clock, value):
    client = client_with_states([value])
    with pytest.raises(guard.DeviceUnlockError, match="有效锁屏状态"):
        guard.ensure_unlocked(client)
    client.http.post.assert_not_called()
    assert_no_business(client)


@pytest.mark.parametrize("failure", ["query", "unlock", "activate"])
def test_transport_response_uncertain_never_repeated_or_leaked(clock, failure, caplog):
    client = client_with_states([True, False])
    error = OSError("private-lock-code")
    if failure == "query":
        client.http.get.side_effect = error
    elif failure == "unlock":
        client.http.post.side_effect = error
    else:
        client.http.post.side_effect = [SimpleNamespace(value=None), error]
    with pytest.raises(guard.DeviceUnlockError) as caught:
        guard.ensure_unlocked(client, resume_bundle=BUNDLE_ID)
    assert "private-lock-code" not in str(caught.value) + caplog.text
    assert client.http.post.call_count == {"query": 0, "unlock": 1, "activate": 2}[failure]
    assert_no_business(client)


def test_expired_budget_does_not_request_device(clock):
    client = Mock()
    with pytest.raises(guard.DeviceUnlockError, match="等待超时"):
        guard.ensure_unlocked(client, deadline=0)
    client.http.get.assert_not_called()
    client.http.post.assert_not_called()


def test_all_requests_share_remaining_budget(clock):
    client = client_with_states([True, False])

    def unlock(*_args, timeout):
        assert timeout == 4
        clock.now += 3
        return SimpleNamespace(value=None)

    client.http.post.side_effect = unlock
    assert guard.ensure_unlocked(client, deadline=4) is True
    assert client.http.get.call_args.kwargs["timeout"] == 1
    assert clock.now == 3


def test_unknown_resume_app_rejected_without_device_action(clock):
    client = Mock()
    with pytest.raises(guard.DeviceUnlockError, match="允许范围"):
        guard.ensure_unlocked(client, resume_bundle="unknown.app")
    client.http.get.assert_not_called()
    client.http.post.assert_not_called()


def test_observed_safari_restored_not_passenger_app(clock):
    client = client_with_states([True, False])
    guard.remember_foreground(client, ET.fromstring('<XCUIElementTypeApplication bundleId="com.apple.mobilesafari" />'))
    assert guard.ensure_unlocked(client) is True
    assert client.http.post.call_args.args[1] == {"bundleId": "com.apple.mobilesafari"}


def test_different_devices_do_not_share_foreground(clock):
    first = client_with_states([True, False])
    second = client_with_states([True, False])
    guard.remember_foreground(first, ET.fromstring(f'<XCUIElementTypeApplication bundleId="{PASSENGER_BUNDLE_ID}" />'))
    assert guard.ensure_unlocked(second) is True
    second.http.post.assert_called_once()
    guard.remember_foreground(first, ET.fromstring('<XCUIElementTypeApplication bundleId="com.apple.Preferences" />'))
    assert guard.ensure_unlocked(first) is True
    first.http.post.assert_called_once()


def test_driver_reads_latest_phase_only_after_confirmed_unlock(clock):
    xml = f'<XCUIElementTypeApplication bundleId="{BUNDLE_ID}"><XCUIElementTypeStaticText label="停止接單" visible="true" /></XCUIElementTypeApplication>'
    client = client_with_states([True, False], source=xml)
    flow = DriverUIFlow(parser(wda_url="http://example.invalid").parse_args([]), client)
    flow.deadline = 30
    root = flow.root()
    assert root.get("bundleId") == BUNDLE_ID
    assert [call.args[0] for call in client.http.get.call_args_list] == [
        "/wda/locked", "/wda/locked", "/wda/activeAppInfo", "/source?format=xml"]
    assert client.http.post.call_args.args[1] == {"bundleId": BUNDLE_ID}
    assert_no_business(client)


def test_driver_unlock_failure_prevents_xml_and_business(clock):
    client = client_with_states([True])
    client.http.post.side_effect = OSError("unlock rejected")
    flow = DriverUIFlow(parser(wda_url="http://example.invalid").parse_args([]), client)
    flow.deadline = 30
    with pytest.raises(guard.DeviceUnlockError):
        flow.root()
    assert [call.args[0] for call in client.http.get.call_args_list] == ["/wda/locked"]
    assert_no_business(client)


def test_unlock_failure_not_driver_slide_retry(clock):
    flow = DriverUIFlow(parser(wda_url="http://example.invalid").parse_args([]), Mock())
    flow.args.stop_after = "submitted"
    flow._activate_driver_app = Mock()
    flow.act = Mock()
    flow.wait_for = Mock(side_effect=[(ET.Element("trip"), "destination"),
                                      guard.DeviceUnlockError("manual unlock needed")])
    with pytest.raises(guard.DeviceUnlockError):
        flow.run()
    flow.act.assert_called_once()
    assert flow.wait_for.call_count == 2


def test_passenger_lock_failure_not_converted_to_empty_text(clock):
    client = client_with_states([True])
    client.http.post.side_effect = OSError("unlock rejected")
    with pytest.raises(guard.DeviceUnlockError):
        iOSBase._ios_get_all_texts(client)
    client.source.assert_not_called()
    assert_no_business(client)


def test_passenger_text_poll_restores_observed_payment_app(clock):
    client = client_with_states([False, True, False])
    client.source.return_value = '<XCUIElementTypeApplication bundleId="com.apple.mobilesafari"><XCUIElementTypeStaticText label="SUCCESS" visible="true" /></XCUIElementTypeApplication>'
    assert iOSBase._ios_get_all_texts(client) == ["SUCCESS"]
    assert iOSBase._ios_get_all_texts(client) == ["SUCCESS"]
    assert client.http.post.call_args.args[1] == {"bundleId": "com.apple.mobilesafari"}
    assert_no_business(client)


def test_login_lock_failure_no_credentials_input(clock):
    flow = iOSBase()
    flow.client = client_with_states([True])
    flow.client.http.post.side_effect = OSError("unlock rejected")
    monitor = Mock()
    with pytest.raises(guard.DeviceUnlockError):
        flow._ios_login_page(monitor)
    monitor.inspect.assert_not_called()
    assert_no_business(flow.client)


def test_otp_lock_failure_no_clear_input_or_verify(clock):
    flow = iOSBase()
    flow.client = client_with_states([True])
    flow.client.http.post.side_effect = OSError("unlock rejected")
    with pytest.raises(guard.DeviceUnlockError):
        flow._ios_handle_otp_page("sandbox")
    flow.client.assert_not_called()
    assert_no_business(flow.client)


def test_page_monitor_unlock_failure_does_not_repeat_or_recover(clock, tmp_path):
    monitor = IOSPageMonitor("http://example.invalid", tmp_path)
    monitor.device_client = client_with_states([True])
    monitor.device_client.http.post.side_effect = OSError("unlock rejected")
    monitor._get = Mock()
    recover = Mock()
    try:
        with pytest.raises(guard.DeviceUnlockError):
            monitor.wait_for("home", lambda _page: True, recover=recover)
        monitor.device_client.http.post.assert_called_once()
        monitor._get.assert_not_called()
        recover.assert_not_called()
    finally:
        monitor.close()


def test_setup_locked_device_is_failure_not_skipped(clock, monkeypatch):
    client = client_with_states([True])
    client.status.return_value = {"ready": True}
    client.http.post.side_effect = OSError("unlock rejected")
    monkeypatch.setattr("ui_framework.JRYG_ios_ui_base.wda.Client", Mock(return_value=client))
    flow = type("LockedFlow", (iOSBase,), {"_wda_url": "http://example.invalid"})
    with pytest.raises(guard.DeviceUnlockError):
        flow.setup_class()
    assert_no_business(client)


@pytest.mark.parametrize("locked,expected", [(False, 0), (True, 1)])
def test_prepare_only_cli_unlock_gate(clock, monkeypatch, locked, expected):
    client = client_with_states([locked])
    client.http.post.side_effect = OSError("unlock rejected")
    monkeypatch.setattr(guard.wda, "Client", Mock(return_value=client))
    monkeypatch.setattr("sys.argv", ["guard", "--wda-url", "http://example.invalid"])
    assert guard.main() == expected
    assert_no_business(client)
