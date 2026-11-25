"""六场景专用入口的选例边界回归；不执行Appium、下单或支付。

来源：2026-11-23 用户要求该入口只执行 cases/main_flow_cases 主功能用例。
默认顺序仍为包车两例、打表四例；目标订单专项只能显式 --case 选择。
"""

import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import JRYG_run_main as runner
from passenger_android_core import JRYG_scenarios as registry


PROJECT = Path(__file__).resolve().parents[2]
MAIN_DIR = PROJECT / "cases" / "main_flow_cases"
DEFAULT_FILES = (
    "JRYG_test_android_charter_alipay_order.py",
    "JRYG_test_android_charter_bankcard_order.py",
    "JRYG_test_android_meter_cash_order.py",
    "JRYG_test_android_meter_epayment_bankcard_order.py",
    "JRYG_test_android_meter_epayment_alipay_order.py",
    "JRYG_test_android_meter_alipay_order.py",
)
TARGET_FILE = "JRYG_test_android_meter_epayment_target_order.py"


@pytest.fixture(autouse=True)
def isolate_execution(monkeypatch):
    import socket
    import subprocess
    import requests
    import pymysql

    def forbidden(*args, **kwargs):
        raise AssertionError("入口离线测试禁止真实设备、进程或网络操作")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(os, "execve", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(requests.Session, "request", forbidden)
    monkeypatch.setattr(pymysql, "connect", forbidden)
    monkeypatch.setattr(runner, "init_all_dirs", Mock())


@pytest.fixture
def entry():
    spec = importlib.util.spec_from_file_location("fixture_six_scene_entry", PROJECT / "香港乘客安卓包车打表六场景.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def engines(monkeypatch):
    calls = Mock(return_value=0)
    batch = Mock(return_value=0)
    monkeypatch.setattr(runner.pytest, "main", calls)
    monkeypatch.setattr(runner, "run_batch", batch)
    return calls, batch


def test_default_wrapper_always_scopes_six_scenarios(entry):
    assert entry._runner_arguments([]) == ["--main-flow-only", "--batch"]


@pytest.mark.parametrize("arguments", [["--case", TARGET_FILE], ["--case=" + TARGET_FILE]])
def test_single_case_wrapper_keeps_scope_without_batch(entry, arguments):
    assert entry._runner_arguments(arguments) == ["--main-flow-only", *arguments]


def test_entry_passes_scope_through_shell_without_running_it(entry, monkeypatch):
    execute = Mock()
    monkeypatch.setattr(entry.os, "execve", execute)
    assert entry.main(["--collect-only"]) == 0
    program, args, environment = execute.call_args.args
    assert program == "/bin/bash"
    assert args[1] == str(PROJECT / "JRYG_run_hk.sh")
    assert args[2:] == ["--main-flow-only", "--batch", "--collect-only"]
    assert environment["HK_ANDROID_PYTHON"] == str(PROJECT / ".venv/bin/python")


def test_scoped_registry_never_reads_optional_version_paths(monkeypatch):
    monkeypatch.setattr(registry, "V150_DEVICE_SCENARIOS", (("missing-version-file.py", "Missing", "test_missing"),))
    nodes = registry.scenario_nodes(include_optional=True, main_flow_only=True)
    assert len(nodes) == 7
    assert {Path(node.split("::")[0]).name for node in nodes} == set(DEFAULT_FILES) | {TARGET_FILE}
    assert all(Path(node.split("::")[0]).parent == MAIN_DIR for node in nodes)
    with pytest.raises(RuntimeError, match="missing-version-file"):
        registry.scenario_nodes(include_optional=True)


def test_registry_refuses_symlink_outside_main_directory(monkeypatch, tmp_path):
    main = tmp_path / "cases" / "main_flow_cases"
    main.mkdir(parents=True)
    outside = tmp_path / "outside.py"
    outside.write_text("", encoding="utf-8")
    (main / "alias.py").symlink_to(outside)
    monkeypatch.setattr(registry, "BASE_DIR", tmp_path)
    monkeypatch.setattr(registry, "SCENARIOS", (("alias.py", "TestAlias"),))
    with pytest.raises(RuntimeError, match="越出"):
        registry.scenario_nodes(main_flow_only=True)


def test_default_collect_only_selects_exact_six_in_original_order(engines):
    pytest_main, batch = engines
    assert runner._run_tests(["--main-flow-only", "--batch", "--collect-only"]) == 0
    batch.assert_not_called()
    args = pytest_main.call_args.args[0]
    selected = [arg for arg in args if "::" in arg]
    assert tuple(Path(node.split("::")[0]).name for node in selected) == DEFAULT_FILES
    assert all(Path(node.split("::")[0]).parent == MAIN_DIR for node in selected)
    assert all(node.endswith("::test_order_flow") for node in selected)
    assert "--collect-only" in args
    assert any(isinstance(plugin, runner.MainFlowCollectionGate) for plugin in pytest_main.call_args.kwargs["plugins"])


def test_batch_and_children_preserve_scope(engines):
    pytest_main, batch = engines
    batch.return_value = 7
    assert runner._run_tests(["--main-flow-only", "--batch", "-q"]) == 7
    selected, extra = batch.call_args.args
    assert tuple(Path(node.split("::")[0]).name for node in selected) == DEFAULT_FILES
    assert extra == ["--main-flow-only", "-q"]
    assert batch.call_args.kwargs["run_case"] is runner.run_case
    pytest_main.assert_not_called()


@pytest.mark.parametrize("form", ["filename", "class", "absolute_file", "absolute_node", "relative_file", "relative_node"])
def test_target_optional_case_can_only_be_explicitly_selected(engines, form):
    pytest_main, batch = engines
    node = next(node for node in registry.scenario_nodes(include_optional=True, main_flow_only=True)
                if Path(node.split("::")[0]).name == TARGET_FILE)
    path, method = node.split("::", 1)
    choices = {"filename": TARGET_FILE, "class": method.split("::")[0],
               "absolute_file": path, "absolute_node": node,
               "relative_file": str(Path(path).relative_to(PROJECT)),
               "relative_node": str(Path(path).relative_to(PROJECT)) + "::" + method}
    assert runner._run_tests(["--main-flow-only", "--case", choices[form], "--co"]) == 0
    assert [arg for arg in pytest_main.call_args.args[0] if "::" in arg] == [node]
    batch.assert_not_called()


@pytest.mark.parametrize("case", [
    "JRYG_test_android_v150_booking.py", "TestV150BookingDevice",
    "cases/passenger_v1_6_0/test_v160_http_api_real.py", "cases", "cases/main_flow_cases",
    str(PROJECT / "cases/passenger_v1_5_0/JRYG_test_android_v150_booking.py"),
    "cases/main_flow_cases/../passenger_v1_5_0/JRYG_test_android_v150_booking.py",
])
def test_scoped_case_rejects_other_modules_before_pytest(engines, case):
    pytest_main, batch = engines
    assert runner._run_tests(["--main-flow-only", "--case", case, "--collect-only"]) == 2
    pytest_main.assert_not_called()
    batch.assert_not_called()


@pytest.mark.parametrize("extra", [
    ["cases/passenger_v1_6_0"], ["--", "cases"], ["--pyargs", "cases"],
    ["-c", "other.ini"], ["-o", "testpaths=cases"], ["--override-ini=addopts=cases"],
    ["-p", "other_plugin"], ["--main-flow-only=false"],
])
def test_scoped_passthrough_cannot_add_test_paths_or_override_config(engines, extra):
    pytest_main, batch = engines
    with pytest.raises(SystemExit) as error:
        runner._run_tests(["--main-flow-only", "--collect-only", *extra])
    assert error.value.code == 2
    pytest_main.assert_not_called()
    batch.assert_not_called()


@pytest.mark.parametrize("extra", [[], ["-q", "-s"], ["-vv", "--tb=short"],
                                   ["-k", "charter and not meter"], ["-x", "--maxfail=1"],
                                   ["--co", "--disable-warnings"], ["-h"]])
def test_safe_scoped_display_filter_and_collect_arguments(extra):
    runner._validate_main_flow_pytest_args(extra)


@pytest.mark.parametrize("raises", [False, True])
def test_environment_addopts_cannot_expand_scope_and_is_restored(monkeypatch, engines, raises):
    pytest_main, _ = engines
    injected = "cases/passenger_v1_6_0 -o python_files=*.py"
    monkeypatch.setenv("PYTEST_ADDOPTS", injected)

    def check(args, plugins):
        assert "PYTEST_ADDOPTS" not in os.environ
        assert "addopts=" in args and "--import-mode=importlib" in args
        assert any(isinstance(plugin, runner.MainFlowCollectionGate) for plugin in plugins)
        if raises:
            raise RuntimeError("fixture-collection-error")
        return 0

    pytest_main.side_effect = check
    if raises:
        with pytest.raises(RuntimeError, match="fixture-collection-error"):
            runner._run_tests(["--main-flow-only", "--co"])
    else:
        assert runner._run_tests(["--main-flow-only", "--co"]) == 0
    assert os.environ["PYTEST_ADDOPTS"] == injected


def item_for(node):
    path, method = node.split("::", 1)
    return SimpleNamespace(path=Path(path), nodeid=str(Path(path).relative_to(PROJECT)) + "::" + method)


def test_collection_gate_allows_only_selected_nodes():
    nodes = registry.scenario_nodes(main_flow_only=True)
    runner.MainFlowCollectionGate(nodes).pytest_collection_finish(SimpleNamespace(items=[item_for(n) for n in nodes]))


@pytest.mark.parametrize("kind", ["outside", "extra_method", "unselected", "duplicate"])
def test_final_collection_gate_rejects_injection_before_setup(kind):
    selected = registry.scenario_nodes(main_flow_only=True)
    item = item_for(selected[0])
    items = [item]
    if kind == "outside":
        item.path = PROJECT / "cases/passenger_v1_6_0/test_v160_driver_entry_offline.py"
    elif kind == "extra_method":
        item.nodeid = item.nodeid.replace("test_order_flow", "test_other")
    elif kind == "unselected":
        extra = next(n for n in registry.scenario_nodes(include_optional=True, main_flow_only=True) if TARGET_FILE in n)
        items.append(item_for(extra))
    else:
        items.append(item)
    with pytest.raises(pytest.UsageError, match="只允许执行"):
        runner.MainFlowCollectionGate(selected).pytest_collection_finish(SimpleNamespace(items=items))


def test_general_runner_retains_optional_version_entry(engines):
    pytest_main, batch = engines
    assert runner._run_tests(["--case", "TestV150BookingDevice", "--co"]) == 0
    selected = [arg for arg in pytest_main.call_args.args[0] if "::" in arg]
    assert len(selected) == 1 and "/passenger_v1_5_0/" in selected[0]
    assert not any(isinstance(plugin, runner.MainFlowCollectionGate) for plugin in pytest_main.call_args.kwargs["plugins"])
    batch.assert_not_called()


def test_pytest_exit_code_is_preserved_for_scoped_entry(engines):
    pytest_main, _ = engines
    pytest_main.return_value = 5
    assert runner._run_tests(["--main-flow-only", "--co", "-k", "not_a_case"]) == 5
