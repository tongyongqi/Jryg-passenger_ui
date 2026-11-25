import base64
import hashlib
import hmac
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

from ui_framework import JRYG_dingtalk_report as report
from runners import JRYG_run_main_ios as runner


@pytest.fixture
def summary_file(tmp_path):
    directory = tmp_path / "20261104_192305_986867"
    directory.mkdir()
    path = directory / "batch_result.json"
    rows = [{"case": name, "status": status, "order_no": "private-order-number",
             "reason": "secret-code private-webhook", "report": "/private/account/report.html"}
            for name, status in zip(report.CASE_LABELS, ["passed", "failed", "not_run", "not_run", "not_run", "not_run"])]
    path.write_text(json.dumps({"exit_code": 1, "cases": rows}), encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    for key in ("HK_IOS_DINGTALK_WEBHOOK", "HK_IOS_DINGTALK_SECRET", "HK_IOS_DINGTALK_ENABLED"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(report.subprocess, "run", Mock(side_effect=AssertionError("禁止访问真实钥匙串")))
    monkeypatch.setattr(report.requests, "Session", Mock(side_effect=AssertionError("禁止发送真实群消息")))


def test_payload_uses_current_summary_without_sensitive_fields(summary_file):
    payload = report.report_payload(summary_file)
    text = json.dumps(payload, ensure_ascii=False)
    assert "1通过、1失败、4未运行、0中断" in text
    assert "20261104_192305_986867" in text
    for secret in ("private-order-number", "secret-code", "private-webhook", "/private", "file://"):
        assert secret not in text
    assert payload["at"] == {"isAtAll": False}
    assert "勿直接重付" in text


def test_running_summary_not_reported_as_finished(summary_file):
    summary_file.write_text(json.dumps({"cases": [{"status": "running"}]}), encoding="utf-8")
    with pytest.raises(ValueError):
        report.report_payload(summary_file)


def test_credentials_loaded_from_keychain_without_print(monkeypatch, capsys):
    monkeypatch.setattr(report.sys, "platform", "darwin")
    saved = {"webhook": "https://oapi.dingtalk.com/robot/send?access_token=fake", "secret": "SECfake"}
    lookup = Mock(return_value=SimpleNamespace(returncode=0, stdout=json.dumps(saved)))
    monkeypatch.setattr(report.subprocess, "run", lookup)
    assert report.robot_credentials() == (saved["webhook"], saved["secret"])
    assert lookup.call_args.args[0][-1] == "-w"
    assert lookup.call_args.kwargs["timeout"] == 15
    assert capsys.readouterr().out == ""


def test_environment_overrides_keychain(monkeypatch):
    monkeypatch.setenv("HK_IOS_DINGTALK_WEBHOOK", "https://oapi.dingtalk.com/robot/send?access_token=fake")
    monkeypatch.setenv("HK_IOS_DINGTALK_SECRET", "SECfake")
    assert report.robot_credentials()[1] == "SECfake"
    report.subprocess.run.assert_not_called()


@pytest.mark.parametrize("url", ["http://oapi.dingtalk.com/robot/send?access_token=fake",
                                "https://evil.invalid/robot/send?access_token=fake",
                                "https://oapi.dingtalk.com/robot/send"])
def test_bad_webhook_cannot_send(monkeypatch, url):
    monkeypatch.setenv("HK_IOS_DINGTALK_WEBHOOK", url)
    monkeypatch.setenv("HK_IOS_DINGTALK_SECRET", "SECfake")
    with pytest.raises(ValueError):
        report.robot_credentials()
    report.requests.Session.assert_not_called()


def test_partial_environment_does_not_use_other_secret(monkeypatch):
    monkeypatch.setenv("HK_IOS_DINGTALK_SECRET", "SECfake")
    with pytest.raises(ValueError):
        report.robot_credentials()
    report.subprocess.run.assert_not_called()


@pytest.mark.parametrize("http,code,status", [(200, 0, "sent"), (200, 310000, "rejected"), (503, 0, "unconfirmed")])
def test_signed_post_once_no_redirect_or_retry(summary_file, monkeypatch, http, code, status):
    webhook = "https://oapi.dingtalk.com/robot/send?access_token=fake"
    secret = "SECfake"
    monkeypatch.setattr(report, "robot_credentials", Mock(return_value=(webhook, secret)))
    monkeypatch.setattr(report.time, "time", lambda: 123.456)
    session = Mock()
    session.post.return_value = Mock(status_code=http, json=Mock(return_value={"errcode": code}))
    context = Mock()
    context.__enter__ = Mock(return_value=session)
    context.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(report.requests, "Session", Mock(return_value=context))
    result = report.send_report(summary_file)
    assert result["status"] == status
    session.post.assert_called_once()
    params = session.post.call_args.kwargs["params"]
    expected = base64.b64encode(hmac.new(secret.encode(), b"123456\nSECfake", hashlib.sha256).digest()).decode()
    assert params == {"timestamp": "123456", "sign": expected}
    assert session.post.call_args.kwargs["allow_redirects"] is False
    assert session.post.call_args.kwargs["timeout"] == (5, 15)
    assert session.mount.call_args.args[1].max_retries.total == 0


@pytest.mark.parametrize("error", [requests.ReadTimeout("private-access-token"), ValueError("private-access-token"), KeyboardInterrupt()])
def test_notification_failure_redacted_and_never_retried(summary_file, monkeypatch, capsys, error):
    sender = Mock(side_effect=error)
    monkeypatch.setattr(report, "send_report", sender)
    assert report.notify_batch(summary_file)["status"] == "unconfirmed"
    sender.assert_called_once_with(summary_file)
    saved = summary_file.with_name("dingtalk_result.json").read_text()
    assert "private-access-token" not in saved + capsys.readouterr().out


def test_disabled_does_not_read_secret_or_send(summary_file, monkeypatch):
    monkeypatch.setenv("HK_IOS_DINGTALK_ENABLED", "0")
    assert report.notify_batch(summary_file) == {"status": "disabled"}
    report.subprocess.run.assert_not_called()
    report.requests.Session.assert_not_called()


@pytest.mark.parametrize("outcome,expected", [("success", 0), ("failed", 1), ("setup_failed", 2), ("interrupted", 130)])
def test_parent_batch_notifies_once_after_final_report(tmp_path, monkeypatch, outcome, expected):
    monkeypatch.setenv("HK_DRIVER_UI_STOP_AFTER", "submitted")
    monkeypatch.setattr(runner.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr("ui_framework.JRYG_device_guard.ensure_unlocked", Mock())

    observed = []

    def inspect_final_report(path):
        observed.append(json.loads(path.read_text()))
        return {"status": "sent"}

    notification = Mock(side_effect=inspect_final_report)
    monkeypatch.setattr(report, "notify_batch", notification)
    calls = []

    def run_case(case, args):
        calls.append(case)
        if outcome == "interrupted":
            raise KeyboardInterrupt
        if outcome != "success":
            return expected
        result_path = Path(next(arg.split("=", 1)[1] for arg in args if arg.startswith("--batch-result=")))
        result_path.write_text(json.dumps({"exit_code": 0, "completed_orders": [{"order_no": "test-order-" + str(len(calls))}]}))
        return 0

    assert runner.run_batch(list(report.CASE_LABELS), [], run_case=run_case, report_dir=tmp_path) == expected
    notification.assert_called_once_with(next(tmp_path.glob("batches/*/batch_result.json")))
    assert len(calls) == (1 if outcome == "interrupted" else 6)
    result = json.loads(next(tmp_path.glob("batches/*/batch_result.json")).read_text())
    assert observed == [result]
    assert result["exit_code"] == expected
    assert all(row["status"] != "running" for row in result["cases"])


@pytest.mark.parametrize("failure", [RuntimeError("private-url"), KeyboardInterrupt()])
def test_notification_exception_never_retries_or_changes_exit_code(tmp_path, monkeypatch, capsys, failure):
    monkeypatch.setenv("HK_DRIVER_UI_STOP_AFTER", "submitted")
    monkeypatch.setattr(runner.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr("ui_framework.JRYG_device_guard.ensure_unlocked", Mock())
    notification = Mock(side_effect=failure)
    monkeypatch.setattr(report, "notify_batch", notification)
    assert runner.run_batch(list(report.CASE_LABELS), [], run_case=lambda *_args: 1, report_dir=tmp_path) == 1
    notification.assert_called_once()
    assert "private-url" not in capsys.readouterr().out


def test_parent_batch_explicitly_disabled_never_sends(tmp_path, monkeypatch):
    monkeypatch.setenv("HK_IOS_DINGTALK_ENABLED", "0")
    sender = Mock(side_effect=AssertionError("禁止发送真实群消息"))
    monkeypatch.setattr(report, "send_report", sender)
    assert runner.run_batch(["case.py"], [], run_case=lambda *_args: 1, report_dir=tmp_path) == 1
    sender.assert_not_called()
    report.subprocess.run.assert_not_called()
    saved = next(tmp_path.glob("batches/*/dingtalk_result.json"))
    assert json.loads(saved.read_text()) == {"status": "disabled"}


def test_interruption_between_cases_reported_as_interrupted(summary_file):
    summary = json.loads(summary_file.read_text())
    summary["exit_code"] = 130
    summary["cases"][1]["status"] = "not_run"
    summary_file.write_text(json.dumps(summary), encoding="utf-8")
    text = report.report_payload(summary_file)["markdown"]["text"]
    assert "批次结果：已中断" in text
    assert "勿直接重付" in text


def test_other_platform_does_not_notify_hk_ios_group(tmp_path, monkeypatch):
    monkeypatch.setenv("HK_DRIVER_UI_STOP_AFTER", "submitted")
    notification = Mock()
    monkeypatch.setattr(report, "notify_batch", notification)
    assert runner.run_batch(["case.py"], [], run_case=lambda *_args: 1, report_dir=tmp_path, platform="android") == 1
    notification.assert_not_called()


def test_default_batch_order_is_charter_online_then_cash(monkeypatch):
    monkeypatch.setattr(runner, "init_all_dirs", Mock())
    pytest_main = Mock(return_value=0)
    monkeypatch.setattr(runner.pytest, "main", pytest_main)
    monkeypatch.setattr(runner, "run_batch", Mock(side_effect=AssertionError("禁止真实批次")))
    assert runner.run_tests(["--batch", "--collect-only"]) == 0
    cases = [path for path in pytest_main.call_args.args[0] if path.endswith("_order.py")]
    assert [Path(path).name for path in cases] == [
        "JRYG_test_ios_charter_alipay_order.py",
        "JRYG_test_ios_charter_bankcard_order.py",
        "JRYG_test_ios_meter_epayment_alipay_order.py",
        "JRYG_test_ios_meter_alipay_order.py",
        "JRYG_test_ios_meter_epayment_bankcard_order.py",
        "JRYG_test_ios_meter_cash_order.py",
    ]
    assert len(cases) == len(set(cases)) == 6
    runner.run_batch.assert_not_called()


def test_batch_order_handles_subsets_without_rotating_positions():
    cases = ["cases/JRYG_test_ios_meter_cash_order.py", "cases/JRYG_test_ios_charter_bankcard_order.py",
             "cases/JRYG_test_ios_meter_epayment_alipay_order.py"]
    assert runner.batch_order(cases) == [cases[1], cases[2], cases[0]]


def test_collect_only_never_sends_or_launches_batch(monkeypatch):
    monkeypatch.setattr(runner, "init_all_dirs", Mock())
    monkeypatch.setattr(runner.pytest, "main", Mock(return_value=0))
    monkeypatch.setattr(runner, "run_batch", Mock())
    notification = Mock()
    monkeypatch.setattr(report, "notify_batch", notification)
    assert runner.run_tests(["--batch", "--collect-only"]) == 0
    runner.run_batch.assert_not_called()
    notification.assert_not_called()


@pytest.fixture
def batch_offline(monkeypatch):
    monkeypatch.setenv("HK_DRIVER_UI_STOP_AFTER", "submitted")
    sleep = Mock()
    monkeypatch.setattr(runner.time, "sleep", sleep)
    monkeypatch.setattr("ui_framework.JRYG_device_guard.ensure_unlocked", Mock())
    return sleep


@pytest.mark.parametrize("failure,expected_code,expected_reason", [
    ("failed", 1, "TimeoutError"), ("setup_failed", 2, "result_missing"),
    ("missing", 1, "result_missing"), ("broken", 1, "result_invalid"),
    ("shape", 1, "result_invalid"), ("missing_order", 1, "missing_order"),
    ("empty_order", 1, "missing_order"), ("exception", 1, "runner_error"),
    ("skipped", 1, "skipped"), ("teardown", 1, "RuntimeError"),
    ("result_failed", 2, "child_failed"),
])
def test_batch_failure_records_reason_and_runs_next_case(tmp_path, batch_offline, capsys, failure, expected_code, expected_reason):
    calls = []

    def run_case(case, args):
        calls.append(case)
        path = Path(next(arg.split("=", 1)[1] for arg in args if arg.startswith("--batch-result=")))
        result = {"exit_code": 0, "completed_orders": [{"order_no": "test-order-" + str(len(calls))}]}
        code = 0
        if len(calls) == 1:
            if failure == "exception":
                raise RuntimeError("private-token")
            if failure in ("missing", "setup_failed"):
                return 2 if failure == "setup_failed" else 0
            if failure == "broken":
                path.write_text("private-token invalid-json")
                return 0
            if failure == "shape":
                path.write_text("[]")
                return 0
            if failure == "missing_order":
                result["completed_orders"] = []
            elif failure == "empty_order":
                result["completed_orders"] = [{"order_no": ""}]
            elif failure == "result_failed":
                result["exit_code"] = 2
            else:
                phase = "teardown" if failure == "teardown" else "call"
                reason_code = {"failed": "TimeoutError", "skipped": "skipped", "teardown": "RuntimeError"}[failure]
                result["failures"] = [{"phase": phase, "error_type": "TimeoutError", "reason_code": reason_code,
                                       "driver_phase": "destination", "reason": "private-token"}]
                result["exit_code"] = code = 0 if failure == "skipped" else 1
                result["reason"] = "private-token"
        path.write_text(json.dumps(result), encoding="utf-8")
        return code

    assert runner.run_batch(["first.py", "second.py"], [], run_case=run_case, report_dir=tmp_path) == expected_code
    assert calls == ["first.py", "second.py"]
    saved = next(tmp_path.glob("batches/*/batch_result.json")).read_text()
    result = json.loads(saved)
    first, second = result["cases"]
    assert first["status"] == "failed"
    assert first["exit_code"] == expected_code
    assert first["reason_code"] == expected_reason
    assert first["reason"]
    assert first["finished_at"]
    assert second["status"] == "passed"
    assert second["exit_code"] == 0
    batch_offline.assert_called_once_with(10)
    assert "private-token" not in saved + capsys.readouterr().out


def test_batch_preserves_individual_exit_codes_and_first_failure(tmp_path, batch_offline):
    codes = iter([2, 1, 3])
    assert runner.run_batch(["a.py", "b.py", "c.py"], [], run_case=lambda *_args: next(codes), report_dir=tmp_path) == 2
    result = json.loads(next(tmp_path.glob("batches/*/batch_result.json")).read_text())
    assert [row["exit_code"] for row in result["cases"]] == [2, 1, 3]
    assert all(row["status"] == "failed" and row["reason"] for row in result["cases"])
    assert [call.args[0] for call in batch_offline.call_args_list] == [10, 10]


def test_batch_interval_never_wakes_phone_after_wda_cleanup(tmp_path, batch_offline, monkeypatch, capsys):
    client = Mock(side_effect=AssertionError("WDA has been cleaned up"))
    monkeypatch.setattr("ui_framework.JRYG_device_guard.wda.Client", client)
    assert runner.run_batch(["a.py", "b.py"], [], run_case=lambda *_args: 1, report_dir=tmp_path) == 1
    client.assert_not_called()
    batch_offline.assert_called_once_with(10)
    assert "WDA就绪后自动唤醒" in capsys.readouterr().out


def test_batch_duplicate_order_fails_only_current_case(tmp_path, batch_offline):
    orders = iter(["same-order", "same-order", "new-order"])
    calls = []

    def run_case(case, args):
        calls.append(case)
        path = Path(next(arg.split("=", 1)[1] for arg in args if arg.startswith("--batch-result=")))
        path.write_text(json.dumps({"exit_code": 0, "completed_orders": [{"order_no": next(orders)}]}))
        return 0

    assert runner.run_batch(["a.py", "b.py", "c.py"], [], run_case=run_case, report_dir=tmp_path) == 1
    rows = json.loads(next(tmp_path.glob("batches/*/batch_result.json")).read_text())["cases"]
    assert [row["status"] for row in rows] == ["passed", "failed", "passed"]
    assert rows[1]["reason_code"] == "duplicate_order"
    assert len(calls) == 3


@pytest.mark.parametrize("interruption,expected", [(KeyboardInterrupt(), 130), (130, 130), (143, 143), (-15, 143)])
def test_batch_interruption_keeps_prior_failure_and_stops_next(tmp_path, batch_offline, interruption, expected):
    calls = []

    def run_case(case, args):
        calls.append(case)
        if len(calls) == 1:
            return 2
        if isinstance(interruption, BaseException):
            raise interruption
        return interruption

    assert runner.run_batch(["a.py", "b.py", "c.py"], [], run_case=run_case, report_dir=tmp_path) == expected
    rows = json.loads(next(tmp_path.glob("batches/*/batch_result.json")).read_text())["cases"]
    assert calls == ["a.py", "b.py"]
    assert [row["status"] for row in rows] == ["failed", "interrupted", "not_run"]
    assert rows[0]["exit_code"] == 2
    assert rows[1]["exit_code"] == expected
    assert rows[1]["reason_code"] == "interrupted"
    batch_offline.assert_called_once_with(10)


def test_batch_interruption_during_interval_keeps_finished_case(tmp_path, batch_offline):
    batch_offline.side_effect = KeyboardInterrupt
    calls = []

    def run_case(case, args):
        calls.append(case)
        path = Path(next(arg.split("=", 1)[1] for arg in args if arg.startswith("--batch-result=")))
        path.write_text(json.dumps({"exit_code": 0, "completed_orders": [{"order_no": "test-order"}]}))
        return 0

    assert runner.run_batch(["a.py", "b.py"], [], run_case=run_case, report_dir=tmp_path) == 130
    rows = json.loads(next(tmp_path.glob("batches/*/batch_result.json")).read_text())["cases"]
    assert calls == ["a.py"]
    assert [row["status"] for row in rows] == ["passed", "not_run"]
    assert rows[0]["exit_code"] == 0


@pytest.mark.parametrize("phase", ["setup", "call", "teardown"])
def test_gate_failure_report_records_safe_phase_not_exception_text(phase):
    gate = runner.CompletedOrderGate()
    item = SimpleNamespace(instance=SimpleNamespace(driver_ui=SimpleNamespace(last_phase="destination")))
    call = SimpleNamespace(excinfo=SimpleNamespace(typename="TimeoutError", value="private-token"))
    report_outcome = Mock(get_result=Mock(return_value=SimpleNamespace(when=phase, failed=True, skipped=False)))
    hook = gate.pytest_runtest_makereport(item, call)
    next(hook)
    with pytest.raises(StopIteration):
        hook.send(report_outcome)
    assert gate.failures[0]["phase"] == phase
    assert gate.failures[0]["driver_phase"] == "destination"
    assert gate.failures[0]["reason_code"] == "TimeoutError"
    assert "private-token" not in json.dumps(gate.failures)


@pytest.mark.parametrize("invalid", ["missing", "unpaid", "different", "old", "awaiting"])
def test_gate_rejects_missing_or_wrong_completed_order(invalid):
    gate = runner.CompletedOrderGate()
    driver = SimpleNamespace(last_phase="complete", order_no="test-order", awaiting_new_order=False, completed_before_run=set())
    instance = SimpleNamespace(driver_ui=driver, completed_order_no="test-order")
    if invalid == "missing":
        instance.completed_order_no = None
    elif invalid == "unpaid":
        driver.last_phase = "unpaid"
    elif invalid == "different":
        driver.order_no = "other-order"
    elif invalid == "old":
        driver.completed_before_run.add("test-order")
    else:
        driver.awaiting_new_order = True
    outcome = Mock(excinfo=None)
    hook = gate.pytest_runtest_call(SimpleNamespace(instance=instance, nodeid="test_order"))
    next(hook)
    with pytest.raises(StopIteration):
        hook.send(outcome)
    outcome.force_exception.assert_called_once()
    assert gate.completed_orders == []
    assert gate.failures[0]["reason_code"] == "completion_gate"
    assert instance.batch_new_order_only


@pytest.mark.parametrize("broken_failures", [[None], ["private-token"], [{}], [{"phase": [], "error_type": "Exception", "reason_code": "child_failed"}]])
def test_batch_corrupt_failure_details_cannot_pass(tmp_path, batch_offline, broken_failures):
    calls = []

    def run_case(case, args):
        calls.append(case)
        path = Path(next(arg.split("=", 1)[1] for arg in args if arg.startswith("--batch-result=")))
        path.write_text(json.dumps({"exit_code": 0, "completed_orders": [{"order_no": "order-" + str(len(calls))}],
                                    "failures": broken_failures if len(calls) == 1 else []}))
        return 0

    assert runner.run_batch(["a.py", "b.py"], [], run_case=run_case, report_dir=tmp_path) == 1
    rows = json.loads(next(tmp_path.glob("batches/*/batch_result.json")).read_text())["cases"]
    assert [row["status"] for row in rows] == ["failed", "passed"]
    assert rows[0]["reason_code"] == "result_invalid"


@pytest.mark.parametrize("actual_interrupt,expected", [(True, 130), (False, 2)])
def test_pytest_user_interrupt_distinct_from_collection_exit_two(tmp_path, monkeypatch, actual_interrupt, expected):
    from _pytest.main import Interrupted

    monkeypatch.setattr(runner, "init_all_dirs", Mock())
    result_file = tmp_path / "result.json"

    def main(args, plugins):
        gate = plugins[0]
        if not actual_interrupt:
            gate.pytest_collectreport(SimpleNamespace(failed=True))
        gate.pytest_keyboard_interrupt(SimpleNamespace(type=KeyboardInterrupt if actual_interrupt else Interrupted))
        return 2

    monkeypatch.setattr(runner.pytest, "main", main)
    assert runner.run_tests(["--case=cases/JRYG_test_ios_meter_cash_order.py", "--no-api-catalog",
                             f"--batch-result={result_file}", f"--report-file={tmp_path / 'report.html'}"]) == expected
    result = json.loads(result_file.read_text())
    assert result["exit_code"] == expected
    assert result["failures"][0]["reason_code"] == ("interrupted" if actual_interrupt else "collection")


def test_single_case_result_writer_keeps_safe_failure_details(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "init_all_dirs", Mock())
    result_file = tmp_path / "result.json"

    def main(args, plugins):
        gate = plugins[0]
        gate.failures.append(runner.failure_detail("setup", "DeviceUnlockError"))
        return 1

    monkeypatch.setattr(runner.pytest, "main", main)
    assert runner.run_tests(["--case=cases/JRYG_test_ios_meter_cash_order.py", "--no-api-catalog",
                             f"--batch-result={result_file}", f"--report-file={tmp_path / 'report.html'}"]) == 1
    result = json.loads(result_file.read_text())
    assert result["failures"][0]["reason_code"] == "DeviceUnlockError"
    assert result["reason"] == "准备阶段：设备解锁失败"
    assert result["retry_safe"] is False


def save_retryable_failure(args, **updates):
    path = Path(next(arg.split("=", 1)[1] for arg in args if arg.startswith("--batch-result=")))
    result = {"exit_code": 1, "completed_orders": [], "retry_safe": True,
              "failures": [runner.failure_detail("call", "RuntimeError", driver_phase="online")]}
    result.update(updates)
    path.write_text(json.dumps(result), encoding="utf-8")
    return path


@pytest.mark.parametrize("retry_passes", [True, False])
def test_safe_failure_waits_five_seconds_retries_once_then_next_case(tmp_path, batch_offline, retry_passes):
    calls = []
    paths = []

    def run_case(case, args):
        calls.append((case, args))
        if len(calls) == 2:
            batch_offline.assert_called_once_with(5)
            assert "--retry-reopen-app" in args
        else:
            assert "--retry-reopen-app" not in args
        path = save_retryable_failure(args)
        paths.append(path)
        if case == "next.py" or (len(calls) == 2 and retry_passes):
            path.write_text(json.dumps({"exit_code": 0, "completed_orders": [{"order_no": "order-" + str(len(calls))}],
                                        "failures": [], "retry_safe": False}))
            return 0
        return 1

    expected = 0 if retry_passes else 1
    assert runner.run_batch(["current.py", "next.py"], [], run_case=run_case, report_dir=tmp_path) == expected
    assert [case for case, _args in calls] == ["current.py", "current.py", "next.py"]
    result = json.loads(next(tmp_path.glob("batches/*/batch_result.json")).read_text())
    current, following = result["cases"]
    assert current["retry_count"] == 1
    assert current["exit_code"] == expected
    assert [attempt["status"] for attempt in current["attempts"]] == ["failed", "passed" if retry_passes else "failed"]
    assert current["attempts"][0]["reason"]
    assert current["result"] == str(paths[1])
    assert "_retry1_" in current["report"]
    assert len(set(paths)) == 3
    assert all(path.exists() for path in paths)
    assert following["status"] == "passed"
    assert [call.args[0] for call in batch_offline.call_args_list] == [5, 10]
    assert result["max_retries"] == 1
    assert result["retry_delay_seconds"] == 5


@pytest.mark.parametrize("blocked", ["unsafe", "missing_safe", "string_safe", "completed", "active_driver", "missing_phase",
                                      "teardown", "skipped", "collection", "completion_gate", "process_mismatch"])
def test_unsafe_or_unproven_failures_are_not_retried(tmp_path, batch_offline, blocked):
    calls = []

    def run_case(case, args):
        calls.append(case)
        path = save_retryable_failure(args)
        result = json.loads(path.read_text())
        if blocked == "unsafe":
            result["retry_safe"] = False
        elif blocked == "missing_safe":
            del result["retry_safe"]
        elif blocked == "string_safe":
            result["retry_safe"] = "true"
        elif blocked == "completed":
            result["completed_orders"] = [{"order_no": "already-paid"}]
        elif blocked == "active_driver":
            result["failures"][0]["driver_phase"] = "destination"
        elif blocked == "missing_phase":
            del result["failures"][0]["driver_phase"]
        elif blocked == "teardown":
            result["failures"].append(runner.failure_detail("teardown", "RuntimeError", driver_phase="online"))
        elif blocked in ("skipped", "collection", "completion_gate"):
            result["failures"][0]["reason_code"] = blocked
        path.write_text(json.dumps(result))
        return 2 if blocked == "process_mismatch" else 1

    assert runner.run_batch(["current.py"], [], run_case=run_case, report_dir=tmp_path) != 0
    assert calls == ["current.py"]
    batch_offline.assert_not_called()
    row = json.loads(next(tmp_path.glob("batches/*/batch_result.json")).read_text())["cases"][0]
    assert row["retry_count"] == 0
    assert row["retry_safe"] is False
    assert row["retry_note"]


@pytest.mark.parametrize("during_retry", [False, True])
def test_interruption_during_retry_wait_or_attempt_stops_batch(tmp_path, batch_offline, during_retry):
    if not during_retry:
        batch_offline.side_effect = KeyboardInterrupt
    calls = []

    def run_case(case, args):
        calls.append(case)
        if len(calls) == 2:
            raise KeyboardInterrupt
        save_retryable_failure(args)
        return 1

    assert runner.run_batch(["current.py", "next.py"], [], run_case=run_case, report_dir=tmp_path) == 130
    rows = json.loads(next(tmp_path.glob("batches/*/batch_result.json")).read_text())["cases"]
    assert len(calls) == (2 if during_retry else 1)
    assert [row["status"] for row in rows] == ["interrupted", "not_run"]
    assert rows[0]["attempts"][0]["status"] == "failed"
    assert rows[0]["attempts"][0]["exit_code"] == 1
    assert all(attempt["status"] != "running" for attempt in rows[0]["attempts"])
    if during_retry:
        assert rows[0]["attempts"][1]["status"] == "interrupted"
    batch_offline.assert_called_once_with(5)


def test_retry_uses_independent_api_reports_and_keeps_capture_flags(tmp_path, batch_offline, monkeypatch):
    merge = Mock(return_value=tmp_path / "接口清单.txt")
    monkeypatch.setattr("ui_framework.JRYG_api_catalog.merge_catalogs", merge)
    api_paths = []
    count = 0

    def run_case(case, args):
        nonlocal count
        count += 1
        api_paths.append(next(arg.split("=", 1)[1] for arg in args if arg.startswith("--api-output=")))
        assert "--api-namespace=test" in args
        path = save_retryable_failure(args)
        if count == 2:
            path.write_text(json.dumps({"exit_code": 0, "completed_orders": [{"order_no": "order-paid"}]}))
            return 0
        return 1

    assert runner.run_batch(["case.py"], [], run_case=run_case, report_dir=tmp_path,
                             api_config={"enabled": True, "namespace": "test"}) == 0
    assert len(set(api_paths)) == 2
    assert Path(api_paths[0]).name == "01_api"
    assert Path(api_paths[1]).name == "01_retry1_api"
    merge.assert_called_once()


@pytest.mark.parametrize("safe", [False, True])
def test_gate_retry_safety_and_reopen_flag_propagation(safe):
    gate = runner.CompletedOrderGate(retry_reopen_app=True)
    instance = SimpleNamespace(retry_safe=safe, completed_order_no=None, resuming_order=False,
                               driver_ui=SimpleNamespace(last_phase="online", awaiting_new_order=True))
    item = SimpleNamespace(instance=instance)
    hook = gate.pytest_runtest_call(item)
    next(hook)
    assert instance.batch_retry is True
    assert instance.batch_new_order_only is True
    with pytest.raises(StopIteration):
        hook.send(Mock(excinfo=(RuntimeError, RuntimeError("private-token"), None)))
    hook = gate.pytest_runtest_makereport(item, SimpleNamespace(excinfo=SimpleNamespace(typename="RuntimeError")))
    next(hook)
    with pytest.raises(StopIteration):
        hook.send(Mock(get_result=Mock(return_value=SimpleNamespace(when="call", failed=True, skipped=False))))
    assert gate.retry_safe is safe


def test_retry_flag_is_consumed_by_runner_and_safe_evidence_saved(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "init_all_dirs", Mock())
    result_file = tmp_path / "result.json"

    def main(args, plugins):
        assert "--retry-reopen-app" not in args
        gate = plugins[0]
        assert gate.retry_reopen_app
        gate.retry_safe = True
        gate.failures.append(runner.failure_detail("call", "RuntimeError", driver_phase="online"))
        return 1

    monkeypatch.setattr(runner.pytest, "main", main)
    assert runner.run_tests(["--case=cases/JRYG_test_ios_meter_cash_order.py", "--no-api-catalog", "--retry-reopen-app",
                             f"--batch-result={result_file}", f"--report-file={tmp_path / 'report.html'}"]) == 1
    assert json.loads(result_file.read_text())["retry_safe"] is True
