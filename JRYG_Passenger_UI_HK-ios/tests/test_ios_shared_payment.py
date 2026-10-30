"""香港iOS共用支付入口、预付/后付兼容和独立渠道场景回归。

验证公共基类可直接付款、订单兼容入口委托、预付不重复确认/回首页、现金
映射不变、默认目录不重复银行卡场景。所有渠道动作均Mock，不产生支付。
"""

import ast
from pathlib import Path
from unittest.mock import Mock

import pytest

from tests.test_driver_readiness import OrderBase, order_module
from ui_framework.JRYG_ios_payment import HKIOSPaymentMixin
from ui_framework.JRYG_ios_ui_base import iOSBase


@pytest.fixture
def passenger(monkeypatch):
    """不依赖订单子类的公共乘客实例，模拟两渠道与页面等待供直接调用测试。"""
    case = iOSBase()
    case.client = Mock()
    case.poco = Mock()
    case._ios_get_all_texts = Mock(return_value=["信用卡或扣帳卡", "Alipay HK", "確認支付5HKD"])
    case._ios_fill_bank_card_form = Mock(return_value=True)
    case._ios_complete_alipay_payment = Mock()
    case._ios_back_to_home = Mock()
    monkeypatch.setattr(order_module.time, "sleep", lambda seconds: None)
    return case


def test_common_payment_available_to_every_hk_ios_base():
    """验证乘客基类和订单基类继承同一个支付实现，不在订单类中复制渠道方法。"""
    assert iOSBase._ios_pay is HKIOSPaymentMixin._ios_pay
    assert OrderBase._ios_pay is iOSBase._ios_pay
    # 比较方法对象身份，防止出现同名但独立维护的重复支付实现。
    for method in ("_ios_complete_alipay_payment", "_ios_safari_click_by_text", "_ios_wait_and_close_safari_alert", "_ios_back_to_home"):
        assert method not in OrderBase.__dict__
        assert getattr(OrderBase, method) is getattr(HKIOSPaymentMixin, method)


@pytest.mark.parametrize("channel", ["bankcard", "alipay"])
def test_non_order_passenger_directly_calls_shared_postpayment(passenger, channel):
    """验证普通乘客基类无需订单参数即可调用后付入口，且只执行指定渠道。

    :param passenger: 已模拟设备及渠道动作的乘客实例。
    :param channel: 后付渠道，bankcard为银行卡，alipay为Alipay HK。
    """
    assert passenger._ios_pay("test", payment=channel) is True
    expected = "信用卡或扣帳卡" if channel == "bankcard" else "Alipay HK"
    assert passenger.client.call_args_list[0].kwargs == {"textContains": expected}
    if channel == "bankcard":
        passenger._ios_fill_bank_card_form.assert_called_once_with("test")
        passenger._ios_complete_alipay_payment.assert_not_called()
        passenger._ios_back_to_home.assert_called_once_with("test")
    else:
        passenger._ios_complete_alipay_payment.assert_called_once_with("test")
        passenger._ios_fill_bank_card_form.assert_not_called()
    # 共用入口不能依赖订单子类的PAYMENT属性才能工作。
    assert "PAYMENT" not in vars(passenger)


@pytest.mark.parametrize("submitted", [True, False])
def test_prepaid_bankcard_never_reselects_or_returns_home(passenger, submitted):
    """预付已确认后只处理银行卡表单，并原样返回提交结果，不重选或回首页。

    :param passenger: 模拟银行卡渠道的乘客实例。
    :param submitted: 银行卡表单返回值，分别覆盖提交和未出现表单两种情况。
    """
    passenger._ios_fill_bank_card_form.return_value = submitted
    assert passenger._ios_pay("test", payment="bankcard", stage="submitted") is submitted
    passenger._ios_fill_bank_card_form.assert_called_once_with("test")
    # 不再次读取费用页或点击渠道，否则可能重复确认预付订单。
    passenger.client.assert_not_called()
    passenger.poco.assert_not_called()
    passenger._ios_get_all_texts.assert_not_called()
    passenger._ios_back_to_home.assert_not_called()


def test_submitted_alipay_only_delegates_current_channel(passenger):
    """已打开Alipay支付页时仅委托渠道步骤，返回App后不得提前返回首页。

    :param passenger: 已模拟Alipay渠道调用的乘客实例。
    """
    passenger._ios_pay("test", payment="alipay", stage="submitted")
    passenger._ios_complete_alipay_payment.assert_called_once_with("test", return_home=False)
    passenger.client.assert_not_called()
    passenger._ios_back_to_home.assert_not_called()


