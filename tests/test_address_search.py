from types import SimpleNamespace
from unittest.mock import Mock
import xml.etree.ElementTree as ET

import pytest

from ui_framework import JRYG_ios_ui_elements as E
from ui_framework.JRYG_device_guard import DeviceUnlockError
from ui_framework.JRYG_ios_ui_base import iOSBase


class AddressClient:
    def __init__(self):
        self.mode = "home"
        self.value = "上次查询"
        self.events = []
        self.submitted = False
        self.polls = 0
        self.delay = 2
        self.result_labels = None
        self.search_labels = ["搜索"]
        self.search_enabled = True
        self.bad_value = False
        self.clear_fails = False
        self.stay_on_search = False
        self.search_error = None
        self.result_error = None
        self.bundle = E.PASSENGER_BUNDLE_ID
        self.alert = False
        self.wrong_field = False
        self.duplicate_field = False
        self.field_enabled = True
        self.actual_start = "銅鑼灣"
        self.actual_end = "大潭郊野公園"
        self.source = Mock(side_effect=self.xml)
        self.send_keys = Mock(side_effect=AssertionError("禁止向未知焦点发送地址"))
        self.click = Mock(side_effect=AssertionError("禁止固定坐标选址"))

    def xml(self, **_kwargs):
        root = ET.Element("XCUIElementTypeApplication", bundleId=self.bundle)
        if self.alert:
            ET.SubElement(root, "XCUIElementTypeAlert", visible="true")
        if self.mode in ("start", "end"):
            start = self.mode == "start"
            placeholder = "您從哪裡出發" if start != self.wrong_field else "請輸入落車點"
            if not start and not self.wrong_field:
                placeholder = "請輸入落車點"
            for index in range(2 if self.duplicate_field else 1):
                ET.SubElement(root, "XCUIElementTypeTextField", name=f"field{index}", label=placeholder,
                              placeholderValue=placeholder, value=self.value, visible="true",
                              enabled=str(self.field_enabled).lower())
            table = ET.SubElement(root, "XCUIElementTypeTable", visible="true")
            self.polls += int(self.submitted)
            if self.submitted and self.polls >= self.delay:
                labels = self.result_labels if self.result_labels is not None else [
                    "銅鑼灣" if start else "大潭郊野公園"]
            else:
                labels = [E.DEFAULT_START_ADDRESS if start else "大新大廈", "大家樂"]
            for label in labels:
                cell = ET.SubElement(table, "XCUIElementTypeCell", visible="true", enabled="true")
                ET.SubElement(cell, "XCUIElementTypeStaticText", label=label, name="result",
                              visible="true", enabled="true")
            keyboard = ET.SubElement(root, "XCUIElementTypeKeyboard", visible="true")
            for label in self.search_labels:
                ET.SubElement(keyboard, "XCUIElementTypeButton", label=label, name="keyboard_search",
                              visible="true", enabled=str(self.search_enabled).lower())
            ET.SubElement(keyboard, "XCUIElementTypeButton", label="Done", name="done", visible="true", enabled="true")
            prediction = ET.SubElement(keyboard, "XCUIElementTypeCell", visible="true", enabled="true")
            ET.SubElement(prediction, "XCUIElementTypeStaticText", label=self.value, visible="true")
        else:
            ET.SubElement(root, "XCUIElementTypeStaticText", label="想去哪裡" if self.mode == "home" else "確認呼叫", visible="true")
            if self.mode == "home":
                row = ET.SubElement(root, "XCUIElementTypeOther", visible="true", enabled="true")
                ET.SubElement(row, "XCUIElementTypeButton", name="start_gate", visible="true", enabled="true")
                ET.SubElement(row, "XCUIElementTypeButton", label="無法取得位置，請輸入起點", visible="false", enabled="true")
            else:
                for marker, text in (("start", self.actual_start), ("end", self.actual_end)):
                    row = ET.SubElement(root, "XCUIElementTypeOther", visible="true", enabled="true")
                    ET.SubElement(row, "XCUIElementTypeImage", name=f"slm_icon_anno_{marker}", visible="true")
                    ET.SubElement(row, "XCUIElementTypeStaticText", label=text, visible="true")
        return ET.tostring(root, encoding="unicode")

    def enter(self, mode):
        self.events.append(("open", mode))
        self.mode, self.value, self.submitted, self.polls = mode, "上次查询", False, 0

    def element(self, node):
        element = Mock(displayed=True, enabled=True, className=node.tag,
                       label=node.get("label"), value=node.get("value"))
        element.name = node.get("name")
        name = node.get("name")
        if name and name.startswith("field"):
            element.click.side_effect = lambda: self.events.append(("focus", self.mode))

            def clear():
                self.events.append(("clear", self.mode))
                if not self.clear_fails:
                    self.value = ""

            def set_text(text):
                self.events.append(("input", self.mode, text))
                self.value = "错误输入" if self.bad_value else text

            element.clear_text.side_effect = clear
            element.set_text.side_effect = set_text
        elif name == "start_gate":
            element.tap.side_effect = lambda: self.enter("start")
        elif name == "keyboard_search":
            def search():
                self.events.append(("search", self.mode))
                self.submitted = True
                if self.search_error:
                    raise self.search_error
            element.tap.side_effect = search
        elif name == "result":
            def select():
                self.events.append(("select", self.mode, node.get("label")))
                if self.result_error:
                    raise self.result_error
                if not self.stay_on_search:
                    self.mode = "home" if self.mode == "start" else "route"
            element.tap.side_effect = select
        else:
            element.tap.side_effect = AssertionError("不能点击键盘Done或无关控件")
        return element

    def __call__(self, **query):
        xpath = query.get("xpath")
        if xpath in (E.START_GATE_XPATH, E.DEST_GATE_XPATH):
            mode = "start" if xpath == E.START_GATE_XPATH else "end"
            return Mock(exists=True, click=Mock(side_effect=lambda: self.enter(mode)))
        if query.get("type") == "TextField":
            return SimpleNamespace(exists=self.mode in ("start", "end"))
        if xpath and xpath.startswith("//XCUIElementTypeApplication[1]/"):
            root = ET.fromstring(self.xml())
            node = root.find(xpath.split("/", 3)[3])
            if node is None:
                return Mock(find_elements=Mock(return_value=[]))
            return Mock(find_elements=Mock(return_value=[self.element(node)]))
        raise AssertionError(f"禁止未限定的查询：{query}")


