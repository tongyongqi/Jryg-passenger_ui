"""安卓端口预检、并发互斥与会话释放的离线回归。"""

import signal
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest
from appium import webdriver

import JRYG_run_main as runner
from jryg_hk_android import JRYG_android_base as base
from jryg_hk_android import JRYG_android_session as session
from jryg_hk_android import JRYG_android_ui as ui
from jryg_hk_android.JRYG_scenarios import android_scenarios
from jryg_hk_android.JRYG_shared_ios import shared_settings


def lease(tmp_path, monkeypatch, udid="device", port=8201):
    result = session.AndroidSessionLease(udid, port, directory=tmp_path)
    monkeypatch.setattr(result, "check_available", Mock())
    return result


@pytest.mark.parametrize("device,port", [("device", 8201), ("device", 8202), ("other", 8201)])
def test_device_or_port_conflict_stops_second_session(tmp_path, monkeypatch, device, port):
    first = lease(tmp_path, monkeypatch).acquire()
    second = lease(tmp_path, monkeypatch, device, port)
    try:
        with pytest.raises(RuntimeError, match="已有|占用"):
            second.acquire()
        second.check_available.assert_not_called()
        assert second.handles == []
    finally:
        first.release()
    second.acquire().release()
    assert second.handles == []


def test_two_independent_devices_with_different_ports_can_run(tmp_path, monkeypatch):
    first = lease(tmp_path, monkeypatch).acquire()
    second = lease(tmp_path, monkeypatch, "other", 8202).acquire()
    first.release()
    second.release()
    first.release()
    assert first.handles == second.handles == []


@pytest.mark.parametrize("port", [0, 1023, 65536, "8201", True])
def test_invalid_system_port_rejected_before_adb(port):
    with pytest.raises(ValueError, match="system_port"):
        session.AndroidSessionLease("device", port)


@pytest.mark.parametrize("forward", [
    "device tcp:8201 tcp:6790\n", "device tcp:8209 tcp:6790\n", "other tcp:8201 tcp:6790\n",
])
def test_existing_uiautomator_forward_never_removed(forward, tmp_path, monkeypatch):
    run = Mock(return_value=SimpleNamespace(stdout=forward))
    monkeypatch.setattr(session.subprocess, "run", run)
    socket = MagicMock()
    monkeypatch.setattr(session.socket, "socket", socket)
    item = session.AndroidSessionLease("device", 8201, directory=tmp_path)
    with pytest.raises(RuntimeError, match="未自动"):
        item.acquire()
    assert item.handles == []
    run.assert_called_once_with(["adb", "forward", "--list"], capture_output=True,
                                text=True, timeout=10, check=True)
    socket.assert_not_called()


def test_unrelated_adb_forward_is_not_a_conflict(tmp_path, monkeypatch):
    monkeypatch.setattr(session.subprocess, "run", Mock(return_value=SimpleNamespace(
        stdout="other tcp:8202 tcp:6790\ndevice tcp:9000 tcp:9000\n")))
    socket = MagicMock()
    monkeypatch.setattr(session.socket, "socket", socket)
    item = session.AndroidSessionLease("device", 8201, directory=tmp_path).acquire()
    socket.return_value.__enter__.return_value.bind.assert_called_once_with(("127.0.0.1", 8201))
    item.release()


def test_busy_local_port_has_clear_error_and_releases_lease(tmp_path, monkeypatch):
    monkeypatch.setattr(session.subprocess, "run", Mock(return_value=SimpleNamespace(stdout="")))
    socket = MagicMock()
    socket.return_value.__enter__.return_value.bind.side_effect = OSError("address in use")
    monkeypatch.setattr(session.socket, "socket", socket)
    item = session.AndroidSessionLease("device", 8201, directory=tmp_path)
    with pytest.raises(RuntimeError, match="8201不可用"):
        item.acquire()
    assert item.handles == []
    lease(tmp_path, monkeypatch).acquire().release()


@pytest.fixture
def connection(monkeypatch):
    monkeypatch.setattr(ui, "ensure_device", Mock())
    item = Mock()
    item.acquire.return_value = item
    monkeypatch.setattr(ui, "AndroidSessionLease", Mock(return_value=item))
    driver = Mock()
    remote = Mock(return_value=driver)
    monkeypatch.setattr(webdriver, "Remote", remote)
    return item, driver, remote


def test_session_created_with_long_setup_timeout_then_bounded_requests(connection):
    item, driver, remote = connection
    observed = []

    def create(url, options, client_config):
        observed.append(client_config.timeout)
        return driver

    remote.side_effect = create
    client = ui.AndroidClient.connect(shared_settings(), "device", 8201)
    assert observed == [180]
    assert remote.call_args.kwargs["client_config"].timeout == 20
    capabilities = remote.call_args.kwargs["options"].to_capabilities()
    assert capabilities["appium:systemPort"] == 8201
    assert capabilities["appium:noReset"] is True
    assert capabilities["appium:autoLaunch"] is False
    assert capabilities["appium:settings[waitForIdleTimeout]"] == 0
    assert capabilities["appium:settings[waitForSelectorTimeout]"] == 0
    assert capabilities["appium:uiautomator2ServerReadTimeout"] == 15000
    assert capabilities["appium:disableWindowAnimation"] is True
    assert capabilities["appium:settings[enableTopmostWindowFromActivePackage]"] is False
    driver.update_settings.assert_called_once_with({
        "waitForIdleTimeout": 0, "waitForSelectorTimeout": 0,
        "enableTopmostWindowFromActivePackage": False})
    from selenium.webdriver.remote.remote_connection import RemoteConnection
    executor = RemoteConnection(client_config=remote.call_args.kwargs["client_config"])
    try:
        pool = executor._conn.connection_from_url("http://127.0.0.1:4723")
        assert pool.retries.total == 0
    finally:
        executor.close()
    item.release.assert_not_called()
    client.quit()
    client.quit()
    driver.quit.assert_called_once()
    item.release.assert_called_once()


