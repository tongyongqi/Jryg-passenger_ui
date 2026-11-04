"""真机地址结果层级、出口空格及搜索局部空闲等待回归。"""

from unittest.mock import Mock
import xml.etree.ElementTree as ET

import pytest

from jryg_hk_android.JRYG_android_passenger import AndroidPassengerBase
from jryg_hk_android.JRYG_android_ui import normalized_tree

PACKAGE = "com.sunlightmobility.client"
DISTRICT = "香港特別行政區東區Eastern District"


def node(text="", resource="", kind="android.widget.TextView", **attrs):
    return ET.Element("node", {"text": text, "resource-id": PACKAGE + ":id/" + resource if resource else "",
                              "class": kind, "bounds": "[10,10][300,200]", "enabled": "true",
                              "displayed": "true", "clickable": "false", **attrs})


def row(title="北角(地鐵站)", district=DISTRICT, exit_text=" A1出入口 "):
    outer = node(resource="rl_parent", kind="android.widget.RelativeLayout", clickable="true")
    address = node(resource="rl_address", kind="android.widget.RelativeLayout")
    address.extend([node(title, "tv_address_name"), node("香港特別行政區", "tv_address_city_name"),
                    node(district, "tv_address_detail_name")])
    outer.append(address)
    if exit_text is not None:
        exits = node(kind="android.widget.LinearLayout")
        exits.extend([node(exit_text, clickable="true"), node(" B1出入口 ", clickable="true")])
        outer.append(exits)
    return outer


def tree(*rows):
    native = ET.Element("hierarchy")
    listing = node(resource="lv_addresses", kind="androidx.recyclerview.widget.RecyclerView")
    listing.extend(rows)
    native.append(listing)
    return normalized_tree(ET.tostring(native, encoding="unicode"), PACKAGE)


def test_real_address_name_nested_details_and_sibling_a1_exit_are_selected():
    root = tree(row(), row("北角", "香港特別行政區離島區Islands District"))
    target = AndroidPassengerBase._native_address_result(root, ["北角(地鐵站)"], True)
    assert target.get("label").strip() == "A1出入口"


@pytest.mark.parametrize("district,exit_text", [("西區", " A1出入口 "), (DISTRICT, " A2出入口 "), (DISTRICT, None)])
def test_wrong_district_exit_or_missing_exit_never_selects(district, exit_text):
    root = tree(row(district=district, exit_text=exit_text))
    assert AndroidPassengerBase._native_address_result(root, ["北角(地鐵站)"], True) is None


def test_cannot_take_exit_from_another_station_row():
    root = tree(row(exit_text=None), row("其他車站"))
    assert AndroidPassengerBase._native_address_result(root, ["北角(地鐵站)"], True) is None


def test_duplicate_real_stations_are_not_selected_by_position():
    with pytest.raises(AssertionError, match="不唯一"):
        AndroidPassengerBase._native_address_result(tree(row(), row()), ["北角(地鐵站)"], True)


def test_duplicate_a1_inside_station_is_rejected():
    station = row()
    station[-1].append(node("A1出入口", clickable="true"))
    with pytest.raises(AssertionError, match="不唯一"):
        AndroidPassengerBase._native_address_result(tree(station), ["北角(地鐵站)"], True)


def test_disabled_a1_not_selected():
    station = row()
    station[-1][0].set("enabled", "false")
    assert AndroidPassengerBase._native_address_result(tree(station), ["北角(地鐵站)"], True) is None


def test_destination_uses_real_name_id_and_rejects_same_named_duplicates():
    destination = row("香港大學", "香港特別行政區中西區", None)
    assert AndroidPassengerBase._native_address_result(tree(destination), ["香港大學"]).get("label") == "香港大學"
    with pytest.raises(AssertionError, match="不唯一"):
        AndroidPassengerBase._native_address_result(tree(destination, row("香港大學")), ["香港大學"])


@pytest.mark.parametrize("failure", [False, True])
def test_search_disables_idle_only_locally_and_restores_on_failure(failure):
    order = AndroidPassengerBase()
    order.client = Mock()
    order.client.driver.get_settings.return_value = {"waitForIdleTimeout": 10000}
    order._search_address_ready = Mock(return_value=True)
    if failure:
        order._search_address_ready.side_effect = TimeoutError("source timeout")
        with pytest.raises(TimeoutError, match="source timeout"):
            order._search_address(["tv_start_address"], [], "北角", ["北角(地鐵站)"])
    else:
        assert order._search_address(["tv_start_address"], [], "北角", ["北角(地鐵站)"])
    assert order.client.driver.update_settings.call_args_list[0].args == ({"waitForIdleTimeout": 0},)
    assert order.client.driver.update_settings.call_args_list[1].args == ({"waitForIdleTimeout": 10000},)
    order._search_address_ready.assert_called_once()


def test_hku_main_campus_is_chosen_by_exact_detail_not_list_position():
    main = "香港特別行政區中西區薄扶林道"
    medical = "香港特別行政區南區薄扶林沙宣道21號"
    root = tree(row("香港大學", medical, None), row("香港大學", main, None))
    selected = AndroidPassengerBase._native_address_result(root, ["香港大學"], expected_details=[main])
    parents = {child: parent for parent in root.iter() for child in parent}
    assert any(node.get("label") == main for node in parents[selected])


def test_hku_detail_cannot_be_taken_from_different_result_row():
    main = "香港特別行政區中西區薄扶林道"
    root = tree(row("香港大學", "南區", None), row("其他學校", main, None))
    assert AndroidPassengerBase._native_address_result(root, ["香港大學"], expected_details=[main]) is None


def test_same_named_main_campus_duplicates_still_stop_selection():
    main = "香港特別行政區中西區薄扶林道"
    root = tree(row("香港大學", main, None), row("香港大學", main, None))
    with pytest.raises(AssertionError, match="不唯一"):
        AndroidPassengerBase._native_address_result(root, ["香港大學"], expected_details=[main])