@pytest.fixture
def flow(monkeypatch):
    monkeypatch.setattr("ui_framework.JRYG_ios_ui_base.ensure_unlocked", Mock())
    monkeypatch.setattr("ui_framework.JRYG_ios_ui_base.remember_foreground", Mock())
    monkeypatch.setattr("ui_framework.JRYG_ios_ui_base.time.sleep", Mock())
    instance = iOSBase()
    instance.client = AddressClient()
    instance.poco = Mock(side_effect=AssertionError("禁止Poco降级选址"))
    instance._ios_screenshot = Mock()
    return instance


def test_real_address_methods_input_start_then_search_then_end(flow):
    flow._ios_configure_addresses("offline", E.DEFAULT_START_ADDRESS, E.DEFAULT_END_ADDRESS)
    assert flow.client.events == [
        ("open", "start"), ("focus", "start"), ("clear", "start"),
        ("input", "start", E.DEFAULT_START_ADDRESS), ("search", "start"),
        ("select", "start", "銅鑼灣"),
        ("open", "end"), ("focus", "end"), ("clear", "end"),
        ("input", "end", E.DEFAULT_END_ADDRESS), ("search", "end"),
        ("select", "end", "大潭郊野公園"),
    ]
    assert flow._ios_call_route_key == ("銅鑼灣", "大潭郊野公園")
    flow.client.send_keys.assert_not_called()
    flow.client.click.assert_not_called()


