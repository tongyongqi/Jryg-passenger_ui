"""司机UI输入公共方法的离线回归，不连接设备。

有限选择器禁止无界迭代，模拟聚焦、清空和输入，验证placeholder唯一定位、
坐标匹配及每步截止时间；失败不得继续输入或记录未经核实的成功。
"""

import logging
from types import SimpleNamespace
from unittest.mock import Mock
import xml.etree.ElementTree as ET

import pytest

from ui_framework import JRYG_driver_ui as driver


class FiniteSelector:
    """强制测试通过有限find_elements读取控件，防止WDA选择器无界迭代。"""

    def __init__(self, fields):
        """保存有限的模拟输入框列表供find_elements返回。"""
        self.find_elements = Mock(return_value=fields)

    def __getitem__(self, index):
        """禁止下标或隐式for迭代，让错误的选择器访问立即失败。"""
        raise AssertionError("不能对WDA Selector进行list或for迭代")


def bill_page():
    """构造两个输入框的模拟账单，用placeholder和坐标验证正确匹配目标。"""
    root = ET.Element("XCUIElementTypeApplication", bundleId=driver.BUNDLE_ID, visible="true")
    for placeholder, y in (("請輸入車費", 295), ("請輸入附加費", 382)):
        ET.SubElement(root, "XCUIElementTypeTextField", visible="true",
                      placeholderValue=placeholder, value=placeholder,
                      x="74", y=str(y), width="242", height="26")
    return root


@pytest.fixture
def flow():
    """跳过真实WDA构造，提供有限控件和5秒输入时限测试实例。"""
    instance = driver.DriverUIFlow.__new__(driver.DriverUIFlow)
    instance.args = driver.parser().parse_args(["--step-timeout", "5"])
    instance.deadline = None
    instance.client = Mock()
    instance.fare_field = Mock(bounds=SimpleNamespace(x=74, y=295, width=242, height=26))
    instance.surcharge_field = Mock(bounds=SimpleNamespace(x=74, y=382, width=242, height=26))
    instance.selector = FiniteSelector([instance.surcharge_field, instance.fare_field])
    instance.client.return_value = instance.selector
    return instance


def test_fill_uses_finite_elements_and_sends_fare(flow):
    flow.fill(bill_page(), "請輸入車費", "5")
    flow.selector.find_elements.assert_called_once_with()
    flow.client.assert_called_once_with(className="XCUIElementTypeTextField")
    flow.client.click.assert_called_once_with(195, 308)
    flow.fare_field.clear_text.assert_called_once_with()
    flow.surcharge_field.clear_text.assert_not_called()
    flow.client.send_keys.assert_called_once_with("5")


def test_fill_logs_all_input_stages(flow, caplog):
    with caplog.at_level(logging.INFO, logger=driver.LOG.name):
        flow.fill(bill_page(), "請輸入車費", "5")
    for stage in ("查找输入框", "读取输入框坐标", "聚焦输入框", "清空旧内容", "输入内容"):
        assert stage in caplog.text


def test_empty_elements_fail_without_input(flow):
    flow.selector.find_elements.return_value = []
    with pytest.raises(RuntimeError, match="无法匹配"):
        flow.fill(bill_page(), "請輸入車費", "5")
    flow.client.click.assert_not_called()
    flow.client.send_keys.assert_not_called()


def test_non_matching_field_is_not_modified(flow):
    flow.selector.find_elements.return_value = [flow.surcharge_field]
    with pytest.raises(RuntimeError, match="无法匹配"):
        flow.fill(bill_page(), "請輸入車費", "5")
    flow.surcharge_field.clear_text.assert_not_called()
    flow.client.send_keys.assert_not_called()


@pytest.mark.parametrize("stage", ["lookup", "focus", "clear"])
def test_failed_stage_does_not_send_input(flow, stage):
    action = {"lookup": flow.selector.find_elements, "focus": flow.client.click,
              "clear": flow.fare_field.clear_text}[stage]
    action.side_effect = RuntimeError("WDA请求失败")
    with pytest.raises(RuntimeError, match="WDA请求失败"):
        flow.fill(bill_page(), "請輸入車費", "5")
    flow.client.send_keys.assert_not_called()


def test_expired_total_deadline_prevents_lookup(flow, monkeypatch):
    monkeypatch.setattr(driver.time, "monotonic", lambda: 10)
    flow.deadline = 9
    with pytest.raises(TimeoutError, match="查找输入框"):
        flow.fill(bill_page(), "請輸入車費", "5")
    flow.selector.find_elements.assert_not_called()
    flow.client.send_keys.assert_not_called()


def test_slow_clear_stops_before_input(flow, monkeypatch):
    clock = [0]
    monkeypatch.setattr(driver.time, "monotonic", lambda: clock[0])
    flow.fare_field.clear_text.side_effect = lambda: clock.__setitem__(0, 6)
    with pytest.raises(TimeoutError, match="清空旧内容耗时过长"):
        flow.fill(bill_page(), "請輸入車費", "5")
    flow.client.send_keys.assert_not_called()


def test_slow_lookup_stops_before_focus(flow, monkeypatch):
    clock = [0]
    monkeypatch.setattr(driver.time, "monotonic", lambda: clock[0])

    def slow_lookup():
        clock[0] = 6
        return [flow.fare_field]

    flow.selector.find_elements.side_effect = slow_lookup
    with pytest.raises(TimeoutError, match="查找输入框耗时过长"):
        flow.fill(bill_page(), "請輸入車費", "5")
    flow.client.click.assert_not_called()
    flow.client.send_keys.assert_not_called()


def test_duplicate_fields_block_input(flow):
    root = bill_page()
    root.append(ET.fromstring(ET.tostring(root[0])))
    with pytest.raises(RuntimeError, match="唯一定位"):
        flow.fill(root, "請輸入車費", "5")
    flow.selector.find_elements.assert_not_called()


def test_constructor_sets_bounded_wda_timeout(monkeypatch):
    monkeypatch.setattr(driver.wda, "HTTP_TIMEOUT", 180)
    monkeypatch.setattr(driver.wda, "Client", Mock())
    instance = driver.DriverUIFlow(driver.parser().parse_args(["--step-timeout", "5"]))
    assert driver.wda.HTTP_TIMEOUT == 5
    assert instance.deadline is None
