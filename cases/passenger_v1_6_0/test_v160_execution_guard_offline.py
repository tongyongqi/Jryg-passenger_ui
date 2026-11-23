"""第一批 UI/订单执行防护回归；仅校验代码行为，不代表真机业务通过。"""

import importlib
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from passenger_android_core.JRYG_android_ui import normalized_tree
from passenger_android_core.JRYG_scenarios import scenario_nodes
from passenger_android_core.main_flow import order_flow, target_order
from passenger_android_core.main_flow.order import AndroidOrderBase, AndroidOrderMixin
from passenger_android_core.v160.device_steps import V160DeviceSteps


@pytest.fixture(autouse=True)
def no_external_access(monkeypatch):
    import pymysql
    import requests
    import subprocess

    def forbidden(*args, **kwargs):
        raise AssertionError("离线回归禁止真实网络、数据库及设备命令")

    monkeypatch.setattr(pymysql, "connect", forbidden)
    monkeypatch.setattr(requests.Session, "request", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)


def selector_tree(height, count=1):
    node = ('<node class="android.widget.LinearLayout" resource-id="fixture:id/car_selector" '
            f'bounds="[0,0][500,{height}]" displayed="true" enabled="true"/>')
    return normalized_tree("<hierarchy>" + node * count + "</hierarchy>", "fixture")


@pytest.fixture
def steps():
    case = object.__new__(V160DeviceSteps)
    case.client = Mock()
    case.client.window_size.return_value = (500, 1000)
    case._ensure_devices_awake = Mock()
    return case


@pytest.mark.parametrize("height,expected", [(900, "expanded"), (500, "default"), (300, "collapsed")])
def test_selector_uses_normalized_height(steps, height, expected):
    root = selector_tree(height)
    assert all("bounds" not in node.attrib for node in root.iter())
    steps._passenger_root = Mock(return_value=root)
    assert steps.v160_car_selector_height_state() == expected


@pytest.mark.parametrize("count", [0, 2])
def test_selector_requires_unique_container(steps, count):
    steps._passenger_root = Mock(return_value=selector_tree(500, count))
    with pytest.raises(RuntimeError, match="必须唯一"):
        steps.v160_car_selector_height_state()


def test_invalid_window_dimensions_are_not_swallowed(steps):
    steps.client.window_size.return_value = (500, 0)
    with pytest.raises(RuntimeError, match="高度无效"):
        steps._v160_screen_height()


def test_scroll_uses_client_and_waits_for_observed_state(steps):
    steps._passenger_root = Mock(side_effect=[selector_tree(500), selector_tree(900)])
    assert steps.v160_scroll_car_selector("up") == "expanded"
    steps.client.swipe.assert_called_once_with(250, 600, 250, 150, 0.4)
    assert steps._passenger_root.call_count == 2


def test_invalid_direction_cannot_swipe(steps):
    with pytest.raises(ValueError, match="up/down"):
        steps.v160_scroll_car_selector("left")
    steps.client.swipe.assert_not_called()


def test_wait_propagates_programming_errors(steps):
    checker = Mock(side_effect=AttributeError("fixture-driver"))
    with pytest.raises(AttributeError, match="fixture-driver"):
        steps._v160_wait_page(checker, "not ready")
    checker.assert_called_once()


def test_wait_has_finite_deadline(steps):
    with pytest.raises(TimeoutError, match="not ready"):
        steps._v160_wait_page(lambda: False, "not ready", timeout=0)


def test_unimplemented_booking_does_not_click_or_return_fabricated_time(steps):
    with pytest.raises(NotImplementedError, match="时间回读"):
        steps.v160_select_booking_departure(minutes=60)
    steps.client.click.assert_not_called()
    steps.client.swipe.assert_not_called()


def api_log(code=10000, path="/passenger/order/estimate"):
    return (f"E/retrofit(1): Sending request https://fixture.invalid{path}\n"
            f'E/retrofit(1): result={{"code":{code},"data":{{}},"message":"fixture"}}')


def test_api_log_uses_lines_url_and_checker_result(steps):
    result = steps.v160_expect_api(api_log(), "/passenger/order/estimate")
    assert result["code"] == 10000
    assert result["url"] == "https://fixture.invalid/passenger/order/estimate"


@pytest.mark.parametrize("code", [0, 50000])
def test_api_log_failed_business_code_is_not_truthy_dict_success(steps, code):
    with pytest.raises(AssertionError, match="校验失败"):
        steps.v160_expect_api(api_log(code), "/passenger/order/estimate")


@pytest.mark.parametrize("text", ["", api_log() + "\n" + api_log(),
                                 api_log(path="/passenger/order/estimate/other")])