def test_launch_and_login_precede_real_start_and_destination_search(flow, monkeypatch):
    monkeypatch.setattr(flow, "_ios_prepare_passenger_app", Mock(side_effect=lambda _tag: flow.client.events.append(("launch",))))
    monkeypatch.setattr(flow, "_ios_ensure_logged_in", Mock(side_effect=lambda **_kwargs: flow.client.events.append(("login",)) or True))
    flow._ios_launch_setup_and_addresses("offline", E.DEFAULT_START_ADDRESS, E.DEFAULT_END_ADDRESS)
    assert [event[0] for event in flow.client.events] == [
        "launch", "login", "open", "focus", "clear", "input", "search", "select",
        "open", "focus", "clear", "input", "search", "select",
    ]
    assert [event[1] for event in flow.client.events if event[0] == "input"] == ["start", "end"]


@pytest.mark.parametrize("start_name", ["铜锣湾", "銅鑼灣"])
def test_only_causeway_bay_input_uses_single_query_and_keyboard_search(flow, start_name):
    flow._ios_configure_addresses("offline", start_name, E.DEFAULT_END_ADDRESS)
    assert ("input", "start", "铜锣湾") in flow.client.events
    assert flow.client.events.index(("search", "start")) < flow.client.events.index(("open", "end"))
    assert flow._ios_call_route_key == ("銅鑼灣", "大潭郊野公園")


@pytest.mark.parametrize("address", ["北角", "铜锣湾地铁站", "铜锣湾地铁站D2出口", "中環", "", None])
@pytest.mark.parametrize("entry", ["search", "query", "select", "configure", "launch", "re_setup"])
def test_other_start_addresses_are_rejected_before_any_ui_action(flow, address, entry):
    from ui_framework.JRYG_order_flow import TestOrderBase

    if entry == "search":
        action = lambda: flow._ios_search_address(True, address)
    elif entry == "query":
        action = lambda: flow._ios_enter_address_query(True, address)
    elif entry == "select":
        action = lambda: flow._ios_select_search_result(True, address, address)
    elif entry == "configure":
        action = lambda: flow._ios_configure_addresses("offline", address, E.DEFAULT_END_ADDRESS)
    elif entry == "launch":
        action = lambda: flow._ios_launch_setup_and_addresses("offline", address, E.DEFAULT_END_ADDRESS)
    else:
        action = lambda: TestOrderBase._ios_re_setup_from_current_page(flow, "offline", address, E.DEFAULT_END_ADDRESS)
    with pytest.raises(AssertionError, match="起点仅允许铜锣湾"):
        action()
    assert flow.client.events == []
    flow.client.source.assert_not_called()
    flow.client.click.assert_not_called()


@pytest.mark.parametrize("label", ["搜索", "搜尋", "Search", "search"])
def test_keyboard_search_submitted_even_with_existing_exact_result(flow, label):
    flow.client.search_labels = [label]
    flow.client.enter("start")
    flow._ios_enter_address_query(True, E.DEFAULT_START_ADDRESS)
    assert flow.client.events[-1] == ("search", "start")
    assert not any(event[0] == "select" for event in flow.client.events)


@pytest.mark.parametrize("fault", ["wrong_field", "duplicate_field", "field_enabled", "bundle", "alert"])
def test_wrong_field_frontground_or_alert_blocks_input(flow, fault):
    flow.client.enter("start")
    setattr(flow.client, fault, False if fault == "field_enabled" else "other.app" if fault == "bundle" else True)
    with pytest.raises(AssertionError):
        flow._ios_enter_address_query(True, E.DEFAULT_START_ADDRESS)
    assert not any(event[0] in ("input", "search", "select") for event in flow.client.events)


@pytest.mark.parametrize("fault", ["clear_fails", "bad_value"])
def test_input_readback_failure_never_submits_search(flow, fault):
    flow.client.enter("start")
    setattr(flow.client, fault, True)
    with pytest.raises(AssertionError):
        flow._ios_enter_address_query(True, E.DEFAULT_START_ADDRESS)
    assert not any(event[0] in ("search", "select") for event in flow.client.events)


