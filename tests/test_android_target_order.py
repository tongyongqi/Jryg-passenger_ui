"""安卓目标单识别与非目标行程结束后的顺序回归，不连接设备。"""

from unittest.mock import Mock
import time
import xml.etree.ElementTree as ET

import pytest

from jryg_hk_android.JRYG_android_order import AndroidDriverUIFlow
from jryg_hk_android.JRYG_android_target_order import (
    AndroidTargetDriverUIFlow, AndroidTargetOrderBase, is_active_passenger_order,
    passenger_status_orders, unique_order,
)
from jryg_hk_android.JRYG_driver_ui import parser


TARGET = "26ABCDEF0001"
OTHER = "26ABCDEF0002"
THIRD = "26ABCDEF0003"


def page(*texts):
    root = ET.Element("XCUIElementTypeApplication", bundleId="com.sunlightmobility.driver", visible="true")
    for text in texts:
        ET.SubElement(root, "XCUIElementTypeStaticText", label=text, visible="true", enabled="true",
                      x="10", y="10", width="100", height="40")
    return root


def passenger_page(*texts, active=False):
    root = page(*texts)
    root.set("bundleId", "com.sunlightmobility.client")
    if active:
        ET.SubElement(root, "XCUIElementTypeStaticText", label="司機正在趕來接您", visible="true",
                      enabled="true", **{"resource-id": "com.sunlightmobility.client:id/tv_status_name"})
        ET.SubElement(root, "XCUIElementTypeStaticText", label="U7679", visible="true", enabled="true",
                      **{"resource-id": "com.sunlightmobility.client:id/tv_car_number"})
    return root


def target_case(root):
    case = AndroidTargetOrderBase()
    case.client = Mock()
    case.client.source.return_value = ET.tostring(root, encoding="unicode")
    case.android_settings = {
        "device": {"udid": "DEVICE"},
        "packages": {"passenger_hk": "com.sunlightmobility.client"},
        "order_validation": {"state_timeout": 1},
    }
    case._assert_passenger_foreground = Mock()
    return case


def args():
    return parser(wda_url="http://127.0.0.1:8100").parse_args([
        "--stop-after", "submitted", "--fare", "9", "--surcharge", "2", "--timeout", "60",
        "--step-timeout", "1", "--interval", "0.01"])


class ScreenFlow(AndroidTargetDriverUIFlow):
    LABELS = {"offer": "立即接單", "pickup": "到達上車地點", "onboard": "已接載乘客",
              "destination": "到達目的地", "bill": "確認賬單", "online": "接單中"}

    def __init__(self, orders, phase="offer", terminal="unpaid"):
        super().__init__(args(), Mock(), {"driver": {"non_target_fare": "5", "non_target_surcharge": "0"}})
        self.orders = orders
        self.index = 0
        self.phase = phase
        self.terminal = terminal
        self.target_order_no = TARGET
        self.events = []
        self.awaiting_new_order = phase == "offer"

    def root(self):
        if self.phase in ("complete", "unpaid"):
            return page(self.orders[self.index], "已完成", "已支付" if self.phase == "complete" else "未支付", "返回首頁")
        labels = [self.LABELS.get(self.phase, self.phase)]
        if self.phase not in ("offer", "online"):
            labels.append(self.orders[self.index])
        if self.phase == "bill":
            labels.append("確認收款")
        return page(*labels)

    def _activate_driver_app(self):
        self.events.append(("activate", self.deadline))

    def act(self, root, labels):
        self.events.append((self.orders[self.index], self.phase))
        if self.phase in ("unpaid", "complete"):
            self.index += 1
            self.phase = "offer"
        else:
            self.phase = {"offer": "pickup", "pickup": "onboard", "onboard": "destination", "destination": "bill"}[self.phase]

    def submit_bill(self, root):
        self.events.append((self.orders[self.index], "submit", self.args.fare, self.args.surcharge, self.args.tail))
        self.phase = self.terminal

    def snapshot(self, name):
        self.events.append(("snapshot", name))


@pytest.mark.parametrize("count", [0, 1, 2])
@pytest.mark.parametrize("terminal", ["unpaid", "complete"])
def test_non_target_trips_end_then_target_is_accepted(count, terminal):
    orders = [OTHER, THIRD][:count] + [TARGET]
    flow = ScreenFlow(orders, terminal=terminal)
    original_args = flow.args
    flow.run()
    assert flow.order_no == TARGET
    assert flow.last_phase == terminal
    assert flow.completed_before_run == set(orders[:-1])
    assert flow.non_target_results == [{"order_no": order, "phase": terminal} for order in orders[:-1]]
    submissions = [e for e in flow.events if len(e) > 1 and e[1] == "submit"]
    assert [e[0] for e in submissions] == orders
    assert [e[2:4] for e in submissions] == [("5", "0")] * count + [("9", "2")]
    assert flow.args is original_args
    assert flow.resume_phase == "pickup"
    assert not flow.awaiting_new_order


