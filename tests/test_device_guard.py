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
    # Mac 防休眠在单元测试中 mock 为空操作，不执行真实系统命令
    monkeypatch.setattr(guard, "ensure_mac_awake", lambda: True)
    monkeypatch.setattr(guard, "mac_prevent_sleep", lambda: None)
    monkeypatch.setattr(guard, "mac_stop_prevent_sleep", lambda: None)
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
    client._session_http.post.return_value = SimpleNamespace(value=None)
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
    client = client_with_states([True, True, False], foreground=bundle or BUNDLE_ID)
    assert guard.ensure_unlocked(client, resume_bundle=bundle) is True
    client.http.post.assert_called_once_with("/wda/unlock", timeout=10)
    if bundle:
        client._session_http.post.assert_called_once_with("/wda/apps/launch", {"bundleId": bundle}, timeout=3)
        assert client.http.get.call_args.args[0] == "/wda/activeAppInfo"
    else:
        client._session_http.post.assert_not_called()
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
        client._session_http.post.side_effect = error
    with pytest.raises(guard.DeviceUnlockError) as caught:
        guard.ensure_unlocked(client, resume_bundle=BUNDLE_ID)
    assert "private-lock-code" not in str(caught.value) + caplog.text
    assert client.http.post.call_count == {"query": 0, "unlock": 1, "activate": 1}[failure]
    assert client._session_http.post.call_count == (1 if failure == "activate" else 0)
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
    client = client_with_states([True, False], foreground="com.apple.mobilesafari")
    guard.remember_foreground(client, ET.fromstring('<XCUIElementTypeApplication bundleId="com.apple.mobilesafari" />'))
    assert guard.ensure_unlocked(client) is True
    assert client._session_http.post.call_args.args[1] == {"bundleId": "com.apple.mobilesafari"}


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
        "/wda/locked", "/wda/locked", "/wda/activeAppInfo", "/wda/activeAppInfo", "/source?format=xml"]
    assert client._session_http.post.call_args.args[1] == {"bundleId": BUNDLE_ID}
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
    flow.wait_before_destination = Mock(return_value=ET.Element("trip"))
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
    client = client_with_states([False, True, False], foreground="com.apple.mobilesafari")
    client.source.return_value = '<XCUIElementTypeApplication bundleId="com.apple.mobilesafari"><XCUIElementTypeStaticText label="SUCCESS" visible="true" /></XCUIElementTypeApplication>'
    assert iOSBase._ios_get_all_texts(client) == ["SUCCESS"]
    assert iOSBase._ios_get_all_texts(client) == ["SUCCESS"]
    assert client._session_http.post.call_args.args[1] == {"bundleId": "com.apple.mobilesafari"}
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


@pytest.fixture
def mac_clock(monkeypatch):
    import plistlib

    clock = SimpleNamespace(now=0)
    monkeypatch.setattr(guard.time, "monotonic", lambda: clock.now)
    monkeypatch.setattr(guard.time, "sleep", Mock(side_effect=AssertionError("Mac wake must not sleep")))
    monkeypatch.setattr(guard, "_is_macos", lambda: True)
    for name in ("_mac_caffeinate_hold", "_mac_display_wake", "_mac_locked_state"):
        monkeypatch.setattr(guard, name, None)
    for name in ("_mac_checked_at", "_mac_wake_at", "_mac_lock_warn_at"):
        monkeypatch.setattr(guard, name, float("-inf"))
    read = Mock(return_value=SimpleNamespace(stdout=plistlib.dumps([{"IOConsoleLocked": False}])))
    monkeypatch.setattr(guard.subprocess, "run", read)
    wake, hold = Mock(), Mock()
    wake.poll.return_value = hold.poll.return_value = None
    spawn = Mock(side_effect=[wake, hold])
    monkeypatch.setattr(guard.subprocess, "Popen", spawn)
    return SimpleNamespace(clock=clock, read=read, spawn=spawn, wake=wake, hold=hold)


@pytest.mark.parametrize("locked", [False, True, None])
def test_mac_wake_nonblocking_hold_and_cached_state(mac_clock, monkeypatch, locked, caplog):
    read = Mock(return_value=locked)
    monkeypatch.setattr(guard, "mac_is_locked", read)
    for _ in range(20):
        assert guard.ensure_mac_awake() is True
    read.assert_called_once()
    assert mac_clock.spawn.call_count == 2
    assert mac_clock.spawn.call_args_list[0].args[0] == ["/usr/bin/caffeinate", "-u", "-t", "5"]
    assert mac_clock.spawn.call_args_list[1].args[0][:5] == ["/usr/bin/caffeinate", "-d", "-i", "-s", "-w"]
    if locked:
        assert "密码锁仍需本人解锁" in caplog.text
        assert caplog.text.count("密码锁仍需本人解锁") == 1
    assert mac_clock.clock.now == 0