def test_api_log_missing_ambiguous_or_partial_path_is_not_accepted(steps, text):
    with pytest.raises(RuntimeError, match="必须唯一"):
        steps.v160_expect_api(text, "/passenger/order/estimate")


def test_unbounded_log_lookup_does_not_guess_latest_order(steps):
    assert steps._v160_extract_order_no_from_logcat() is None
    steps.client.assert_not_called()


@pytest.fixture
def caller():
    case = object.__new__(AndroidOrderBase)
    case._android_click_confirm_call = Mock()
    case._android_is_login_page = Mock(return_value=False)
    case._android_wait_order_result = Mock(return_value="success")
    case._android_re_setup_from_current_page = Mock()
    case._android_handle_unfinished_order_popup = Mock()
    case._android_ui_login = Mock()
    return case


@pytest.mark.parametrize("result", ["timeout", "ongoing_order", "too_close", "estimate_updated",
                                   "cashier", "unknown", None])
def test_non_success_never_resubmits_or_cleans_order(caller, result):
    caller._android_wait_order_result.return_value = result
    with pytest.raises(RuntimeError, match="禁止换终点"):
        order_flow.TestOrderBase._click_call_and_check_login_then_retry(caller, "fixture")
    caller._android_click_confirm_call.assert_called_once()
    caller._android_re_setup_from_current_page.assert_not_called()
    caller._android_handle_unfinished_order_popup.assert_not_called()
    caller._android_ui_login.assert_not_called()
    with pytest.raises(RuntimeError, match="禁止重复提交"):
        order_flow.TestOrderBase._click_call_and_check_login_then_retry(caller, "fixture")
    caller._android_click_confirm_call.assert_called_once()


def test_success_returns_only_after_actual_result(caller):
    assert order_flow.TestOrderBase._click_call_and_check_login_then_retry(caller, "fixture") is True
    caller._android_wait_order_result.assert_called_once_with("fixture", max_checks=15)


def test_uncertain_click_failure_keeps_submission_guard(caller):
    caller._android_click_confirm_call.side_effect = TimeoutError("fixture-click")
    with pytest.raises(TimeoutError, match="fixture-click"):
        order_flow.TestOrderBase._click_call_and_check_login_then_retry(caller, "fixture")
    with pytest.raises(RuntimeError, match="禁止重复提交"):
        order_flow.TestOrderBase._click_call_and_check_login_then_retry(caller, "fixture")
    caller._android_click_confirm_call.assert_called_once()


def test_login_after_submission_does_not_repeat_order(caller):
    caller._android_is_login_page.return_value = True
    with pytest.raises(RuntimeError, match="登录页"):
        order_flow.TestOrderBase._click_call_and_check_login_then_retry(caller, "fixture")
    caller._android_ui_login.assert_not_called()
    caller._android_re_setup_from_current_page.assert_not_called()


@pytest.fixture(params=["bankcard", "alipay"])
def charter(caller, request):
    caller.CAR_TYPE = "charter"
    caller.PAYMENT = request.param
    caller._android_select_payment = Mock()
    caller._android_screenshot = Mock()
    caller._android_click_confirm_pay = Mock()
    caller._android_pay = Mock(return_value=True)
    caller._android_click_refreshed_estimate_call = Mock()
    caller._android_reselect_refreshed_estimate = Mock()
    return caller


@pytest.mark.parametrize("result", ["estimate_updated", "timeout", "ongoing_order", "success", None])
def test_charter_uncertain_creation_never_replays_or_pays(charter, result):
    charter._android_wait_order_result.return_value = result
    with pytest.raises(RuntimeError, match="禁止重新呼叫或进入支付"):
        charter._charter_click_call_and_select_payment("fixture")
    with pytest.raises(RuntimeError, match="禁止重复提交"):
        charter._charter_click_call_and_select_payment("fixture")
    charter._android_click_confirm_call.assert_called_once()
    charter._android_click_refreshed_estimate_call.assert_not_called()
    charter._android_reselect_refreshed_estimate.assert_not_called()
    charter._android_select_payment.assert_not_called()
    charter._android_click_confirm_pay.assert_not_called()
    charter._android_pay.assert_not_called()


