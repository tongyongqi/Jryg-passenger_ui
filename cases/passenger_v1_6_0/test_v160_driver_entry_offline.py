"""2026-11-23 六场景启动失败的工程回归；不登录、出车、下单或接触设备。

证据：report/diagnostics/1795433366815560000_0.xml 原始 source 只有
一个零面积不可见 View；当前 API35 dumpsys power 返回 mWakefulness=Awake。
合成有效页面仅测试现有识别器/导航分支，不代表实际 UI 已恢复。
"""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from passenger_android_core import JRYG_android_device_guard as guard
from passenger_android_core.JRYG_android_ui import normalized_tree
from passenger_android_core.main_flow import order


@pytest.fixture(autouse=True)
def forbid_external_access(monkeypatch):
    import pymysql
    import requests
    import socket
    import subprocess

    def forbidden(*args, **kwargs):
        raise AssertionError("离线测试禁止真实设备、网络或数据库访问")

    monkeypatch.setattr(guard, "_adb_shell", forbidden)
    monkeypatch.setattr(guard, "_adb_device_connected", forbidden)
    monkeypatch.setattr(pymysql, "connect", forbidden)
    monkeypatch.setattr(requests.Session, "request", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)


@pytest.mark.parametrize("raw,expected", [
    ("  mWakefulness=Awake\r\n", True),
    ("  mWakefulness=Asleep\n", False),
    ("mScreenOn=true", True), ("mScreenOn=false", False),
    ("mAwake=true", True), ("mAwake=false", False),
    ("mWakefulness=Awake\nmAwake=true\nmScreenOn=true", True),
    ("mWakefulness=Asleep\nmScreenOn=false", False),
    ("mWakefulness=Awake\n  mWakefulness=Awake", True),
])
def test_confirmed_power_values(raw, expected):
    assert guard._screen_state_from_power(raw) is expected


@pytest.mark.parametrize("raw", [
    "", "unrelated=true", "last_mWakefulness=Awake", "mScreenOnExtra=true",
    "mWakefulness=", "mWakefulness=Dozing", "mWakefulness=Dreaming",
    "mWakefulness=awake", "mScreenOn=unknown", "mAwake=1",
    "mWakefulness=Awake\nmAwake=false",
    "mWakefulness=Awake\nmWakefulness=Asleep",
])
def test_missing_unknown_or_conflicting_power_never_defaults_to_success(raw):
    with pytest.raises(guard.DeviceUnlockError):
        guard._screen_state_from_power(raw)


@pytest.mark.parametrize("value", [None, b"mWakefulness=Awake", 1])
def test_power_output_type_is_required(value):
    with pytest.raises(TypeError):
        guard._screen_state_from_power(value)


def test_connected_awake_device_requires_only_power_read(monkeypatch, caplog):
    monkeypatch.setattr(guard, "_adb_device_connected", Mock(return_value=True))
    shell = Mock(return_value="  mWakefulness=Awake\r\n")
    monkeypatch.setattr(guard, "_adb_shell", shell)
    assert guard.ensure_unlocked("fixture-device") is False
    shell.assert_called_once_with("fixture-device", "dumpsys", "power", timeout=10)
    assert "假设" not in caplog.text


def test_unknown_power_stops_before_input(monkeypatch):
    monkeypatch.setattr(guard, "_adb_device_connected", Mock(return_value=True))
    shell = Mock(return_value="unrecognized power format")
    monkeypatch.setattr(guard, "_adb_shell", shell)
    with pytest.raises(guard.DeviceUnlockError, match="缺少"):
        guard.ensure_unlocked("fixture-device")
    shell.assert_called_once_with("fixture-device", "dumpsys", "power", timeout=10)


def test_disconnected_device_is_not_reported_as_awake(monkeypatch):
    monkeypatch.setattr(guard, "_adb_device_connected", Mock(return_value=False))
    shell = Mock()
    monkeypatch.setattr(guard, "_adb_shell", shell)
    with pytest.raises(guard.DeviceUnlockError, match="未连接"):
        guard.is_screen_on("fixture-device")
    shell.assert_not_called()


def test_adb_failure_is_not_swallowed(monkeypatch):
    monkeypatch.setattr(guard, "_adb_device_connected", Mock(return_value=True))
    shell = Mock(side_effect=guard.DeviceUnlockError("fixture-transport-failure"))
    monkeypatch.setattr(guard, "_adb_shell", shell)
    with pytest.raises(guard.DeviceUnlockError, match="fixture-transport-failure"):
        guard.is_screen_on("fixture-device")


# 脱敏后保留失败原始树的 class、显示属性与几何信息，不包含账号或订单。
EMPTY_NATIVE = '''<hierarchy width="1172" height="2748">
<android.view.View package="com.sunlightmobility.driver" text="" enabled="false"
 bounds="[0,0][0,0]" displayed="false" a11y-important="false" />
</hierarchy>'''


def empty_tree():
    return normalized_tree(EMPTY_NATIVE, "com.sunlightmobility.driver")


def page(text):
    return normalized_tree(
        '<hierarchy><node class="android.widget.Button" text="' + text + '" '
        'enabled="true" displayed="true" bounds="[0,100][300,160]"/></hierarchy>',
        "com.sunlightmobility.driver")


