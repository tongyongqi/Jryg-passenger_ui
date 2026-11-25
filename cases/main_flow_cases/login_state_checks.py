"""主流程登录态策略离线回归，显式按本文件运行，不加入六场景批量。

2026-11-23 用户要求：司机、乘客只判断是否登录，不与配置账号比较。
合成页面/客户端仅验证代码分支，不代表真机、登录接口或支付验证通过。
"""

import importlib
from types import SimpleNamespace
from unittest.mock import Mock
import xml.etree.ElementTree as ET

import pytest

from cases.main_flow_cases.passenger_login_state import MainFlowLoginStateMixin
from passenger_android_core import JRYG_android_login as login
from passenger_android_core.main_flow.order import AndroidOrderBase


PACKAGE = "com.sunlightmobility.client"
SCENARIOS = (
    ("JRYG_test_android_charter_alipay_order", "TestCharterAlipayAndroid"),
    ("JRYG_test_android_charter_bankcard_order", "TestCharterBankcardAndroid"),
    ("JRYG_test_android_meter_cash_order", "TestMeterCashAndroid"),
    ("JRYG_test_android_meter_alipay_order", "TestMeterAlipayAndroid"),
    ("JRYG_test_android_meter_epayment_bankcard_order", "TestMeterEpaymentBankcardAndroid"),
    ("JRYG_test_android_meter_epayment_alipay_order", "TestMeterEpaymentAlipayAndroid"),
    ("JRYG_test_android_meter_epayment_target_order", "TestMeterEpaymentTargetOrderAndroid"),
)


@pytest.fixture(autouse=True)
def no_external_actions(monkeypatch):
    import socket
    import subprocess
    import requests
    import pymysql

    def forbidden(*args, **kwargs):
        raise AssertionError("登录态离线回归禁止网络、设备及业务操作")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(requests.Session, "request", forbidden)
    monkeypatch.setattr(pymysql, "connect", forbidden)


class LoginProbe(MainFlowLoginStateMixin, AndroidOrderBase):
    __test__ = False

    @property
    def order_settings(self):
        # 故意不提供合法凭据；已登录流程不能读取或验证配置手机号、验证码。
        return {"packages": {"passenger_hk": PACKAGE}, "login": {"timeout": 3}}


class Clock:
    def __init__(self):
        self.now = 0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


@pytest.fixture
def probe(monkeypatch):
    monkeypatch.setattr(login, "time", Clock())
    value = object.__new__(LoginProbe)
    value.client = SimpleNamespace(driver=Mock(current_package=PACKAGE))
    value._login_credentials = Mock(side_effect=AssertionError("已登录时禁止读取配置账号"))
    value._login_submit_phone = Mock()
    value._login_submit_code = Mock()
    value._login_native = Mock(return_value=Mock())
    value._login_activate_app = Mock()
    return value


def add(root, text, resource="", displayed=True, bounds="[0,0][300,50]"):
    return ET.SubElement(root, "node", {
        "class": "android.widget.TextView", "package": PACKAGE,
        "text": text, "resource-id": PACKAGE + ":id/" + resource if resource else "",
        "bounds": bounds, "displayed": str(displayed).lower(), "enabled": "true",
    })


def mine(label="****1727", *, logged=True):
    root = ET.Element("hierarchy")
    add(root, "我的行程")
    add(root, "聯繫客服")
    add(root, "首頁")
    add(root, label if logged else "登錄/註冊", "tv_mine_name")
    return root


def home():
    root = ET.Element("hierarchy")
    add(root, "上車地址", "tv_start_address")
    add(root, "我的")
    return root


def snapshot(probe, root):
    return probe._login_classify(root, PACKAGE), root


@pytest.mark.parametrize("label", ["****1727", "****8255", "••••9999", "乘客昵称"])
def test_logged_profile_is_accepted_without_identity_comparison(probe, label):
    probe._login_verify_account(mine(label))
    probe._login_credentials.assert_not_called()