@pytest.mark.parametrize("channel,stage", [("cash", "postpaid"), ("unknown", "postpaid"), ("bankcard", "unknown")])
def test_bad_channel_or_stage_stops_before_any_ui(passenger, channel, stage):
    """非法渠道或阶段必须在任何设备动作、卡表单或Alipay调用前被拒绝。

    :param passenger: 用于检查无副作用的模拟乘客实例。
    :param channel: 不支持的渠道，或与非法阶段组合的银行卡渠道。
    :param stage: 待校验的支付阶段。
    """
    with pytest.raises(ValueError):
        passenger._ios_pay("test", payment=channel, stage=stage)
    passenger.client.assert_not_called()
    passenger._ios_fill_bank_card_form.assert_not_called()
    passenger._ios_complete_alipay_payment.assert_not_called()


@pytest.mark.parametrize("channel", ["bankcard", "alipay"])
def test_existing_order_and_cleanup_entry_delegates_common_payment(channel):
    """正常订单和清理流程使用的兼容入口应委托共用支付，不改下单方式。

    :param channel: 本次电子支付订单的后付渠道。
    """
    case = OrderBase()
    case.CAR_TYPE, case.PAYMENT, case.FINAL_PAYMENT = "meter", "epayment", channel
    case._ios_pay = Mock(return_value=True)
    assert case._ios_complete_payment("legacy") is True
    case._ios_pay.assert_called_once_with("legacy", payment=channel)
    # FINAL_PAYMENT仅控制后付，不能反向改写下单时的电子支付选项。
    assert case.PAYMENT == "epayment"


def test_cash_does_not_enter_online_payment():
    """现金场景保留返回首页路径，不调用银行卡或Alipay线上支付入口。"""
    case = OrderBase()
    case.CAR_TYPE, case.PAYMENT = "meter", "cash"
    case._ios_pay = Mock()
    case._ios_back_to_home = Mock(return_value=True)
    assert case._ios_complete_payment("cash") is True
    case._ios_back_to_home.assert_called_once_with("cash")
    case._ios_pay.assert_not_called()


@pytest.mark.parametrize("channel,present", [("bankcard", True), ("bankcard", False), ("alipay", True)])
def test_charter_prepaid_keeps_confirmation_then_shared_payment(monkeypatch, channel, present):
    """包车两渠道预付均先完成公共支付，返回App后才开始等待下单结果。

    :param monkeypatch: 替换等待，不运行真实预付流程。
    :param channel: 银行卡或Alipay HK预付渠道。
    :param present: 银行卡表单兼容返回值；Alipay必须在SUCCESS后返回。
    """
    case = OrderBase()
    case.CAR_TYPE, case.PAYMENT = "charter", channel
    case.client = Mock()
    # 用动作列表记录各步骤先后，而非只断言方法分别执行过。
    actions = []
    case._ios_click_confirm_call = Mock(side_effect=lambda tag: actions.append("call"))
    case._ios_get_all_texts = Mock(return_value=[order_module.E.CASHIER_PAGE_KEYWORDS[0]])
    case._ios_select_payment = Mock(side_effect=lambda *args, **kwargs: actions.append("select"))
    case._ios_screenshot = Mock()
    case._ios_click_confirm_pay = Mock(side_effect=lambda tag: actions.append("confirm"))
    case._ios_pay = Mock(side_effect=lambda *args, **kwargs: actions.append("shared_payment") or present)
    case._ios_is_login_page = Mock(return_value=False)
    case._ios_wait_order_result = Mock(side_effect=lambda *args, **kwargs: actions.append("wait_order") or "success")
    monkeypatch.setattr(order_module.time, "sleep", lambda seconds: None)
    assert case._charter_click_call_and_select_payment("prepaid") is True
    assert actions == ["call", "select", "confirm", "shared_payment", "wait_order"]
    # submitted表示调用方已经确认，付款封装不得重复点击确认支付。
    case._ios_pay.assert_called_once_with("prepaid", payment=channel, stage="submitted")


def test_charter_alipay_prepaid_failure_never_waits_for_order(monkeypatch):
    """预付支付宝弹窗或付款失败必须抛错，不进入下单轮询或重复确认。"""
    case = OrderBase()
    case.CAR_TYPE, case.PAYMENT = "charter", "alipay"
    case.client = Mock()
    case._ios_click_confirm_call = Mock()
    case._ios_get_all_texts = Mock(return_value=[order_module.E.CASHIER_PAGE_KEYWORDS[0]])
    case._ios_select_payment = Mock()
    case._ios_screenshot = Mock()
    case._ios_click_confirm_pay = Mock()
    case._ios_pay = Mock(side_effect=TimeoutError("Safari弹窗未稳定消失"))
    case._ios_wait_order_result = Mock()
    monkeypatch.setattr(order_module.time, "sleep", lambda seconds: None)
    with pytest.raises(TimeoutError, match="弹窗未稳定消失"):
        case._charter_click_call_and_select_payment("prepaid")
    case._ios_click_confirm_pay.assert_called_once_with("prepaid")
    case._ios_pay.assert_called_once_with("prepaid", payment="alipay", stage="submitted")
    case._ios_wait_order_result.assert_not_called()


