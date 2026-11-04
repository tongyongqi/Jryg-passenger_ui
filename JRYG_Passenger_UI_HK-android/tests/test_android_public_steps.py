"""验证 Android 公共步骤被真实用例引用；离线替换 UI，不提交业务订单。"""

import ast
import importlib.util
from pathlib import Path
from unittest.mock import Mock, call

import pytest

from jryg_hk_android import JRYG_android_base as base
from jryg_hk_android import JRYG_android_passenger as passenger
from jryg_hk_android import JRYG_android_coupon as coupon
from jryg_hk_android.JRYG_android_order import AndroidOrderMixin
from jryg_hk_android.JRYG_android_payment import AndroidPaymentMixin
from jryg_hk_android.JRYG_shared_ios import ios_scenarios, shared_settings
from ui_framework.JRYG_ios_ui_base import iOSBase
from ui_framework.JRYG_ios_payment import HKIOSPaymentMixin

BASE_DIR = Path(__file__).resolve().parents[1]


def load_case(filename, name):
    """从指定用例文件动态加载测试类，供离线验证公共步骤复用。"""
    spec = importlib.util.spec_from_file_location("offline_" + filename, BASE_DIR / "cases" / "legacy" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, name)


CASES = [
    load_case("JRYG_test_open_and_login.py", "TestJRYGHKOneKeyLogin"),
    load_case("JRYG_test_open_and_route.py", "TestJRYGHKOpenAndRoute"),
    load_case("JRYG_test_open_app.py", "TestJRYGHKAndroidOrder"),
]


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.__name__)
def test_existing_cases_use_same_public_passenger_implementation(case):
    """验证现有用例复用乘客公共实现，且公共基类不包含可收集的测试方法。"""
    assert case.prepare_passenger_route is passenger.AndroidPassengerMixin.prepare_passenger_route
    assert case.ensure_passenger_login is passenger.AndroidPassengerMixin.ensure_passenger_login
    assert case._ios_prepare_passenger_app is passenger.AndroidPassengerMixin._ios_prepare_passenger_app
    assert case._ios_configure_addresses is passenger.AndroidPassengerMixin._ios_configure_addresses
    assert case._ios_get_all_texts is base.AndroidUIBase._ios_get_all_texts
    assert case.setup_class.__func__ is base.AndroidUIBase.setup_class.__func__
    assert not any(name.startswith("test_") for name in vars(base.AndroidUIBase))
    assert not any(name.startswith("test_") for name in vars(passenger.AndroidPassengerBase))


@pytest.mark.parametrize("ios_case", list(ios_scenarios()), ids=lambda case: case.__name__)
def test_order_mro_never_selects_ios_device_setup(ios_case):
    """验证订单继承顺序优先采用 Android 设备实现，同时保留共享支付流程。"""
    case = type("OfflineOrder", (AndroidOrderMixin, ios_case), {"__test__": False})
    assert case.__mro__.index(base.AndroidUIBase) < case.__mro__.index(iOSBase)
    assert case._ios_screenshot is base.AndroidUIBase._ios_screenshot
    assert case._ios_get_all_texts is base.AndroidUIBase._ios_get_all_texts
    assert case._ios_pay is HKIOSPaymentMixin._ios_pay
    assert case._ios_fill_bank_card_form is AndroidPaymentMixin._ios_fill_bank_card_form
    assert case.prepare_passenger_route is passenger.AndroidPassengerMixin.prepare_passenger_route


@pytest.mark.parametrize("verify_login", [False, True])
def test_public_route_preparation_is_called_in_order(verify_login):
    """所有路线入口先调用统一启动登录封装，再设置起终点。"""
    instance = passenger.AndroidPassengerBase()
    actions = []
    instance.ensure_passenger_login = lambda tag: actions.append("login") or True
    instance._ios_prepare_passenger_app = Mock()
    instance._ios_ensure_logged_in = Mock()
    instance._ios_configure_addresses = lambda *args: actions.append("addresses")
    instance.prepare_passenger_route("offline", verify_login=verify_login)
    assert actions == ["login", "addresses"]
    instance._ios_prepare_passenger_app.assert_not_called()
    instance._ios_ensure_logged_in.assert_not_called()