@pytest.mark.parametrize("stage", ["call", "confirm", "channel"])
def test_charter_uncertain_submission_cannot_be_repeated(charter, stage):
    charter._android_wait_order_result.side_effect = ["cashier", "success"]
    action = {"call": charter._android_click_confirm_call,
              "confirm": charter._android_click_confirm_pay,
              "channel": charter._android_pay}[stage]
    action.side_effect = TimeoutError("fixture-unknown")
    with pytest.raises(TimeoutError, match="fixture-unknown"):
        charter._charter_click_call_and_select_payment("fixture")
    with pytest.raises(RuntimeError, match="禁止重复提交"):
        charter._charter_click_call_and_select_payment("fixture")
    charter._android_click_confirm_call.assert_called_once()
    assert charter._android_click_confirm_pay.call_count == (0 if stage == "call" else 1)
    assert charter._android_pay.call_count == (1 if stage == "channel" else 0)
    if stage != "call":
        with pytest.raises(RuntimeError, match="禁止重复提交"):
            charter._submit_prepayment_once("fixture")
        charter._android_click_confirm_pay.assert_called_once()


def test_charter_success_uses_one_call_and_one_prepayment(charter):
    charter._android_wait_order_result.side_effect = ["cashier", "success"]
    assert charter._charter_click_call_and_select_payment("fixture") is True
    charter._android_click_confirm_call.assert_called_once_with("fixture")
    charter._android_click_confirm_pay.assert_called_once_with("fixture")
    charter._android_pay.assert_called_once_with("fixture", payment=charter.PAYMENT, stage="submitted")
    with pytest.raises(RuntimeError, match="禁止重复提交"):
        charter._submit_prepayment_once("fixture")
    charter._android_click_confirm_pay.assert_called_once()


def test_prepayment_requires_this_scene_creation(charter):
    with pytest.raises(RuntimeError, match="尚未发起"):
        charter._submit_prepayment_once("fixture")
    charter._android_click_confirm_pay.assert_not_called()


def test_charter_payment_result_unknown_cannot_create_again(charter):
    charter._android_wait_order_result.side_effect = ["cashier", "timeout"]
    assert charter._charter_click_call_and_select_payment("fixture") is False
    with pytest.raises(RuntimeError, match="禁止重复提交"):
        charter._charter_click_call_and_select_payment("fixture")
    charter._android_click_confirm_call.assert_called_once()
    charter._android_click_confirm_pay.assert_called_once()
    charter._android_pay.assert_called_once()


def passenger_case(texts):
    case = object.__new__(AndroidOrderBase)
    case.client = Mock(return_value=SimpleNamespace(exists=True))
    case._assert_passenger_foreground = Mock()
    case._android_get_all_texts = Mock(return_value=texts)
    case._click_text = Mock()
    case._android_click_dialog_button = Mock()
    return case


@pytest.mark.parametrize("texts", [["取消訂單"], ["確認支付"], ["费用明细"], ["未完成訂單"]])
def test_existing_orders_are_never_cancelled_or_paid(texts):
    case = passenger_case(texts)
    with pytest.raises(RuntimeError, match="禁止自动取消或付款"):
        case._clear_waiting_order("fixture")
    case._click_text.assert_not_called()
    case._android_click_dialog_button.assert_not_called()


def test_clean_home_is_allowed_without_clicks():
    case = passenger_case(["首頁"])
    assert case._clear_waiting_order("fixture") is None
    case._click_text.assert_not_called()
    case._android_click_dialog_button.assert_not_called()


@pytest.mark.parametrize("method,args", [
    (AndroidOrderMixin._android_handle_unfinished_order_popup, ("fixture",)),
    (AndroidOrderMixin._cancel_mismatched_driver_order, ("fixture", 1, 3)),
    (target_order.AndroidTargetDriverUIFlow.finish_non_target, (100,)),
    (target_order.AndroidTargetOrderBase._complete_legacy_passenger_order, ("fixture",)),
])
def test_unsafe_entrypoints_stop_without_any_action(method, args):
    case = Mock()
    with pytest.raises(RuntimeError, match="禁止"):
        method(case, *args)
    assert case.mock_calls == []


def test_target_run_without_target_never_delegates(monkeypatch):
    case = object.__new__(target_order.AndroidTargetDriverUIFlow)
    case.target_order_no = None
    run = Mock()
    monkeypatch.setattr(target_order.DriverUIFlow, "run", run)
    with pytest.raises(ValueError, match="目标订单号无效"):
        case.run()
    run.assert_not_called()


@pytest.mark.parametrize("observed", ["", "CD1234567890"])
def test_target_identity_checked_before_accept(observed):
    case = object.__new__(target_order.AndroidTargetDriverUIFlow)
    case.target_order_no = "AB1234567890"
    case.completed_before_run = set()
    case._activate_driver_app = Mock()
    root = normalized_tree(
        f'<hierarchy><node class="android.widget.TextView" text="{observed}" '
        'bounds="[0,0][300,40]"/></hierarchy>', "fixture")
    case.wait_for = Mock(return_value=(root, "offer"))
    case._run_remaining = Mock()
    with pytest.raises(RuntimeError):
        case.accept_and_identify(100)
    case._run_remaining.assert_not_called()