def test_separate_epayment_cases_share_everything_except_channel():
    """银行卡与Alipay后付用例只改变渠道，车型、下单方式和公共方法均相同。"""
    from cases.JRYG_test_ios_meter_epayment_alipay_order import TestMeterEpaymentAlipay
    from cases.JRYG_test_ios_meter_epayment_bankcard_order import TestMeterEpaymentBankcard

    assert TestMeterEpaymentBankcard.PAYMENT == TestMeterEpaymentAlipay.PAYMENT == "epayment"
    assert TestMeterEpaymentBankcard.CAR_TYPE == TestMeterEpaymentAlipay.CAR_TYPE == "meter"
    assert TestMeterEpaymentBankcard().final_payment == "bankcard"
    assert TestMeterEpaymentAlipay().final_payment == "alipay"
    assert TestMeterEpaymentBankcard.test_order_flow is TestMeterEpaymentAlipay.test_order_flow
    assert TestMeterEpaymentBankcard._ios_pay is TestMeterEpaymentAlipay._ios_pay


@pytest.mark.parametrize("module,class_name,car,payment", [
    ("JRYG_test_ios_meter_cash_order", "TestMeterCash", "meter", "cash"),
    ("JRYG_test_ios_meter_alipay_order", "TestMeterAlipay", "meter", "alipay"),
    ("JRYG_test_ios_charter_alipay_order", "TestCharterAlipay", "charter", "alipay"),
    ("JRYG_test_ios_charter_bankcard_order", "TestCharterBankcard", "charter", "bankcard"),
])
def test_other_scenario_payment_mapping_is_unchanged(module, class_name, car, payment):
    """公共支付封装不得改写现金、直接Alipay及包车场景的原有配置。

    :param module: 用例模块名，不含cases包前缀。
    :param class_name: 模块中待检查的用例类名。
    :param car: 原有车型标识。
    :param payment: 原有下单与默认后付方式。
    """
    from importlib import import_module

    cls = getattr(import_module("cases." + module), class_name)
    assert cls.CAR_TYPE == car
    assert cls.PAYMENT == payment
    assert cls().final_payment == payment


@pytest.mark.parametrize("payment", ["cash", "epayment", "bankcard", "alipay"])
def test_supported_order_setup_still_connects_device(monkeypatch, payment):
    class SupportedOrder(OrderBase):
        PAYMENT = payment

    device_setup = Mock()
    monkeypatch.setattr(iOSBase, "setup_class", device_setup)
    SupportedOrder.setup_class()
    device_setup.assert_called_once_with()


def test_runner_selects_two_explicit_channels_without_legacy_duplicate():
    """运行器分别选择两个独立后付文件，排除旧银行卡入口以避免重复下单。"""
    root = Path(__file__).resolve().parents[1]
    # 静态解析运行器，不导入或执行可能创建订单的主入口。
    tree = ast.parse((root / "runners/JRYG_run_main_ios.py").read_text())
    names = [node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)]
    assert names.count("JRYG_test_ios_meter_epayment_bankcard_order.py") == 1
    assert names.count("JRYG_test_ios_meter_epayment_alipay_order.py") == 1
    assert "JRYG_test_ios_meter_epayment_order.py" not in names


def test_shared_safari_uses_actual_passenger_client_source(passenger):
    """Safari定位读取当前乘客客户端XML，不能使用固定端口或另一设备的页面。

    :param passenger: 页面源码读取方法已被模拟的乘客实例。
    """
    passenger.client.source.return_value = "<root />"
    assert passenger._ios_get_source_xml() == "<root />"
    passenger.client.source.assert_called_once_with(format="xml")


def test_shared_safari_source_failure_keeps_original_empty_result(passenger):
    """设备源码读取失败时保持空字符串契约，由调用方判断定位失败或重试。

    :param passenger: 用于模拟设备不可用异常的乘客实例。
    """
    passenger.client.source.side_effect = RuntimeError("device unavailable")
    assert passenger._ios_get_source_xml() == ""
