"""司机 App 全 UI 出车、接单、滑动及账单的离线回归。

页面树与WDA均为模拟对象；覆盖同阶段有限重滑、现金收款保护、订单号一致性
及到账详情刷新。已完成文本不能替代已支付证据，无派单不得进入后续行程。
"""

from unittest.mock import Mock
import xml.etree.ElementTree as ET

import pytest

from ui_framework import JRYG_driver_ui as ui


def page(phase):
    """构造模拟阶段页面，终态包含同一测试订单号及明确已付/未付文案。"""
    root = ET.Element("root")
    if phase in ("unpaid", "complete"):
        for label in ("已完成", "未支付" if phase == "unpaid" else "已支付", "26A4J04WECNY"):
            ET.SubElement(root, "node", visible="true", label=label)
    return root, phase


@pytest.fixture
def driver(monkeypatch):
    """以模拟WDA及状态等待构造司机状态机，单测不发送任何设备动作。"""
    monkeypatch.setattr(ui.wda, "Client", Mock(return_value=Mock()))
    instance = ui.DriverUIFlow(ui.parser().parse_args([]))
    instance.wait_for = Mock(return_value=page("offline"))
    instance.act = Mock()
    instance.root = Mock(return_value=ET.Element("root"))
    return instance


def test_default_is_ui_online_only(driver):
    driver.wait_for.side_effect = [page("offline"), page("online")]
    driver.run()
    driver.client.app_activate.assert_called_once_with(ui.BUNDLE_ID)
    driver.act.assert_called_once()
    assert driver.act.call_args.args[1] == ui.ACTION_LABELS["offline"]
    assert driver.last_phase == "online"


@pytest.mark.parametrize("phase", ["online", "offer"])
def test_only_go_online_mode_does_not_accept_offer(driver, phase):
    driver.wait_for.return_value = page(phase)
    driver.run()
    driver.act.assert_not_called()


@pytest.mark.parametrize("phase", ["login", "code", "departure", "pickup", "onboard", "tail", "destination", "bill"])
def test_go_online_refuses_login_or_existing_trip(driver, phase):
    driver.wait_for.return_value = page(phase)
    with pytest.raises(RuntimeError):
        driver.run()
    driver.act.assert_not_called()


def test_inspect_never_modifies_order(driver):
    driver.args.inspect = True
    driver.run()
    driver.act.assert_not_called()


def test_order_flow_accepts_and_slides_using_ui(driver):
    driver.args.stop_after = "bill"
    driver.wait_for.side_effect = [page(phase) for phase in ("online", "offer", "departure", "pickup", "onboard", "destination", "bill")]
    driver.run()
    assert [call.args[1] for call in driver.act.call_args_list] == [
        driver.accept_labels, ui.ACTION_LABELS["departure"], ui.ACTION_LABELS["pickup"],
        ui.ACTION_LABELS["onboard"], ui.ACTION_LABELS["destination"]]
    assert driver.last_phase == "bill"


@pytest.mark.parametrize("stop,expected_count", [("pickup", 1), ("onboard", 2), ("destination", 3), ("bill", 4)])
def test_stop_stage_does_not_modify_later_ui(driver, stop, expected_count):
    driver.args.stop_after = stop
    driver.wait_for.side_effect = [page(phase) for phase in ("offer", "pickup", "onboard", "destination", "bill")]
    driver.run()
    assert driver.act.call_count == expected_count
    assert driver.last_phase == stop


def test_tail_verification_is_done_in_app(driver):
    driver.args.stop_after = "bill"
    driver.enter_tail = Mock()
    driver.wait_for.side_effect = [page(phase) for phase in ("onboard", "tail", "destination", "bill")]
    driver.run()
    driver.enter_tail.assert_called_once()
    assert driver.last_phase == "bill"


