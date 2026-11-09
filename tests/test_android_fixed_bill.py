"""安卓包车只读固定车费与单次确认收款滑块回归，不连接设备。"""

from decimal import Decimal
from unittest.mock import Mock
import xml.etree.ElementTree as ET

import pytest

from jryg_hk_android.JRYG_android_order import AndroidDriverUIFlow, read_android_fixed_fare
from jryg_hk_android.JRYG_android_ui import normalized_tree
from jryg_hk_android.JRYG_driver_ui import ACTION_LABELS, DriverUIFlow, parser


PREFIX = "com.sunlightmobility.driver:id/"


def node(resource, text="", kind="android.widget.TextView", bounds="[10,10][200,100]"):
    return ET.Element(kind, {"class": kind, "resource-id": PREFIX + resource, "text": text,
                            "bounds": bounds, "displayed": "true", "enabled": "true"})


def native_bill(value="15.39", unit="HKD"):
    root = ET.Element("hierarchy")
    root.append(node("tv_title", "確認賬單"))
    section = node("cl_fixed_price", kind="android.view.ViewGroup")
    section.append(node("tv_fixed_price_title", "車費"))
    row = node("ll_fixed_price_amount", kind="android.widget.LinearLayout")
    row.append(node("tv_fixed_price_amount", value))
    row.append(node("tv_fixed_price_unit", unit))
    section.append(row)
    root.append(section)
    track = node("ll_drag_view", kind="android.widget.LinearLayout", bounds="[52,2501][1120,2709]")
    track.append(node("iv_arrow", kind="android.widget.ImageView", bounds="[68,2517][244,2693]"))
    track.append(node("tv_next_service_tip", "確認收款", bounds="[442,2501][730,2709]"))
    root.append(track)
    return root


def normalize(root):
    return normalized_tree(ET.tostring(root, encoding="unicode"), "com.sunlightmobility.driver")


def bill(value="15.39", unit="HKD"):
    return normalize(native_bill(value, unit))


def flow():
    args = parser(wda_url="http://127.0.0.1:8100").parse_args(["--car-type", "charter", "--payment", "online"])
    client = Mock()
    client.window_size.return_value = (1172, 2748)
    instance = AndroidDriverUIFlow(args, client)
    instance.root = Mock(return_value=bill())
    instance.wait_for = Mock()
    return instance


@pytest.mark.parametrize("value", ["0", "7", "15.39", "123.4"])
def test_separate_native_amount_and_currency_are_read_only(value):
    root = bill(value)
    before = ET.tostring(root)
    assert read_android_fixed_fare(root) == Decimal(value)
    assert ET.tostring(root) == before


def test_confirm_receipt_is_one_real_drag_after_two_readbacks():
    instance = flow()
    root = bill()
    before = ET.tostring(root)
    instance.submit_bill(root)
    assert instance.bill_total == Decimal("15.39")
    instance.root.assert_called_once_with()
    instance.client.driver.execute_script.assert_called_once_with("mobile: dragGesture", {
        "startX": 156, "startY": 2605, "endX": 1114, "endY": 2605, "speed": 1198})
    instance.client.click.assert_not_called()
    instance.client.assert_not_called()
    instance.wait_for.assert_called_once_with({"unpaid", "complete"})
    assert ET.tostring(root) == before


@pytest.mark.parametrize("resource", ["cl_fixed_price", "tv_fixed_price_title", "ll_fixed_price_amount",
                                      "tv_fixed_price_amount", "tv_fixed_price_unit"])
@pytest.mark.parametrize("mode", ["missing", "duplicate", "hidden"])
def test_missing_duplicate_or_hidden_native_field_blocks_drag(resource, mode):
    root = native_bill()
    target = next(n for n in root.iter() if n.get("resource-id") == PREFIX + resource)
    parent = next(n for n in root.iter() if target in list(n))
    if mode == "missing":
        parent.remove(target)
    elif mode == "duplicate":
        parent.append(ET.fromstring(ET.tostring(target)))
    else:
        target.set("displayed", "false")
    instance = flow()
    with pytest.raises(RuntimeError):
        instance.submit_bill(normalize(root))
    instance.client.driver.execute_script.assert_not_called()


@pytest.mark.parametrize("value", ["-1", "NaN", "Infinity", "15.399", "1,234.56", "HKD 15.39", ""])
def test_invalid_native_amount_does_not_confirm(value):
    instance = flow()
    with pytest.raises(RuntimeError, match="金额无效"):
        instance.submit_bill(bill(value))
    instance.client.driver.execute_script.assert_not_called()


