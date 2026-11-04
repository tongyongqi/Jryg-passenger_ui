"""Canvas实际截图路线核验回归，不以搜索意图替代当前画面。"""

from unittest.mock import Mock
from pathlib import Path

import pytest

from jryg_hk_android import JRYG_android_route_ocr as ocr
from jryg_hk_android.JRYG_android_passenger import AndroidPassengerBase
from tests.test_shared_android_orders import quote_tree


def observation(text, confidence=0.5, y=0.3):
    return {"text": text, "confidence": confidence, "x": 0.2, "y": y, "width": 0.3, "height": 0.02}


def canvas_root():
    root = quote_tree()
    for node in root.iter():
        if node.get("resource-id", "").endswith(("/tv_start_address", "/tv_destination")):
            node.attrib.pop("resource-id")
            node.set("label", "")
        if node.get("label") == "包車價的士":
            node.set("resource-id", "com.sunlightmobility.client:id/tv_car_type_name")
            node.set("y", "1400")
    return root


@pytest.mark.parametrize("start,end", [("北角（地鐵站） A1出入口", "香港大學"),
                                       ("北角(地铁站)A1出入口＞", "香港大学，")])
def test_canvas_markers_are_normalized_without_losing_exit(start, end):
    assert ocr.map_route([observation(start), observation(end)], .6) == ("北角(地鐵站) A1出入口", "香港大學")


@pytest.mark.parametrize("start,end", [("北角(地鐵站)A2出入口", "香港大學"),
                                       ("北角(地鐵站)", "香港大學"),
                                       ("北角(地鐵站)A1出入口", "香港中文大學")])
def test_canvas_wrong_exit_or_destination_never_passes(start, end):
    assert ocr.map_route([observation(start), observation(end)], .6) is None


@pytest.mark.parametrize("fault", ["low", "outside", "duplicate", "missing"])
def test_canvas_uncertain_or_non_unique_result_never_passes(fault):
    items = [observation("北角(地鐵站)A1出入口"), observation("香港大學")]
    if fault == "low":
        items[0]["confidence"] = .3
    elif fault == "outside":
        items[0]["y"] = .7
    elif fault == "duplicate":
        items.append(observation("香港大學"))
    else:
        items.pop()
    assert ocr.map_route(items, .6) is None


def test_route_reader_uses_fresh_screenshot_every_time_including_quote(monkeypatch):
    order = AndroidPassengerBase()
    order.client = Mock()
    order.client.window_size.return_value = (1080, 2400)
    route = ("北角(地鐵站) A1出入口", "香港大學")
    read = Mock(return_value=route)
    monkeypatch.setattr(ocr, "current_map_route", read)
    root = canvas_root()
    assert order._ios_estimate_route_identity(root) == route
    assert order._ios_estimate_route_identity(root) == route
    assert order._ios_estimate_quote(root, "charter") == (route, "50")
    assert read.call_count == 3


def test_native_route_keeps_existing_contract_and_does_not_ocr(monkeypatch):
    order = AndroidPassengerBase()
    read = Mock()
    monkeypatch.setattr(ocr, "current_map_route", read)
    assert order._ios_estimate_route_identity(quote_tree()) == ("北角(地鐵站) A1", "香港大學")
    read.assert_not_called()


def test_partial_native_route_cannot_be_filled_from_screenshot(monkeypatch):
    order = AndroidPassengerBase()
    root = quote_tree()
    for node in root.iter():
        if node.get("resource-id", "").endswith("/tv_destination"):
            node.set("label", "")
    read = Mock()
    monkeypatch.setattr(ocr, "current_map_route", read)
    assert order._ios_estimate_route_identity(root) is None
    read.assert_not_called()


def test_canvas_quote_stops_when_current_screenshot_is_uncertain(monkeypatch):
    order = AndroidPassengerBase()
    order.client = Mock()
    order.client.window_size.return_value = (1080, 2400)
    monkeypatch.setattr(ocr, "current_map_route", Mock(return_value=None))
    assert order._ios_estimate_quote(canvas_root(), "charter") is None


def test_screenshot_temporary_files_are_removed_and_foreground_checked(monkeypatch):
    client = Mock()
    client.driver.current_package = "com.sunlightmobility.client"
    paths = []

    def screenshot(path):
        paths.append(Path(path))
        Path(path).write_bytes(b"test")

    client.screenshot.side_effect = screenshot
    recognize = Mock(return_value=[observation("北角(地鐵站)A1出入口"), observation("香港大學")])
    monkeypatch.setattr(ocr, "recognize_markers", recognize)
    assert ocr.current_map_route(client, .6) == ("北角(地鐵站) A1出入口", "香港大學")
    assert not paths[0].exists()
    assert not paths[0].parent.exists()


def test_foreground_change_during_ocr_never_passes(monkeypatch):
    client = Mock()
    client.driver.current_package = "com.sunlightmobility.client"

    def recognize(path, bottom):
        client.driver.current_package = "com.sunlightmobility.driver"
        return [observation("北角(地鐵站)A1出入口"), observation("香港大學")]

    monkeypatch.setattr(ocr, "recognize_markers", recognize)
    with pytest.raises(RuntimeError, match="已离开"):
        ocr.current_map_route(client, .6)