def test_existing_non_target_finishes_before_new_offer():
    flow = ScreenFlow([OTHER, TARGET], phase="destination")
    flow.resume_phase = "destination"
    flow.run()
    assert (OTHER, "offer") not in flow.events
    assert (TARGET, "offer") in flow.events
    assert flow.order_no == TARGET


def test_failed_non_target_does_not_accept_target():
    flow = ScreenFlow([OTHER, TARGET])
    flow.finish_non_target = Mock(side_effect=RuntimeError("非目标行程失败"))
    with pytest.raises(RuntimeError, match="失败"):
        flow.run()
    assert flow.index == 0
    assert not any(e[0] == TARGET for e in flow.events)


def test_non_target_processing_is_bounded():
    flow = ScreenFlow([OTHER, THIRD, TARGET])
    flow.settings["order_validation"] = {"max_attempts": 1}
    with pytest.raises(RuntimeError, match="处理上限"):
        flow.run()
    assert flow.index == 1
    assert not any(e[:2] == (THIRD, "submit") for e in flow.events)


def test_bound_order_cannot_switch_identity():
    flow = ScreenFlow([OTHER], phase="pickup")
    flow.order_no = TARGET
    with pytest.raises(RuntimeError, match="串单"):
        flow.accept_and_identify(float("inf"))
    assert not any(e[0] == OTHER for e in flow.events)


def test_processed_order_cannot_be_processed_twice():
    flow = ScreenFlow([OTHER], phase="pickup")
    flow.completed_before_run.add(OTHER)
    with pytest.raises(RuntimeError, match="旧订单"):
        flow.accept_and_identify(float("inf"))


def test_unfinished_trip_cannot_return_to_listening():
    flow = ScreenFlow([OTHER, TARGET], phase="destination")
    flow.order_no = OTHER
    with pytest.raises(RuntimeError, match="未结束"):
        flow.return_to_listening(float("inf"))
    assert flow.index == 0


def test_unpaid_trip_is_not_claimed_as_paid():
    flow = ScreenFlow([OTHER, TARGET], phase="unpaid")
    flow.order_no = OTHER
    flow.finish_non_target(float("inf"))
    assert flow.non_target_results == [{"order_no": OTHER, "phase": "unpaid"}]
    flow.return_to_listening(float("inf"))
    assert flow.order_no is None
    assert flow.resume_phase is None
    assert flow.awaiting_new_order


def test_unpaid_return_waits_for_delayed_home_without_reclicking():
    flow = AndroidTargetDriverUIFlow(args(), Mock())
    flow.order_no = OTHER
    flow.deadline = float("inf")
    unpaid = page(OTHER, "已完成", "未支付", "返回首頁")
    online = page("接單中")
    flow.root = Mock(side_effect=[unpaid, unpaid, unpaid, online])
    flow.return_to_listening(float("inf"))
    flow.client.click.assert_called_once_with(60, 30)
    flow.client.back.assert_not_called()
    assert flow.completed_before_run == {OTHER}
    assert flow.order_no is None
    assert flow.awaiting_new_order
    assert flow.last_phase == "online"


def test_unpaid_return_timeout_does_not_reclick_or_clear_identity():
    flow = AndroidTargetDriverUIFlow(args(), Mock())
    flow.order_no = OTHER
    unpaid = page(OTHER, "已完成", "未支付", "返回首頁")
    flow.root = Mock(return_value=unpaid)
    flow.args.step_timeout = 0.02
    with pytest.raises(TimeoutError, match="页面未进入预期状态"):
        flow.return_to_listening(time.monotonic() + 1)
    flow.client.click.assert_called_once_with(60, 30)
    flow.client.back.assert_not_called()
    assert flow.completed_before_run == set()
    assert flow.order_no == OTHER
    assert not flow.awaiting_new_order


@pytest.mark.parametrize("operation", ["return_to_listening", "_run_remaining"])
def test_expired_deadline_has_no_ui_actions(operation):
    flow = ScreenFlow([OTHER, TARGET], phase="complete")
    flow.order_no = OTHER
    with pytest.raises(TimeoutError, match="超时"):
        getattr(flow, operation)(0)
    assert flow.events == []