@pytest.mark.parametrize("invalid", ["missing", "duplicate", "empty", "hidden", "zero_area", "unlogged"])
def test_unconfirmed_login_state_is_not_default_success(probe, invalid):
    root = mine(logged=invalid != "unlogged")
    name = next(n for n in root if n.get("resource-id") == PACKAGE + ":id/tv_mine_name")
    if invalid == "missing":
        root.remove(name)
    elif invalid == "duplicate":
        add(root, "另一昵称", "tv_mine_name")
    elif invalid == "empty":
        name.set("text", "")
    elif invalid == "hidden":
        name.set("displayed", "false")
    elif invalid == "zero_area":
        name.set("bounds", "[0,0][0,0]")
    with pytest.raises(RuntimeError):
        probe._login_verify_account(root)
    probe._login_credentials.assert_not_called()


@pytest.mark.parametrize("package", ["com.sunlightmobility.driver", "com.android.permissioncontroller"])
def test_other_foreground_app_is_not_logged_passenger(probe, package):
    probe.client.driver.current_package = package
    with pytest.raises(RuntimeError, match="不在前台"):
        probe._login_verify_account(mine())


def test_empty_source_is_not_logged_in(probe):
    with pytest.raises(RuntimeError, match="未确认"):
        probe._login_verify_account(ET.Element("hierarchy"))


def test_existing_logged_account_returns_home_without_relogin(probe):
    start, profile, end = home(), mine(), home()
    probe._login_snapshot = Mock(side_effect=[snapshot(probe, r) for r in (start, profile, end)])
    result = probe.login_passenger(launch=False)
    assert result.verified is True and result.page == "home"
    assert result.authenticated_now is False
    assert probe._android_login_driver is probe.client.driver
    assert probe._login_native.call_count == 2
    probe._login_credentials.assert_not_called()
    probe._login_submit_phone.assert_not_called()
    probe._login_submit_code.assert_not_called()


def test_unlogged_passenger_still_runs_existing_phone_and_code_steps(probe):
    unlogged = mine(logged=False)
    phone, code = ET.Element("hierarchy"), ET.Element("hierarchy")
    add(phone, "請輸入手機號碼", "phone_num")
    add(code, "請輸入驗證碼", "verify_code")
    profile, end = mine("已登录昵称"), home()
    probe._login_snapshot = Mock(side_effect=[snapshot(probe, r) for r in (unlogged, phone, code, profile, end)])
    result = probe.login_passenger(launch=False)
    assert result.verified is True and result.authenticated_now is True
    probe._login_submit_phone.assert_called_once_with(phone)
    probe._login_submit_code.assert_called_once_with(code)
    probe._login_credentials.assert_not_called()  # 输入边界为Mock；真实未登录仍由原输入步骤读取凭据。


def test_unknown_page_still_times_out_without_login_or_order_actions(probe):
    root = ET.Element("hierarchy")
    probe._login_snapshot = Mock(return_value=snapshot(probe, root))
    with pytest.raises(TimeoutError):
        probe.login_passenger(launch=False)
    probe._login_native.assert_not_called()
    probe._login_submit_phone.assert_not_called()
    probe._login_submit_code.assert_not_called()


def test_profile_current_target_does_not_force_navigation(probe):
    root = mine()
    probe._login_snapshot = Mock(return_value=snapshot(probe, root))
    result = probe.login_passenger(launch=False, target="current")
    assert result.verified is True and result.page == "mine"
    probe._login_native.assert_not_called()


@pytest.mark.parametrize("module_name,class_name", SCENARIOS, ids=[s[0] for s in SCENARIOS])
def test_all_seven_main_cases_use_only_the_local_login_policy(module_name, class_name):
    module = importlib.import_module("cases.main_flow_cases." + module_name)
    cls = getattr(module, class_name)
    assert cls._login_verify_account is MainFlowLoginStateMixin._login_verify_account
    assert cls.login_passenger is login.AndroidLoginMixin.login_passenger
    assert cls.ensure_passenger_login is login.AndroidLoginMixin.ensure_passenger_login
    assert cls._place_order_with_expected_driver is MainFlowLoginStateMixin._place_order_with_expected_driver
    # 不修改继承基类的订单执行方法。
    assert cls._run_order_flow is cls.__bases__[1]._run_order_flow