def test_target_run_mismatch_never_advances_or_listens():
    case = object.__new__(target_order.AndroidTargetDriverUIFlow)
    case.target_order_no = "AB1234567890"
    case.args = SimpleNamespace(timeout=10)
    case.accept_and_identify = Mock(return_value="CD1234567890")
    case._run_remaining = Mock()
    case.finish_non_target = Mock()
    case.return_to_listening = Mock()
    with pytest.raises(RuntimeError, match="非目标订单"):
        case.run()
    case._run_remaining.assert_not_called()
    case.finish_non_target.assert_not_called()
    case.return_to_listening.assert_not_called()


def driver_action_tree(order_no="AB1234567890", label="接單", *, slider=False, thumb=True):
    identity = (f'<node class="android.widget.TextView" text="{order_no}" '
                'bounds="[0,0][300,40]"/>')
    button = (f'<node class="android.widget.Button" text="{label}" '
              'bounds="[200,100][300,140]"/>')
    if slider:
        image = ('<node class="android.widget.ImageView" bounds="[10,100][40,130]"/>'
                 if thumb else "")
        button = ('<node class="android.widget.LinearLayout" resource-id="fixture:id/ll_drag_view" '
                  'bounds="[0,100][500,160]">' + button + image + '</node>')
    return normalized_tree("<hierarchy>" + identity + button + "</hierarchy>", "fixture")


@pytest.fixture
def target_driver():
    case = object.__new__(target_order.AndroidTargetDriverUIFlow)
    case.target_order_no = "AB1234567890"
    case.order_no = None
    case.completed_before_run = set()
    case.handling_non_target = False
    case.accept_labels = ("接單",)
    case.client = Mock()
    case.client.window_size.return_value = (500, 1000)
    case.root = Mock(return_value=driver_action_tree())
    case._activate_driver_app = Mock()
    case.resume_phase = None
    case.args = SimpleNamespace(timeout=10, step_timeout=5, dispatch_timeout=5,
                                stop_after="submitted", inspect=False)
    return case


def assert_no_driver_submission(case):
    case.client.click.assert_not_called()
    case.client.driver.execute_script.assert_not_called()


@pytest.mark.parametrize("observed", ["", "CD1234567890"])
def test_parent_run_cannot_accept_changed_offer(target_driver, observed):
    import time

    initial = driver_action_tree()
    changed = driver_action_tree(observed)
    target_driver.wait_for = Mock(side_effect=[(initial, "offer"), (changed, "offer")])
    with pytest.raises(RuntimeError):
        target_driver.accept_and_identify(time.monotonic() + 10)
    assert target_driver.wait_for.call_count == 2
    assert_no_driver_submission(target_driver)


@pytest.mark.parametrize("observed", ["", "CD1234567890"])
def test_action_fresh_page_must_still_match_target(target_driver, observed):
    target_driver.root.return_value = driver_action_tree(observed)
    with pytest.raises(RuntimeError):
        target_driver.act(driver_action_tree(), target_driver.accept_labels)
    assert_no_driver_submission(target_driver)


def test_slider_layout_reread_cannot_switch_orders(target_driver, monkeypatch):
    monkeypatch.setattr(target_order.time, "sleep", lambda seconds: None)
    initial = driver_action_tree(slider=True, thumb=False)
    changed = driver_action_tree("CD1234567890", slider=True)
    target_driver.root.side_effect = [initial, changed]
    with pytest.raises(RuntimeError):
        target_driver.act(initial, target_driver.accept_labels)
    assert target_driver.root.call_count == 2
    assert_no_driver_submission(target_driver)


@pytest.mark.parametrize("slider", [False, True])
@pytest.mark.parametrize("raises", [False, True])
def test_target_accept_is_single_submission_even_after_error(target_driver, slider, raises):
    root = driver_action_tree(slider=slider)
    target_driver.root.return_value = root
    action = target_driver.client.driver.execute_script if slider else target_driver.client.click
    if raises:
        action.side_effect = TimeoutError("fixture-driver-unknown")
        with pytest.raises(TimeoutError, match="fixture-driver-unknown"):
            target_driver.act(root, target_driver.accept_labels)
    else:
        target_driver.act(root, target_driver.accept_labels)
    action.assert_called_once()
    with pytest.raises(RuntimeError, match="禁止重复提交"):
        target_driver.act(root, target_driver.accept_labels)
    action.assert_called_once()


