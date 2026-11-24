import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ui_framework import JRYG_api_catalog as catalog
from ui_framework.JRYG_ui_trace import UIRecorder, UITracePlugin, ui_step


@pytest.fixture
def config():
    return {"enabled": True, "cluster": "hk", "namespace": "test", "step_padding_seconds": 5,
            "server_timezone": "Asia/Hong_Kong", "tail_lines": 2}


@pytest.fixture
def steps():
    return [{"run_id": "run", "step_id": "step", "role": "passenger", "case": "case.py::test_order",
             "name": "确认呼叫", "started_at": "2026-11-17T10:00:00+08:00",
             "finished_at": "2026-11-17T10:00:02+08:00", "status": "passed"}]


def api(**overrides):
    row = {"category": "api", "time": "2026-11-17T10:00:01+08:00", "request_method": "POST",
           "request_uri": "/passenger/real-order/place", "mobile": "80000001", "trace_id": "trace-a",
           "user_agent": "YGPassenger/1.2.0(iOS;iOS18)", "response_status": 200}
    row.update(overrides)
    return row


def logs(*rows, role="passenger"):
    return [(role, "entry-pod", "\n".join(json.dumps(row) for row in rows))]


def build(rows, steps, config, role="passenger"):
    return catalog.build_catalog(logs(*rows, role=role), steps, {role: {"80000001"}}, config)


def test_recorder_nested_failed_steps_redact_exception_and_reset(tmp_path):
    recorder = UIRecorder(tmp_path)
    with recorder.activate("case.py::test"):
        with pytest.raises(RuntimeError):
            with ui_step("下单", "passenger"):
                with ui_step("确认呼叫", "passenger"):
                    raise RuntimeError("secret-token-and-code")
    assert len(recorder.steps) == 2
    assert all(row["status"] == "failed" for row in recorder.steps)
    assert recorder.steps[1]["parent_id"] == recorder.steps[0]["step_id"]
    assert catalog.parse_time(recorder.steps[0]["started_at"]).tzinfo is not None
    assert "secret-token-and-code" not in (tmp_path / "ui_steps.jsonl").read_text()
    with ui_step("未启用动作", "driver"):
        pass
    assert len(recorder.steps) == 2
    saved, bad = catalog.read_steps(tmp_path / "ui_steps.jsonl")
    assert bad == 0 and len(saved) == 2 and saved[0]["status"] == "failed"


def test_recorder_interruption_and_repeat_directory(tmp_path):
    for _ in range(2):
        recorder = UIRecorder(tmp_path)
        with recorder.activate("case"):
            with pytest.raises(KeyboardInterrupt):
                with ui_step("支付", "passenger"):
                    raise KeyboardInterrupt
    saved, _ = catalog.read_steps(tmp_path / "ui_steps.jsonl")
    assert len(saved) == 1 and saved[0]["status"] == "interrupted"


def test_recorder_file_error_never_replays_action(tmp_path):
    blocker = tmp_path / "not_a_directory"
    blocker.write_text("x")
    recorder = UIRecorder(blocker)
    calls = []
    with recorder.activate("case"):
        with ui_step("确认支付", "passenger"):
            calls.append("submit")
    assert calls == ["submit"] and recorder.warnings


def test_wrapper_restores_inherited_method_without_recording_input(tmp_path):
    calls = []

    class Parent:
        def fill(self, root, placeholder, value):
            calls.append(value)
            return 42

    class Child(Parent):
        pass

    plugin = UITracePlugin(tmp_path)
    plugin._patch(Child, "fill", "填写输入框", "driver")
    with plugin.recorder.activate("case"):
        assert Child().fill(None, "phone", "secret-input") == 42
    plugin.pytest_unconfigure(None)
    assert "fill" not in Child.__dict__ and calls == ["secret-input"]
    assert "secret-input" not in (tmp_path / "ui_steps.jsonl").read_text()


