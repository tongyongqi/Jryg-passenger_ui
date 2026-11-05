from contextlib import nullcontext
from datetime import datetime
import fcntl
import json
from pathlib import Path
import plistlib
import signal
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from runners import JRYG_run_scheduled_ios as scheduled


@pytest.fixture(autouse=True)
def no_real_execution(monkeypatch):
    monkeypatch.setattr(scheduled.subprocess, "Popen", Mock(side_effect=AssertionError("禁止真实任务启动")))
    monkeypatch.setattr(scheduled.subprocess, "run", Mock(side_effect=AssertionError("禁止改变Mac电源状态")))


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    python = tmp_path / "python"
    python.write_text("test-only")
    python.chmod(0o700)
    entry = tmp_path / "entry.py"
    entry.write_text("test-only")
    monkeypatch.setattr(scheduled, "PYTHON", python)
    monkeypatch.setattr(scheduled, "ENTRY", entry)
    monkeypatch.setattr(scheduled, "REPORT_DIR", tmp_path / "report")
    clock = SimpleNamespace(now=datetime(2026, 11, 5, 10, 45))

    class TestClock:
        @staticmethod
        def now():
            return clock.now

    monkeypatch.setattr(scheduled, "datetime", TestClock)
    monkeypatch.setattr(scheduled, "mac_state", Mock(return_value={
        "logged_in": True, "locked": True, "ac_power": True,
    }))
    monkeypatch.setattr(scheduled, "awake_for_run", Mock(side_effect=lambda: nullcontext()))
    monkeypatch.setattr(scheduled, "execute_batch", Mock(return_value=0))
    return clock


@pytest.mark.parametrize("hour,minute,second,expected", [
    (10, 44, 59, False), (10, 45, 0, True), (10, 54, 59, True),
    (10, 55, 0, False), (12, 0, 0, False), (0, 0, 0, False),
    (10, 40, 0, False), (7, 0, 0, False),
])
def test_schedule_window_no_late_payments(hour, minute, second, expected):
    assert scheduled.in_schedule_window(datetime(2026, 11, 5, hour, minute, second)) is expected


@pytest.mark.parametrize("locked", [True, False, None])
def test_locked_mac_continues_without_unlocking(sandbox, locked):
    scheduled.mac_state.return_value["locked"] = locked
    assert scheduled.run_scheduled() == 0
    scheduled.execute_batch.assert_called_once()
    saved = json.loads((scheduled.REPORT_DIR / "ios_schedule_result.json").read_text())
    assert saved["status"] == "completed"
    assert saved["mac_locked"] is locked
    scheduled.awake_for_run.assert_called_once()


@pytest.mark.parametrize("field", ["logged_in", "ac_power"])
def test_not_logged_in_or_battery_blocks_business(sandbox, field):
    scheduled.mac_state.return_value[field] = False
    assert scheduled.run_scheduled() == 2
    scheduled.execute_batch.assert_not_called()
    scheduled.awake_for_run.assert_not_called()
    assert not (scheduled.REPORT_DIR / "ios_schedule_result.json").exists()


def test_afternoon_wake_does_not_make_up_orders(sandbox):
    sandbox.now = datetime(2026, 11, 5, 15, 0)
    assert scheduled.run_scheduled() == 0
    scheduled.mac_state.assert_not_called()
    scheduled.execute_batch.assert_not_called()
    assert not scheduled.REPORT_DIR.exists()


def test_prepare_past_window_does_not_start(sandbox):
    def prepare():
        sandbox.now = datetime(2026, 11, 5, 10, 55)
        return nullcontext()

    scheduled.awake_for_run.side_effect = prepare
    assert scheduled.run_scheduled() == 0
    scheduled.execute_batch.assert_not_called()
    assert not (scheduled.REPORT_DIR / "ios_schedule_result.json").exists()


