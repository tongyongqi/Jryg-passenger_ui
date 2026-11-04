"""安卓到账核验只按绑定号打开行程，不使用首页第一条收入通知。"""

from unittest.mock import Mock
import xml.etree.ElementTree as ET

import pytest

from jryg_hk_android.JRYG_android_order import AndroidDriverUIFlow
from ui_framework.JRYG_driver_ui import parser


TARGET = "26B4J54WECNY"
OLD = "26B4J4MWECNY"
PREFIX = "com.sunlightmobility.driver:id/"


def page(*labels):
    root = ET.Element("XCUIElementTypeApplication", bundleId="com.sunlightmobility.driver", visible="true")
    for label in labels:
        ET.SubElement(root, "XCUIElementTypeStaticText", label=label, visible="true", enabled="true")
    return root


def detail(order=TARGET, paid=False):
    return page(order, "已完成", "已支付" if paid else "未支付", "返回首頁")


def history_detail(order=TARGET, paid=False):
    return page(order, "已完成", "已支付" if paid else "未支付")


def history(*orders):
    root = page()
    ET.SubElement(root, "XCUIElementTypeStaticText", label="我的行程", visible="true", enabled="true",
                  **{"resource-id": PREFIX + "tv_bar_title"})
    area = ET.SubElement(root, "XCUIElementTypeOther", visible="true", x="0", y="446", width="1172", height="2302",
                         **{"resource-id": PREFIX + "rl_order_list"})
    for order in orders:
        row = ET.SubElement(area, "XCUIElementTypeOther", visible="true", enabled="true")
        ET.SubElement(row, "XCUIElementTypeStaticText", visible="true", enabled="true", label=order,
                      **{"resource-id": PREFIX + "tv_order_id"})
        ET.SubElement(row, "XCUIElementTypeStaticText", visible="true", label="已完成")
    return root


@pytest.fixture
def state(monkeypatch):
    args = parser(wda_url="http://127.0.0.1:8100").parse_args([
        "--payment-timeout", "5", "--interval", "0.01", "--step-timeout", "1"])
    flow = AndroidDriverUIFlow(args, Mock())
    flow.order_no = TARGET
    flow.awaiting_new_order = False
    flow.last_phase = "unpaid"
    flow._activate_driver_app = Mock()
    flow.snapshot = Mock()
    data = {"screen": detail(), "pages": [history(OLD, TARGET)], "index": 0, "time": 0,
            "result": detail(paid=True), "actions": []}
    card = Mock()
    card.is_displayed.return_value = card.is_enabled.return_value = True
    identifier = Mock()
    identifier.text = TARGET
    card.find_elements.return_value = [identifier]
    card.click.side_effect = lambda: data.update(screen=data["result"])
    flow.client.driver.find_elements.return_value = [card]
    flow.root = Mock(side_effect=lambda: data["screen"])

    def act(root, labels):
        data["actions"].append(labels)
        if labels == ("返回首頁",):
            data["screen"] = page("接單中", "我的行程", "收入到賬", "查看詳情", "11-03 18:43", "15.39港元")
        elif labels == ("我的行程",):
            data["screen"] = data["pages"][data["index"]]
        else:
            raise AssertionError(f"不应点击其他控件 {labels}")

    def swipe(*args, **kwargs):
        data["index"] = min(data["index"] + 1, len(data["pages"]) - 1)
        data["screen"] = data["pages"][data["index"]]

    def clock():
        data["time"] += 0.01
        return data["time"]

    def sleep(seconds):
        data["time"] += seconds

    flow.act = Mock(side_effect=act)
    flow.client.swipe.side_effect = swipe
    monkeypatch.setattr("jryg_hk_android.JRYG_android_order.time.monotonic", clock)
    monkeypatch.setattr("jryg_hk_android.JRYG_android_order.time.sleep", sleep)
    return flow, card, identifier, data


