"""安卓独立场景、原生司机输入及完整订单门禁的离线回归。"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import xml.etree.ElementTree as ET

import pytest

import JRYG_run_main as runner
from jryg_hk_android import JRYG_android_order as android
from jryg_hk_android.JRYG_android_ui import normalized_tree
from jryg_hk_android.JRYG_scenarios import SCENARIOS, android_scenarios
from jryg_hk_android.JRYG_shared_ios import ios_scenarios
from jryg_hk_android.JRYG_order_flow import TestOrderBase as BusinessBase
import jryg_hk_android.JRYG_order_flow as business

CASES = list(android_scenarios())


def driver_flow():
    args = SimpleNamespace(step_timeout=0.01, accept_label=None, report_dir="unused", code=None, tail=None)
    flow = android.AndroidDriverUIFlow(args, client=Mock())
    flow.wait_for = Mock()
    flow.dismiss_keyboard = Mock()
    flow.act = Mock()
    return flow


def driver_field(resource="et_input_fee", hint="", text=""):
    source = ('<hierarchy><node class="android.widget.EditText" text="' + text + '" hint="' + hint + '" '
              'resource-id="com.sunlightmobility.driver:id/' + resource + '" '
              'enabled="true" bounds="[10,10][200,100]"/></hierarchy>')
    return normalized_tree(source, "com.sunlightmobility.driver")


def test_android_six_local_files_define_own_tests_and_match_ios():
    ios = {case.__name__: case for case in ios_scenarios()}
    assert len(CASES) == len(SCENARIOS) == 6
    for case, (filename, class_name) in zip(CASES, SCENARIOS):
        baseline = ios[case.ios_scenario_name]
        assert case.__name__ == class_name
        assert "test_order_flow" in vars(case)
        assert case.__bases__ == (android.AndroidOrderBase,)
        assert (case.CAR_TYPE, case.PAYMENT, case.FINAL_PAYMENT) == (
            baseline.CAR_TYPE, baseline.PAYMENT, baseline.FINAL_PAYMENT)
        assert case.final_payment.fget is BusinessBase.final_payment.fget
        assert (runner.BASE_DIR / "cases" / filename).is_file()
        assert case.pytestmark == []


def test_business_imports_only_android_local():
    """验证业务基类来自 jryg_hk_android 包，不依赖 iOS 快照。"""
    assert "jryg_hk_android" in Path(business.__file__).resolve().parts


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.__name__)
def test_each_scene_calls_full_android_flow_once(case):
    order = case()
    order._run_order_flow = Mock()
    order.test_order_flow()
    order._run_order_flow.assert_called_once_with()


@pytest.mark.parametrize("filename,class_name", SCENARIOS)
def test_runner_accepts_independent_file_path_and_class(monkeypatch, filename, class_name):
    run = Mock(return_value=0)
    monkeypatch.setattr(runner.pytest, "main", run)
    path = runner.BASE_DIR / "cases" / filename
    for selection in (filename, str(path), "cases/" + filename, class_name):
        assert runner.run_tests(["--case", selection, "--collect-only"]) == 0
        assert f"{path}::{class_name}::test_order_flow" in run.call_args.args[0]


def test_only_accepted_mode_cannot_run_full_scene(monkeypatch):
    monkeypatch.setenv("HK_DRIVER_UI_STOP_AFTER", "accepted")
    run = Mock()
    monkeypatch.setattr(BusinessBase, "test_order_flow", run)
    with pytest.raises(RuntimeError, match="仅接单"):
        CASES[0]().test_order_flow()
    run.assert_not_called()


@pytest.mark.parametrize("fault", ["missing", "unpaid", "changed", "old", "waiting"])
def test_full_scene_cannot_pass_without_unique_completed_paid_order(monkeypatch, fault):
    monkeypatch.delenv("HK_DRIVER_UI_STOP_AFTER", raising=False)
    order = CASES[0]()
    order.completed_order_no = "26A6P22WECNY"
    order.driver_ui = SimpleNamespace(order_no="26A6P22WECNY", last_phase="complete",
                                      awaiting_new_order=False, completed_before_run=set())
    if fault == "missing":
        order.completed_order_no = None
    elif fault == "unpaid":
        order.driver_ui.last_phase = "unpaid"
    elif fault == "changed":
        order.driver_ui.order_no = "26A6P22WECNX"
    elif fault == "old":
        order.driver_ui.completed_before_run.add(order.completed_order_no)
    else:
        order.driver_ui.awaiting_new_order = True
    monkeypatch.setattr(BusinessBase, "test_order_flow", lambda self: None)
    with pytest.raises(AssertionError, match="已支付核验"):
        order.test_order_flow()


def test_native_driver_fare_fill_uses_resource_and_exact_readback():
    flow = driver_flow()
    field = Mock()
    field.native.id = "fare-field"
    field.native.text = ""
    field.set_text.side_effect = lambda value: setattr(field.native, "text", value)
    flow.client.return_value.unique.return_value = field
    flow.fill(driver_field(), "請輸入車費", "5")
    field.set_text.assert_called_once_with("5")
    assert flow.client.call_args.kwargs == {"resourceId": "com.sunlightmobility.driver:id/et_input_fee"}
    flow.client.click.assert_not_called()
    flow.client.send_keys.assert_not_called()


def test_driver_fill_failed_readback_never_confirms_bill():
    flow = driver_flow()
    field = Mock()
    field.native.text = "wrong"
    flow.client.return_value.unique.return_value = field
    with pytest.raises(TimeoutError, match="回读"):
        flow.fill(driver_field(), "請輸入車費", "5")
    flow.act.assert_not_called()


def test_native_tail_does_not_require_ios_placeholder():
    flow = driver_flow()
    flow.args.tail = "1234"
    field = Mock()
    field.native.text = "1234"
    flow.client.return_value.unique.return_value = field
    root = driver_field("tail_input")
    flow.root = Mock(return_value=root)
    flow.detect_phase = Mock(return_value="tail")
    flow.enter_tail(root)
    field.set_text.assert_called_once_with("1234")
    flow.act.assert_called_once()
    flow.wait_for.assert_called_once_with({"destination"})


def test_tail_bad_readback_never_submits():
    flow = driver_flow()
    flow.args.tail = "1234"
    flow.client.return_value.unique.return_value.native.text = "0000"
    with pytest.raises(RuntimeError, match="回读"):
        flow.enter_tail(driver_field("tail_input"))
    flow.act.assert_not_called()


@pytest.mark.parametrize("count", [1, 6])
def test_driver_code_native_one_field_or_six_digits(count):
    flow = driver_flow()
    flow.args.code = "123456"
    fields = [Mock(bounds=SimpleNamespace(x=10 * index, y=10)) for index in range(count)]
    flow.client.return_value.find_elements.return_value = fields
    flow.enter_code(ET.Element("root"))
    for index, field in enumerate(fields):
        field.set_text.assert_called_once_with("123456" if count == 1 else str(index + 1))
    flow.wait_for.assert_called_once_with({"offline", "online", "pickup"})


def test_driver_ambiguous_code_never_inputs():
    flow = driver_flow()
    flow.args.code = "123456"
    fields = [Mock(), Mock()]
    flow.client.return_value.find_elements.return_value = fields
    with pytest.raises(RuntimeError, match="不唯一"):
        flow.enter_code(ET.Element("root"))
    for field in fields:
        field.set_text.assert_not_called()


def test_full_order_prepares_route_with_verified_login():
    order = CASES[0]()
    order.prepare_passenger_route = Mock()
    order._ios_launch_setup_and_addresses("offline", "北角地鐵站", "香港大學")
    order.prepare_passenger_route.assert_called_once_with(
        "offline", "北角地鐵站", "香港大學", verify_login=True)