def test_mac_state_rechecked_and_hold_not_duplicated(mac_clock, monkeypatch, caplog):
    read = Mock(side_effect=[True, False])
    monkeypatch.setattr(guard, "mac_is_locked", read)
    guard.ensure_mac_awake()
    mac_clock.clock.now = 5
    guard.ensure_mac_awake()
    assert read.call_count == 2
    assert mac_clock.spawn.call_count == 2
    assert "控制台已解锁" in caplog.text


def test_mac_display_wake_rate_limited_and_finished_process_reaped(mac_clock):
    guard.mac_prevent_sleep()
    mac_clock.wake.poll.return_value = 0
    mac_clock.clock.now = 5
    guard.mac_prevent_sleep()
    mac_clock.wake.wait.assert_called_once()
    assert mac_clock.spawn.call_count == 2
    mac_clock.clock.now = 30
    wake = Mock()
    wake.poll.return_value = None
    mac_clock.spawn.side_effect = [wake]
    guard.mac_prevent_sleep()
    assert mac_clock.spawn.call_count == 3
    assert guard._mac_caffeinate_hold is mac_clock.hold


@pytest.mark.parametrize("root,array,expected", [
    ({"IOConsoleLocked": True}, False, True),
    ({"IOConsoleLocked": False}, True, False),
    ({"IOConsoleUsers": [{"kCGSSessionOnConsoleKey": True, "CGSSessionScreenIsLocked": True}]}, True, True),
    ({"IOConsoleUsers": [{"kCGSSessionOnConsoleKey": True, "CGSSessionScreenIsLocked": False}]}, False, False),
    ({"IOConsoleUsers": [{"kCGSSessionOnConsoleKey": False, "CGSSessionScreenIsLocked": True}]}, True, None),
    ({"IOConsoleLocked": "false"}, False, None),
])
def test_mac_actual_lock_field_contract(mac_clock, root, array, expected):
    import plistlib

    mac_clock.read.return_value.stdout = plistlib.dumps([root] if array else root)
    assert guard.mac_is_locked() is expected
    assert mac_clock.read.call_args.kwargs["timeout"] == 1
    mac_clock.spawn.assert_not_called()


def test_mac_wake_failure_never_prints_password_or_changes_lock_settings(mac_clock, caplog):
    mac_clock.spawn.side_effect = OSError("private-password")
    guard.ensure_mac_awake()
    assert "private-password" not in caplog.text
    assert "未修改系统锁屏设置" in caplog.text


def test_mac_cleanup_only_terminates_owned_processes(mac_clock):
    guard.mac_prevent_sleep()
    guard.mac_stop_prevent_sleep()
    for process in (mac_clock.wake, mac_clock.hold):
        process.terminate.assert_called_once()
        process.wait.assert_called_once_with(timeout=5)
    assert guard._mac_caffeinate_hold is guard._mac_display_wake is None
    assert guard._mac_checked_at == float("-inf")


def test_mac_only_cli_binds_shell_without_wda(mac_clock, monkeypatch):
    import os

    client = Mock()
    monkeypatch.setattr(guard.wda, "Client", client)
    monkeypatch.setattr("sys.argv", ["guard", "--mac-only", "--hold-pid", str(os.getppid())])
    assert guard.main() == 0
    assert mac_clock.spawn.call_args.args[0][-1] == str(os.getppid())
    client.assert_not_called()


def test_mac_only_cli_rejects_unrelated_pid(mac_clock, monkeypatch):
    import os

    monkeypatch.setattr("sys.argv", ["guard", "--mac-only", "--hold-pid", str(os.getppid() + 999)])
    with pytest.raises(SystemExit) as caught:
        guard.main()
    assert caught.value.code == 2
    mac_clock.spawn.assert_not_called()


def test_mac_detection_consumes_shared_device_budget(clock, monkeypatch):
    monkeypatch.setattr(guard, "ensure_mac_awake", lambda: setattr(clock, "now", clock.now + 2))
    client = client_with_states([False])
    assert guard.ensure_unlocked(client, deadline=3) is False
    client.http.get.assert_called_once_with("/wda/locked", timeout=1)
    assert_no_business(client)


@pytest.mark.parametrize("foreground", ["com.apple.Preferences", None])
def test_unlock_different_foreground_never_replays_or_reads_page(clock, foreground):
    client = client_with_states([True, False], foreground=foreground)
    with pytest.raises(guard.DeviceUnlockError, match="原App前台未确认"):
        guard.ensure_unlocked(client, resume_bundle=BUNDLE_ID)
    client.http.post.assert_called_once()
    client._session_http.post.assert_called_once()
    assert_no_business(client)