def test_existing_login_case_delegates_to_verified_login():
    """验证既有登录用例仅调用一次公共登录校验步骤。"""
    instance = CASES[0]()
    instance._ios_prepare_passenger_app = Mock()
    instance.ensure_passenger_login = Mock(return_value=True)
    instance._assert_passenger_foreground = Mock()
    instance._ios_screenshot = Mock()
    instance.test_passenger_hk_login_flow()
    instance.ensure_passenger_login.assert_called_once_with("login")


def test_existing_route_case_delegates_without_order_submission():
    """验证路线用例委托公共路线准备，仅定位确认呼叫控件而不提交订单。"""
    instance = CASES[1]()
    instance.prepare_passenger_route = Mock()
    instance._assert_passenger_foreground = Mock()
    instance._ios_screenshot = Mock()
    instance.client = Mock()
    instance.test_open_app_and_select_route()
    instance.prepare_passenger_route.assert_called_once_with("route", start="铜锣湾", verify_login=True)
    instance.client.assert_called_once_with(textContains="確認呼叫")


def test_independent_passenger_connection_needs_no_driver(monkeypatch):
    """验证独立乘客用例只创建乘客会话，并在清理后释放会话引用。"""
    settings = shared_settings()
    settings["driver"]["device_mode"] = "dual"
    monkeypatch.setattr(base, "shared_settings", lambda: settings)
    client = Mock()
    connect = Mock(return_value=client)
    monkeypatch.setattr(base.AndroidClient, "connect", connect)
    case = type("OfflinePassenger", (passenger.AndroidPassengerBase,), {})
    case.setup_class()
    assert connect.call_count == 1
    assert connect.call_args.kwargs["packages"] == (settings["packages"]["passenger_hk"],)
    case.teardown_class()
    client.quit.assert_called_once()
    assert case.client is None
    assert case.clients == {}


def test_dual_failure_releases_first_session_without_app_actions(monkeypatch):
    """验证第二个设备会话创建失败时释放首个会话，且不启动应用。"""
    monkeypatch.setenv("HK_DRIVER_ANDROID_UDID", "driver-test")
    settings = shared_settings()
    monkeypatch.setattr(base, "shared_settings", lambda: settings)
    client = Mock()
    connect = Mock(side_effect=[client, RuntimeError("second session failed")])
    monkeypatch.setattr(base.AndroidClient, "connect", connect)
    case = type("OfflineOrder", (AndroidOrderMixin, list(ios_scenarios())[1]), {})
    with pytest.raises(RuntimeError, match="second session"):
        case.setup_class()
    client.quit.assert_called_once()
    client.app_activate.assert_not_called()
    assert case.clients == {}


def test_coupon_target_never_falls_back_to_other_coupon(monkeypatch):
    """验证指定优惠券未找到时直接报错，不确认或替换为其他优惠券。"""
    monkeypatch.setattr(coupon.time, "sleep", lambda seconds: None)
    instance = coupon.AndroidCouponBase()
    instance.open_coupon_list = Mock()
    instance.client = Mock()
    instance.client.return_value.find_elements.return_value = []
    instance.confirm_coupon_selection = Mock()
    with pytest.raises(RuntimeError, match="指定优惠券"):
        instance.select_coupons(policy="target", target_keywords=["100元优惠券"])
    instance.confirm_coupon_selection.assert_not_called()


def test_coupon_all_policy_is_distinct_and_confirmed_once(monkeypatch):
    """验证全选优惠券时按原生标识去重，每张券及最终确认均只点击一次。"""
    monkeypatch.setattr(coupon.time, "sleep", lambda seconds: None)
    instance = coupon.AndroidCouponBase()
    instance.open_coupon_list = Mock()
    instance.client = Mock()
    first = Mock(label="100元优惠券")
    first.native.id = "coupon-1"
    second = Mock(label="111折扣")
    second.native.id = "coupon-2"
    instance.client.return_value.find_elements.return_value = [first, first, second]
    instance.confirm_coupon_selection = Mock()
    labels = instance.select_coupons(policy="all")
    assert labels == ("100元优惠券", "111折扣")
    first.click.assert_called_once()
    second.click.assert_called_once()
    instance.confirm_coupon_selection.assert_called_once()


@pytest.mark.parametrize("policy,keywords", [("unknown", None), ("target", None)])
def test_invalid_coupon_policy_has_no_ui_side_effects(policy, keywords):
    """验证策略无效或指定券缺少关键词时，在打开优惠券界面前报错。"""
    instance = coupon.AndroidCouponBase()
    instance.open_coupon_list = Mock()
    with pytest.raises(ValueError):
        instance.select_coupons(policy=policy, target_keywords=keywords)
    instance.open_coupon_list.assert_not_called()