@pytest.mark.parametrize("field", ["logged_in", "ac_power"])
def test_session_or_power_changed_during_wake_blocks_business(sandbox, field):
    initial = {"logged_in": True, "locked": True, "ac_power": True}
    changed = {**initial, field: False}
    scheduled.mac_state.side_effect = [initial, changed]
    assert scheduled.run_scheduled() == 2
    scheduled.execute_batch.assert_not_called()
    assert not (scheduled.REPORT_DIR / "ios_schedule_result.json").exists()


@pytest.mark.parametrize("code", [0, 1, 2, 130, 143])
def test_one_attempt_per_day_even_after_failure(sandbox, code):
    scheduled.execute_batch.return_value = code
    assert scheduled.run_scheduled() == code
    assert scheduled.run_scheduled() == 0
    scheduled.execute_batch.assert_called_once()
    record = json.loads((scheduled.REPORT_DIR / "ios_schedule_result.json").read_text())
    assert record["exit_code"] == code
    assert record["status"] == ("completed" if code == 0 else "failed")


def test_marker_saved_before_any_real_order(sandbox):
    def execute():
        record = json.loads((scheduled.REPORT_DIR / "ios_schedule_result.json").read_text())
        assert record["status"] == "started"
        assert record["date"] == "2026-11-05"
        return 1

    scheduled.execute_batch.side_effect = execute
    assert scheduled.run_scheduled() == 1


def test_crashed_previous_batch_not_repeated(sandbox):
    scheduled.REPORT_DIR.mkdir()
    (scheduled.REPORT_DIR / "ios_schedule_result.json").write_text(
        json.dumps({"date": "2026-11-05", "status": "started"}))
    assert scheduled.run_scheduled() == 0
    scheduled.execute_batch.assert_not_called()


def test_following_day_runs_new_batch_once(sandbox):
    assert scheduled.run_scheduled() == 0
    sandbox.now = datetime(2026, 11, 6, 10, 45)
    assert scheduled.run_scheduled() == 0
    assert scheduled.execute_batch.call_count == 2


