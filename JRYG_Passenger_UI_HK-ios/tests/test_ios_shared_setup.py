"""公共启动、地址配置和页面文本解析离线回归，不操作真机。

固定验证原有等待参数、起点后终点及当前页重选不重启App；文本解析与
IOSPage共用规则并使用实际调用客户端。所有设备动作均用Mock记录顺序。
"""

from unittest.mock import Mock

import pytest

from tests.test_driver_readiness import OrderBase, order_module
from ui_framework.JRYG_ios_ui_base import iOSBase
from ui_framework import JRYG_ios_ui_elements as E


@pytest.fixture
def passenger(monkeypatch):
    """提供无引导/广告的模拟乘客页面，替换等待以保证离线快速执行。"""
    case = iOSBase()
    case.client = Mock()
    case.client.return_value.exists = False
    case.poco = Mock()
    case.poco.return_value.exists.return_value = False
    case._ios_dismiss_privacy_agreement = Mock()
    monkeypatch.setattr(order_module.time, "sleep", Mock())
    return case


@pytest.mark.parametrize("launch_wait,alert_wait", [(10, 2), (8, 1)])
def test_shared_setup_preserves_action_and_wait_order(passenger, launch_wait, alert_wait):
    """正常下单和预清理仅等待参数不同，启动及遮挡处理顺序保持一致。"""
    actions = []
    passenger.client.home.side_effect = lambda: actions.append("home")
    passenger.client.session.side_effect = lambda bundle: actions.append("passenger")
    passenger.client.alert.accept.side_effect = lambda: actions.append("permission")
    passenger._ios_dismiss_privacy_agreement.side_effect = lambda: actions.append("privacy")
    passenger._ios_prepare_passenger_app("test", launch_wait=launch_wait, alert_wait=alert_wait)
    assert actions == ["home", "passenger", "permission", "privacy"]
    passenger.client.session.assert_called_once_with(E.PASSENGER_BUNDLE_ID)
    assert [call.args[0] for call in order_module.time.sleep.call_args_list] == [2, launch_wait, alert_wait]


def test_setup_permission_absent_still_handles_privacy(passenger):
    """无系统权限弹窗不阻断应用内隐私处理，也不追加权限等待。"""
    passenger.client.alert.accept.side_effect = RuntimeError("no alert")
    passenger._ios_prepare_passenger_app("test")
    passenger._ios_dismiss_privacy_agreement.assert_called_once()
    assert [call.args[0] for call in order_module.time.sleep.call_args_list] == [2, 10]


def test_setup_guide_is_bounded_and_closes_only_first_ad(passenger):
    """引导最多跳过五次，广告首次命中即停止，不重复点击页面遮挡。"""
    passenger.client.return_value.exists = True
    passenger.poco.return_value.exists.return_value = True
    passenger._ios_prepare_passenger_app("test")
    assert passenger.client.return_value.tap.call_count == 5
    passenger.poco.return_value.click.assert_called_once()
    assert passenger.poco.call_count == 1


def test_launch_entry_delegates_setup_before_addresses(passenger):
    """初次下单先完成启动准备，之后统一配置起终点。"""
    actions = []
    passenger._ios_prepare_passenger_app = Mock(side_effect=lambda tag: actions.append("setup"))
    passenger._ios_configure_addresses = Mock(side_effect=lambda *args: actions.append("addresses"))
    passenger._ios_launch_setup_and_addresses("test", "起点", "终点")
    assert actions == ["setup", "addresses"]
    passenger._ios_configure_addresses.assert_called_once_with("test", "起点", "终点")


def test_addresses_keep_start_then_destination_order(passenger):
    """公共地址入口原样传递起终点，不启动设备或混入车型选择。"""
    passenger._ios_search_address = Mock()
    passenger._ios_configure_addresses("test", "北角", "备选终点")
    assert [call.kwargs for call in passenger._ios_search_address.call_args_list] == [
        {"is_start": True, "address": "北角"}, {"is_start": False, "address": "备选终点"},
    ]
    passenger.client.home.assert_not_called()
    passenger.client.session.assert_not_called()


