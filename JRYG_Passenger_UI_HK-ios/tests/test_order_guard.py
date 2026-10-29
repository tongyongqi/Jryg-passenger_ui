"""离线回归：禁止连接真机及业务接口，所有状态来自显式测试替身。"""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

from jryg_hk_ios.JRYG_order_guard import OrderGuard, OrderValidationError
from jryg_hk_ios.JRYG_order_api import HKOrderAPI
from jryg_hk_ios.JRYG_page_monitor import IOSPage
from jryg_hk_ios.JRYG_run_result import E2EResult
from jryg_hk_ios.JRYG_verified_order_flow import VerifiedOrderFlow


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    """forbid_network —— 公开方法：forbid network。

        :return: None"""
    def fail(*args, **kwargs):
        """fail —— 公开方法：fail。

        :return: None"""
        raise AssertionError("离线回归不得调用网络")
    monkeypatch.setattr(requests.sessions.Session, "request", fail)


class Clock:
    """Clock —— 公开方法：Clock。

        :return: None"""
    def __init__(self):
        """Clock.__init__ —— 内部辅助方法：init  。

        :return: None"""
        self.now = 0

    def __call__(self):
        """Clock.__call__ —— 内部辅助方法：call  。

        :return: None"""
        return self.now

    def sleep(self, seconds):
        """Clock.sleep —— 公开方法：sleep。

        :return: None"""
        self.now += seconds


class API:
    """API —— 公开方法：API。

        :return: None"""
    driver_id = "31"

    def __init__(self, drivers=("31",)):
        """API.__init__ —— 内部辅助方法：init  。

        :return: None"""
        self.drivers = iter(drivers)
        self.rows = []
        self.states = {}
        self.trips = {}
        self.events = []
        self.serial = 0
        self.cancel_result = {"canceled": True}
        self.confirm_cancel = True
        self.remove_cancelled = True
        self.extra_active = False

    def unfinished(self):
        """API.unfinished —— 公开方法：unfinished。

        :return: None"""
        self.events.append("list")
        return [dict(row) for row in self.rows]

    def status(self, no):
        """API.status —— 公开方法：status。

        :return: None"""
        self.events.append(("status", no))
        return dict(self.states[no])

    def trip_detail(self, no):
        """API.trip_detail —— 公开方法：trip detail。

        :return: None"""
        return self.trips.get(no, {"order_no": no, "order": {"order_status": 2, "pay_status": 0}})

    def prepare_cancel(self, no):
        """API.prepare_cancel —— 公开方法：prepare cancel。

        :return: None"""
        self.events.append(("prepare_cancel", no))

    def cancel(self, no):
        """API.cancel —— 公开方法：cancel。

        :return: None"""
        self.events.append(("cancel", no))
        if self.confirm_cancel and self.cancel_result.get("canceled") is True:
            self.states[no]["order_status"] = -1
            if self.remove_cancelled:
                self.rows = [r for r in self.rows if r["order_no"] != no]
        return self.cancel_result

    def create(self):
        """API.create —— 公开方法：create。

        :return: None"""
        assert not self.rows, "旧单没有消失前不能下单"
        self.serial += 1
        no = f"ORDER{self.serial}"
        self.rows = [{"order_no": no, "start_address": "北角(地鐵站)", "end_address": "香港大學"}]
        self.states[no] = {"order_no": no, "driver_id": next(self.drivers), "order_status": 2}
        self.events.append(("create", no))
        return True

    def finish(self, no):
        """API.finish —— 公开方法：finish。

        :return: None"""
        self.events.append(("finish", no))
        self.states[no]["order_status"] = 5
        self.trips[no] = {"order_no": no, "order": {"order_status": 8, "pay_status": 1}}
        self.rows = []


def guard(api, **kwargs):
    """guard —— 公开方法：guard。

        :return: None"""
    clock = Clock()
    return OrderGuard(api, ["北角(地鐵站)"], ["香港大學"],
                      dispatch_timeout=3, state_timeout=3, completion_timeout=3,
                      total_timeout=30, interval=1, clock=clock, sleep=clock.sleep, **kwargs)


def test_wrong_driver_cancel_confirm_then_new_order_and_complete():
    """test_wrong_driver_cancel_confirm_then_new_order_and_complete —— 测试用例：验证 wrong driver cancel confirm then new order and complete 场景。

        :return: None"""
    api = API(("99", "31"))
    g = guard(api)
    result = g.run(api.create, api.finish, lambda: api.events.append("reset"))
    assert result.order_no == "ORDER2"
    assert result.driver_id == "31"
    assert ("finish", "ORDER1") not in api.events
    cancel = api.events.index(("cancel", "ORDER1"))
    new = api.events.index(("create", "ORDER2"))
    assert cancel < api.events.index(("status", "ORDER1"), cancel) < new
    g.assert_all_completed(1)