def bill_tree(car_type, *, fare="5", surcharge="0", payment="現金", slider=False, thumb=True):
    root = driver_action_tree(label="確認收款", slider=slider, thumb=thumb)
    prefix = "com.sunlightmobility.driver:id/"
    common = (f'<node class="android.widget.TextView" text="{payment}" bounds="[0,40][150,80]"/>'
              '<node class="android.widget.TextView" text="確認賬單" bounds="[0,160][200,200]"/>')
    if car_type == "meter":
        fields = (f'<node class="android.widget.EditText" resource-id="{prefix}et_input_fee" '
                  f'text="{fare}" bounds="[0,200][200,240]"/>'
                  f'<node class="android.widget.EditText" resource-id="{prefix}et_input_other_fee" '
                  f'text="{surcharge}" bounds="[0,240][200,280]"/>')
    else:
        fields = (f'<node class="android.widget.LinearLayout" resource-id="{prefix}cl_fixed_price" '
                  'bounds="[0,200][400,300]">'
                  f'<node class="android.widget.TextView" resource-id="{prefix}tv_fixed_price_title" '
                  'text="車費" bounds="[0,200][100,240]"/>'
                  f'<node class="android.widget.LinearLayout" resource-id="{prefix}ll_fixed_price_amount" '
                  'bounds="[100,200][400,240]">'
                  f'<node class="android.widget.TextView" resource-id="{prefix}tv_fixed_price_amount" '
                  f'text="{fare}" bounds="[100,200][200,240]"/>'
                  f'<node class="android.widget.TextView" resource-id="{prefix}tv_fixed_price_unit" '
                  'text="HKD" bounds="[200,200][300,240]"/></node></node>')
    root.extend(normalized_tree("<hierarchy>" + common + fields + "</hierarchy>", "fixture"))
    return root


@pytest.fixture(params=["meter", "charter"])
def bill_driver(target_driver, request):
    target_driver.order_no = target_driver.target_order_no
    target_driver.args.car_type = request.param
    target_driver.args.payment = "cash"
    target_driver.args.cash_collected = True
    target_driver.args.fare = "5"
    target_driver.args.surcharge = "0"
    target_driver.bill_total = Decimal("5")
    target_driver.deadline = None
    target_driver.root.return_value = bill_tree(request.param)
    return target_driver


@pytest.mark.parametrize("slider", [False, True])
@pytest.mark.parametrize("raises", [False, True])
def test_target_bill_action_is_single_submission(bill_driver, slider, raises):
    root = bill_tree(bill_driver.args.car_type, slider=slider)
    bill_driver.root.return_value = root
    action = bill_driver.client.driver.execute_script if slider else bill_driver.client.click
    if raises:
        action.side_effect = TimeoutError("fixture-bill-unknown")
        with pytest.raises(TimeoutError, match="fixture-bill-unknown"):
            bill_driver.act(root, target_order.ACTION_LABELS["bill"])
    else:
        bill_driver.act(root, target_order.ACTION_LABELS["bill"])
    action.assert_called_once()
    with pytest.raises(RuntimeError, match="禁止重复提交"):
        bill_driver.act(root, target_order.ACTION_LABELS["bill"])
    action.assert_called_once()


@pytest.mark.parametrize("change", [{"fare": "6"}, {"payment": ""}, {"payment": "現金支付"}])
@pytest.mark.parametrize("layout_reread", [False, True])
def test_refreshed_bill_must_match_amount_and_payment(bill_driver, monkeypatch, change, layout_reread):
    monkeypatch.setattr(target_order.time, "sleep", lambda seconds: None)
    original = bill_tree(bill_driver.args.car_type, slider=layout_reread, thumb=False)
    changed = bill_tree(bill_driver.args.car_type, slider=layout_reread, **change)
    bill_driver.root.side_effect = [original, changed] if layout_reread else [changed]
    with pytest.raises(RuntimeError):
        bill_driver.act(original, target_order.ACTION_LABELS["bill"])
    assert_no_driver_submission(bill_driver)
    assert not getattr(bill_driver, "_target_submissions", set())
    assert bill_driver._bill_action_snapshot is None


@pytest.mark.parametrize("change", [{"fare": "4", "surcharge": "1"}, {"surcharge": "1"}])
def test_meter_components_cannot_change_even_if_total_matches(target_driver, change):
    case = target_driver
    case.order_no = case.target_order_no
    case.args.car_type, case.args.payment = "meter", "cash"
    case.args.cash_collected, case.args.fare, case.args.surcharge = True, "5", "0"
    case.bill_total = Decimal("5")
    case.root.return_value = bill_tree("meter", **change)
    with pytest.raises(RuntimeError, match="不符合预期"):
        case.act(bill_tree("meter"), target_order.ACTION_LABELS["bill"])
    assert_no_driver_submission(case)