def test_real_plugin_lifecycle_records_steps_and_restores_methods(tmp_path, monkeypatch):
    from ui_framework.JRYG_order_flow import TestOrderBase
    calls = []

    def fake_call(instance, tag):
        calls.append("call")
        return True

    monkeypatch.setattr(TestOrderBase, "_ios_click_confirm_call", fake_call)
    instance = TestOrderBase()
    instance.driver_ui = SimpleNamespace(order_no="TESTORDER123", args=SimpleNamespace(mobile="80000001"))
    item = SimpleNamespace(instance=instance, nodeid="case.py::test_order")
    plugin = UITracePlugin(tmp_path)
    try:
        plugin.pytest_sessionstart(None)
        lifecycle = plugin.pytest_runtest_protocol(item, None)
        next(lifecycle)
        assert instance._ios_click_confirm_call("private-input") is True
        plugin.pytest_runtest_logreport(SimpleNamespace(failed=True, nodeid=item.nodeid))
        with pytest.raises(StopIteration):
            next(lifecycle)
        plugin.pytest_sessionfinish(None, 1)
        assert plugin.recorder.steps[0]["status"] == "failed"
        assert plugin.recorder.steps[1]["name"] == "确认呼叫"
        assert "TESTORDER123" in plugin.clues["driver"]
        assert calls == ["call"] and "private-input" not in (tmp_path / "ui_steps.jsonl").read_text()
    finally:
        plugin.pytest_unconfigure(None)
    assert TestOrderBase._ios_click_confirm_call is fake_call


@pytest.mark.parametrize("changes", [
    {"category": "http"}, {"user_agent": "YGPassenger(Android)"},
    {"user_agent": "order_service_daemon"}, {"user_agent": ""},
    {"mobile": "80000002", "trace_id": "other-trace"},
    {"mobile": "1800000019", "trace_id": "other-trace"},
    {"time": "2026-11-17T09:00:00+08:00"},
    {"request_method": ""}, {"request_uri": "/source"},
    {"request_uri": "/session/test/source"},
])
def test_filters_internal_other_client_other_account_and_old_logs(changes, steps, config):
    records, notes = build([api(**changes)], steps, config)
    assert records == [] and notes


def test_utc_and_nested_time_window_and_request_time(steps, config):
    outer = dict(steps[0], step_id="outer", name="下单并等待结果",
                 started_at="2026-11-17T09:59:50+08:00", finished_at="2026-11-17T10:00:20+08:00")
    row = api(time="2026-11-17T02:00:10Z", request_time="2026-11-17T02:00:01Z")
    records, notes = build([row], [outer, *steps], config)
    assert not notes and records[0]["ui_steps"] == ["确认呼叫"]
    assert records[0]["evidence"][0]["step_id"] == "step"


@pytest.mark.parametrize("value", ["2026-11-17T10:00:01.468+0800", "2026-11-17T02:00:01Z", "2026-11-17T10:00:01"])
def test_real_log_timestamp_formats(value):
    parsed = catalog.parse_time(value)
    assert parsed is not None and parsed.tzinfo is not None


def test_verified_driver_identity_includes_requests_without_mobile(steps, config):
    driver_steps = [dict(steps[0], role="driver")]
    seed = api(driver_id=31)
    same_account = api(driver_id=31, mobile="", trace_id="other", request_uri="/driverApi/online")
    other_account = api(driver_id=32, mobile="", trace_id="unrelated", request_uri="/driverApi/unrelated")
    records, _ = build([seed, same_account, other_account], driver_steps, config, role="driver")
    assert {row["path"] for row in records} == {"/passenger/real-order/place", "/driverApi/online"}


def test_remote_awk_keeps_only_bounded_ios_api_window(tmp_path):
    import subprocess
    path = tmp_path / "entry.log"
    rows = [api(request_id="one"), api(category="http"), api(user_agent="YGPassenger(Android)"),
            api(request_id="two"), api(request_id="three")]
    path.write_text("\n".join(json.dumps(row) for row in rows))
    result = subprocess.run(["awk", "-v", "limit=2", catalog.ENTRY_AWK, str(path)], capture_output=True, text=True, check=True)
    saved, bad = catalog.decode_lines(result.stdout)
    assert bad == 0 and [row["request_id"] for row, _ in saved] == ["two", "three"]


def test_trace_seed_and_deduplicate_replicas(steps, config):
    seed = api(category="middleware-encryptPrepare")
    entry = api(mobile="", request_id="request-a")
    dataset = logs(seed, entry) + [("passenger", "replica", json.dumps(entry))]
    records, _ = catalog.build_catalog(dataset, steps, {"passenger": {"80000001"}}, config)
    assert len(records) == 1 and records[0]["count"] == 1