def test_existing_wrong_driver_is_cancelled_not_mistaken_for_new():
    """test_existing_wrong_driver_is_cancelled_not_mistaken_for_new —— 测试用例：验证 existing wrong driver is cancelled not mistaken for new 场景。

        :return: None"""
    api = API(("99", "31"))
    api.create()
    g = guard(api)
    result = g.run(api.create, api.finish, lambda: None)
    assert result.order_no == "ORDER2"
    assert ("cancel", "ORDER1") in api.events


def test_existing_target_order_cannot_replace_new_payment_scenario():
    """test_existing_target_order_cannot_replace_new_payment_scenario —— 测试用例：验证 existing target order cannot replace new payment scenario 场景。

        :return: None"""
    api = API()
    api.create()
    g = guard(api)
    with pytest.raises(OrderValidationError, match="车型和支付方式"):
        g.run(api.create, api.finish, lambda: None)
    assert api.serial == 1
    assert ("finish", "ORDER1") not in api.events
    assert not g.completed


@pytest.mark.parametrize("mode", ["rejected", "not_terminal", "still_listed"])
def test_cancel_failure_never_creates_next_order(mode):
    """test_cancel_failure_never_creates_next_order —— 测试用例：验证 cancel failure never creates next order 场景。

        :return: None"""
    api = API(("99", "31"))
    if mode == "rejected":
        api.cancel_result = {"canceled": False}
    elif mode == "not_terminal":
        api.confirm_cancel = False
    else:
        api.remove_cancelled = False
    with pytest.raises(OrderValidationError):
        guard(api).run(api.create, api.finish, lambda: None)
    assert api.serial == 1
    assert not any(isinstance(e, tuple) and e[0] == "finish" for e in api.events)


def test_unknown_driver_waits_then_fails_without_cancel():
    """test_unknown_driver_waits_then_fails_without_cancel —— 测试用例：验证 unknown driver waits then fails without cancel 场景。

        :return: None"""
    api = API((None,))
    with pytest.raises(OrderValidationError, match="等待真实司机分配"):
        guard(api).run(api.create, api.finish, lambda: None)
    assert not any(isinstance(e, tuple) and e[0] == "cancel" for e in api.events)


def test_retry_limit_fails_and_last_wrong_order_is_cancelled():
    """test_retry_limit_fails_and_last_wrong_order_is_cancelled —— 测试用例：验证 retry limit fails and last wrong order is cancelled 场景。

        :return: None"""
    api = API(("99", "98"))
    with pytest.raises(OrderValidationError, match="上限"):
        guard(api, max_attempts=2).run(api.create, api.finish, lambda: None)
    assert api.serial == 2 and not api.rows


def test_driver_coming_is_not_pass_even_if_finish_callback_returns_true():
    """test_driver_coming_is_not_pass_even_if_finish_callback_returns_true —— 测试用例：验证 driver coming is not pass even if finish callback returns true 场景。

        :return: None"""
    api = API()
    g = guard(api)
    with pytest.raises(OrderValidationError, match="已完成且已支付"):
        g.run(api.create, lambda no: True, lambda: None)
    assert not g.completed and api.rows


@pytest.mark.parametrize("driver_status,pay_status,passenger_status", [(8, 0, 5), (2, 1, 5), (8, 1, 2), (9, 1, 5)])
def test_all_terminal_fields_are_mandatory(driver_status, pay_status, passenger_status):
    """test_all_terminal_fields_are_mandatory —— 测试用例：验证 all terminal fields are mandatory 场景。

        :return: None"""
    api = API()
    def incomplete(no):
        """incomplete —— 公开方法：incomplete。

        :return: None"""
        api.states[no]["order_status"] = passenger_status
        api.trips[no] = {"order_no": no, "order": {"order_status": driver_status, "pay_status": pay_status}}
    with pytest.raises(OrderValidationError):
        guard(api).run(api.create, incomplete, lambda: None)