@pytest.mark.parametrize("texts", [[], [OTHER, TARGET], ["123456789012"], ["ABCDEFGHIJKL"]])
def test_order_identity_must_be_unique_real_number(texts):
    with pytest.raises(RuntimeError, match="缺失或不唯一"):
        unique_order(page(*texts))


@pytest.mark.parametrize("text", [TARGET, "訂單編號 " + TARGET, "订单号：" + TARGET])
def test_order_identity_supports_visible_labels(text):
    assert unique_order(page(text)) == TARGET


def test_passenger_status_order_uses_only_exact_current_status_requests():
    output = "\n".join([
        f"E/retrofit: Sending request https://host/passenger/order/status?order_no={TARGET}",
        f"E/retrofit: url=https://host/passenger/order/status?order_no={TARGET}",
        f"E/retrofit: https://host/passenger/order/detail?order_no={OTHER}",
        f"random order_no={OTHER}",
        "E/retrofit: https://host/passenger/order/status?order_no=123456789012",
    ])
    assert passenger_status_orders(output) == {TARGET}


def test_fresh_status_order_requires_active_passenger_page():
    assert not is_active_passenger_order(passenger_page("下單成功"))
    assert is_active_passenger_order(passenger_page("下單成功", active=True))


def test_passenger_adb_uses_real_device_setting_without_runtime_attribute(monkeypatch):
    case = target_case(passenger_page("下單成功", active=True))
    invoked = Mock(return_value=Mock(stdout="25430\n"))
    monkeypatch.setattr("jryg_hk_android.JRYG_android_target_order.subprocess.run", invoked)
    assert not hasattr(case, "passenger_runtime")
    assert case._adb("shell", "pidof", "-s", "com.sunlightmobility.client") == "25430\n"
    invoked.assert_called_once_with(
        ["adb", "-s", "DEVICE", "shell", "pidof", "-s", "com.sunlightmobility.client"],
        capture_output=True, text=True, timeout=10, check=True,
    )


def test_passenger_target_binds_unique_fresh_status_order():
    case = target_case(passenger_page("打錶的士司機正在趕來接您", active=True))
    case._start_passenger_order_log = Mock(return_value="123")
    case._fresh_passenger_orders = Mock(return_value={TARGET})
    assert case._read_passenger_target() == TARGET
    case._start_passenger_order_log.assert_called_once_with()
    case._fresh_passenger_orders.assert_called_once_with("123")


def test_passenger_target_rejects_multiple_fresh_status_orders():
    case = target_case(passenger_page("打錶的士司機正在趕來接您", active=True))
    case._start_passenger_order_log = Mock(return_value="123")
    case._fresh_passenger_orders = Mock(return_value={TARGET, OTHER})
    with pytest.raises(RuntimeError, match="多个新鲜状态订单号"):
        case._read_passenger_target()


def test_visible_passenger_order_does_not_read_device_logs():
    case = target_case(passenger_page(TARGET))
    case._start_passenger_order_log = Mock(side_effect=AssertionError("不应读取日志"))
    assert case._read_passenger_target() == TARGET
    case._start_passenger_order_log.assert_not_called()


def test_passenger_history_stops_before_reading_device_logs():
    case = target_case(passenger_page("我的行程"))
    case._start_passenger_order_log = Mock(side_effect=AssertionError("不应读取日志"))
    with pytest.raises(RuntimeError, match="历史列表"):
        case._read_passenger_target()
    case._start_passenger_order_log.assert_not_called()


def raw_page(*texts):
    root = ET.Element("hierarchy")
    for text in texts:
        ET.SubElement(root, "node", text=text, displayed="true", enabled="true")
    return root


def test_unfinished_popup_goes_to_completion_before_later_flow():
    case = target_case(passenger_page())
    popup = raw_page("您還有未完成的訂單，請處理後再下單。", "稍後再說", "去完成")
    terminal = raw_page("打錶的士行程結束", "訂單編號 " + OTHER, "確認支付 5 HKD")
    case._login_activate_app = Mock()
    case._login_snapshot = Mock(side_effect=[("business", popup), ("terminal_unpaid", terminal)])
    case._ios_click_dialog_button = Mock(return_value=True)
    case._complete_legacy_passenger_order = Mock()
    case._ui_cleanup_ongoing_order("target")
    case._ios_click_dialog_button.assert_called_once_with(["去完成", "去處理", "去处理"], wait_after=1)
    case._complete_legacy_passenger_order.assert_called_once_with("target")