def test_common_base_keeps_its_original_identity_check():
    assert AndroidOrderBase._login_verify_account is login.AndroidLoginMixin._login_verify_account
    assert not issubclass(AndroidOrderBase, MainFlowLoginStateMixin)


def test_account_identity_change_does_not_remove_current_order_protection(probe):
    home_root = home()
    probe._login_snapshot = Mock(return_value=("business", home_root))
    with pytest.raises(RuntimeError, match="订单或路线页"):
        probe.login_passenger(launch=False)
    probe._login_submit_phone.assert_not_called()
    probe._login_submit_code.assert_not_called()
    probe._login_native.assert_not_called()


@pytest.fixture
def placement():
    class PlacementProbe(MainFlowLoginStateMixin, AndroidOrderBase):
        __test__ = False

        @property
        def order_settings(self):
            return {
                "driver": {"mobile": "fixture-current-driver"},
                "login": {"mobile": "fixture-configured-passenger"},
                "order_validation": {"expected_driver_phone": "fixture-other-driver",
                                     "expected_driver_car_number": "fixture-old-mapping",
                                     "state_timeout": 3},
            }

    case = object.__new__(PlacementProbe)
    case.CAR_TYPE, case.PAYMENT = "meter", "cash"
    for name in ("_android_launch_setup_and_addresses", "_android_select_car_type",
                 "_android_screenshot", "_android_select_payment"):
        setattr(case, name, Mock())
    case._click_call_and_check_login_then_retry = Mock(return_value=True)
    case._charter_click_call_and_select_payment = Mock(return_value=True)
    case._passenger_assigned_driver = Mock(return_value={"status": "fixture-status", "car_number": "fixture-current-car"})
    case._wait = Mock(side_effect=lambda observe, message, timeout: observe())
    for name in ("_expected_driver_assignment", "_driver_assignment_attempt_limit",
                 "_assigned_driver_matches", "_cancel_mismatched_driver_order",
                 "_login_credentials", "_driver_login_mobile"):
        setattr(case, name, Mock(side_effect=AssertionError("本下单步骤禁止比较账号或处理错单")))
    return case


@pytest.mark.parametrize("car_type,payment", [
    ("charter", "alipay"), ("charter", "bankcard"), ("meter", "cash"),
    ("meter", "epayment"), ("meter", "alipay"),
])
def test_placement_ignores_phone_mismatch_and_keeps_payment_branch(placement, car_type, payment):
    case = placement
    case.CAR_TYPE, case.PAYMENT = car_type, payment
    case._place_order_with_expected_driver("fixture", "fixture-payment")
    case._android_launch_setup_and_addresses.assert_called_once()
    case._android_select_car_type.assert_called_once_with("fixture", car_type=car_type)
    assert case._android_screenshot.call_count == 3
    assert case.assigned_driver_identity == {"status": "fixture-status", "car_number": "fixture-current-car"}
    case._wait.assert_called_once()
    if car_type == "meter":
        case._android_select_payment.assert_called_once_with("fixture", payment=payment)
        case._click_call_and_check_login_then_retry.assert_called_once()
        case._charter_click_call_and_select_payment.assert_not_called()
    else:
        case._charter_click_call_and_select_payment.assert_called_once()
        case._android_select_payment.assert_not_called()
        case._click_call_and_check_login_then_retry.assert_not_called()
    case._expected_driver_assignment.assert_not_called()
    case._driver_assignment_attempt_limit.assert_not_called()
    case._assigned_driver_matches.assert_not_called()
    case._cancel_mismatched_driver_order.assert_not_called()
    case._login_credentials.assert_not_called()
    case._driver_login_mobile.assert_not_called()