def test_submission_returns_to_allow_passenger_payment(driver):
    driver.args.stop_after = "submitted"
    driver.submit_bill = Mock()
    driver.wait_for.side_effect = [page("bill"), page("unpaid")]
    driver.run()
    driver.submit_bill.assert_called_once()
    assert driver.last_phase == "unpaid"


def test_resume_current_bill_does_not_repeat_accept_or_slide(driver):
    driver.args.stop_after = "complete"
    driver.submit_bill = Mock()
    driver.wait_for.side_effect = [page("bill"), page("unpaid"), page("complete")]
    driver.run()
    driver.submit_bill.assert_called_once()
    driver.act.assert_not_called()
    assert driver.last_phase == "complete"


def test_ui_transition_failure_stops_before_bill(driver):
    driver.args.stop_after = "complete"
    driver.submit_bill = Mock()
    driver.wait_for.side_effect = [page("pickup"), TimeoutError("到达滑块未生效")]
    with pytest.raises(TimeoutError, match="未生效"):
        driver.run()
    assert driver.act.call_count == 1
    driver.submit_bill.assert_not_called()


def test_unpaid_page_is_not_completed(driver):
    driver.args.stop_after = "complete"
    driver.wait_for.side_effect = [page("unpaid"), TimeoutError("未收到已支付")]
    with pytest.raises(TimeoutError, match="已支付"):
        driver.run()
    assert driver.last_phase == "unpaid"


def test_final_ui_check_never_repeats_bill(driver):
    driver.order_no = "26A4J04WECNY"
    driver.wait_for.return_value = page("complete")
    driver.snapshot = Mock()
    driver.submit_bill = Mock()
    driver.wait_completed()
    driver.wait_for.assert_called_once_with({"unpaid", "complete"})
    driver.submit_bill.assert_not_called()
    driver.act.assert_not_called()


def test_foreign_foreground_blocks_driver_actions(driver):
    driver.root = ui.DriverUIFlow.root.__get__(driver)
    driver.client.source.return_value = '<XCUIElementTypeApplication bundleId="com.sunlightmobility.client" />'
    with pytest.raises(RuntimeError, match="不在前台"):
        driver.root()
    driver.act.assert_not_called()


def test_cached_online_state_is_not_used(driver):
    driver.root.return_value = ET.fromstring('<root><node visible="true" label="點擊出車" /></root>')
    with pytest.raises(RuntimeError, match="离开听单"):
        driver.check_online()


def test_act_uses_real_ui_slider_coordinates(driver):
    root = ET.fromstring('<root><XCUIElementTypeOther visible="true" x="10" y="300" width="350" height="60"><XCUIElementTypeImage visible="true" name="ca_icon_order_detail_hdjt" x="15" y="310" width="40" height="40"/><XCUIElementTypeStaticText visible="true" label="到達上車地點" x="120" y="320" width="150" height="20"/></XCUIElementTypeOther></root>')
    ui.DriverUIFlow.act(driver, root, ui.ACTION_LABELS["pickup"])
    driver.client.swipe.assert_called_once_with(35, 330, 354, 330, duration=0.8)
    driver.client.click.assert_not_called()


def test_act_clicks_accept_button_when_no_slider(driver):
    root = ET.fromstring('<root><XCUIElementTypeButton visible="true" label="接單" x="10" y="100" width="100" height="40" /></root>')
    ui.DriverUIFlow.act(driver, root, driver.accept_labels)
    driver.client.click.assert_called_once_with(60, 120)
    driver.client.swipe.assert_not_called()


@pytest.mark.parametrize("fare,surcharge", [("5.00", "0.00"), ("9", "0"), ("5", "2")])
def test_bill_ui_verifies_both_amounts_before_submit(driver, fare, surcharge):
    driver.args.fare, driver.args.surcharge = "5", "0"
    driver.fill, driver.dismiss_keyboard = Mock(), Mock()
    driver.field = Mock(side_effect=[ET.Element("field", value=fare), ET.Element("field", value=surcharge)])
    if fare == "5.00" and surcharge == "0.00":
        driver.submit_bill(ET.Element("root"))
        driver.act.assert_called_once()
        assert driver.fill.call_count == 2
    else:
        with pytest.raises(RuntimeError, match="输入未确认"):
            driver.submit_bill(ET.Element("root"))
        driver.act.assert_not_called()