@pytest.mark.parametrize("labels,enabled", [([], True), (["Done"], True), (["搜索"], False), (["搜索", "Search"], True)])
def test_missing_disabled_or_duplicate_keyboard_search_never_selects(flow, labels, enabled):
    flow.client.enter("end")
    flow.client.search_labels, flow.client.search_enabled = labels, enabled
    with pytest.raises(AssertionError, match="搜索"):
        flow._ios_enter_address_query(False, E.DEFAULT_END_ADDRESS)
    assert not any(event[0] in ("search", "select") for event in flow.client.events)


@pytest.mark.parametrize("labels", [["大新大廈", "大家樂"], ["大潭郊野公園餐廳"]])
def test_unrelated_result_cannot_be_selected(flow, labels):
    flow.client.result_labels = labels
    with pytest.raises(AssertionError, match="结果"):
        flow._ios_search_address(False, E.DEFAULT_END_ADDRESS)
    assert not any(event[0] == "select" for event in flow.client.events)
    flow.client.click.assert_not_called()


def test_duplicate_exact_result_selects_first(flow):
    """同名精确结果出现在多个Cell时，选App排序的第一个，不报错。"""
    flow.client.result_labels = ["大潭郊野公園", "大潭郊野公園"]
    flow._ios_search_address(False, E.DEFAULT_END_ADDRESS)
    assert any(event[0] == "select" for event in flow.client.events)


@pytest.mark.parametrize("stage", ["search", "result"])
def test_uncertain_click_is_not_replayed(flow, stage):
    setattr(flow.client, f"{stage}_error", TimeoutError("response lost"))
    with pytest.raises(TimeoutError):
        flow._ios_search_address(False, E.DEFAULT_END_ADDRESS)
    assert len([event for event in flow.client.events if event[0] == ("search" if stage == "search" else "select")]) == 1
    flow.client.click.assert_not_called()


def test_no_jump_does_not_try_other_result(flow):
    flow.client.stay_on_search = True
    with pytest.raises(AssertionError, match="跳转"):
        flow._ios_search_address(False, E.DEFAULT_END_ADDRESS)
    assert len([event for event in flow.client.events if event[0] == "select"]) == 1


def test_start_failure_prevents_opening_destination(flow):
    flow.client.search_labels = []
    with pytest.raises(AssertionError):
        flow._ios_configure_addresses("offline", E.DEFAULT_START_ADDRESS, E.DEFAULT_END_ADDRESS)
    assert ("open", "end") not in flow.client.events


@pytest.mark.parametrize("actual_start,actual_end", [
    ("北角地鐵站", "大潭郊野公園"), ("中環", "大潭郊野公園"),
    ("銅鑼灣", "大新大廈"), ("铜锣湾地铁站D2出口", "大新大廈"),
])
def test_route_addresses_must_match_request(flow, actual_start, actual_end):
    flow.client.actual_start, flow.client.actual_end = actual_start, actual_end
    with pytest.raises(AssertionError, match="实际起终点"):
        flow._ios_configure_addresses("offline", E.DEFAULT_START_ADDRESS, E.DEFAULT_END_ADDRESS)
    assert not hasattr(flow, "_ios_call_route_key")


def test_device_unlock_failure_blocks_all_address_operations(flow, monkeypatch):
    monkeypatch.setattr("ui_framework.JRYG_ios_ui_base.ensure_unlocked", Mock(side_effect=DeviceUnlockError("locked")))
    with pytest.raises(DeviceUnlockError):
        flow._ios_enter_address_query(True, E.DEFAULT_START_ADDRESS)
    assert flow.client.events == []


@pytest.mark.parametrize("visible,enabled,keyboard", [(False, True, False), (True, False, False), (True, True, True)])
def test_hidden_disabled_and_keyboard_results_are_excluded(visible, enabled, keyboard):
    root = ET.Element("XCUIElementTypeApplication", bundleId=E.PASSENGER_BUNDLE_ID)
    parent = ET.SubElement(root, "XCUIElementTypeKeyboard") if keyboard else root
    cell = ET.SubElement(parent, "XCUIElementTypeCell", visible=str(visible).lower(), enabled=str(enabled).lower())
    ET.SubElement(cell, "XCUIElementTypeStaticText", label="大潭郊野公園", visible="true")
    assert iOSBase._ios_address_result_node(root, E.DEFAULT_END_ADDRESS) is None