def test_old_first_income_notification_is_never_clicked(state):
    flow, card, _, data = state
    flow.completed_before_run.add(OLD)
    flow.wait_completed()
    assert data["actions"] == [("返回首頁",), ("我的行程",)]
    path = flow.client.driver.find_elements.call_args.args[1]
    assert TARGET in path
    assert OLD not in path
    assert "tv_order_id" in path
    assert "ancestor::*[@clickable='true'][1]" in path
    card.click.assert_called_once()
    assert flow.order_no == TARGET
    assert flow.last_phase == "complete"
    flow.snapshot.assert_called_once_with("completed_paid")


def test_same_paid_detail_passes_without_history_or_new_payment(state):
    flow, card, _, data = state
    data["screen"] = detail(paid=True)
    flow.wait_completed()
    assert data["actions"] == []
    card.click.assert_not_called()
    assert flow.last_phase == "complete"


def test_unpaid_history_detail_without_home_button_waits_in_place(state):
    flow, card, _, data = state
    unpaid = history_detail()
    paid = history_detail(paid=True)
    screens = iter([unpaid, unpaid, paid])
    flow.root = Mock(side_effect=lambda: next(screens, paid))
    flow.wait_completed()
    assert data["actions"] == []
    flow.act.assert_not_called()
    flow.client.back.assert_not_called()
    flow.client.swipe.assert_not_called()
    card.click.assert_not_called()
    assert flow.order_no == TARGET
    assert flow.last_phase == "complete"
    flow.snapshot.assert_called_once_with("completed_paid")


def test_unpaid_history_detail_wrong_order_never_passes(state):
    flow, card, _, data = state
    screens = iter([history_detail(), history_detail(OLD, paid=True)])
    flow.root = Mock(side_effect=lambda: next(screens, history_detail(OLD, paid=True)))
    with pytest.raises(RuntimeError, match="其他订单"):
        flow.wait_completed()
    assert data["actions"] == []
    flow.act.assert_not_called()
    card.click.assert_not_called()
    flow.snapshot.assert_not_called()


@pytest.mark.parametrize("fault", ["missing_binding", "waiting", "old"])
def test_unbound_or_old_order_stops_before_ui_navigation(state, fault):
    flow, card, _, _ = state
    if fault == "missing_binding":
        flow.order_no = None
    elif fault == "waiting":
        flow.awaiting_new_order = True
    else:
        flow.completed_before_run.add(TARGET)
    with pytest.raises(RuntimeError):
        flow.wait_completed()
    flow._activate_driver_app.assert_not_called()
    card.click.assert_not_called()


def test_initial_wrong_detail_is_not_rebound_to_target(state):
    flow, card, _, data = state
    data["screen"] = detail(OLD, paid=True)
    with pytest.raises(RuntimeError, match="其他订单"):
        flow.wait_completed()
    assert flow.order_no == TARGET
    flow.act.assert_not_called()
    card.click.assert_not_called()
    flow.snapshot.assert_not_called()


def test_history_opens_exact_order_beyond_first_page(state):
    flow, card, _, data = state
    data["pages"] = [history(OLD), history("26B6P68WECNY", TARGET)]
    flow.wait_completed()
    flow.client.swipe.assert_called_once()
    card.click.assert_called_once()
    assert flow.order_no == TARGET


def test_missing_target_cannot_pass_using_another_paid_order(state):
    flow, card, _, data = state
    data["pages"] = [history(OLD)]
    with pytest.raises(TimeoutError, match="未找到本次订单"):
        flow.wait_completed()
    card.click.assert_not_called()
    flow.snapshot.assert_not_called()
    assert flow.order_no == TARGET
    assert flow.last_phase != "complete"
    assert flow.client.swipe.call_count <= 10


def test_duplicate_target_rows_are_rejected(state):
    flow, card, _, data = state
    data["pages"] = [history(TARGET, TARGET)]
    with pytest.raises(RuntimeError, match="记录不唯一"):
        flow.wait_completed()
    card.click.assert_not_called()