def test_cash_bill_requires_confirmation(driver):
    driver.args.fare = "5"
    driver.args.payment = "cash"
    driver.fill = Mock()
    with pytest.raises(RuntimeError, match="实际已收款"):
        driver.submit_bill(ET.Element("root"))
    driver.fill.assert_not_called()


@pytest.mark.parametrize("option", ["--session-file", "--order-no"])
def test_removed_interface_options_are_not_accepted(option):
    with pytest.raises(SystemExit):
        ui.parser().parse_args([option, "unused"])


def test_departed_status_text_does_not_override_arrival_action():
    root = ET.fromstring('<root><node visible="true" label="已出發" x="10" y="10" width="100" height="20"/><XCUIElementTypeButton visible="true" label="到達上車地點" x="10" y="100" width="200" height="40" /></root>')
    assert ui.detect_phase(root) == "pickup"


def test_departure_requires_an_actionable_button():
    root = ET.fromstring('<root><node visible="true" label="已出發" x="10" y="10" width="100" height="20"/></root>')
    assert ui.detect_phase(root) == "unknown"
    root[0].tag = "XCUIElementTypeButton"
    assert ui.detect_phase(root) == "departure"


@pytest.mark.parametrize("phase", ["departure", "pickup"])
def test_accept_only_stops_before_any_status_slider(driver, phase):
    driver.args.stop_after = "accepted"
    driver.wait_for.side_effect = [page("offer"), page(phase)]
    driver.run()
    driver.act.assert_called_once()
    assert driver.act.call_args.args[1] == driver.accept_labels
    assert driver.last_phase == phase


@pytest.mark.parametrize("phase", ["onboard", "tail", "destination", "bill", "unpaid", "complete"])
def test_accept_only_rejects_order_already_past_acceptance(driver, phase):
    driver.args.stop_after = "accepted"
    driver.wait_for.return_value = page(phase)
    with pytest.raises(RuntimeError, match="超出接单阶段"):
        driver.run()
    driver.act.assert_not_called()


def visible_page(*labels):
    root = ET.Element("root")
    for label in labels:
        ET.SubElement(root, "node", visible="true", label=label, x="10", y="10", width="100", height="20")
    return root


@pytest.mark.parametrize("phase,next_phase", [("pickup", "onboard"), ("onboard", "destination"), ("destination", "bill")])
def test_slider_retries_once_only_on_same_stage(driver, phase, next_phase):
    driver.args.stop_after = next_phase
    driver.root.return_value = visible_page(ui.ACTION_LABELS[phase][0])
    driver.wait_for.side_effect = [page(phase), TimeoutError("first swipe"), page(next_phase)]
    driver.run()
    assert [c.args[1] for c in driver.act.call_args_list] == [ui.ACTION_LABELS[phase]] * 2


def test_destination_retry_failure_never_submits_bill(driver):
    driver.args.stop_after = "submitted"
    driver.root.return_value = visible_page("到達目的地")
    driver.submit_bill = Mock()
    driver.wait_for.side_effect = [page("destination"), TimeoutError("first"), TimeoutError("second")]
    with pytest.raises(TimeoutError, match="second"):
        driver.run()
    assert driver.act.call_count == 2
    driver.submit_bill.assert_not_called()


@pytest.mark.parametrize("current", ["已取消", "確認賬單", ""])
def test_destination_does_not_retry_after_page_changed(driver, current):
    driver.args.stop_after = "bill"
    driver.root.return_value = visible_page(current)
    driver.wait_for.side_effect = [page("destination"), TimeoutError("failed transition")]
    with pytest.raises(TimeoutError):
        driver.run()
    assert driver.act.call_count == 1