def test_unfinished_popup_uncertain_response_is_not_clicked_twice():
    case = target_case(passenger_page())
    popup = raw_page("您還有未完成的訂單，請處理後再下單。", "去完成")
    case._login_activate_app = Mock()
    case._login_snapshot = Mock(return_value=("business", popup))
    case._ios_click_dialog_button = Mock(return_value=True)
    with pytest.raises(RuntimeError, match="单次点击未生效"):
        case._ui_cleanup_ongoing_order("target")
    case._ios_click_dialog_button.assert_called_once()


def test_legacy_unpaid_order_is_paid_verified_then_returns_to_listening():
    case = target_case(passenger_page(OTHER))
    case.target_order_no = None
    case.legacy_order_no = None
    case._read_passenger_target = Mock(return_value=OTHER)
    case._ios_wait_current_payment = Mock()
    case._ios_complete_payment = Mock()
    case._ios_back_to_home = Mock()
    driver = Mock(order_no=None, completed_before_run=set())
    def bind(order_no):
        driver.order_no = order_no
        driver.last_phase = "unpaid"
        return "unpaid"
    driver.bind_existing_history_order.side_effect = bind
    def completed():
        driver.last_phase = "complete"
    driver.wait_completed.side_effect = completed
    case.driver_ui = driver
    case._complete_legacy_passenger_order("target")
    driver.bind_existing_history_order.assert_called_once_with(OTHER)
    case._ios_wait_current_payment.assert_called_once_with("target")
    case._ios_complete_payment.assert_called_once_with("target")
    driver.wait_completed.assert_called_once_with()
    driver.return_to_listening.assert_called_once()
    assert case.legacy_completed_order_no == OTHER
    assert case.target_order_no is None


def test_legacy_order_mismatch_stops_before_payment():
    case = target_case(passenger_page(OTHER))
    case.legacy_order_no = TARGET
    case._read_passenger_target = Mock(return_value=OTHER)
    case._ios_complete_payment = Mock()
    case.driver_ui = Mock(order_no=TARGET)
    with pytest.raises(RuntimeError, match="不是同一订单"):
        case._complete_legacy_passenger_order("target")
    case._ios_complete_payment.assert_not_called()


def test_resumed_driver_order_stays_bound_until_passenger_completion(monkeypatch):
    from jryg_hk_android.JRYG_android_order import AndroidOrderBase
    case = target_case(passenger_page())
    driver = Mock(order_no=OTHER)
    case.driver_ui = driver
    def prepare(self, tag):
        self.driver_ui = driver
        self.resuming_order = True
    monkeypatch.setattr(AndroidOrderBase, "_driver_ui_go_online", prepare)
    case._driver_ui_go_online("target")
    driver.finish_non_target.assert_called_once()
    driver.return_to_listening.assert_not_called()
    assert case.legacy_order_no == OTHER
    assert not case.resuming_order


def test_driver_binds_existing_history_order_by_exact_number():
    flow = AndroidDriverUIFlow(args(), Mock())
    flow._activate_driver_app = Mock()
    flow.act = Mock()
    flow._open_bound_history_order = Mock()
    unpaid = page(OTHER, "已完成", "未支付", "返回首頁")
    flow.wait_for = Mock(side_effect=[(page("接單中"), "online"), (unpaid, "unpaid")])
    assert flow.bind_existing_history_order(OTHER) == "unpaid"
    flow.act.assert_called_once()
    flow._open_bound_history_order.assert_called_once_with()
    assert flow.order_no == OTHER
    assert not flow.awaiting_new_order


def test_driver_expands_and_restores_original_phase():
    flow = AndroidTargetDriverUIFlow(args(), Mock())
    flow.deadline = float("inf")
    collapsed = page("到達目的地", "展開")
    flow.root = Mock(side_effect=[collapsed, page(OTHER), collapsed])
    assert flow.read_active_order() == OTHER
    flow.client.click.assert_called_once_with(60, 30)
    flow.client.back.assert_called_once_with()


def test_missing_identity_does_not_advance_order():
    flow = AndroidTargetDriverUIFlow(args(), Mock())
    flow.root = Mock(return_value=page("到達目的地"))
    with pytest.raises(RuntimeError, match="缺少订单号"):
        flow.read_active_order()
    flow.client.click.assert_not_called()
    flow.client.back.assert_not_called()


def test_non_target_charter_does_not_inherit_target_meter_fare(monkeypatch):
    flow = AndroidTargetDriverUIFlow(args(), Mock())
    flow.handling_non_target = True
    seen = []
    monkeypatch.setattr(AndroidDriverUIFlow, "submit_bill", lambda self, root: seen.append((self.args.car_type, self.args.fare, self.args.surcharge)))
    flow.submit_bill(page("確認賬單", "確認收款", "車費", "18 HKD"))
    assert seen == [("charter", None, None)]