@pytest.mark.parametrize("unit", ["CNY", "USD", "", "HK$"])
def test_foreign_or_missing_currency_blocks_confirm(unit):
    instance = flow()
    with pytest.raises(RuntimeError, match="币种不符"):
        instance.submit_bill(bill(unit=unit))
    instance.client.driver.execute_script.assert_not_called()


def test_unit_outside_fixed_amount_row_is_not_combined():
    root = native_bill()
    row = next(n for n in root.iter() if n.get("resource-id") == PREFIX + "ll_fixed_price_amount")
    unit = row[-1]
    row.remove(unit)
    root.append(unit)
    with pytest.raises(RuntimeError, match="不属于同一"):
        read_android_fixed_fare(normalize(root))


def test_editable_field_blocks_fixed_price():
    root = native_bill()
    root.append(node("et_fare", "15.39", kind="android.widget.EditText"))
    instance = flow()
    with pytest.raises(RuntimeError, match="输入框"):
        instance.submit_bill(normalize(root))
    instance.client.driver.execute_script.assert_not_called()


def test_fare_change_before_drag_blocks_submission():
    instance = flow()
    instance.root.return_value = bill("16")
    with pytest.raises(RuntimeError, match="发生变化"):
        instance.submit_bill(bill())
    instance.client.driver.execute_script.assert_not_called()


@pytest.mark.parametrize("setting,value,error", [("fare", "5", "预期金额"),
                                                  ("surcharge", "1", "附加费"),
                                                  ("payment", "cash", "实际已收款")])
def test_explicit_business_constraints_are_not_bypassed(setting, value, error):
    instance = flow()
    setattr(instance.args, setting, value)
    with pytest.raises(RuntimeError, match=error):
        instance.submit_bill(bill())
    instance.client.driver.execute_script.assert_not_called()


def test_cash_label_switch_on_second_read_blocks_submission():
    instance = flow()
    changed = native_bill()
    changed.append(node("tv_payment", "現金"))
    instance.root.return_value = normalize(changed)
    with pytest.raises(RuntimeError, match="现金支付"):
        instance.submit_bill(bill())
    instance.client.driver.execute_script.assert_not_called()


def test_uncertain_receipt_response_is_not_retried():
    instance = flow()
    instance.client.driver.execute_script.side_effect = RuntimeError("lost response")
    with pytest.raises(RuntimeError, match="禁止重复提交"):
        instance.submit_bill(bill())
    assert instance.client.driver.execute_script.call_count == 1
    instance.wait_for.assert_not_called()


def test_timeout_after_drag_does_not_retry_bill():
    instance = flow()
    instance.wait_for.side_effect = TimeoutError("订单终态未就绪")
    with pytest.raises(TimeoutError):
        instance.submit_bill(bill())
    assert instance.client.driver.execute_script.call_count == 1


def test_expired_deadline_blocks_drag():
    instance = flow()
    instance.deadline = 0
    with pytest.raises(TimeoutError, match="未滑动"):
        instance.submit_bill(bill())
    instance.client.driver.execute_script.assert_not_called()


def test_meter_bill_still_delegates_to_shared_implementation(monkeypatch):
    instance = flow()
    instance.args.car_type = "meter"
    delegated = Mock()
    monkeypatch.setattr(DriverUIFlow, "submit_bill", delegated)
    root = bill()
    instance.submit_bill(root)
    delegated.assert_called_once_with(root)
    instance.root.assert_not_called()


def test_combined_text_bill_remains_supported():
    root = ET.Element("XCUIElementTypeApplication")
    for text in ("確認賬單", "確認收款"):
        ET.SubElement(root, "XCUIElementTypeStaticText", label=text, visible="true")
    section = ET.SubElement(root, "XCUIElementTypeOther", visible="true")
    ET.SubElement(section, "XCUIElementTypeStaticText", label="車費", visible="true")
    ET.SubElement(section, "XCUIElementTypeStaticText", label="15.39 HKD", visible="true")
    assert read_android_fixed_fare(root) == Decimal("15.39")


def test_shared_run_reaches_fixed_bill_then_binds_completed_order():
    instance = flow()
    instance.args.stop_after = "submitted"
    instance._activate_driver_app = Mock()
    complete = ET.Element("XCUIElementTypeApplication", visible="true", bundleId="com.sunlightmobility.driver")
    for text in ("已完成", "已支付", "26B4J4MWECNY"):
        ET.SubElement(complete, "XCUIElementTypeStaticText", label=text, visible="true")
    instance.root.side_effect = [bill(), complete]
    instance.wait_for.side_effect = [(bill(), "bill"), (complete, "complete"), (complete, "complete")]
    instance.run()
    assert instance.order_no == "26B4J4MWECNY"
    assert instance.last_phase == "complete"
    assert instance.bill_total == Decimal("15.39")
    assert instance.client.driver.execute_script.call_count == 1