def history_page():
    prefix = "com.sunlightmobility.driver:id/"
    return normalized_tree(
        f'<hierarchy><node class="android.widget.TextView" resource-id="{prefix}tv_bar_title" '
        'text="我的行程" bounds="[0,0][300,50]"/>'
        f'<node class="android.widget.LinearLayout" resource-id="{prefix}rl_order_list" '
        'bounds="[0,100][300,500]"/></hierarchy>', "com.sunlightmobility.driver")


class Clock:
    def __init__(self):
        self.now = 0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        assert seconds > 0
        self.now += seconds


@pytest.fixture
def entry(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(order, "time", clock)
    case = object.__new__(order.AndroidDriverUIFlow)
    case.args = SimpleNamespace(step_timeout=3, interval=1)
    case.accept_labels = ("接單",)
    case.deadline = 10
    case.client = Mock()
    case.root = Mock(return_value=empty_tree())
    case.snapshot = Mock()
    case.login = Mock()
    case.act = Mock()
    return case


def assert_no_business_actions(case):
    case.client.click.assert_not_called()
    case.client.swipe.assert_not_called()
    case.client.driver.execute_script.assert_not_called()
    case.login.assert_not_called()
    case.act.assert_not_called()


def test_empty_raw_source_stays_empty_after_normalization():
    root = empty_tree()
    assert root.get("visible") == "true"  # 包装节点不能被计为正常业务节点。
    assert len(list(root)) == 1
    child = root[0]
    assert child.get("visible") == "false"
    assert child.get("width") == child.get("height") == "0"
    assert child.get("label") == ""


def test_persistent_empty_source_reports_source_not_history_failure(entry):
    with pytest.raises(TimeoutError, match="页面树不可用.*采样3次、空树3次"):
        entry.wait_for_entry_page()
    entry.snapshot.assert_called_once_with("driver_entry_empty_source_timeout")
    assert entry.entry_page_observation == {
        "source_reads": 3, "empty_source_reads": 3,
        "last_source_empty": True, "history_returned": False,
    }
    entry.client.back.assert_not_called()
    assert_no_business_actions(entry)


def test_snapshot_failure_does_not_replace_empty_source_error(entry, caplog):
    entry.snapshot.side_effect = OSError("fixture-screenshot")
    with pytest.raises(TimeoutError, match="页面树不可用"):
        entry.wait_for_entry_page()
    assert "取证失败" in caplog.text
    entry.client.back.assert_not_called()
    assert_no_business_actions(entry)


@pytest.mark.parametrize("text,expected", [("登錄/註冊", "login"), ("點擊出車", "offline"),
                                          ("接單中", "online")])
def test_transient_empty_source_can_recover_to_existing_entry_phase(entry, text, expected):
    recovered = page(text)
    entry.root.side_effect = [empty_tree(), recovered]
    root, phase = entry.wait_for_entry_page()
    assert root is recovered and phase == expected
    assert entry.root.call_count == 2
    entry.client.back.assert_not_called()
    entry.snapshot.assert_not_called()
    assert_no_business_actions(entry)


def test_unknown_visible_page_is_not_misclassified_as_empty(entry):
    entry.root.return_value = page("fixture-new-page")
    with pytest.raises(TimeoutError, match="存在有效节点.*未执行历史返回"):
        entry.wait_for_entry_page()
    entry.snapshot.assert_called_once_with("driver_entry_unknown_page_timeout")
    assert entry.entry_page_observation["empty_source_reads"] == 0
    entry.client.back.assert_not_called()
    assert_no_business_actions(entry)


def test_history_return_occurs_once_even_if_history_stays(entry):
    entry.root.return_value = history_page()
    with pytest.raises(TimeoutError, match="历史列表已单次返回"):
        entry.wait_for_entry_page()
    entry.client.back.assert_called_once()
    entry.snapshot.assert_called_once_with("driver_entry_navigation_timeout")
    assert entry.entry_page_observation["history_returned"] is True
    assert_no_business_actions(entry)


def test_empty_source_after_history_return_preserves_evidence(entry):
    entry.root.side_effect = [history_page(), empty_tree(), empty_tree()]
    with pytest.raises(TimeoutError, match="页面树不可用"):
        entry.wait_for_entry_page()
    assert entry.entry_page_observation["history_returned"] is True
    assert entry.entry_page_observation["empty_source_reads"] == 2
    entry.client.back.assert_called_once()
    assert_no_business_actions(entry)


def test_history_to_home_recovers_without_order_actions(entry):
    home = page("接單中")
    entry.root.side_effect = [history_page(), home]
    assert entry.wait_for_entry_page() == (home, "online")
    entry.client.back.assert_called_once()
    entry.snapshot.assert_not_called()
    assert_no_business_actions(entry)


def test_expired_deadline_does_not_claim_page_was_observed(entry):
    entry.deadline = 0
    with pytest.raises(TimeoutError, match="未获得页面证据"):
        entry.wait_for_entry_page()
    entry.root.assert_not_called()
    entry.snapshot.assert_called_once_with("driver_entry_deadline_expired")
    assert entry.entry_page_observation["source_reads"] == 0
    assert_no_business_actions(entry)


def test_source_transport_failure_is_not_reclassified_as_empty(entry):
    entry.root.side_effect = ConnectionError("fixture-source")
    with pytest.raises(ConnectionError, match="fixture-source"):
        entry.wait_for_entry_page()
    entry.client.back.assert_not_called()
    entry.snapshot.assert_not_called()
    assert_no_business_actions(entry)