@pytest.mark.parametrize("label", ["銅鑼灣(地鐵站)", "銅鑼灣地鐵站D2出入口", "銅鑼灣廣場", "北角地鐵站", "(銅鑼灣)"])
def test_station_exit_or_similar_name_is_not_the_only_start(label):
    root = ET.Element("XCUIElementTypeApplication", bundleId=E.PASSENGER_BUNDLE_ID)
    cell = ET.SubElement(root, "XCUIElementTypeCell", visible="true", enabled="true")
    ET.SubElement(cell, "XCUIElementTypeStaticText", label=label, visible="true")
    ET.SubElement(cell, "XCUIElementTypeButton", label="D2出入口", visible="true", enabled="true")
    assert iOSBase._ios_address_result_node(root, E.DEFAULT_START_ADDRESS, is_start=True) is None


@pytest.mark.parametrize("label", ["铜锣湾", "銅鑼灣"])
def test_start_result_only_accepts_exact_simplified_or_traditional_name(label):
    root = ET.Element("XCUIElementTypeApplication", bundleId=E.PASSENGER_BUNDLE_ID)
    cell = ET.SubElement(root, "XCUIElementTypeCell", visible="true", enabled="true")
    target = ET.SubElement(cell, "XCUIElementTypeStaticText", label=label, visible="true")
    assert iOSBase._ios_address_result_node(root, E.DEFAULT_START_ADDRESS, is_start=True) is target


def test_multiple_start_results_selects_first_by_y():
    """真机搜索铜锣湾返回多个同名Cell；取App排序第一个，与App解析结果一致。"""
    root = ET.Element("XCUIElementTypeApplication", bundleId=E.PASSENGER_BUNDLE_ID)
    cell0 = ET.SubElement(root, "XCUIElementTypeCell", visible="true", enabled="true", y="131")
    ET.SubElement(cell0, "XCUIElementTypeStaticText", label="香港特別行政區灣仔區Wan Chai District", visible="true")
    target0 = ET.SubElement(cell0, "XCUIElementTypeStaticText", label="銅鑼灣", visible="true")
    cell1 = ET.SubElement(root, "XCUIElementTypeCell", visible="true", enabled="true", y="200")
    ET.SubElement(cell1, "XCUIElementTypeStaticText", label="銅鑼灣(地鐵站)", visible="true")
    cell2 = ET.SubElement(root, "XCUIElementTypeCell", visible="true", enabled="true", y="401")
    ET.SubElement(cell2, "XCUIElementTypeStaticText", label="香港特別行政區灣仔區禮頓道140號", visible="true")
    ET.SubElement(cell2, "XCUIElementTypeStaticText", label="銅鑼灣", visible="true")
    cell3 = ET.SubElement(root, "XCUIElementTypeCell", visible="true", enabled="true", y="539")
    ET.SubElement(cell3, "XCUIElementTypeStaticText", label="香港特別行政區油尖旺區尖沙咀金巴利街22號", visible="true")
    ET.SubElement(cell3, "XCUIElementTypeStaticText", label="銅鑼灣", visible="true")
    node = iOSBase._ios_address_result_node(root, E.DEFAULT_START_ADDRESS, is_start=True)
    assert node is target0


def test_route_accepts_station_exit_parsed_start():
    """App把铜锣湾解析成铜锣湾地铁站D2出口，路线核验按前缀接受。"""
    root = ET.Element("XCUIElementTypeApplication", bundleId=E.PASSENGER_BUNDLE_ID)
    parents = {child: parent for parent in root.iter() for child in parent}
    start_row = ET.SubElement(root, "XCUIElementTypeOther", visible="true", enabled="true")
    ET.SubElement(start_row, "XCUIElementTypeImage", name="slm_icon_anno_start", visible="true")
    ET.SubElement(start_row, "XCUIElementTypeStaticText", label="铜锣湾地铁站D2出口", visible="true")
    end_row = ET.SubElement(root, "XCUIElementTypeOther", visible="true", enabled="true")
    ET.SubElement(end_row, "XCUIElementTypeImage", name="slm_icon_anno_end", visible="true")
    ET.SubElement(end_row, "XCUIElementTypeStaticText", label="大潭郊野公园", visible="true")
    route = iOSBase._ios_estimate_route_identity(root)
    assert route == ("铜锣湾地铁站D2出口", "大潭郊野公园")
    assert route[0].startswith(E.START_ROUTE_PREFIXES[0])