def test_coupon_resume_retains_process_without_cold_start(monkeypatch):
    """验证恢复乘客应用只返回桌面并激活原进程，不执行冷启动。"""
    monkeypatch.setattr(coupon.time, "sleep", lambda seconds: None)
    instance = coupon.AndroidCouponBase()
    instance.client = Mock()
    instance._assert_passenger_foreground = Mock()
    instance.resume_passenger_app()
    assert instance.client.mock_calls == [call.home(), call.app_activate("com.sunlightmobility.client")]


def test_old_driver_and_direct_order_skip_limits_preserved():
    """验证旧司机流程与直接下单测试仍保留跳过标记。"""
    for name in ("test_android_launch_to_order", "test_android_driver_order_flow"):
        method = getattr(CASES[2], name)
        assert any(mark.name == "skip" for mark in method.pytestmark)


@pytest.mark.parametrize("filename", ["JRYG_test_open_and_login.py", "JRYG_test_open_and_route.py", "JRYG_test_open_app.py"])
def test_cases_no_longer_inline_adb_login_or_address_implementations(filename):
    """静态验证用例不再内联设备、登录和地址实现，且不导入旧界面框架。"""
    tree = ast.parse((BASE_DIR / "cases" / "legacy" / filename).read_text(encoding="utf-8"))
    methods = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    assert not methods.intersection({"setup_class", "_adb", "_ensure_logged_in", "_input_text", "_set_origin", "_set_destination", "_tap_ratio"})
    imports = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert not any("airtest" in name or "poco" in name for name in imports)


def test_coupon_rules_still_enforce_initial_and_retention_assertions(monkeypatch):
    """验证优惠券进入收银台后未保持选中时断言失败，且不会继续确认付款。"""
    monkeypatch.setattr(coupon.time, "sleep", lambda seconds: None)
    instance = CASES[2]()
    for name in ("prepare_passenger_route", "_ios_select_car_type", "_ios_screenshot", "resume_passenger_app",
                 "open_coupon_list", "return_to_quote", "open_prepaid_cashier", "close_prepaid_cashier", "_ios_click_confirm_pay"):
        setattr(instance, name, Mock())
    instance.client = Mock()
    instance.client.return_value.exists = False
    instance.select_coupons = Mock(return_value=("100元优惠券",))
    instance.selected_coupons_retained = Mock(side_effect=[True, False])
    instance._ios_wait_order_result = Mock(return_value="success")
    with pytest.raises(AssertionError, match="收银台"):
        instance.test_android_coupon_rules_scenarios()
    instance._ios_click_confirm_pay.assert_not_called()


@pytest.mark.parametrize("checked,expected", [("true", True), ("false", False)])
def test_same_coupon_must_still_be_checked(checked, expected):
    """验证优惠券保留判断取决于同一张券当前是否仍处于勾选状态。"""
    instance = coupon.AndroidCouponBase()
    instance._assert_passenger_foreground = Mock()
    instance.client = Mock()
    instance.client.driver.page_source = (
        '<hierarchy><node><node text="100元优惠券"/>'
        f'<node checkable="true" checked="{checked}"/></node></hierarchy>')
    assert instance.selected_coupons_retained(("100元优惠券",)) is expected


def test_visible_coupon_without_exposed_selection_is_not_retention():
    """验证优惠券仅在列表可见而未暴露选中状态时，不能认定选券已保留。"""
    instance = coupon.AndroidCouponBase()
    instance._assert_passenger_foreground = Mock()
    instance.client = Mock()
    instance.client.driver.page_source = '<hierarchy><node text="100元优惠券"/></hierarchy>'
    with pytest.raises(RuntimeError, match="不能把列表中存在"):
        instance.selected_coupons_retained(("100元优惠券",))


def test_other_selected_coupon_cannot_satisfy_previous_selection():
    """验证其他优惠券被选中不能替代此前指定优惠券的保留检查。"""
    instance = coupon.AndroidCouponBase()
    instance._assert_passenger_foreground = Mock()
    instance.client = Mock()
    instance.client.driver.page_source = (
        '<hierarchy><node><node text="111折扣"/><node checked="true" checkable="true"/></node></hierarchy>')
    assert instance.selected_coupons_retained(("100元优惠券",)) is False