@pytest.mark.parametrize("result", [False, None, 1, "success"])
def test_unconfirmed_order_cannot_continue_or_be_resubmitted(placement, result):
    placement._click_call_and_check_login_then_retry.return_value = result
    with pytest.raises(AssertionError, match="下单未确认成功"):
        placement._place_order_with_expected_driver("fixture", "cash")
    placement._wait.assert_not_called()
    with pytest.raises(RuntimeError, match="禁止重复"):
        placement._place_order_with_expected_driver("fixture", "cash")
    placement._click_call_and_check_login_then_retry.assert_called_once()


@pytest.mark.parametrize("observation", [None, {}, {"status": "ok"},
                                         {"status": "", "car_number": "car"},
                                         {"status": "ok", "car_number": 1}])
def test_ready_assignment_still_needs_actual_valid_observation(placement, observation):
    placement._passenger_assigned_driver.return_value = observation
    with pytest.raises((RuntimeError, TypeError)):
        placement._place_order_with_expected_driver("fixture", "cash")
    assert not hasattr(placement, "assigned_driver_identity")
    placement._cancel_mismatched_driver_order.assert_not_called()


def test_no_assignment_keeps_wait_timeout_without_cleanup_or_replay(placement):
    placement._wait.side_effect = TimeoutError("fixture-no-assignment")
    with pytest.raises(TimeoutError, match="fixture-no-assignment"):
        placement._place_order_with_expected_driver("fixture", "cash")
    with pytest.raises(RuntimeError, match="禁止重复"):
        placement._place_order_with_expected_driver("fixture", "cash")
    placement._click_call_and_check_login_then_retry.assert_called_once()
    placement._cancel_mismatched_driver_order.assert_not_called()


@pytest.fixture
def driver_probe(monkeypatch):
    from passenger_android_core.main_flow.order import AndroidDriverUIFlow
    from passenger_android_core import JRYG_driver_ui

    monkeypatch.setattr(JRYG_driver_ui, "time", Clock())
    case = object.__new__(AndroidDriverUIFlow)
    case.args = SimpleNamespace(timeout=3, mobile="fixture-current-driver")
    case.completed_before_run = set()
    case._activate_driver_app = Mock()
    case.login = Mock()
    case.enter_code = Mock()
    case.act = Mock()
    case.snapshot = Mock()
    case.wait_for = Mock(return_value=(ET.Element("hierarchy"), "online"))
    case.wait_for_entry_page = Mock(return_value=(ET.Element("hierarchy"), "online"))
    return case


@pytest.mark.parametrize("stage", ["online", "offline"])
def test_driver_logged_stage_continues_without_account_read_or_login(driver_probe, stage):
    driver_probe.wait_for_entry_page.return_value = (ET.Element("hierarchy"), stage)
    assert driver_probe.ensure_online(resume_existing=False) is False
    assert driver_probe.last_phase == "online" and driver_probe.awaiting_new_order is True
    driver_probe.login.assert_not_called()
    driver_probe.enter_code.assert_not_called()
    assert driver_probe.act.call_count == (1 if stage == "offline" else 0)


@pytest.mark.parametrize("stage", ["login", "code"])
def test_driver_unlogged_stage_still_uses_existing_login_steps(driver_probe, stage):
    root = ET.Element("hierarchy")
    driver_probe.wait_for_entry_page.side_effect = [(root, stage), (root, "online")]
    assert driver_probe.ensure_online(resume_existing=False) is False
    if stage == "login":
        driver_probe.login.assert_called_once_with(root)
        driver_probe.enter_code.assert_not_called()
    else:
        driver_probe.enter_code.assert_called_once_with(root)
        driver_probe.login.assert_not_called()


@pytest.mark.parametrize("stage", ["pickup", "unknown"])
def test_driver_order_or_unknown_stage_is_not_default_logged_ready(driver_probe, stage):
    driver_probe.wait_for_entry_page.return_value = (ET.Element("hierarchy"), stage)
    with pytest.raises(RuntimeError, match="不适合新下单"):
        driver_probe.ensure_online(resume_existing=False)
    driver_probe.act.assert_not_called()
    driver_probe.login.assert_not_called()