def test_other_start_constants_and_special_search_are_removed():
    from ui_framework.JRYG_config import SETTINGS

    assert E.DEFAULT_START_ADDRESS == "铜锣湾"
    assert E.START_ADDRESS_NAMES == ("铜锣湾", "銅鑼灣")
    assert SETTINGS["order_validation"]["start_names"] == ["铜锣湾", "銅鑼灣"]
    assert not hasattr(E, "BOOKING_START_ADDRESS")
    assert not any(name.startswith("NORTH_POINT_") for name in vars(E))
    assert not hasattr(iOSBase, "_ios_north_point_exit")
    assert not hasattr(iOSBase, "_ios_search_north_point_start")


def test_stale_xpath_cannot_click_different_address(flow):
    root = ET.Element("XCUIElementTypeApplication")
    node = ET.SubElement(root, "XCUIElementTypeStaticText", label="大潭郊野公園")
    element = Mock(displayed=True, enabled=True, className=node.tag, label="大新大廈")
    flow.client = Mock(return_value=Mock(find_elements=Mock(return_value=[element])))
    with pytest.raises(AssertionError, match="身份已变化"):
        flow._ios_click_address_node(root, node)
    element.tap.assert_not_called()


def start_entry_page(prompt="無法取得位置，請輸入起點"):
    root = ET.Element("XCUIElementTypeApplication", bundleId=E.PASSENGER_BUNDLE_ID)
    map_row = ET.SubElement(root, "XCUIElementTypeOther", visible="true", enabled="true")
    ET.SubElement(map_row, "XCUIElementTypeButton", visible="true", enabled="true")
    ET.SubElement(map_row, "XCUIElementTypeStaticText", label="無法獲取位置", visible="false", enabled="true")
    row = ET.SubElement(root, "XCUIElementTypeOther", visible="true", enabled="true", x="23", y="544", width="347", height="43")
    target = ET.SubElement(row, "XCUIElementTypeButton", visible="true", enabled="true", x="41", y="558", width="311", height="36")
    ET.SubElement(row, "XCUIElementTypeButton", label=prompt, visible="false", enabled="true", x="52", y="566", width="165", height="20")
    destination = ET.SubElement(root, "XCUIElementTypeOther", visible="true", enabled="true")
    ET.SubElement(destination, "XCUIElementTypeButton", label="想去哪裡？", visible="true", enabled="true")
    return root, row, target


@pytest.mark.parametrize("prompt", [
    "無法取得位置，請輸入起點", "無法獲取位置，請輸入起點", "无法取得位置，请输入起点", "无法获取位置，请输入起点",
])
def test_hidden_start_prompt_selects_its_visible_sibling_not_map_or_destination(prompt):
    root, _row, target = start_entry_page(prompt)
    assert iOSBase._ios_start_entry_node(root) is target


@pytest.mark.parametrize("fault", ["hidden_row", "disabled_row", "hidden_button", "disabled_button", "duplicate_button", "duplicate_row", "history"])
def test_unavailable_or_ambiguous_start_entry_is_never_selected(fault):
    root, row, target = start_entry_page()
    if fault == "hidden_row":
        row.set("visible", "false")
    elif fault == "disabled_row":
        row.set("enabled", "false")
    elif fault == "hidden_button":
        target.set("visible", "false")
    elif fault == "disabled_button":
        target.set("enabled", "false")
    elif fault == "duplicate_button":
        ET.SubElement(row, "XCUIElementTypeButton", visible="true", enabled="true")
    elif fault == "duplicate_row":
        other = ET.SubElement(root, "XCUIElementTypeOther", visible="true", enabled="true")
        ET.SubElement(other, "XCUIElementTypeButton", label="請輸入起點", visible="true", enabled="true")
    else:
        row.tag = "XCUIElementTypeCell"
    if fault.startswith("duplicate"):
        with pytest.raises(AssertionError, match="不唯一"):
            iOSBase._ios_start_entry_node(root)
    else:
        assert iOSBase._ios_start_entry_node(root) is None