def test_request_query_can_match_login_without_mobile_field(steps, config):
    row = api(mobile="", request_query="mobile=80000001&code=123456")
    records, _ = build([row], steps, config)
    assert len(records) == 1


def test_response_phone_does_not_identify_requester(steps, config):
    row = api(mobile="80000002", response={"mobile": "80000001"})
    records, _ = build([row], steps, config)
    assert records == []


def test_same_path_keeps_distinct_methods_and_roles(steps, config):
    driver_steps = [dict(steps[0], role="driver", step_id="driver-step")]
    dataset = logs(api(), api(request_method="GET", trace_id="trace-b")) + logs(api(), role="driver")
    records, _ = catalog.build_catalog(dataset, [*steps, *driver_steps],
                                       {role: {"80000001"} for role in catalog.ROLES}, config)
    assert len(records) == 3


def test_bad_json_missing_status_and_nearby_time_not_faked(steps, config):
    dataset = logs(api(time="2026-11-17T10:00:04+08:00", response_status=None))
    dataset[0] = (dataset[0][0], dataset[0][1], dataset[0][2] + '\n{"broken"')
    records, notes = catalog.build_catalog(dataset, steps, {"passenger": {"80000001"}}, config)
    assert notes and records[0]["evidence"][0]["http_status"] is None
    assert "待确认" in records[0]["evidence"][0]["association"]


@pytest.mark.parametrize("uri,expected", [
    ("https://app.example/api/place?token=secret#fragment", "/api/place"),
    ("/v1/order/26A4ID0WECNW", "/v1/order/{id}"),
    ("/mobile/80000001", "/mobile/{id}"),
    ("/token/secretvalue", "/token/{id}"),
    ("/email/person%40example.com", "/email/{id}"),
    ("/unsafe%0Apath", None),
])
def test_safe_path(uri, expected):
    assert catalog.safe_path(uri) == expected


def test_reports_only_allowlisted_fields_and_unknown_purpose(tmp_path, steps, config):
    row = api(request_uri="/api/unconfirmed?token=secret-token", access_token="secret-token",
              headers={"Cookie": "secret-cookie"}, request_body={"code": "123456", "card": "9999999999999999"})
    records, notes = build([row], steps, config)
    target = catalog.write_catalog(tmp_path, records, notes, config)
    text = target.read_text()
    output = text + (tmp_path / "接口明细.json").read_text()
    assert "POST /api/unconfirmed  # 用途待确认" in text
    for private in ("secret-token", "secret-cookie", "123456", "80000001", "9999999999999999"):
        assert private not in output
    config["endpoint_labels"] = {"POST /api/unconfirmed": "核验用途"}
    assert catalog.purpose(records[0], config) == "核验用途"


def test_merge_counts_and_evidence(tmp_path, steps, config):
    records, notes = build([api()], steps, config)
    for index in (1, 2):
        catalog.write_catalog(tmp_path / f"{index:02d}_api", records, notes, config)
    catalog.merge_catalogs(tmp_path, config)
    rows = json.loads((tmp_path / "接口明细.json").read_text())["interfaces"]
    assert len(rows) == 1 and rows[0]["count"] == 2 and len(rows[0]["evidence"]) == 2


def test_backend_selects_only_all_entry_replicas_and_marks_cap(config):
    backend = catalog.TraceQueryBackend.__new__(catalog.TraceQueryBackend)
    backend.config = config
    pod_names = ["passenger-ab12-cd34", "passenger-ab12-ef56", "passenger-service-ab12-gh78",
                 "driver-api-new-ab12-ij90", "dispatcher-ab12-kl12"]
    pods = {"items": [{"metadata": {"name": name}, "status": {"phase": "Running"}} for name in pod_names]}
    backend.command = Mock(side_effect=[json.dumps(pods), "a\nb\nc", "a", "b"])
    rows, notes = backend.collect("2026-11-17T02:00:00Z")
    assert len(rows) == 3 and notes
    calls = backend.command.call_args_list
    assert all("dispatcher-ab12-kl12" not in call.args for call in calls)
    assert all("passenger-service-ab12-gh78" not in call.args for call in calls)