@pytest.mark.parametrize("payment", ["", "現金"])
def test_online_bill_without_confirmed_positive_ui_contract_is_blocked(bill_driver, payment):
    bill_driver.args.payment = "online"
    root = bill_tree(bill_driver.args.car_type, payment=payment)
    with pytest.raises(RuntimeError, match="正向标识尚未核实|支付方式不符"):
        bill_driver.act(root, target_order.ACTION_LABELS["bill"])
    assert_no_driver_submission(bill_driver)


def test_cash_receipt_must_be_explicit(bill_driver):
    bill_driver.args.cash_collected = False
    with pytest.raises(RuntimeError, match="实际收款确认缺失"):
        bill_driver.act(bill_tree(bill_driver.args.car_type), target_order.ACTION_LABELS["bill"])
    assert_no_driver_submission(bill_driver)


@pytest.mark.parametrize("total", [None, Decimal("NaN"), Decimal("6")])
def test_missing_or_wrong_verified_total_blocks_submission(bill_driver, total):
    bill_driver.bill_total = total
    with pytest.raises(RuntimeError):
        bill_driver.act(bill_tree(bill_driver.args.car_type), target_order.ACTION_LABELS["bill"])
    assert_no_driver_submission(bill_driver)


def test_full_bill_flow_rechecks_after_parent_validation(bill_driver):
    original = bill_tree(bill_driver.args.car_type)
    changed = bill_tree(bill_driver.args.car_type, fare="6")
    bill_driver.fill = Mock()
    bill_driver.dismiss_keyboard = Mock()
    bill_driver.wait_for = Mock()
    bill_driver.root.side_effect = [original, original, changed]
    with pytest.raises(RuntimeError):
        bill_driver.submit_bill(original)
    assert_no_driver_submission(bill_driver)
    bill_driver.wait_for.assert_not_called()


def test_full_bill_flow_accepts_unchanged_valid_cash_bill_once(bill_driver):
    root = bill_tree(bill_driver.args.car_type)
    bill_driver.root.return_value = root
    bill_driver.fill = Mock()
    bill_driver.dismiss_keyboard = Mock()
    bill_driver.wait_for = Mock()
    bill_driver.submit_bill(root)
    bill_driver.client.click.assert_called_once()
    bill_driver.wait_for.assert_called_once_with({"unpaid", "complete"})
    with pytest.raises(RuntimeError, match="禁止重复提交"):
        bill_driver.submit_bill(root)
    bill_driver.client.click.assert_called_once()


def test_bill_identity_is_checked_before_fields_are_processed(target_driver, monkeypatch):
    target_driver.order_no = target_driver.target_order_no
    target_driver.root.return_value = driver_action_tree("CD1234567890", label="確認收款")
    parent = Mock()
    monkeypatch.setattr(target_order.AndroidDriverUIFlow, "submit_bill", parent)
    with pytest.raises(RuntimeError):
        target_driver.submit_bill(driver_action_tree(label="確認收款"))
    parent.assert_not_called()
    assert_no_driver_submission(target_driver)


def test_rejected_offer_does_not_mark_unsubmitted_action(target_driver):
    with pytest.raises(RuntimeError):
        target_driver.act(driver_action_tree("CD1234567890"), target_driver.accept_labels)
    target_driver.act(driver_action_tree(), target_driver.accept_labels)
    target_driver.client.click.assert_called_once()


def test_offline_preparation_is_not_an_order_submission(target_driver):
    target_driver.target_order_no = None
    target_driver.detect_phase = Mock(return_value="offline")
    root = driver_action_tree(order_no="", label="點擊出車")
    target_driver.root.return_value = root
    target_driver.act(root, target_order.ACTION_LABELS["offline"])
    target_driver.client.click.assert_called_once()
    assert not getattr(target_driver, "_target_submissions", set())


def navigation_tree(label, phase, order_no=""):
    """仅构造现有识别器的输入；不是实际页面证据或业务规则来源。"""
    root = driver_action_tree(order_no=order_no, label=label)
    texts = {"online": ["接單中"], "offline": ["點擊出車"], "offer": ["接單"],
             "unpaid": ["已完成", "未支付"], "complete": ["已完成", "已支付"],
             "cancelled": ["已取消"], "pickup": ["到達上車地點"], "unknown": []}[phase]
    nodes = "".join(f'<node class="android.widget.TextView" text="{text}" '
                    'bounds="[0,300][200,340]"/>' for text in texts)
    root.extend(normalized_tree("<hierarchy>" + nodes + "</hierarchy>", "fixture"))
    return root


@pytest.fixture
def navigation_driver(target_driver):
    case = target_driver
    case.order_no = case.target_order_no
    case.awaiting_new_order = False
    case.args.payment_timeout = 5
    case.args.interval = 0
    case.snapshot = Mock()
    return case


