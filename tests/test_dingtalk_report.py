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
    sent = []

    def notify(path):
        result = json.loads(path.read_text(encoding="utf-8"))
        assert result["exit_code"] == expected
        assert all(row["status"] != "running" for row in result["cases"])
        sent.append(path)

    monkeypatch.setattr(report, "notify_batch", notify)
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
    assert len(sent) == 1
    assert len(calls) == (6 if outcome == "success" else 1)


@pytest.mark.parametrize("failure", [RuntimeError("private-url"), KeyboardInterrupt()])
def test_notification_exception_does_not_replace_batch_exit(tmp_path, monkeypatch, capsys, failure):
    monkeypatch.setenv("HK_DRIVER_UI_STOP_AFTER", "submitted")
    notification = Mock(side_effect=failure)
    monkeypatch.setattr(report, "notify_batch", notification)
    assert runner.run_batch(list(report.CASE_LABELS), [], run_case=lambda *_args: 1, report_dir=tmp_path) == 1
    notification.assert_called_once()
    assert "private-url" not in capsys.readouterr().out


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


def test_collect_only_never_sends_or_launches_batch(monkeypatch):
    monkeypatch.setattr(runner, "init_all_dirs", Mock())
    monkeypatch.setattr(runner.pytest, "main", Mock(return_value=0))
    monkeypatch.setattr(runner, "run_batch", Mock())
    notification = Mock()
    monkeypatch.setattr(report, "notify_batch", notification)
    assert runner.run_tests(["--batch", "--collect-only"]) == 0
    runner.run_batch.assert_not_called()
    notification.assert_not_called()