def test_backend_nonzero_exit_does_not_expose_stderr(monkeypatch, config):
    backend = catalog.TraceQueryBackend.__new__(catalog.TraceQueryBackend)
    backend.config, backend.kubeconfig, backend.deadline = config, "config", float("inf")
    monkeypatch.setattr(catalog.subprocess, "run", Mock(return_value=SimpleNamespace(returncode=1, stderr="secret", stdout="")))
    with pytest.raises(RuntimeError, match="只读查询失败") as error:
        backend.command("get", "pods")
    assert "secret" not in str(error.value)


def test_capture_failure_still_writes_steps_and_report(tmp_path, monkeypatch, config):
    plugin = UITracePlugin(tmp_path)
    with plugin.recorder.activate("case"):
        with ui_step("确认支付", "passenger"):
            pass
    monkeypatch.setattr(catalog, "TraceQueryBackend", Mock(side_effect=RuntimeError("secret-kube-config")))
    target = catalog.finish_capture(plugin, config)
    assert target.exists() and (tmp_path / "ui_steps.jsonl").exists()
    assert "secret-kube-config" not in target.read_text()


def test_collect_only_never_enables_capture(monkeypatch):
    from runners import JRYG_run_main_ios as runner
    monkeypatch.setattr(runner, "init_all_dirs", Mock())
    monkeypatch.setattr(runner.pytest, "main", Mock(return_value=0))
    monkeypatch.setattr(catalog, "load_config", Mock(side_effect=AssertionError("must not load")))
    assert runner.run_tests(["--batch", "--collect-only"]) == 0
    assert runner.pytest.main.call_args.kwargs["plugins"] == []


def test_runner_report_failure_preserves_ui_exit(tmp_path, monkeypatch, config):
    from runners import JRYG_run_main_ios as runner
    monkeypatch.setattr(runner, "init_all_dirs", Mock())
    monkeypatch.setattr(runner.pytest, "main", Mock(return_value=7))
    monkeypatch.setattr(catalog, "load_config", Mock(return_value=config))
    monkeypatch.setattr(catalog, "finish_capture", Mock(side_effect=RuntimeError("secret")))
    assert runner.run_tests(["--api-output", str(tmp_path)]) == 7
    runner.pytest.main.assert_called_once()
    catalog.finish_capture.assert_called_once()


@pytest.mark.parametrize("args", [[], ["--no-api-catalog"]])
def test_bad_or_disabled_config_does_not_block_ui_run(monkeypatch, args):
    from runners import JRYG_run_main_ios as runner
    monkeypatch.setattr(runner, "init_all_dirs", Mock())
    monkeypatch.setattr(runner.pytest, "main", Mock(return_value=1))
    monkeypatch.setattr(catalog, "load_config", Mock(side_effect=ValueError("private-config")))
    assert runner.run_tests(args) == 1
    assert runner.pytest.main.call_args.kwargs["plugins"] == []
    if args:
        catalog.load_config.assert_not_called()


def test_batch_propagates_capture_and_does_not_query_in_parent(tmp_path, monkeypatch, config):
    from runners import JRYG_run_main_ios as runner
    monkeypatch.setenv("HK_DRIVER_UI_STOP_AFTER", "submitted")
    child = Mock(return_value=1)
    assert runner.run_batch(["case.py"], [], run_case=child, report_dir=tmp_path, api_config=config) == 1
    args = child.call_args.args[1]
    assert "--api-namespace=test" in args and any(arg.startswith("--api-output=") for arg in args)
    assert len(list(tmp_path.glob("batches/*/接口清单.txt"))) == 1


def test_disabled_batch_propagates_no_capture(tmp_path, monkeypatch, config):
    from runners import JRYG_run_main_ios as runner
    monkeypatch.setenv("HK_DRIVER_UI_STOP_AFTER", "submitted")
    config["enabled"] = False
    child = Mock(return_value=1)
    assert runner.run_batch(["case.py"], [], run_case=child, report_dir=tmp_path, api_config=config) == 1
    assert "--no-api-catalog" in child.call_args.args[1]
    assert not list(tmp_path.glob("batches/*/接口清单.txt"))
