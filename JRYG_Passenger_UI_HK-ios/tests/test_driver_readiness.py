"""双端全 UI 订单衔接回归；不连接设备或司机业务服务。

替换设备和各业务步骤为Mock，断言司机出车→乘客下单→司机账单→乘客付款
→司机同订单核验。银行卡与Alipay后付共用顺序，仅接单调试不得提交账单或支付。
"""

import ast
from pathlib import Path
from unittest.mock import Mock

import pytest

from ui_framework import JRYG_order_flow as order_module

BASE_DIR = Path(__file__).resolve().parents[1]
OrderBase = order_module.TestOrderBase


@pytest.fixture
def order(monkeypatch):
    """隔离5+0测试账单与双端动作，用模拟订单实例验证编排而不连接设备。"""
    instance = OrderBase()
    instance.CAR_TYPE = "meter"
    instance.PAYMENT = "epayment"
    instance.client = Mock()
    instance.driver_ui = Mock(last_phase="unpaid", order_no="26A4J04WECNY")
    for name in ("_driver_ui_go_online", "_ui_cleanup_ongoing_order", "_ios_launch_setup_and_addresses",
                 "_ios_select_car_type", "_ios_select_payment", "_ios_screenshot", "_driver_ui_grab_and_flow",
                 "_ios_complete_payment", "_ios_back_to_home"):
        setattr(instance, name, Mock())
    instance._click_call_and_check_login_then_retry = Mock(return_value=True)
    instance._charter_click_call_and_select_payment = Mock(return_value=True)
    instance._ios_get_all_texts = Mock(return_value=["確認支付5HKD"])
    monkeypatch.setenv("HK_ORDER_AMOUNT", "5")
    monkeypatch.setenv("HK_OTHER_AMOUNT", "0")
    monkeypatch.setattr(order_module.time, "sleep", lambda seconds: None)
    return instance


@pytest.mark.parametrize("final_payment", ["", "bankcard", "alipay"])
def test_driver_then_passenger_then_driver_then_payment_order(order, final_payment):
    order.FINAL_PAYMENT = final_payment
    actions = []
    order._driver_ui_go_online.side_effect = lambda tag: actions.append("driver_online")
    order._ui_cleanup_ongoing_order.side_effect = lambda tag: actions.append("passenger_cleanup")
    order._ios_launch_setup_and_addresses.side_effect = lambda *args: actions.append("passenger_addresses")
    order._click_call_and_check_login_then_retry.side_effect = lambda tag: actions.append("passenger_order") or True
    order._driver_ui_grab_and_flow.side_effect = lambda tag: actions.append("driver_trip")
    order.client.app_activate.side_effect = lambda bundle: actions.append("passenger_foreground")
    order._ios_complete_payment.side_effect = lambda tag: actions.append("passenger_payment")
    order.driver_ui.wait_completed.side_effect = lambda: actions.append("driver_paid_ui")
    order.test_order_flow()
    assert actions == ["driver_online", "passenger_cleanup", "passenger_addresses", "passenger_order",
                       "driver_trip", "passenger_foreground", "passenger_payment", "driver_paid_ui"]
    order._ios_select_payment.assert_called_once_with("打錶的士+電子支付" + (
        "+后付" + order_module.PAYMENT_LABELS[final_payment] if final_payment else ""), payment="epayment")
    assert "driver_api" not in vars(order)
    assert "socket_client" not in vars(order)


def test_passenger_failed_order_does_not_accept_driver_offer(order):
    order._click_call_and_check_login_then_retry.return_value = False
    with pytest.raises(AssertionError, match="下单失败"):
        order.test_order_flow()
    order._driver_ui_grab_and_flow.assert_not_called()


def test_failed_driver_ui_does_not_start_payment(order):
    order._driver_ui_grab_and_flow.side_effect = RuntimeError("UI 滑动失败")
    with pytest.raises(RuntimeError, match="UI 滑动失败"):
        order.test_order_flow()
    order._ios_complete_payment.assert_not_called()
    order.driver_ui.wait_completed.assert_not_called()


def test_payment_failure_does_not_mark_order_complete(order):
    order._ios_complete_payment.side_effect = RuntimeError("支付失败")
    with pytest.raises(RuntimeError, match="支付失败"):
        order.test_order_flow()
    order.driver_ui.wait_completed.assert_not_called()


def test_unpaid_driver_page_does_not_pass_final_verification(order):
    order.driver_ui.wait_completed.side_effect = TimeoutError("仍未支付")
    with pytest.raises(TimeoutError, match="仍未支付"):
        order.test_order_flow()


def test_charter_prepaid_order_uses_ui_without_repeat_payment(order):
    order.CAR_TYPE = "charter"
    order.PAYMENT = "bankcard"
    order._ios_get_all_texts.return_value = ["已支付"]
    order.test_order_flow()
    order._charter_click_call_and_select_payment.assert_called_once()
    order._ios_select_payment.assert_not_called()
    order._ios_complete_payment.assert_not_called()
    order.driver_ui.wait_completed.assert_called_once()


@pytest.mark.parametrize("method", ["_ios_click_confirm_call", "_ios_click_confirm_pay"])
def test_passenger_submission_only_calls_passenger_ui(monkeypatch, method):
    instance = OrderBase()
    click = Mock()
    monkeypatch.setattr(order_module.iOSBase, method, click)
    getattr(instance, method)("test")
    click.assert_called_once()
    assert not any(name.startswith("_driver_api_") for name in dir(OrderBase))


@pytest.mark.parametrize("file", ["ui_framework/JRYG_order_flow.py", "ui_framework/JRYG_driver_ui.py", "tools/JRYG_setup_driver.py", "ui_framework/JRYG_driver_runtime.py", "runners/JRYG_run_driver_flow.py"])
def test_ui_entrypoints_have_no_driver_business_api_imports(file):
    tree = ast.parse((BASE_DIR / file).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        names = [node.module or ""] if isinstance(node, ast.ImportFrom) else [alias.name for alias in node.names] if isinstance(node, ast.Import) else []
        assert not any("JRYG_Passenger_API_HK" in name or "JRYG_driver_order_api" in name for name in names)
    assert not (BASE_DIR / "ui_framework/JRYG_driver_order_api.py").exists()


def test_accept_debug_does_not_submit_bill_or_start_payment(order, monkeypatch):
    monkeypatch.setenv("HK_DRIVER_UI_STOP_AFTER", "accepted")
    order.driver_ui.last_phase = "pickup"
    order.test_order_flow()
    order._driver_ui_grab_and_flow.assert_called_once()
    order.driver_ui.snapshot.assert_called_once_with("accepted_order")
    order._ios_complete_payment.assert_not_called()
    order.driver_ui.wait_completed.assert_not_called()
    order.client.app_activate.assert_not_called()
