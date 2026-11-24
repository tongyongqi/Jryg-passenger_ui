from types import SimpleNamespace
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET

import pytest
from wda.usbmux.exceptions import HTTPError

from ui_framework.JRYG_driver_ui import (
    ACTION_LABELS,
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
    flow.wait_before_destination = Mock(return_value=ET.fromstring(DRIVER_XML))
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


def driver_slider(label, *, visible="true", thumb=True):
    root = ET.Element("XCUIElementTypeApplication", bundleId=BUNDLE_ID)
    track = ET.SubElement(root, "XCUIElementTypeOther", x="12", y="761", width="369", height="68", visible=visible)
    if thumb:
        ET.SubElement(track, "XCUIElementTypeImage", name="ca_icon_order_detail_hdjtcs",
                      x="17", y="766", width="58", height="58", visible=visible)
    ET.SubElement(track, "XCUIElementTypeStaticText", label=label, enabled="true",
                  x="139", y="778", width="116", height="33", visible=visible)
    return root


@pytest.mark.parametrize("label", ["出發接乘客", "出发接乘客", "已出發", "已出发"])
def test_departure_slider_detected_and_swiped_in_correct_direction(flow, label):
    page = driver_slider(label)
    assert flow.detect_phase(page) == "departure"
    flow.act(page, ACTION_LABELS["departure"])
    flow.client.swipe.assert_called_once_with(46, 795, 375, 795, duration=0.8)
    flow.client.click.assert_not_called()


@pytest.mark.parametrize("label", ["出發接乘客", "已出發"])
@pytest.mark.parametrize("visible,thumb", [("false", True), ("true", False)])
def test_departure_history_text_is_not_actionable(flow, label, visible, thumb):
    assert flow.detect_phase(driver_slider(label, visible=visible, thumb=thumb)) == "unknown"
    flow.client.swipe.assert_not_called()


def test_resume_departure_keeps_departure_arrival_pickup_destination_order(flow):
    pages = [(driver_slider(label), phase) for label, phase in (
        ("出發接乘客", "departure"), ("到達上車地點", "pickup"),
        ("已接載乘客", "onboard"), ("到達目的地", "destination"), ("確認收款", "bill"))]
    flow.resume_phase = "departure"
    flow.args.stop_after = "bill"
    flow._activate_driver_app = Mock()
    flow.wait_for = Mock(side_effect=pages)
    flow.wait_before_destination = Mock(return_value=pages[3][0])
    flow.act = Mock()
    flow.submit_bill = Mock()
    with patch("ui_framework.JRYG_driver_ui.time.monotonic", return_value=10):
        flow.run()
    assert [call.args[1] for call in flow.act.call_args_list] == [
        ACTION_LABELS[phase] for phase in ("departure", "pickup", "onboard", "destination")]
    assert [call.args[0] for call in flow.wait_for.call_args_list[1:]] == [
        {"pickup"}, {"onboard"}, {"tail", "destination"}, {"bill", "unpaid", "complete"}]
    flow.submit_bill.assert_not_called()
    assert flow.last_phase == "bill"


def test_arrival_timeout_boundary_accepts_expected_page_without_reswiping(flow):
    original = driver_slider("到達上車地點")
    arrived = driver_slider("已接載乘客")
    flow.args.stop_after = "onboard"
    flow.resume_phase = "pickup"
    flow._activate_driver_app = Mock()
    flow.wait_for = Mock(side_effect=[(original, "pickup"), TimeoutError("boundary")])
    flow.root = Mock(return_value=arrived)
    flow.act = Mock()
    with patch("ui_framework.JRYG_driver_ui.time.monotonic", return_value=10):
        flow.run()
    flow.act.assert_called_once_with(original, ACTION_LABELS["pickup"])
    assert flow.last_phase == "onboard"


@pytest.mark.parametrize("observed", ["出發接乘客", "unrecognized"])
def test_arrival_unexpected_phase_stops_without_backtracking(flow, observed):
    original = driver_slider("到達上車地點")
    flow.args.stop_after = "submitted"
    flow.resume_phase = "pickup"
    flow._activate_driver_app = Mock()
    flow.wait_for = Mock(side_effect=[(original, "pickup"), TimeoutError("not arrived")])
    flow.root = Mock(return_value=driver_slider(observed))
    flow.act = Mock()
    flow.submit_bill = Mock()
    with patch("ui_framework.JRYG_driver_ui.time.monotonic", return_value=10):
        with pytest.raises(RuntimeError, match="非预期阶段.*不自动回退"):
            flow.run()
    flow.act.assert_called_once_with(original, ACTION_LABELS["pickup"])
    flow.submit_bill.assert_not_called()


@pytest.mark.parametrize("blocked", ["alert", "network", "cancelled", "transport"])
def test_arrival_wait_failure_never_reswipes_on_unsafe_page(flow, blocked):
    page = driver_slider("到達上車地點")
    if blocked == "alert":
        ET.SubElement(page, "XCUIElementTypeAlert", visible="true")
    if blocked == "network":
        ET.SubElement(page, "XCUIElementTypeStaticText", label="獲取網絡/位置信息異常", visible="true")
    if blocked == "cancelled":
        page = ET.Element("root")
        ET.SubElement(page, "XCUIElementTypeStaticText", label="已取消", visible="true")
    flow.args.stop_after = "submitted"
    flow._activate_driver_app = Mock()
    flow.wait_for = Mock(side_effect=[(page, "pickup"), TimeoutError("wait failed")])
    flow.root = Mock(side_effect=DriverPageReadError("transport") if blocked == "transport" else None, return_value=page)
    flow.act = Mock()
    flow.snapshot = Mock()
    with patch("ui_framework.JRYG_driver_ui.time.monotonic", return_value=10):
        with pytest.raises((TimeoutError, RuntimeError)):
            flow.run()
    flow.act.assert_called_once()


@pytest.mark.parametrize("second_timeout", [True, False])
def test_arrival_same_stage_only_reswipes_once(flow, second_timeout):
    page = driver_slider("到達上車地點")
    arrived = driver_slider("已接載乘客")
    flow.args.stop_after = "onboard"
    flow._activate_driver_app = Mock()
    final = TimeoutError("second wait") if second_timeout else (arrived, "onboard")
    flow.wait_for = Mock(side_effect=[(page, "pickup"), TimeoutError("first wait"), final])
    flow.root = Mock(return_value=page)
    flow.act = Mock()
    with patch("ui_framework.JRYG_driver_ui.time.monotonic", return_value=10):
        if second_timeout:
            with pytest.raises(TimeoutError, match="second wait"):
                flow.run()
        else:
            flow.run()
            assert flow.last_phase == "onboard"
    assert flow.act.call_count == 2
    assert all(call.args[1] == ACTION_LABELS["pickup"] for call in flow.act.call_args_list)


@pytest.fixture
def ride_clock(monkeypatch):
    clock = SimpleNamespace(now=10.0, sleeps=[])

    def sleep(seconds):
        clock.sleeps.append(seconds)
        clock.now += seconds

    monkeypatch.setattr("ui_framework.JRYG_driver_ui.time.monotonic", lambda: clock.now)
    monkeypatch.setattr("ui_framework.JRYG_driver_ui.time.sleep", sleep)
    return clock


@pytest.mark.parametrize("via_tail,tail_seconds", [(False, 0), (True, 12), (True, 35)])
def test_destination_wait_starts_after_onboard_confirmation(flow, ride_clock, via_tail, tail_seconds):
    onboard = driver_slider("已接載乘客")
    destination = driver_slider("到達目的地")
    bill = driver_slider("確認收款")
    tail = ET.Element("tail")
    pages = [(onboard, "onboard"), (tail, "tail"), (destination, "destination"), (bill, "bill")] if via_tail else [
        (onboard, "onboard"), (destination, "destination"), (bill, "bill")]
    flow.args.stop_after = "bill"
    flow._activate_driver_app = Mock()
    flow.wait_for = Mock(side_effect=pages)
    flow.root = Mock(return_value=destination)
    actions = []

    def act(root, labels):
        actions.append((labels, ride_clock.now))
        if labels == ACTION_LABELS["onboard"]:
            ride_clock.now += 4

    flow.act = Mock(side_effect=act)
    flow.enter_tail = Mock(side_effect=lambda _root: setattr(ride_clock, "now", ride_clock.now + tail_seconds))
    flow.run()
    assert actions == [(ACTION_LABELS["onboard"], 10), (ACTION_LABELS["destination"], 14 + max(30, tail_seconds))]
    assert flow.destination_not_before == 44
    assert sum(ride_clock.sleeps) == max(0, 30 - tail_seconds)
    flow.root.assert_called_once()


@pytest.mark.parametrize("resume_phase", [None, "destination"])
def test_direct_destination_conservatively_waits_full_30_seconds(flow, ride_clock, resume_phase):
    page = driver_slider("到達目的地")
    flow.resume_phase = resume_phase
    flow.args.stop_after = "bill"
    flow._activate_driver_app = Mock()
    flow.wait_for = Mock(side_effect=[(page, "destination"), (driver_slider("確認收款"), "bill")])
    flow.root = Mock(return_value=page)
    actions = []
    flow.act = Mock(side_effect=lambda _root, _labels: actions.append(ride_clock.now))
    flow.run()
    assert actions == [40]
    assert ride_clock.sleeps == [30]


def test_destination_retry_does_not_repeat_30_second_wait(flow, ride_clock):
    page = driver_slider("到達目的地")
    bill = driver_slider("確認收款")
    flow.args.stop_after = "bill"
    flow._activate_driver_app = Mock()
    flow.wait_for = Mock(side_effect=[(page, "destination"), TimeoutError("first wait"), (bill, "bill")])
    flow.root = Mock(return_value=page)
    actions = []
    flow.act = Mock(side_effect=lambda _root, _labels: actions.append(ride_clock.now))
    flow.run()
    assert actions == [40, 40]
    assert ride_clock.sleeps == [30]
    assert flow.root.call_count == 2


@pytest.mark.parametrize("blocked", ["alert", "network", "cancelled", "unknown", "transport", "foreground", "unlock"])
def test_destination_wait_refresh_blocks_unsafe_action(flow, ride_clock, blocked):
    from ui_framework.JRYG_device_guard import DeviceUnlockError

    page = driver_slider("到達目的地")
    fresh = driver_slider("到達目的地")
    if blocked == "alert":
        ET.SubElement(fresh, "XCUIElementTypeAlert", visible="true")
    elif blocked in ("network", "cancelled", "unknown"):
        fresh = ET.Element("root")
        label = {"network": "獲取網絡/位置信息異常", "cancelled": "已取消", "unknown": "unrecognized"}[blocked]
        ET.SubElement(fresh, "XCUIElementTypeStaticText", label=label, visible="true")
    error = {"transport": DriverPageReadError("private-token"),
             "foreground": DriverAppNotForegroundError("private-token"),
             "unlock": DeviceUnlockError("private-token")}.get(blocked)
    flow.args.stop_after = "submitted"
    flow._activate_driver_app = Mock()
    flow.wait_for = Mock(return_value=(page, "destination"))
    flow.root = Mock(side_effect=error, return_value=fresh)
    flow.snapshot = Mock()
    flow.act = Mock()
    with pytest.raises(RuntimeError):
        flow.run()
    assert ride_clock.sleeps == [30]
    flow.act.assert_not_called()
    flow.wait_for.assert_called_once()


def test_destination_wait_does_not_shorten_for_insufficient_deadline(flow, ride_clock):
    flow.deadline = ride_clock.now + 29
    flow.root = Mock()
    with pytest.raises(TimeoutError, match="30秒等待超出"):
        flow.wait_before_destination()
    assert ride_clock.sleeps == []
    flow.root.assert_not_called()


def test_destination_wait_rechecks_clock_after_short_sleep(flow, ride_clock, monkeypatch):
    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        ride_clock.now += min(seconds, 10)

    monkeypatch.setattr("ui_framework.JRYG_driver_ui.time.sleep", sleep)
    flow.root = Mock(return_value=driver_slider("到達目的地"))
    flow.wait_before_destination()
    assert ride_clock.now == 40
    assert sleeps == [30, 20, 10]


def test_destination_wait_refresh_deadline_prevents_action(flow, ride_clock):
    flow.args.timeout = 31
    flow.args.stop_after = "submitted"
    flow._activate_driver_app = Mock()
    flow.wait_for = Mock(return_value=(driver_slider("到達目的地"), "destination"))

    def root():
        ride_clock.now += 2
        return driver_slider("到達目的地")

    flow.root = Mock(side_effect=root)
    flow.act = Mock()
    with pytest.raises(TimeoutError, match="页面核验超时"):
        flow.run()
    flow.act.assert_not_called()


def assert_no_foreground_business(flow):
    flow.client.click.assert_not_called()
    flow.client.swipe.assert_not_called()
    flow.client.send_keys.assert_not_called()
    flow.client.session.assert_not_called()
    flow.client.app_activate.assert_not_called()


def test_springboard_recovers_once_after_five_seconds_without_business(flow, ride_clock):
    flow.order_no = "TESTORDER123"
    flow.last_phase = "pickup"
    flow.client.http.get.side_effect = [response({"bundleId": "com.apple.springboard"}),
                                       response({"bundleId": BUNDLE_ID}), response(DRIVER_XML)]

    def activate(endpoint, data, timeout):
        assert ride_clock.now == 15
        assert endpoint == "/wda/apps/launch"
        assert data == {"bundleId": BUNDLE_ID}
        assert timeout == 3
        assert flow.client.http.get.call_count == 1

    flow.client._session_http.post.side_effect = activate
    assert flow.root().tag == "AppiumAUT"
    assert ride_clock.sleeps == [5]
    flow.client._session_http.post.assert_called_once_with("/wda/apps/launch", {"bundleId": BUNDLE_ID}, timeout=3)
    assert flow.foreground_recovery_used
    assert flow.order_no == "TESTORDER123"
    assert flow.last_phase == "pickup"
    assert [call.args[0] for call in flow.client.http.get.call_args_list] == [
        "/wda/activeAppInfo", "/wda/activeAppInfo", "/source?format=xml"]
    assert_no_foreground_business(flow)
    flow.client.http.get.side_effect = None
    flow.client.http.get.return_value = response({"bundleId": "com.apple.springboard"})
    with pytest.raises(DriverAppNotForegroundError):
        flow.root()
    assert ride_clock.sleeps == [5]
    assert flow.client._session_http.post.call_count == 1


@pytest.mark.parametrize("bundle", ["com.apple.Preferences", "com.sunlightmobility.client", None])
def test_other_or_unknown_app_never_recovers_or_reads_xml(flow, ride_clock, bundle):
    flow.client.http.get.return_value = response({"bundleId": bundle})
    with pytest.raises(DriverAppNotForegroundError):
        flow.root()
    assert not flow.foreground_recovery_used
    assert ride_clock.sleeps == []
    flow.client.http.get.assert_called_once()
    flow.client._session_http.post.assert_not_called()
    assert_no_foreground_business(flow)


@pytest.mark.parametrize("seconds", [4, 5])
def test_springboard_recovery_insufficient_budget_stops_without_activation(flow, ride_clock, seconds):
    flow.client.http.get.return_value = response({"bundleId": "com.apple.springboard"})
    with pytest.raises(DriverAppNotForegroundError, match="不足5秒"):
        flow.root(read_deadline=ride_clock.now + seconds)
    assert ride_clock.sleeps == []
    flow.client._session_http.post.assert_not_called()
    flow.client.http.get.assert_called_once()
    assert_no_foreground_business(flow)


def test_springboard_activation_waits_use_remaining_original_budget(flow, ride_clock):
    deadline = ride_clock.now + 8
    flow.client.http.get.side_effect = [response({"bundleId": "com.apple.springboard"}),
                                       response({"bundleId": BUNDLE_ID}), response(DRIVER_XML)]

    def activate(*args, **kwargs):
        ride_clock.now += 1

    flow.client._session_http.post.side_effect = activate
    flow.root(read_deadline=deadline)
    assert flow.deadline == 1000
    assert [call.kwargs["timeout"] for call in flow.client.http.get.call_args_list] == [8, 2, 2]
    flow.client._session_http.post.assert_called_once_with("/wda/apps/launch", {"bundleId": BUNDLE_ID}, timeout=3)
    assert_no_foreground_business(flow)


@pytest.mark.parametrize("step", ["activate", "foreground", "source"])
def test_recovery_transport_failure_never_becomes_business_timeout(flow, ride_clock, step):
    error = OSError("private-token")
    values = [response({"bundleId": "com.apple.springboard"})]
    if step == "activate":
        flow.client._session_http.post.side_effect = error
    elif step == "foreground":
        values.append(error)
    else:
        values.extend([response({"bundleId": BUNDLE_ID}), error])
    flow.client.http.get.side_effect = values
    with pytest.raises(DriverPageReadError) as caught:
        flow.root()
    assert not isinstance(caught.value, TimeoutError)
    assert caught.value.__cause__ is error
    assert "private-token" not in str(caught.value)
    assert flow.client._session_http.post.call_count == 1
    assert_no_foreground_business(flow)


def test_recovery_still_springboard_times_out_as_foreground_error(flow, ride_clock):
    flow.client.http.get.return_value = response({"bundleId": "com.apple.springboard"})
    with pytest.raises(DriverAppNotForegroundError, match="单次恢复后"):
        flow.root(read_deadline=ride_clock.now + 7)
    assert sum(ride_clock.sleeps) == 7
    assert flow.client._session_http.post.call_count == 1
    assert all(call.args[0] == "/wda/activeAppInfo" for call in flow.client.http.get.call_args_list)
    assert_no_foreground_business(flow)


def test_recovery_different_app_or_wrong_xml_still_blocks(flow, ride_clock):
    flow.client.http.get.side_effect = [response({"bundleId": "com.apple.springboard"}),
                                       response({"bundleId": BUNDLE_ID}),
                                       response('<XCUIElementTypeApplication bundleId="com.apple.Preferences" />')]
    with pytest.raises(DriverAppNotForegroundError):
        flow.root()
    assert flow.client._session_http.post.call_count == 1
    assert_no_foreground_business(flow)


def test_startup_activation_does_not_nest_springboard_recovery(flow, ride_clock):
    flow.client.http.get.side_effect = [response({"bundleId": "com.apple.springboard"}),
                                       response({"bundleId": BUNDLE_ID}), response(DRIVER_XML)]
    flow._activate_driver_app()
    flow.client.app_activate.assert_called_once_with(BUNDLE_ID)
    flow.client._session_http.post.assert_not_called()
    assert not flow.foreground_recovery_used
    assert ride_clock.sleeps == [flow.args.interval]
    flow.client.click.assert_not_called()
    flow.client.swipe.assert_not_called()


def test_inspect_does_not_auto_recover_springboard(flow, ride_clock):
    flow.args.inspect = True
    flow.client.http.get.return_value = response({"bundleId": "com.apple.springboard"})
    with pytest.raises(DriverAppNotForegroundError):
        flow.root()
    assert ride_clock.sleeps == []
    flow.client._session_http.post.assert_not_called()
    assert_no_foreground_business(flow)


def test_recovery_sleep_overshoot_does_not_activate_after_deadline(flow, ride_clock, monkeypatch):
    flow.client.http.get.return_value = response({"bundleId": "com.apple.springboard"})
    monkeypatch.setattr("ui_framework.JRYG_driver_ui.time.sleep", lambda _seconds: setattr(ride_clock, "now", ride_clock.now + 10))
    with pytest.raises(DriverAppNotForegroundError, match="恢复已超时"):
        flow.root(read_deadline=15.1)
    flow.client._session_http.post.assert_not_called()
    assert_no_foreground_business(flow)


def test_recovery_accepts_no_shortened_five_second_sleep(flow, ride_clock, monkeypatch):
    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        ride_clock.now += min(2, seconds)

    monkeypatch.setattr("ui_framework.JRYG_driver_ui.time.sleep", sleep)
    flow.client.http.get.side_effect = [response({"bundleId": "com.apple.springboard"}),
                                       response({"bundleId": BUNDLE_ID}), response(DRIVER_XML)]
    flow.root()
    assert ride_clock.now == 15
    assert sleeps == [5, 3, 1]
    assert flow.client._session_http.post.call_count == 1


def test_wait_after_pickup_slide_recovers_and_never_repeats_successful_slide(flow, ride_clock):
    pickup = driver_slider("到達上車地點")
    onboard = driver_slider("已接載乘客")
    flow.args.stop_after = "onboard"
    flow._activate_driver_app = Mock()
    flow.act = Mock()
    flow.client.http.get.side_effect = [response({"bundleId": BUNDLE_ID}), response(ET.tostring(pickup, encoding="unicode")),
                                       response({"bundleId": "com.apple.springboard"}), response({"bundleId": BUNDLE_ID}),
                                       response(ET.tostring(onboard, encoding="unicode"))]
    flow.run()
    flow.act.assert_called_once()
    assert flow.act.call_args.args[1] == ACTION_LABELS["pickup"]
    assert flow.last_phase == "onboard"
    assert ride_clock.sleeps == [5]
    assert flow.client._session_http.post.call_count == 1
    assert_no_foreground_business(flow)


def test_foreground_recovery_failure_after_slide_does_not_retry_slide(flow, ride_clock):
    pickup = driver_slider("到達上車地點")
    flow.args.stop_after = "onboard"
    flow._activate_driver_app = Mock()
    flow.act = Mock()
    flow.client.http.get.side_effect = [response({"bundleId": BUNDLE_ID}), response(ET.tostring(pickup, encoding="unicode")),
                                       response({"bundleId": "com.apple.springboard"}), response({"bundleId": "com.apple.Preferences"})]
    with pytest.raises(DriverAppNotForegroundError):
        flow.run()
    flow.act.assert_called_once()
    assert flow.client._session_http.post.call_count == 1
    assert_no_foreground_business(flow)


def test_recovery_real_wda_client_uses_supported_session_launch_endpoint(flow, ride_clock, monkeypatch):
    import wda

    client = wda.Client("http://example.invalid", _session_id="test-session")
    flow.client = client
    flow._read_page_value = Mock(side_effect=[{"bundleId": "com.apple.springboard"},
                                             {"bundleId": BUNDLE_ID}, DRIVER_XML])
    transport = Mock(return_value=response(None))
    monkeypatch.setattr(wda, "httpdo", transport)
    flow.root()
    transport.assert_called_once_with("http://example.invalid/session/test-session/wda/apps/launch",
                                       "POST", {"bundleId": BUNDLE_ID}, 3)
    assert ride_clock.sleeps == [5]