def test_unlock_then_springboard_readonly_wait_no_repeated_activation(clock):
    client = client_with_states([True, False])
    old_read = client.http.get.side_effect
    foregrounds = iter(["com.apple.springboard", BUNDLE_ID])

    def read(endpoint, **kwargs):
        if endpoint == "/wda/activeAppInfo":
            return SimpleNamespace(value={"bundleId": next(foregrounds)})
        return old_read(endpoint, **kwargs)

    client.http.get.side_effect = read
    assert guard.ensure_unlocked(client, resume_bundle=BUNDLE_ID)
    assert clock.now == 0.5
    client._session_http.post.assert_called_once()
    client.http.post.assert_called_once()
    assert_no_business(client)


def test_unlock_foreground_timeout_remains_bounded(clock):
    client = client_with_states([True, False], foreground="com.apple.springboard")
    with pytest.raises(guard.DeviceUnlockError, match="等待超时"):
        guard.ensure_unlocked(client, deadline=2, resume_bundle=BUNDLE_ID)
    assert clock.now == 2
    client._session_http.post.assert_called_once()
    client.http.post.assert_called_once()
    assert_no_business(client)


def test_unlock_real_wda_session_uses_launch_not_activate(clock, monkeypatch):
    client = guard.wda.Client("http://example.invalid", _session_id="test-session")
    transport = Mock(side_effect=[SimpleNamespace(value=True), SimpleNamespace(value=None),
                                  SimpleNamespace(value=False), SimpleNamespace(value=None),
                                  SimpleNamespace(value={"bundleId": BUNDLE_ID})])
    monkeypatch.setattr(guard.wda, "httpdo", transport)
    assert guard.ensure_unlocked(client, resume_bundle=BUNDLE_ID)
    requests = transport.call_args_list
    assert requests[1].args[0] == "http://example.invalid/wda/unlock"
    assert requests[3].args == ("http://example.invalid/session/test-session/wda/apps/launch",
                                "POST", {"bundleId": BUNDLE_ID}, 3)
    assert requests[4].args[0].endswith("/wda/activeAppInfo")


@pytest.mark.parametrize("text", ["Pay Now", "Return to Merchant", "打开"])
def test_safari_lock_failure_propagates_without_fallback_payment(clock, text):
    flow = iOSBase()
    flow.client = client_with_states([True])
    flow.client.http.post.side_effect = OSError("locked")
    with pytest.raises(guard.DeviceUnlockError):
        flow._ios_safari_click_by_text(text, 196, 400)
    flow.client.source.assert_not_called()
    assert_no_business(flow.client)


def test_safari_xml_read_restores_observed_app_after_unlock(clock):
    flow = iOSBase()
    flow.client = client_with_states([False, True, False], foreground="com.apple.mobilesafari")
    xml = '<XCUIElementTypeApplication bundleId="com.apple.mobilesafari"><XCUIElementTypeStaticText label="Pay Now" visible="true" /></XCUIElementTypeApplication>'
    flow.client.source.return_value = xml
    assert flow._ios_get_source_xml() == xml
    assert flow._ios_get_source_xml() == xml
    flow.client._session_http.post.assert_called_once_with("/wda/apps/launch", {"bundleId": "com.apple.mobilesafari"}, timeout=3)
    assert_no_business(flow.client)


def test_page_monitor_wake_and_read_share_deadline(clock, tmp_path):
    monitor = IOSPageMonitor("http://example.invalid", tmp_path)
    monitor.device_client = client_with_states([True, False])

    def unlock(*args, **kwargs):
        clock.now += 2
        return SimpleNamespace(value=None)

    monitor.device_client.http.post.side_effect = unlock
    monitor._get = Mock(return_value='<XCUIElementTypeApplication bundleId="com.sunlightmobility.client" />')
    try:
        monitor.inspect(timeout=3)
        monitor._get.assert_called_once_with("/source?format=xml", 1)
    finally:
        monitor.close()
    assert_no_business(monitor.device_client)


def test_card_form_unlock_failure_prevents_input(clock):
    flow = iOSBase()
    flow.client = client_with_states([True])
    flow.client.http.post.side_effect = OSError("locked")
    flow._ios_get_all_texts = Mock(return_value=["卡號"])
    flow._ios_screenshot = Mock()
    with pytest.raises(guard.DeviceUnlockError):
        flow._ios_fill_bank_card_form("sandbox")
    flow.client.assert_not_called()
    assert_no_business(flow.client)


def test_shell_wakes_mac_before_device_and_phone_only_after_wda():
    from pathlib import Path

    script = (Path(__file__).resolve().parents[1] / "runners/JRYG_run_hk_ios.sh").read_text()
    assert script.index("--collect-only|--co|--help|-h") < script.index("--mac-only --hold-pid")
    assert script.index("--mac-only --hold-pid") < script.index("xcrun devicectl device info")
    assert script.index("--mac-only --hold-pid") < script.index("if ! wda_ready;")
    assert script.rindex("if ! wda_ready;") < script.index('--wda-url "$WDA_URL"')