def test_simultaneous_schedule_refused(sandbox):
    scheduled.REPORT_DIR.mkdir()
    with (scheduled.REPORT_DIR / ".ios-scheduled.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert scheduled.run_scheduled() == 0
    scheduled.execute_batch.assert_not_called()


def test_start_exception_keeps_attempt_marker(sandbox):
    scheduled.execute_batch.side_effect = OSError("private-error-detail")
    assert scheduled.run_scheduled() == 2
    assert scheduled.run_scheduled() == 0
    scheduled.execute_batch.assert_called_once()


def test_missing_interpreter_no_orders(sandbox):
    scheduled.PYTHON.unlink()
    assert scheduled.run_scheduled() == 2
    scheduled.execute_batch.assert_not_called()


def test_default_cli_only_reads_mac_state(sandbox, monkeypatch):
    monkeypatch.setattr(scheduled.sys, "platform", "darwin")
    monkeypatch.setattr(scheduled.os, "getuid", lambda: 501)
    assert scheduled.main([]) == 0
    scheduled.execute_batch.assert_not_called()
    scheduled.awake_for_run.assert_not_called()
    assert not scheduled.REPORT_DIR.exists()


def test_corrupt_attempt_record_does_not_erase_or_run(sandbox, monkeypatch):
    monkeypatch.setattr(scheduled.sys, "platform", "darwin")
    monkeypatch.setattr(scheduled.os, "getuid", lambda: 501)
    scheduled.REPORT_DIR.mkdir()
    state = scheduled.REPORT_DIR / "ios_schedule_result.json"
    state.write_text("broken")
    assert scheduled.main(["--run"]) == 2
    scheduled.execute_batch.assert_not_called()
    assert state.read_text() == "broken"


@pytest.mark.parametrize("array,locked,login,console_uid", [
    (False, True, True, 501), (True, False, True, 501),
    (False, True, False, 501), (False, True, True, 502),
])
def test_mac_system_fields_match_actual_contract(monkeypatch, array, locked, login, console_uid):
    payload = {"IOConsoleLocked": locked, "IOConsoleUsers": [{
        "kCGSSessionUserIDKey": 501, "kCGSSessionOnConsoleKey": True,
        "kCGSessionLoginDoneKey": login,
    }]}
    monkeypatch.setattr(scheduled.os, "getuid", lambda: 501)
    monkeypatch.setattr(scheduled, "Path", lambda _path: SimpleNamespace(stat=lambda: SimpleNamespace(st_uid=console_uid)))
    monkeypatch.setattr(scheduled.subprocess, "run", Mock(side_effect=[
        SimpleNamespace(stdout=plistlib.dumps([payload] if array else payload)),
        SimpleNamespace(stdout="Now drawing from 'AC Power'"),
    ]))
    result = scheduled.mac_state()
    assert result == {"locked": locked, "logged_in": login and console_uid == 501, "ac_power": True}


def test_hold_awake_released_after_batch_failure(monkeypatch):
    hold = Mock()
    hold.poll.return_value = None
    monkeypatch.setattr(scheduled.subprocess, "Popen", Mock(return_value=hold))
    pulse = Mock()
    monkeypatch.setattr(scheduled.subprocess, "run", pulse)
    with pytest.raises(ValueError):
        with scheduled.awake_for_run():
            raise ValueError("test failure")
    assert scheduled.subprocess.Popen.call_args.args[0][1:4] == ["-i", "-s", "-w"]
    pulse.assert_called_once_with(["/usr/bin/caffeinate", "-u", "-t", "5"], check=True, timeout=8)
    hold.terminate.assert_called_once()
    hold.wait.assert_called_once_with(timeout=5)


def test_caffeinate_failure_blocks_task_body(monkeypatch):
    hold = Mock()
    hold.poll.return_value = 1
    monkeypatch.setattr(scheduled.subprocess, "Popen", Mock(return_value=hold))
    monkeypatch.setattr(scheduled.subprocess, "run", Mock())
    body = Mock()
    with pytest.raises(RuntimeError):
        with scheduled.awake_for_run():
            body()
    body.assert_not_called()
    hold.wait.assert_called_once()


def test_signal_forwarded_to_existing_batch_no_restart(monkeypatch):
    child = Mock(pid=9999)
    child.poll.return_value = None
    handlers = {}

    def set_signal(sig, handler):
        handlers[sig] = handler
        return "previous"

    def wait():
        handlers[signal.SIGTERM](signal.SIGTERM, None)
        child.poll.return_value = 143
        return 143

    child.wait.side_effect = wait
    monkeypatch.setattr(scheduled.subprocess, "Popen", Mock(return_value=child))
    monkeypatch.setattr(scheduled.signal, "signal", set_signal)
    monkeypatch.setattr(scheduled.os, "killpg", Mock())
    assert scheduled.execute_batch() == 143
    scheduled.os.killpg.assert_called_once_with(9999, signal.SIGTERM)
    scheduled.subprocess.Popen.assert_called_once()
    command = scheduled.subprocess.Popen.call_args.args[0]
    assert command == [str(scheduled.PYTHON), str(scheduled.ENTRY)]
    assert handlers[signal.SIGTERM] == "previous"


def test_launchd_manifest_no_immediate_run_or_failure_restart():
    path = Path(scheduled.__file__).with_name("com.jryg.hk-ios.daily.plist")
    job = plistlib.loads(path.read_bytes())
    assert job["Label"] == scheduled.LABEL
    assert job["StartCalendarInterval"] == {"Hour": 10, "Minute": 45}
    assert job["RunAtLoad"] is False
    assert job["KeepAlive"] is False
    assert job["LimitLoadToSessionType"] == "Aqua"
    assert job["ProgramArguments"] == [str(scheduled.PYTHON), str(Path(scheduled.__file__)), "--run"]
    assert job["StandardOutPath"] == str(scheduled.LOG_DIR / "daily.log")