@pytest.mark.parametrize("fault", ["missing", "duplicate", "hidden", "disabled", "changed_id", "duplicate_ids"])
def test_native_card_must_still_match_bound_order(state, fault):
    flow, card, identifier, _ = state
    if fault == "missing":
        flow.client.driver.find_elements.return_value = []
    elif fault == "duplicate":
        flow.client.driver.find_elements.return_value = [card, Mock()]
    elif fault == "hidden":
        card.is_displayed.return_value = False
    elif fault == "disabled":
        card.is_enabled.return_value = False
    elif fault == "changed_id":
        identifier.text = OLD
    else:
        card.find_elements.return_value = [identifier, Mock()]
    with pytest.raises(RuntimeError):
        flow.wait_completed()
    card.click.assert_not_called()
    flow.snapshot.assert_not_called()
    assert flow.order_no == TARGET


def test_opened_wrong_detail_still_fails_strict_identity_check(state):
    flow, card, _, data = state
    data["result"] = detail(OLD, paid=True)
    with pytest.raises(RuntimeError, match="其他订单"):
        flow.wait_completed()
    card.click.assert_called_once()
    assert flow.order_no == TARGET
    flow.snapshot.assert_not_called()
    assert flow.last_phase != "complete"


def test_target_detail_unpaid_times_out_without_repaying(state):
    flow, card, _, data = state
    data["result"] = detail(TARGET, paid=False)
    with pytest.raises(TimeoutError, match="未确认已完成且已支付"):
        flow.wait_completed()
    card.click.assert_called_once()
    assert data["actions"] == [("返回首頁",), ("我的行程",)]
    flow.snapshot.assert_not_called()
    assert flow.last_phase != "complete"


def test_clicked_card_response_failure_is_not_retried(state):
    flow, card, _, _ = state
    card.click.side_effect = RuntimeError("lost response")
    with pytest.raises(RuntimeError, match="lost response"):
        flow.wait_completed()
    card.click.assert_called_once()
    flow.snapshot.assert_not_called()


def test_history_scroll_count_is_bounded_with_changing_pages(state):
    flow, card, _, data = state
    data["pages"] = [history(f"26ABCDEF{i:04d}") for i in range(12)]
    flow.args.payment_timeout = 30
    with pytest.raises(TimeoutError, match="未找到本次订单"):
        flow.wait_completed()
    assert flow.client.swipe.call_count == 10
    card.click.assert_not_called()


def test_history_does_not_read_order_id_outside_list(state):
    flow, card, _, data = state
    root = history(OLD)
    ET.SubElement(root, "XCUIElementTypeStaticText", label=TARGET, visible="true",
                  **{"resource-id": PREFIX + "tv_order_id"})
    data["pages"] = [root]
    with pytest.raises(TimeoutError, match="未找到本次订单"):
        flow.wait_completed()
    card.click.assert_not_called()


def test_multiple_history_lists_are_rejected(state):
    flow, card, _, data = state
    root = history(TARGET)
    root.append(ET.fromstring(ET.tostring(root[-1])))
    data["pages"] = [root]
    with pytest.raises(RuntimeError, match="列表不唯一"):
        flow.wait_completed()
    card.click.assert_not_called()


def test_history_wrong_title_is_not_opened(state):
    flow, card, _, data = state
    root = history(TARGET)
    root[0].set("label", "其他資訊")
    data["pages"] = [root]
    with pytest.raises(RuntimeError, match="不是司机行程列表"):
        flow.wait_completed()
    card.click.assert_not_called()


@pytest.mark.parametrize("mode", ["list", "loading_filters"])
def test_native_history_entry_returns_once_without_business_actions(state, mode):
    flow, _, _, data = state
    root = history(TARGET, OLD)
    if mode == "loading_filters":
        root.remove(root[-1])
        for resource in ("tv_order_time", "tv_order_status"):
            ET.SubElement(root, "XCUIElementTypeStaticText", visible="true", label="默認日期",
                          **{"resource-id": PREFIX + resource})
    data["screen"] = root
    flow.deadline = 10
    flow.client.back.side_effect = lambda: data.update(screen=page("接單中"))
    _, phase = flow.wait_for_entry_page()
    assert phase == "online"
    flow.client.back.assert_called_once()
    flow.act.assert_not_called()
    flow.client.swipe.assert_not_called()
    flow.client.click.assert_not_called()
    assert flow.order_no == TARGET