def test_destination_does_not_retry_with_system_alert(driver):
    driver.args.stop_after = "bill"
    root = visible_page("到達目的地")
    ET.SubElement(root, "XCUIElementTypeAlert", visible="true", label="停止提示")
    driver.root.return_value = root
    driver.wait_for.side_effect = [page("destination"), TimeoutError("alert")]
    with pytest.raises(TimeoutError):
        driver.run()
    assert driver.act.call_count == 1


def test_detail_without_home_button_recognizes_paid_status():
    assert ui.detect_phase(page("complete")[0]) == "complete"
    assert ui.read_order_no(page("complete")[0]) == "26A4J04WECNY"


@pytest.mark.parametrize("labels", [("已完成",), ("已完成", "已支付", "未支付")])
def test_completed_text_alone_or_conflicting_payment_is_not_success(labels):
    assert ui.detect_phase(visible_page(*labels)) != "complete"


def test_refresh_uses_verified_home_income_detail_sequence(driver, monkeypatch):
    monkeypatch.setattr(ui.time, "sleep", lambda seconds: None)
    driver.order_no = "26A4J04WECNY"
    driver.snapshot = Mock()
    driver.wait_for.side_effect = [page("unpaid"), page("online")]
    driver.root.side_effect = [visible_page("接單中"), visible_page("接單中", "收入到賬", "查看詳情  "),
                               ET.Element("root"), page("complete")[0]]
    driver.wait_completed()
    assert [c.args[1] for c in driver.act.call_args_list] == [("返回首頁",), ("查看詳情  ",)]
    assert driver.last_phase == "complete"
    driver.snapshot.assert_called_once_with("completed_paid")


def test_refresh_rejects_income_from_another_order(driver):
    driver.order_no = "26A4J04WECNY"
    driver.wait_for.side_effect = [page("unpaid"), page("online")]
    driver.root.side_effect = [visible_page("收入到賬", "查看詳情  "),
                               visible_page("已完成", "已支付", "26A4J04OTHR1")]
    with pytest.raises(RuntimeError, match="其他订单"):
        driver.wait_completed()
    assert driver.last_phase != "complete"


def test_final_verification_requires_captured_order_number(driver):
    with pytest.raises(RuntimeError, match="缺少本次账单订单号"):
        driver.wait_completed()
    driver.client.app_activate.assert_not_called()


def test_no_income_notification_times_out_without_repeat_payment(driver, monkeypatch):
    driver.order_no = "26A4J04WECNY"
    driver.args.payment_timeout = 2
    driver.wait_for.side_effect = [page("unpaid"), page("online")]
    driver.root.return_value = visible_page("接單中")
    monkeypatch.setattr(ui.time, "monotonic", Mock(side_effect=[0, 0, 3]))
    monkeypatch.setattr(ui.time, "sleep", lambda seconds: None)
    with pytest.raises(TimeoutError, match="到账通知"):
        driver.wait_completed()
    assert driver.act.call_count == 1


def test_paid_previous_detail_can_return_home_without_rebilling(driver):
    driver.wait_for.side_effect = [page("complete"), page("online")]
    driver.client.window_size.return_value = (393, 852)
    driver.ensure_online()
    assert driver.last_phase == "online"
    driver.client.click.assert_called_once_with(22, 60)
    driver.act.assert_not_called()


def test_dispatch_timeout_does_not_advance_trip_or_confirm_bill(driver):
    driver.args.stop_after = "submitted"
    driver.args.dispatch_timeout = 90
    driver.wait_for.side_effect = [page("online"), TimeoutError("no dispatch")]
    driver.submit_bill = Mock()
    with pytest.raises(TimeoutError, match="no dispatch"):
        driver.run()
    assert driver.wait_for.call_args.kwargs["timeout"] == 90
    driver.act.assert_not_called()
    driver.submit_bill.assert_not_called()