@pytest.mark.parametrize("failure", [RuntimeError("connection failed"), KeyboardInterrupt()])
def test_create_failure_or_interrupt_releases_lease_without_retry(connection, failure):
    item, driver, remote = connection
    remote.side_effect = failure
    with pytest.raises(type(failure)):
        ui.AndroidClient.connect(shared_settings(), "device", 8201)
    remote.assert_called_once()
    item.release.assert_called_once()
    driver.quit.assert_not_called()


def test_initialization_failure_quits_created_session(connection):
    item, driver, remote = connection
    driver.implicitly_wait.side_effect = RuntimeError("initialization failed")
    with pytest.raises(RuntimeError, match="initialization failed"):
        ui.AndroidClient.connect(shared_settings(), "device", 8201)
    driver.quit.assert_called_once()
    item.release.assert_called_once()
    remote.assert_called_once()


@pytest.mark.parametrize("server_timeout", [True, 0, -1, 20000, 25000, "15000"])
def test_invalid_server_timeout_stops_before_creating_session(connection, server_timeout):
    item, driver, remote = connection
    settings = shared_settings()
    settings["device"]["uiautomator2_server_read_timeout"] = server_timeout
    with pytest.raises(ValueError, match="uiautomator2_server_read_timeout"):
        ui.AndroidClient.connect(settings, "device", 8201)
    item.acquire.assert_not_called()
    remote.assert_not_called()


def test_page_settings_failure_releases_lease_without_retry(connection):
    item, driver, remote = connection
    driver.update_settings.side_effect = RuntimeError("settings update failed")
    with pytest.raises(RuntimeError, match="settings update failed"):
        ui.AndroidClient.connect(shared_settings(), "device", 8201)
    remote.assert_called_once()
    driver.update_settings.assert_called_once()
    driver.quit.assert_called_once()
    item.release.assert_called_once()


def test_exit_failure_still_releases_own_lease():
    driver = Mock()
    item = Mock()
    driver.quit.side_effect = RuntimeError("delete failed")
    client = ui.AndroidClient(driver, lease=item)
    with pytest.raises(RuntimeError, match="delete failed"):
        client.quit()
    item.release.assert_called_once()
    client.quit()
    driver.quit.assert_called_once()


def test_cleanup_failure_does_not_hide_initialization_error(connection):
    item, driver, _ = connection
    driver.implicitly_wait.side_effect = RuntimeError("initialization failed")
    driver.quit.side_effect = RuntimeError("cleanup failed")
    with pytest.warns(RuntimeWarning, match="会话清理"):
        with pytest.raises(RuntimeError, match="initialization failed"):
            ui.AndroidClient.connect(shared_settings(), "device", 8201)
    item.release.assert_called_once()


def test_dual_device_interrupt_releases_first_session(monkeypatch):
    settings = shared_settings()
    settings["driver"]["udid"] = "driver-device"
    settings["driver"]["device_mode"] = "dual"
    monkeypatch.delenv("HK_DRIVER_ANDROID_UDID", raising=False)
    monkeypatch.delenv("HK_DRIVER_DEVICE_MODE", raising=False)
    monkeypatch.setattr(base, "shared_settings", lambda: settings)
    first = Mock()
    monkeypatch.setattr(ui.AndroidClient, "connect", Mock(side_effect=[first, KeyboardInterrupt()]))
    case = list(android_scenarios())[0]
    with pytest.raises(KeyboardInterrupt):
        case.setup_class()
    first.quit.assert_called_once()
    assert case.clients == {}
    assert case.client is None


def test_direct_case_runner_installs_and_restores_termination_handler(monkeypatch):
    previous = signal.getsignal(signal.SIGTERM)

    def run(*args, **kwargs):
        handler = signal.getsignal(signal.SIGTERM)
        assert handler is not previous
        handler(signal.SIGTERM, None)

    monkeypatch.setattr(runner.pytest, "main", run)
    result = runner.run_tests(["--case", "TestCharterAlipayAndroid", "--collect-only"])
    assert result == 128 + signal.SIGTERM
    assert signal.getsignal(signal.SIGTERM) is previous


def test_port_probe_reuses_time_wait_but_not_active_listener(tmp_path, monkeypatch):
    monkeypatch.setattr(session.subprocess, "run", Mock(return_value=SimpleNamespace(stdout="")))
    with session.socket.socket(session.socket.AF_INET, session.socket.SOCK_STREAM) as listener:
        listener.setsockopt(session.socket.SOL_SOCKET, session.socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        item = session.AndroidSessionLease("device", port, directory=tmp_path)
        with pytest.raises(RuntimeError, match="不可用"):
            item.acquire()
        assert item.handles == []
    item.acquire().release()


def test_port_probe_only_uses_reuseaddr_not_reuseport(tmp_path, monkeypatch):
    monkeypatch.setattr(session.subprocess, "run", Mock(return_value=SimpleNamespace(stdout="")))
    socket = MagicMock()
    monkeypatch.setattr(session.socket, "socket", socket)
    item = session.AndroidSessionLease("device", 8201, directory=tmp_path).acquire()
    socket.return_value.__enter__.return_value.setsockopt.assert_called_once_with(
        session.socket.SOL_SOCKET, session.socket.SO_REUSEADDR, 1)
    item.release()