def test_failed_start_stops_before_destination(passenger):
    """起点失败不能继续终点或后续下单步骤。"""
    passenger._ios_search_address = Mock(side_effect=RuntimeError("start failed"))
    with pytest.raises(RuntimeError, match="start failed"):
        passenger._ios_configure_addresses("test", "起点", "终点")
    assert passenger._ios_search_address.call_count == 1


def test_current_page_recovery_calls_addresses_without_relaunch(passenger):
    """登录后恢复沿用当前页面，保留地址→等待→车型→付款的顺序。"""
    case = OrderBase()
    case.CAR_TYPE, case.PAYMENT = "meter", "epayment"
    case.client, case.poco = passenger.client, passenger.poco
    case._ios_ensure_monitor = Mock(return_value=Mock(inspect=Mock(return_value=Mock(state="address"))))
    actions = []
    case._ios_configure_addresses = Mock(side_effect=lambda *args: actions.append("addresses"))
    case._ios_select_car_type = Mock(side_effect=lambda *args, **kwargs: actions.append("car"))
    case._ios_select_payment = Mock(side_effect=lambda *args, **kwargs: actions.append("payment"))
    case._ios_re_setup_from_current_page("test", "起点", "备选终点")
    assert actions == ["addresses", "car", "payment"]
    case._ios_configure_addresses.assert_called_once_with("test", "起点", "备选终点")
    case.client.home.assert_not_called()
    case.client.session.assert_not_called()
    order_module.time.sleep.assert_called_once_with(7)


def test_current_page_failed_addresses_do_not_select_payment(passenger):
    """地址恢复失败即停止，不继续车型或付款。"""
    case = OrderBase()
    case.CAR_TYPE, case.PAYMENT = "meter", "epayment"
    case._ios_ensure_monitor = Mock(return_value=Mock(inspect=Mock(return_value=Mock(state="address"))))
    case._ios_configure_addresses = Mock(side_effect=RuntimeError("address failed"))
    case._ios_select_car_type, case._ios_select_payment = Mock(), Mock()
    with pytest.raises(RuntimeError, match="address failed"):
        case._ios_re_setup_from_current_page("test", "起点", "终点")
    case._ios_select_car_type.assert_not_called()
    case._ios_select_payment.assert_not_called()


def test_cleanup_delegates_setup_with_original_waits(passenger):
    """遗留订单清理仅共用启动步骤，仍由原编排处理订单和登录。"""
    case = OrderBase()
    case.CAR_TYPE, case.PAYMENT = "meter", "cash"
    case.client = passenger.client
    case._ios_prepare_passenger_app = Mock()
    case._ios_get_all_texts = Mock(return_value=["主頁"])
    case._ios_ensure_logged_in = Mock()
    case._ui_cleanup_ongoing_order("cleanup")
    case._ios_prepare_passenger_app.assert_called_once_with("cleanup", launch_wait=8, alert_wait=1)
    case._ios_ensure_logged_in.assert_called_once_with(tag="cleanup")


def test_text_reading_reuses_visible_deduplicated_page_rules(passenger):
    """只读取当前客户端，过滤隐藏文本并按label/name/value去重保序。"""
    passenger.client.source.return_value = '<root><node visible="true" label=" A " name="B" value="A"/><node visible="false" label="hidden"/><node label="C"/><node value=" "/></root>'
    assert passenger._ios_get_all_texts(passenger.client) == ["A", "B", "C"]
    passenger.client.source.assert_called_once_with(format="xml")


@pytest.mark.parametrize("source", ["", "invalid xml", "<root />"])
def test_bad_or_empty_page_texts_keep_empty_result(passenger, source):
    """坏XML、空页面沿用原空列表返回契约，不影响调用方重试策略。"""
    passenger.client.source.return_value = source
    assert passenger._ios_get_all_texts(passenger.client) == []


def test_page_source_failure_keeps_empty_result(passenger):
    """页面读取异常不返回其他设备的文本，留给调用方判断超时或失败。"""
    passenger.client.source.side_effect = RuntimeError("unavailable")
    assert passenger._ios_get_all_texts(passenger.client) == []