def test_current_start_entry_opens_search_without_input_or_location(flow):
    root, _row, target = start_entry_page()
    home = ET.tostring(root, encoding="unicode")
    flow.client.enter("start")
    search = flow.client.xml()
    flow.client.events.clear()
    flow._ios_get_source_xml = Mock(side_effect=[home, home, search])
    button = Mock(displayed=True, enabled=True, className="XCUIElementTypeButton", label=None, value=None,
                  bounds=SimpleNamespace(x=41, y=558, width=311, height=36))
    button.name = "XCUIElementTypeButton"
    flow.client = Mock(return_value=Mock(find_elements=Mock(return_value=[button])))
    flow._ios_open_start_search()
    button.tap.assert_called_once()
    assert flow.client.call_args.kwargs == {"xpath": flow._ios_address_node_xpath(root, target)}
    flow.client.click.assert_not_called()
    flow.client.send_keys.assert_not_called()


@pytest.mark.parametrize("outcome", ["response_lost", "no_jump", "destination_search", "alert", "wrong_app"])
def test_start_entry_failure_never_replays_click_or_changes_other_page(flow, outcome):
    root, _row, _target = start_entry_page()
    home = ET.tostring(root, encoding="unicode")
    after = ET.fromstring(home)
    if outcome == "destination_search":
        ET.SubElement(after, "XCUIElementTypeTextField", visible="true", enabled="true", placeholderValue="請輸入落車點")
    elif outcome == "alert":
        ET.SubElement(after, "XCUIElementTypeAlert", visible="true")
    elif outcome == "wrong_app":
        after.set("bundleId", "other.app")
    after_xml = ET.tostring(after, encoding="unicode")
    pages = iter([home, home])
    flow._ios_get_source_xml = Mock(side_effect=lambda: next(pages, after_xml))
    button = Mock(displayed=True, enabled=True, className="XCUIElementTypeButton", label=None, value=None,
                  bounds=SimpleNamespace(x=41, y=558, width=311, height=36))
    button.name = "XCUIElementTypeButton"
    if outcome == "response_lost":
        button.tap.side_effect = TimeoutError("lost")
    flow.client = Mock(return_value=Mock(find_elements=Mock(return_value=[button])))
    with pytest.raises((AssertionError, TimeoutError)):
        flow._ios_open_start_search()
    button.tap.assert_called_once()
    flow.client.click.assert_not_called()
    flow.client.send_keys.assert_not_called()


@pytest.mark.parametrize("fault", ["moved", "missing_bounds", "wrong_name", "wrong_type"])
def test_anonymous_start_button_identity_must_still_match(flow, fault):
    root, _row, target = start_entry_page()
    button = Mock(displayed=True, enabled=True, className="XCUIElementTypeButton", label=None, value=None,
                  bounds=SimpleNamespace(x=41, y=558, width=311, height=36))
    button.name = "XCUIElementTypeButton"
    if fault == "moved":
        button.bounds.y = 610
    elif fault == "missing_bounds":
        target.attrib.pop("width")
    elif fault == "wrong_name":
        button.name = "確認呼叫"
    else:
        button.className = "XCUIElementTypeStaticText"
    flow.client = Mock(return_value=Mock(find_elements=Mock(return_value=[button])))
    with pytest.raises(AssertionError):
        flow._ios_click_address_node(root, target)
    button.tap.assert_not_called()


def test_already_in_start_search_does_not_click_home_or_clear_query(flow):
    flow.client.enter("start")
    flow.client.events.clear()
    flow._ios_open_start_search()
    assert flow.client.events == []
    assert flow.client.value == "上次查询"