def test_non_target_cash_requires_separate_real_receipt(monkeypatch):
    flow = AndroidTargetDriverUIFlow(args(), Mock())
    flow.handling_non_target = True
    flow.args.cash_collected = False
    root = page("確認賬單", "確認收款", "現金")
    with pytest.raises(RuntimeError, match="实际已收款"):
        flow.submit_bill(root)
    flow.client.click.assert_not_called()


def test_non_target_failure_restores_target_arguments():
    flow = ScreenFlow([OTHER], phase="destination")
    flow.order_no = OTHER
    original = flow.args
    flow._run_remaining = Mock(side_effect=RuntimeError("提交失败"))
    with pytest.raises(RuntimeError, match="提交失败"):
        flow.finish_non_target(float("inf"))
    assert flow.args is original
    assert not flow.handling_non_target
    assert flow.non_target_results == []


def test_target_cannot_be_finished_as_non_target():
    flow = ScreenFlow([TARGET], phase="destination")
    flow.order_no = TARGET
    with pytest.raises(RuntimeError, match="不能按非目标"):
        flow.finish_non_target(float("inf"))


def test_target_result_must_match_passenger_order(monkeypatch):
    from jryg_hk_android.JRYG_android_order import AndroidOrderBase
    monkeypatch.setattr(AndroidOrderBase, "_run_order_flow", lambda self: None)
    case = AndroidTargetOrderBase()
    case.target_order_no = TARGET
    case.completed_order_no = OTHER
    with pytest.raises(AssertionError, match="不是本次乘客"):
        case._run_order_flow()
    case.completed_order_no = TARGET
    case._run_order_flow()


@pytest.mark.parametrize("value", ["", "123", "123456789012", "ABCDEFGHIJKL", 123])
def test_invalid_target_stops_before_accepting(value):
    flow = ScreenFlow([OTHER, TARGET])
    flow.target_order_no = value
    with pytest.raises(ValueError, match="目标订单号无效"):
        flow.run()
    assert flow.events == []


@pytest.mark.parametrize("tail", ["12", 1234])
def test_invalid_non_target_tail_preserves_target_configuration(tail):
    flow = ScreenFlow([OTHER], phase="destination")
    flow.order_no = OTHER
    flow.settings["driver"]["non_target_passenger_tail"] = tail
    original = flow.args
    with pytest.raises(ValueError, match="非目标乘客尾号"):
        flow.finish_non_target(float("inf"))
    assert flow.args is original
    assert flow.events == []


def test_target_scenario_is_optional_and_keeps_default_six():
    from jryg_hk_android.JRYG_scenarios import scenario_nodes
    default = scenario_nodes()
    optional = scenario_nodes(include_optional=True)
    assert len(default) == 6
    assert optional[:6] == default
    assert len(optional) == 7
    assert optional[-1].endswith("JRYG_test_android_meter_epayment_target_order.py::TestMeterEpaymentTargetOrderAndroid::test_order_flow")


@pytest.mark.parametrize("form", ["filename", "relative", "absolute", "class", "node"])
def test_runner_accepts_explicit_target_case(monkeypatch, form):
    import JRYG_run_main as runner
    from jryg_hk_android.JRYG_scenarios import scenario_nodes
    node = scenario_nodes(include_optional=True)[-1]
    path, class_name, _ = node.split("::")
    filename = path.rsplit("/", 1)[-1]
    choices = {"filename": filename, "relative": "cases/" + filename,
               "absolute": path, "class": class_name, "node": node}
    invoked = Mock(return_value=0)
    monkeypatch.setattr(runner, "init_all_dirs", lambda: None)
    monkeypatch.setattr(runner.pytest, "main", invoked)
    assert runner._run_tests(["--case", choices[form], "--collect-only"]) == 0
    invoked.assert_called_once()
    selected = [arg for arg in invoked.call_args.args[0] if "::test_order_flow" in arg]
    assert selected == [node]


def test_target_case_script_can_collect_without_device():
    from pathlib import Path
    import subprocess
    import sys
    directory = Path(__file__).resolve().parents[1]
    result = subprocess.run([sys.executable, str(directory / "cases/JRYG_test_android_meter_epayment_target_order.py"),
                             "--collect-only", "-q"], cwd=directory, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "<Class TestMeterEpaymentTargetOrderAndroid>" in result.stdout
    assert "<Function test_order_flow>" in result.stdout
    assert "1 test collected" in result.stdout