def test_paid_detail_then_history_restores_home_with_two_distinct_backs(state):
    flow, _, _, data = state
    root = history(TARGET, OLD)
    data["screen"] = detail(paid=True)
    data["screen"].remove(data["screen"][-1])
    data["actions"] = []
    flow.order_no = None
    flow.completed_before_run = set()

    def back():
        data["actions"].append("back")
        data["screen"] = root if len(data["actions"]) == 1 else page("接單中")

    flow.client.back.side_effect = back
    assert flow.ensure_online(resume_existing=True) is False
    assert flow.client.back.call_count == 2
    assert TARGET in flow.completed_before_run
    assert flow.order_no is None
    assert flow.awaiting_new_order
    flow.act.assert_not_called()
    flow.client.swipe.assert_not_called()


def test_history_back_has_no_retry_when_page_does_not_change(state):
    flow, _, _, data = state
    data["screen"] = history(TARGET)
    flow.deadline = 3
    with pytest.raises(TimeoutError, match="准备页恢复超时"):
        flow.wait_for_entry_page()
    flow.client.back.assert_called_once()
    flow.act.assert_not_called()
    flow.snapshot.assert_called_once_with("driver_entry_navigation_timeout")


@pytest.mark.parametrize("screen", ["blank", "only_title", "wrong_title"])
def test_unconfirmed_native_page_never_blindly_returns(state, screen):
    flow, _, _, data = state
    root = history(TARGET)
    if screen == "blank":
        root = page()
    elif screen == "only_title":
        root.remove(root[-1])
    else:
        root[0].set("label", "其他資訊")
    data["screen"] = root
    flow.deadline = 3
    with pytest.raises(TimeoutError):
        flow.wait_for_entry_page()
    flow.client.back.assert_not_called()
    flow.act.assert_not_called()


def test_native_history_transient_blank_after_back_only_waits(state):
    flow, _, _, data = state
    flow.deadline = 3
    flow.root.side_effect = [history(TARGET), page(), page("接單中")]
    _, phase = flow.wait_for_entry_page()
    assert phase == "online"
    flow.client.back.assert_called_once()
    flow.act.assert_not_called()


@pytest.mark.parametrize("duplicate", ["title", "list"])
def test_ambiguous_native_history_does_not_return(state, duplicate):
    flow, _, _, data = state
    root = history(TARGET)
    root.append(ET.fromstring(ET.tostring(root[0] if duplicate == "title" else root[-1])))
    data["screen"] = root
    flow.deadline = 3
    with pytest.raises(RuntimeError, match="不唯一"):
        flow.wait_for_entry_page()
    flow.client.back.assert_not_called()


def test_uncertain_native_history_back_preserves_cause_and_stops(state):
    flow, _, _, data = state
    data["screen"] = history(TARGET)
    flow.deadline = 3
    failure = RuntimeError("unit lost response")
    flow.client.back.side_effect = failure
    with pytest.raises(RuntimeError, match="禁止重复返回") as error:
        flow.wait_for_entry_page()
    assert error.value.__cause__ is failure
    flow.client.back.assert_called_once()
    flow.act.assert_not_called()


@pytest.mark.parametrize("phase_label,phase", [("到達上車地點", "pickup"), ("已接載乘客", "onboard"),
                                              ("到達目的地", "destination")])
def test_active_order_entry_never_uses_history_back(state, phase_label, phase):
    flow, _, _, data = state
    data["screen"] = page(phase_label, TARGET)
    flow.deadline = 3
    _, actual = flow.wait_for_entry_page()
    assert actual == phase
    flow.client.back.assert_not_called()
    flow.act.assert_not_called()