@pytest.mark.parametrize("phase", ["online", "offline", "offer"])
def test_bound_history_navigation_does_not_require_order_on_home(navigation_driver, phase):
    case = navigation_driver
    root = navigation_tree("我的行程", phase)
    case.root.return_value = root
    case.act(root, ("我的行程",))
    case.client.click.assert_called_once()
    case.client.driver.execute_script.assert_not_called()
    assert not getattr(case, "_target_submissions", set())
    assert case.order_no == case.target_order_no


@pytest.mark.parametrize("phase", ["unpaid", "pickup", "unknown", "cancelled"])
def test_history_navigation_requires_actual_home_stage(navigation_driver, phase):
    root = navigation_tree("我的行程", phase, navigation_driver.order_no)
    with pytest.raises(RuntimeError, match="司机首页"):
        navigation_driver.act(root, ("我的行程",))
    assert_no_driver_submission(navigation_driver)


@pytest.mark.parametrize("state", ["unbound", "different", "old", "awaiting", "non_target"])
def test_history_navigation_never_weakens_target_ownership(navigation_driver, state):
    case = navigation_driver
    if state == "unbound":
        case.order_no = None
    elif state == "different":
        case.order_no = "CD1234567890"
    elif state == "old":
        case.completed_before_run.add(case.order_no)
    elif state == "awaiting":
        case.awaiting_new_order = True
    else:
        case.handling_non_target = True
    with pytest.raises(RuntimeError):
        case.act(navigation_tree("我的行程", "online"), ("我的行程",))
    assert_no_driver_submission(case)


def test_navigation_refresh_rechecks_stage(navigation_driver):
    case = navigation_driver
    initial = navigation_tree("我的行程", "online")
    case.root.return_value = navigation_tree("我的行程", "pickup", case.order_no)
    with pytest.raises(RuntimeError, match="司机首页"):
        case.act(initial, ("我的行程",))
    assert_no_driver_submission(case)


@pytest.mark.parametrize("invalid", ["duplicate", "disabled", "missing"])
def test_navigation_requires_unique_enabled_control(navigation_driver, invalid):
    case = navigation_driver
    root = navigation_tree("我的行程" if invalid != "missing" else "其他", "online")
    if invalid == "duplicate":
        root.extend(driver_action_tree(order_no="", label="我的行程"))
    elif invalid == "disabled":
        for node in root.iter():
            if node.get("label") == "我的行程":
                node.set("enabled", "false")
    case.root.return_value = root
    with pytest.raises(RuntimeError, match="导航控件"):
        case.act(root, ("我的行程",))
    assert_no_driver_submission(case)


@pytest.mark.parametrize("phase", ["unpaid", "complete"])
def test_current_completion_can_return_home(navigation_driver, phase):
    case = navigation_driver
    root = navigation_tree("返回首頁", phase, case.order_no)
    case.root.return_value = root
    case.act(root, ("返回首頁",))
    case.client.click.assert_called_once()
    assert not getattr(case, "_target_submissions", set())


@pytest.mark.parametrize("change", ["order", "phase"])
def test_completion_return_cannot_hide_another_order(navigation_driver, change):
    case = navigation_driver
    initial = navigation_tree("返回首頁", "unpaid", case.order_no)
    case.root.return_value = navigation_tree("返回首頁", "pickup" if change == "phase" else "unpaid",
                                            "CD1234567890" if change == "order" else case.order_no)
    with pytest.raises(RuntimeError):
        case.act(initial, ("返回首頁",))
    assert_no_driver_submission(case)


def test_startup_completed_order_return_preserves_exclusion(navigation_driver):
    case = navigation_driver
    old_no = case.order_no
    case.order_no = case.target_order_no = None
    completed = navigation_tree("返回首頁", "complete", old_no)
    home = navigation_tree("我的行程", "online")
    case.root.return_value = completed
    case.wait_for_entry_page = Mock(side_effect=[(completed, "complete"), (home, "online")])
    assert case.ensure_online(resume_existing=False) is False
    case.client.click.assert_called_once()
    assert case.order_no is None and case.target_order_no is None
    assert case.completed_before_run == {old_no}
    assert case._paid_exit_order_no is None
    assert case.awaiting_new_order is True