def test_other_order_completed_does_not_prove_current_order():
    """test_other_order_completed_does_not_prove_current_order —— 测试用例：验证 other order completed does not prove current order 场景。

        :return: None"""
    api = API()
    def wrong_detail(no):
        """wrong_detail —— 公开方法：wrong detail。

        :return: None"""
        api.finish(no)
        api.trips[no]["order_no"] = "OLD_COMPLETED_ORDER"
    with pytest.raises(OrderValidationError, match="其他订单"):
        guard(api).run(api.create, wrong_detail, lambda: None)


def test_status_response_must_echo_order_id():
    """test_status_response_must_echo_order_id —— 测试用例：验证 status response must echo order id 场景。

        :return: None"""
    api = API()
    def create():
        """create —— 公开方法：create。

        :return: None"""
        api.create()
        api.states["ORDER1"]["order_no"] = "OLD_ORDER"
    with pytest.raises(OrderValidationError, match="其他订单"):
        guard(api).run(create, api.finish, lambda: None)


def test_multiple_unfinished_orders_not_cancelled_in_bulk():
    """test_multiple_unfinished_orders_not_cancelled_in_bulk —— 测试用例：验证 multiple unfinished orders not cancelled in bulk 场景。

        :return: None"""
    api = API()
    api.create()
    api.rows.append(dict(api.rows[0], order_no="OTHER"))
    with pytest.raises(OrderValidationError, match="多笔"):
        guard(api).run(api.create, api.finish, lambda: None)
    assert not any(isinstance(e, tuple) and e[0] == "cancel" for e in api.events)


def test_route_mismatch_not_cancelled():
    """test_route_mismatch_not_cancelled —— 测试用例：验证 route mismatch not cancelled 场景。

        :return: None"""
    api = API(("99",))
    api.create()
    api.rows[0]["start_address"] = "銅鑼灣"
    with pytest.raises(OrderValidationError, match="路线"):
        guard(api).run(api.create, api.finish, lambda: None)


def test_old_order_id_reused_after_cancel_fails():
    """test_old_order_id_reused_after_cancel_fails —— 测试用例：验证 old order id reused after cancel fails 场景。

        :return: None"""
    api = API(("99", "31"))
    def create():
        """create —— 公开方法：create。

        :return: None"""
        if api.serial:
            api.serial = 0
        api.create()
    with pytest.raises(OrderValidationError, match="旧订单号"):
        guard(api).run(create, api.finish, lambda: None)


def test_timeout_of_create_never_retries_uncertain_write():
    """test_timeout_of_create_never_retries_uncertain_write —— 测试用例：验证 timeout of create never retries uncertain write 场景。

        :return: None"""
    api = API()
    def create():
        """create —— 公开方法：create。

        :return: None"""
        api.create()
        raise TimeoutError("response lost")
    with pytest.raises(TimeoutError):
        guard(api).run(create, api.finish, lambda: None)
    assert api.serial == 1


def test_driver_changes_before_cancel_prevents_cancellation():
    """test_driver_changes_before_cancel_prevents_cancellation —— 测试用例：验证 driver changes before cancel prevents cancellation 场景。

        :return: None"""
    api = API(("99",))
    def prepare(no):
        """prepare —— 公开方法：prepare。

        :return: None"""
        api.states[no]["driver_id"] = "31"
    api.prepare_cancel = prepare
    with pytest.raises(OrderValidationError, match="状态已变化"):
        guard(api).run(api.create, api.finish, lambda: None)
    assert ("cancel", "ORDER1") not in api.events


def test_no_final_pass_with_any_unfinished_order():
    """test_no_final_pass_with_any_unfinished_order —— 测试用例：验证 no final pass with any unfinished order 场景。

        :return: None"""
    api = API(("31", "31"))
    g = guard(api)
    g.run(api.create, api.finish, lambda: None)
    api.create()
    with pytest.raises(OrderValidationError, match="仍有未完成"):
        g.assert_all_completed(1)


@pytest.mark.parametrize("texts,expected", [
    (["司機正在趕來接您", "已完成"], "order_active"),
    (["重新下單"], "order_cancelled"),
    (["已取消", "行程結束"], "order_cancelled"),
    (["費用明細"], "unknown"),
    (["行程結束"], "order_complete"),
    (["未能查閱到付款記錄"], "payment_failed"),
    (["已完成的訂單"], "unknown"),
])
def test_page_state_does_not_confuse_cancel_or_waiting_with_completed(texts, expected):
    """test_page_state_does_not_confuse_cancel_or_waiting_with_completed —— 测试用例：验证 page state does not confuse cancel or waiting with completed 场景。

        :return: None"""
    xml = '<XCUIElementTypeApplication>' + ''.join(
        f'<XCUIElementTypeStaticText label="{t}" />' for t in texts) + '</XCUIElementTypeApplication>'
    assert IOSPage(xml).state == expected