@pytest.mark.parametrize("failure", ["switched", "unpaid", "unregistered", "cancelled"])
def test_startup_return_is_not_generic_old_order_bypass(navigation_driver, failure):
    case = navigation_driver
    old_no = case.order_no
    case.order_no = case.target_order_no = None
    if failure != "unregistered":
        case.completed_before_run.update({old_no, "CD1234567890"})
    initial = navigation_tree("返回首頁", "complete", old_no)
    phase = failure if failure in ("unpaid", "cancelled") else "complete"
    case.root.return_value = navigation_tree("返回首頁", phase,
                                            "CD1234567890" if failure == "switched" else old_no)
    with pytest.raises(RuntimeError):
        case.act(initial, ("返回首頁", "返回", "ca_icon_back_black", "ca icon back black"))
    assert_no_driver_submission(case)
    assert case.order_no is None


def history_tree(order_no):
    prefix = "com.sunlightmobility.driver:id/"
    return normalized_tree(
        '<hierarchy><node class="android.widget.TextView" '
        f'resource-id="{prefix}tv_bar_title" text="我的行程" bounds="[0,0][300,60]"/>'
        f'<node class="android.widget.LinearLayout" resource-id="{prefix}rl_order_list" '
        'bounds="[0,100][500,800]">'
        f'<node class="android.widget.TextView" resource-id="{prefix}tv_order_id" '
        f'text="{order_no}" bounds="[0,100][300,150]"/></node></hierarchy>', "fixture")


@pytest.mark.parametrize("card_changes", [False, True])
def test_payment_verification_uses_home_then_exact_history_card(navigation_driver, card_changes):
    """执行原wait_completed与原历史选单方法；仅设备读取/等待、原生元素为替身。"""
    case = navigation_driver
    unpaid = navigation_tree("返回首頁", "unpaid", case.order_no)
    home = navigation_tree("我的行程", "online")
    paid = navigation_tree("返回首頁", "complete", case.order_no)
    case.wait_for = Mock(side_effect=[(unpaid, "unpaid"), (home, "online")])
    case.root.side_effect = [unpaid, home, home, history_tree(case.order_no), paid]
    card = Mock()
    card.is_displayed.return_value = card.is_enabled.return_value = True
    card.find_elements.return_value = [SimpleNamespace(text="CD1234567890" if card_changes else case.order_no)]
    case.client.driver.find_elements.return_value = [card]
    if card_changes:
        with pytest.raises(RuntimeError, match="卡片已改变"):
            case.wait_completed()
        card.click.assert_not_called()
        case.snapshot.assert_not_called()
    else:
        case.wait_completed()
        card.click.assert_called_once()
        assert case.last_phase == "complete"
        case.snapshot.assert_called_once_with("completed_paid")
    assert case.client.click.call_count == 2
    selector = case.client.driver.find_elements.call_args.args[1]
    assert "@text='AB1234567890'" in selector
    assert "rl_order_list" in selector and "tv_order_id" in selector
    case.client.driver.execute_script.assert_not_called()
    assert not getattr(case, "_target_submissions", set())


@pytest.mark.parametrize("observed", ["AB1234567890", "CD1234567890"])
def test_expand_reads_target_only_and_returns_without_business_action(navigation_driver, observed):
    import time

    case = navigation_driver
    overview = navigation_tree("展開", "pickup")
    detail = driver_action_tree(order_no=observed, label="详情")
    case.deadline = time.monotonic() + 5
    case.root.side_effect = [overview, overview, detail]
    case.wait_for = Mock(return_value=(overview, "pickup"))
    if observed == case.target_order_no:
        assert case.read_active_order() == observed
    else:
        with pytest.raises(RuntimeError, match="不是本轮目标订单"):
            case.read_active_order()
    case.client.click.assert_called_once()
    case.client.back.assert_called_once()
    case.wait_for.assert_called_once_with({"pickup"})
    case.client.driver.execute_script.assert_not_called()
    assert not getattr(case, "_target_submissions", set())


def test_registered_scenarios_resolve_to_real_version_directories():
    default = scenario_nodes()
    assert len(default) == 6
    assert all(Path(node.split("::")[0]).parent.name == "main_flow_cases" for node in default)
    optional = scenario_nodes(include_optional=True)
    assert all(Path(node.split("::")[0]).is_file() for node in optional)
    assert any(Path(node.split("::")[0]).parent.name == "passenger_v1_5_0" for node in optional)


@pytest.mark.parametrize("name", ["test_12_real_endpoint_display_in_expanded",
                                 "test_16_real_vehicle_image_color",
                                 "test_25_real_wait_for_accept_or_diagnose"])
def test_incomplete_ui_cases_cannot_report_local_contract_as_real_pass(name):
    module = importlib.import_module("cases.passenger_v1_6_0.JRYG_test_android_v160_ride_hailing")
    case = object.__new__(module.TestV160RideHailingDevice)
    method = getattr(type(case), name)
    assert any(mark.name == "skip" for mark in method.pytestmark)
    with pytest.raises(NotImplementedError):
        method(case)