def test_driver_session_requires_phone_and_driver_id():
    """test_driver_session_requires_phone_and_driver_id —— 测试用例：验证 driver session requires phone and driver id 场景。

        :return: None"""
    session = {"code": 10000, "data": {"driver_info": {"driver_phone": "+85211000005", "driver_id": 31},
                                     "sign_info": {"mobile": "11000005", "access_token": "fake-test-token"}}}
    assert HKOrderAPI.validate_driver_session(session)[0] == "31"
    session["data"]["driver_info"]["driver_phone"] = "+85211000006"
    with pytest.raises(OrderValidationError, match="不属于11000005"):
        HKOrderAPI.validate_driver_session(session)


def test_missing_credentials_fails_before_any_api_call(monkeypatch):
    """test_missing_credentials_fails_before_any_api_call —— 测试用例：验证 missing credentials fails before any api call 场景。

        :return: None"""
    monkeypatch.delenv("HK_PASSENGER_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("HK_DRIVER_SESSION_FILE", raising=False)
    with pytest.raises(OrderValidationError, match="HK_DRIVER_SESSION_FILE"):
        HKOrderAPI.from_environment()


def test_production_host_rejected():
    """test_production_host_rejected —— 测试用例：验证 production host rejected 场景。

        :return: None"""
    client = SimpleNamespace(base_url="https://driver.sunlightmobility.hk", access_token="fake")
    with pytest.raises(OrderValidationError, match="测试环境"):
        HKOrderAPI(client, client, None, None, "31")


def report(passed=False, skipped=False, failed=False, verified=False, when="call"):
    """report —— 公开方法：report。

        :return: None"""
    return SimpleNamespace(passed=passed, skipped=skipped, failed=failed, when=when,
                           user_properties=[("order_verified", verified)])


def test_collect_only_never_says_all_passed():
    """test_collect_only_never_says_all_passed —— 测试用例：验证 collect only never says all passed 场景。

        :return: None"""
    result = E2EResult()
    code, text = result.outcome(0, collect_only=True)
    assert code == 0 and "未执行" in text and "全部通过" not in text


@pytest.mark.parametrize("event", [report(skipped=True), report(passed=True), report(failed=True)])
def test_skip_or_unverified_pass_or_failure_is_nonzero(event):
    """test_skip_or_unverified_pass_or_failure_is_nonzero —— 测试用例：验证 skip or unverified pass or failure is nonzero 场景。

        :return: None"""
    result = E2EResult()
    result.pytest_runtest_logreport(event)
    assert result.outcome(0)[0] == 1


def test_verified_success_then_teardown_failure_is_not_passed():
    """test_verified_success_then_teardown_failure_is_not_passed —— 测试用例：验证 verified success then teardown failure is not passed 场景。

        :return: None"""
    result = E2EResult()
    result.pytest_runtest_logreport(report(passed=True, verified=True))
    assert result.outcome(0)[0] == 0
    result.pytest_runtest_logreport(report(failed=True, when="teardown"))
    assert result.outcome(0)[0] == 1


def test_finished_api_order_but_ui_still_driver_coming_fails():
    """test_finished_api_order_but_ui_still_driver_coming_fails —— 测试用例：验证 finished api order but ui still driver coming fails 场景。

        :return: None"""
    flow = VerifiedOrderFlow()
    flow.PASSENGER_BUNDLE = "passenger"
    flow._ensure_order_guard = Mock(return_value=SimpleNamespace(
        run=Mock(return_value=SimpleNamespace(order_no="ORDER1")), remaining=lambda: 30))
    flow._activate_app = Mock()
    flow._capture = Mock()
    flow.monitor = Mock()
    def wait(description, predicate, timeout, recover=None):
        """wait —— 公开方法：wait。

        :return: None"""
        page = SimpleNamespace(root={"bundleId": "passenger"}, state="order_active")
        assert predicate(page) is False
        raise OrderValidationError("UI仍在司机赶来")
    flow.monitor.wait_for = wait
    with pytest.raises(OrderValidationError, match="司机赶来"):
        flow._run_verified_order(lambda: True)


def test_timeout_during_ui_preparation_never_submits_order():
    """test_timeout_during_ui_preparation_never_submits_order —— 测试用例：验证 timeout during ui preparation never submits order 场景。

        :return: None"""
    api = API()
    g = guard(api)
    with pytest.raises(OrderValidationError, match="总时限"):
        g.run(api.create, api.finish, lambda: g.sleep(31))
    assert api.serial == 0


def test_no_order_created_after_button_click_must_fail():
    """test_no_order_created_after_button_click_must_fail —— 测试用例：验证 no order created after button click must fail 场景。

        :return: None"""
    api = API()
    with pytest.raises(OrderValidationError, match="唯一新订单"):
        guard(api).run(lambda: True, api.finish, lambda: None)
    assert api.serial == 0


def test_ui_wait_uses_remaining_budget():
    """test_ui_wait_uses_remaining_budget —— 测试用例：验证 ui wait uses remaining budget 场景。

        :return: None"""
    flow = VerifiedOrderFlow()
    flow._ensure_order_guard = Mock(return_value=SimpleNamespace(remaining=lambda: 0.5))
    flow.monitor = Mock()
    flow._recover_blocking_popup = Mock()
    predicate = lambda page: False
    flow._order_wait("bounded", predicate, 30)
    flow.monitor.wait_for.assert_called_once_with(
        "bounded", predicate, timeout=0.5, recover=flow._recover_blocking_popup)


def build_finished_service_flow(scenario):
    """build_finished_service_flow —— 公开方法：build finished service flow。

        :return: None"""
    flow = VerifiedOrderFlow()
    flow.FARE_AMOUNT = "5"
    flow.current_scenario = scenario
    api = Mock()
    api.service_detail.return_value = {
        "order_no": "ORDER1", "order": {"start_address": "北角", "end_address": "香港大學",
                                         "start_lat": 22.29, "start_lng": 114.2,
                                         "end_lat": 22.28, "end_lng": 114.13},
        "service": {"service_status": 4}}
    flow.order_guard = SimpleNamespace(api=api, require_target=Mock(), remaining=lambda: 30,
                                      start_names={"北角"}, end_names={"香港大學"})
    return flow, api


@pytest.mark.parametrize("scenario", ["charter", "postpay", "cash"])
def test_billing_does_not_convert_electronic_payment_to_cash(scenario):
    """test_billing_does_not_convert_electronic_payment_to_cash —— 测试用例：验证 billing does not convert electronic payment to cash 场景。

        :return: None"""
    flow, api = build_finished_service_flow(scenario)
    flow._finish_bound_order("ORDER1")
    assert api.confirm_bill.call_count == (0 if scenario == "charter" else 1)
    assert api.service_change.call_count == (1 if scenario == "cash" else 0)


def test_bill_failure_prevents_confirming_receipt():
    """test_bill_failure_prevents_confirming_receipt —— 测试用例：验证 bill failure prevents confirming receipt 场景。

        :return: None"""
    flow, api = build_finished_service_flow("cash")
    api.confirm_bill.side_effect = OrderValidationError("账单失败")
    with pytest.raises(OrderValidationError, match="账单失败"):
        flow._finish_bound_order("ORDER1")
    api.service_change.assert_not_called()


def test_missing_critical_status_field_cannot_default_to_complete():
    """test_missing_critical_status_field_cannot_default_to_complete —— 测试用例：验证 missing critical status field cannot default to complete 场景。

        :return: None"""
    api = API()
    def finish(no):
        """finish —— 公开方法：finish。

        :return: None"""
        api.finish(no)
        del api.trips[no]["order"]["pay_status"]
    with pytest.raises(OrderValidationError, match="pay_status"):
        guard(api).run(api.create, finish, lambda: None)


@pytest.mark.parametrize("cancel_type,alert_type,tip,allowed", [
    (0, 0, "馬上為您找到司機了，您確定不再等等嗎？", True),
    (0, 0, "", True), (1, 0, "", False), (0, 1, "", False),
    (0, 0, "需支付取消費用", False),
])
def test_cancel_notice_validation(cancel_type, alert_type, tip, allowed):
    """test_cancel_notice_validation —— 测试用例：验证 cancel notice validation 场景。

        :return: None"""
    api = object.__new__(HKOrderAPI)
    api.request = Mock(return_value={"cancel_type": cancel_type, "alert_type": alert_type,
                                    "buyout_cancel_tip": tip, "limit_cancel_notice": ""})
    if allowed:
        api.prepare_cancel("ORDER1")
    else:
        with pytest.raises(OrderValidationError, match="取消存在"):
            api.prepare_cancel("ORDER1")


def test_api_http_success_but_business_failure_is_not_success():
    """test_api_http_success_but_business_failure_is_not_success —— 测试用例：验证 api http success but business failure is not success 场景。

        :return: None"""
    client = SimpleNamespace(base_url="http://localhost", access_token="fake",
                             _build_headers=lambda **kwargs: {})
    api = HKOrderAPI(client, client, lambda values: "fake-sign", lambda values: "fake-sign", "31")
    api.http.close()
    api.http = Mock()
    api.http.request.return_value = SimpleNamespace(status_code=200, json=lambda: {"code": 10506, "data": {}})
    with pytest.raises(OrderValidationError, match="业务失败"):
        api.cancel("ORDER1")
    assert api.http.request.call_count == 1


def test_ui_logged_in_reused_without_api_or_typing(monkeypatch):
    """test_ui_logged_in_reused_without_api_or_typing —— 测试用例：验证 ui logged in reused without api or typing 场景。

        :return: None"""
    from jryg_hk_ios.JRYG_ios_login import IOSLogin
    flow = IOSLogin()
    flow._is_app_running = Mock(return_value=True)
    flow._passenger_account_page = Mock(return_value=SimpleNamespace(
        state="mine_logged", matches_account=lambda phone: True))
    flow._capture = Mock()
    flow.client = Mock()
    flow._ensure_order_guard = Mock(side_effect=AssertionError("登录阶段不得要求API会话"))
    assert flow.login_passenger() is True
    flow.client.send_keys.assert_not_called()
    flow._ensure_order_guard.assert_not_called()


def test_ui_other_account_cannot_skip_login():
    """test_ui_other_account_cannot_skip_login —— 测试用例：验证 ui other account cannot skip login 场景。

        :return: None"""
    from jryg_hk_ios.JRYG_ios_base import IOSBase
    flow = IOSBase()
    flow._passenger_account_page = Mock(return_value=SimpleNamespace(
        state="mine_logged", matches_account=lambda phone: False))
    with pytest.raises(OrderValidationError, match="其他账号"):
        flow._is_logged_in()


def test_unlogged_ui_does_not_require_api_credentials():
    """test_unlogged_ui_does_not_require_api_credentials —— 测试用例：验证 unlogged ui does not require api credentials 场景。

        :return: None"""
    from jryg_hk_ios.JRYG_ios_base import IOSBase
    flow = IOSBase()
    flow.PASSENGER_BUNDLE = "passenger"
    page = SimpleNamespace(root={"bundleId": "passenger"}, state="login_phone_input")
    flow._passenger_ready = Mock(return_value=page)
    flow._ensure_order_guard = Mock(side_effect=AssertionError("不得建立API会话"))
    assert flow._is_logged_in() is False
    flow._ensure_order_guard.assert_not_called()


def test_ui_open_login_verify_before_api_guard():
    """test_ui_open_login_verify_before_api_guard —— 测试用例：验证 ui open login verify before api guard 场景。

        :return: None"""
    import importlib.util
    from pathlib import Path
    path = Path(__file__).resolve().parents[1] / "cases" / "JRYG_test_ios_e2e_order.py"
    spec = importlib.util.spec_from_file_location("e2e_order_unit_target", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    flow = module.TestJRYGE2EOrder()
    events = []
    flow._order_scenarios = lambda: ("cash",)
    flow.open_passenger_app = lambda: events.append("open") or True
    flow.login_passenger = lambda: events.append("ui_login") or True
    flow._verify_passenger_account = lambda: events.append("verify")
    def blocked_guard():
        """blocked_guard —— 公开方法：blocked guard。

        :return: None"""
        events.append("guard")
        raise OrderValidationError("会话缺失")
    flow._ensure_order_guard = blocked_guard
    flow._capture = Mock()
    flow.order_meter_taxi = Mock()
    with pytest.raises(OrderValidationError, match="会话缺失"):
        flow.test_e2e_full_flow()
    assert events == ["open", "ui_login", "verify", "guard"]
    assert flow.e2e_verified is False
    flow.order_meter_taxi.assert_not_called()


def route_home_page(address="怡安大廈", entry_count=1):
    """构造模拟首页；entry_count 用于覆盖起点入口缺失或重复的情况。

    复现已保存页面树中可见匿名按钮与不可见地址文字同属起点栏的结构。
    XML 和坐标均为测试数据，不代表当前真机页面或定位结果。
    """
    from xml.sax.saxutils import quoteattr
    button = ("<XCUIElementTypeButton visible='true' enabled='true' "
              "x='41' y='596' width='311' height='36'/>")
    return IOSPage(
        "<App><XCUIElementTypeScrollView visible='true'>"
        "<XCUIElementTypeButton name='slm icon tool location' visible='true' "
        "x='338' y='530' width='43' height='42'/>"
        "<XCUIElementTypeOther visible='true'>" + button * entry_count +
        f"<XCUIElementTypeButton label={quoteattr('從 ' + address)} visible='false'/>"
        "<XCUIElementTypeButton label='出發' visible='false'/>"
        "</XCUIElementTypeOther></XCUIElementTypeScrollView>"
        "<XCUIElementTypeStaticText label='想去哪裡？' visible='true'/></App>")


def route_search_page(marker):
    """构造带指定起点或终点标记的搜索页，验证输入框类型判断。"""
    return IOSPage(f"<App><XCUIElementTypeImage name='{marker}' visible='true'/>"
                   "<XCUIElementTypeTextField visible='true'/>"
                   "<XCUIElementTypeButton label='搜尋' visible='true'/></App>")


@pytest.fixture
def route_flow():
    """用模拟页面驱动真实路线编排，检查调用顺序与失败时的停止行为。

    点击、页面读取、等待及地址输入选择均被替换，不连接 WDA 或业务接口。
    用例通过仅表示给定模拟状态下断言成立，不能证明真机输入或下单成功。
    """
    flow = VerifiedOrderFlow()
    flow.START_ADDRESS = "北角地鐵站"
    flow.DEST_ADDRESS = "香港大學"
    flow.order_guard = guard(API())
    flow.client = Mock()
    flow.monitor = Mock()
    flow._recover_blocking_popup = Mock()
    ui = SimpleNamespace(
        events=[], page=route_home_page(),
        origin_result=route_home_page("北角(地鐵站)"),
        destination_result=route_search_page("slm_icon_search_end_dot"),
        quote=IOSPage("<App><Text label='確認呼叫'/><Text label='北角(地鐵站)'/>"
                      "<Text label='香港大學'/></App>"))
    flow._passenger_ready = lambda: ui.page
    flow.monitor.inspect = lambda: ui.page
    flow._capture = lambda reason: ui.events.append(reason)

    def click_origin(x, y):
        """校验点击坐标来自模拟起点按钮中心，不执行真实触屏操作。"""
        assert (x, y) == (196, 614)
        assert ui.page.state == "home_unlogged"
        ui.events.append("起点入口")
        ui.page = route_search_page("slm_icon_search_start_dot")

    def click_text(client, *texts):
        """模拟返回首页或打开终点，并禁止在起点确认前进入终点。"""
        assert client is flow.client
        if texts == ("slm_icon_navi_arrow_left",):
            ui.events.append("返回首页")
            ui.page = route_home_page()
        else:
            assert texts == ("想去哪裡？",)
            assert "verified_origin" in ui.events, "起点未确认不得点击终点"
            ui.events.append("终点入口")
            ui.page = ui.destination_result
        return True

    def select_address(query, accepted, marker):
        """核对地址参数后切换预设页面，不验证真实输入、搜索服务或选点结果。"""
        assert ui.page.has(marker)
        ui.events.append(("输入并选择", query, marker))
        if marker == "slm_icon_search_start_dot":
            assert query == flow.START_ADDRESS
            assert accepted == flow.order_guard.start_names
            ui.page = ui.origin_result
        else:
            assert query == flow.DEST_ADDRESS
            assert accepted == flow.order_guard.end_names
            ui.page = ui.quote

    def wait(description, predicate, timeout, recover=None):
        """只检查当前模拟页的条件，不覆盖真实轮询、超时耗时或弹窗恢复。"""
        if not predicate(ui.page):
            raise OrderValidationError(description + "未满足")
        return ui.page

    flow.client.click.side_effect = click_origin
    flow.monitor.click_text.side_effect = click_text
    flow.monitor.wait_for.side_effect = wait
    flow._select_address = Mock(side_effect=select_address)
    return flow, ui


@pytest.mark.parametrize("existing_route", [False, True])
def test_route_preparation_confirms_origin_before_destination(route_flow, existing_route):
    """从首页或旧报价页出发，都必须按起点、起点确认、终点的顺序流转。"""
    flow, ui = route_flow
    if existing_route:
        ui.page = ui.quote
    flow._prepare_order_route()
    expected = [
        "起点入口", ("输入并选择", "北角地鐵站", "slm_icon_search_start_dot"),
        "verified_origin", "终点入口",
        ("输入并选择", "香港大學", "slm_icon_search_end_dot"), "verified_route",
    ]
    assert ui.events == (["返回首页"] if existing_route else []) + expected


@pytest.mark.parametrize("entry_count", [0, 2])
def test_route_preparation_missing_or_ambiguous_origin_stops(route_flow, entry_count):
    """没有起点入口或有多个候选时，不允许点击任何替代控件或输入地址。"""
    flow, ui = route_flow
    ui.page = route_home_page(entry_count=entry_count)
    with pytest.raises(OrderValidationError, match="无法唯一识别首页起点"):
        flow._prepare_order_route()
    flow.client.click.assert_not_called()
    flow.monitor.click_text.assert_not_called()
    flow._select_address.assert_not_called()


@pytest.mark.parametrize("still_searching", [False, True])
def test_route_preparation_unconfirmed_origin_blocks_destination(route_flow, still_searching):
    """仍在搜索页或首页保留旧起点时，禁止把选点调用当作确认成功。"""
    flow, ui = route_flow
    ui.origin_result = (route_search_page("slm_icon_search_start_dot")
                        if still_searching else route_home_page("怡安大廈"))
    with pytest.raises(OrderValidationError, match="首页起点确认为北角地铁站"):
        flow._prepare_order_route()
    flow.monitor.click_text.assert_not_called()
    assert flow._select_address.call_count == 1
    assert "verified_origin" not in ui.events


@pytest.mark.parametrize("prompt", ["請先輸入起點", "请先输入起点"])
def test_route_preparation_origin_prompt_stops_without_retry(route_flow, prompt):
    """两种字体的缺少起点提示都应终止流程，不重试终点点击或输入。"""
    flow, ui = route_flow
    ui.destination_result = IOSPage(f"<App><Text label='{prompt}'/></App>")
    with pytest.raises(OrderValidationError, match="App提示请先输入起点"):
        flow._prepare_order_route()
    assert flow.monitor.click_text.call_count == 1
    assert flow._select_address.call_count == 1
    assert "verified_route" not in ui.events


@pytest.mark.parametrize("address,confirmed", [
    ("北角(地鐵站)", True), ("怡安大廈", False), ("北角(地鐵站)附近", False),
])
def test_route_origin_confirmation_only_uses_exact_home_card(route_flow, address, confirmed):
    """只认可起点栏完整地址；栏外同名节点及含“附近”的名称均不能替代。"""
    flow, _ = route_flow
    page = route_home_page(address)
    from xml.etree.ElementTree import SubElement
    SubElement(page.root, "XCUIElementTypeStaticText", label="北角(地鐵站)")
    assert flow._home_origin_confirmed(page) is confirmed
    assert not page.has("從 " + address)


@pytest.mark.parametrize("attribute,value", [
    ("visible", "false"), ("enabled", "false"), ("height", "0"), ("width", "0"),
])
def test_route_origin_unusable_entry_is_not_clicked(route_flow, attribute, value):
    """隐藏、禁用或尺寸无效的起点控件必须被排除，不能继续点击终点。"""
    flow, ui = route_flow
    origin, _ = flow._home_origin_entry(ui.page)
    origin.set(attribute, value)
    with pytest.raises(OrderValidationError, match="无法唯一识别首页起点"):
        flow._prepare_order_route()
    flow.client.click.assert_not_called()
    flow.monitor.click_text.assert_not_called()


def test_route_origin_hidden_card_cannot_confirm(route_flow):
    """起点栏整体隐藏时，即使其子节点地址正确，也不能证明当前起点生效。"""
    flow, ui = route_flow
    _, row = flow._home_origin_entry(ui.origin_result)
    row.set("visible", "false")
    assert flow._home_origin_confirmed(ui.origin_result) is False


@pytest.mark.parametrize("prompt", ["請先輸入起點", "请先输入起点"])
def test_route_destination_input_checks_origin_prompt_again(route_flow, prompt):
    """直接调用真实地址选择方法，验证新出现的缺少起点提示会阻止输入。"""
    flow, ui = route_flow
    ui.page = IOSPage(f"<App><Text label='{prompt}'/>"
                      "<Text label='slm_icon_search_end_dot'/><XCUIElementTypeTextField/></App>")
    with pytest.raises(OrderValidationError, match="App提示请先输入起点"):
        # 绕过 fixture 中的地址选择替身，但设备客户端仍为 Mock，不连接真机。
        VerifiedOrderFlow._select_address(flow, flow.DEST_ADDRESS,
                                          flow.order_guard.end_names, "slm_icon_search_end_dot")
    flow.client.assert_not_called()
