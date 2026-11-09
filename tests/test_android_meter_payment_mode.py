"""安卓打表下单现金/电子支付与行程后Alipay渠道隔离回归，无设备与业务请求。"""

from unittest.mock import Mock
import xml.etree.ElementTree as ET

import pytest

from jryg_hk_android.JRYG_android_passenger import AndroidPassengerBase
from jryg_hk_android.JRYG_scenarios import android_scenarios
from jryg_hk_android import JRYG_ios_ui_elements as E


PREFIX = E.PASSENGER_BUNDLE_ID + ":id/"


def selected_page(mode):
    root = ET.Element("XCUIElementTypeApplication", bundleId=E.PASSENGER_BUNDLE_ID)
    ET.SubElement(root, "XCUIElementTypeStaticText", visible="true", label="確認呼叫")
    ET.SubElement(root, "XCUIElementTypeStaticText", visible="true", label=f"支付方式：本次已選擇{mode}，請行程結束後支付",
                  **{"resource-id": PREFIX + "tv_pay_mode"})
    return root


@pytest.fixture
def passenger():
    instance = AndroidPassengerBase()
    instance.CAR_TYPE = "meter"
    instance._passenger_root = Mock(return_value=selected_page("電子支付"))
    instance._click_text = Mock()
    instance.client = Mock()
    instance._wait = lambda predicate, message, timeout=30: predicate() or (_ for _ in ()).throw(TimeoutError(message))
    return instance


@pytest.mark.parametrize("payment,mode", [("alipay", "電子支付"), ("bankcard", "電子支付"),
                                          ("epayment", "電子支付"), ("cash", "現金支付")])
def test_selected_mode_does_not_click_channel_support_description(passenger, payment, mode):
    passenger._passenger_root.return_value = selected_page(mode)
    passenger._ios_select_payment("meter", payment)
    passenger.client.assert_not_called()
    passenger._click_text.assert_not_called()


def options(passenger, initial="現金支付", selected="電子支付"):
    passenger._passenger_root.return_value = selected_page(initial)
    entry = Mock(label=f"本次已選擇{initial}")
    electronic = Mock()
    electronic.label = "電子支付"
    cash = Mock()
    cash.label = "現金支付"
    description = Mock()
    description.label = "支持Alipay HK、信用卡或扣帳卡"
    confirm = Mock()
    confirm.label = "確認選擇"
    confirm.click.side_effect = lambda: setattr(passenger._passenger_root, "return_value", selected_page(selected))
    controls = {PREFIX + "tv_pay_mode": [entry], PREFIX + "tv_payment_name": [electronic, cash, description],
                PREFIX + "btn_confirm": [confirm]}

    def selector(**query):
        result = Mock()
        result.find_elements.return_value = controls.get(query.get("resourceId"), [])
        result.exists = query == {"text": "請選擇本單支付方式"}
        return result

    passenger.client.side_effect = selector
    return entry, electronic, cash, description, confirm, controls


@pytest.mark.parametrize("payment", ["alipay", "bankcard", "epayment"])
def test_online_channel_selects_native_electronic_mode_and_reads_back(passenger, payment):
    entry, electronic, cash, description, confirm, _ = options(passenger)
    passenger._ios_select_payment("meter", payment)
    entry.click.assert_called_once()
    electronic.click.assert_called_once()
    confirm.click.assert_called_once()
    description.click.assert_not_called()
    cash.click.assert_not_called()
    passenger._click_text.assert_not_called()


def test_cash_is_selected_independently_of_postpaid_channels(passenger):
    entry, electronic, cash, description, confirm, _ = options(passenger, initial="電子支付", selected="現金支付")
    passenger._ios_select_payment("meter", "cash")
    cash.click.assert_called_once()
    confirm.click.assert_called_once()
    electronic.click.assert_not_called()
    description.click.assert_not_called()


@pytest.mark.parametrize("fault", ["missing_option", "duplicate_option", "wrong_confirm", "duplicate_confirm", "readback"])
def test_unsafe_mode_selection_never_calls_car_or_channel_payment(passenger, fault):
    _, electronic, _, description, confirm, controls = options(passenger)
    if fault == "missing_option":
        controls[PREFIX + "tv_payment_name"].remove(electronic)
    elif fault == "duplicate_option":
        duplicate = Mock()
        duplicate.label = "電子支付"
        controls[PREFIX + "tv_payment_name"].append(duplicate)
    elif fault == "wrong_confirm":
        confirm.label = "確認支付並呼叫"
    elif fault == "duplicate_confirm":
        controls[PREFIX + "btn_confirm"].append(Mock())
    else:
        confirm.click.side_effect = None
    with pytest.raises((RuntimeError, TimeoutError)):
        passenger._ios_select_payment("meter", "alipay")
    passenger._click_text.assert_not_called()
    description.click.assert_not_called()
    if fault != "readback":
        confirm.click.assert_not_called()


@pytest.mark.parametrize("fault", ["missing", "duplicate"])
def test_payment_mode_entry_must_be_unique(passenger, fault):
    root = selected_page("現金支付")
    if fault == "duplicate":
        root.append(ET.fromstring(ET.tostring(root[-1])))
    else:
        root.remove(root[-1])
        passenger.client.return_value.find_elements.return_value = []
    passenger._passenger_root.return_value = root
    with pytest.raises(RuntimeError, match="不唯一"):
        passenger._ios_select_payment("meter", "alipay")
    passenger._click_text.assert_not_called()


def test_unsupported_mode_stops_before_ui_read(passenger):
    with pytest.raises(ValueError):
        passenger._ios_select_payment("meter", "unsupported")
    passenger._passenger_root.assert_not_called()
    passenger.client.assert_not_called()


def test_charter_alipay_keeps_actual_prepaid_channel_selection(passenger):
    passenger.CAR_TYPE = "charter"
    passenger._click_text.side_effect = [False, True]
    passenger._ios_get_all_texts = Mock(return_value=["預付車費", "Alipay HK"])
    passenger._ios_select_payment("charter", "alipay")
    assert passenger._click_text.call_args_list[1].args == (E.ALIPAY_KEYWORDS,)
    passenger._passenger_root.assert_not_called()


def test_meter_alipay_final_payment_stays_alipay_not_default_bankcard():
    case = next(case for case in android_scenarios() if case.__name__ == "TestMeterAlipayAndroid")
    order = case()
    assert order.CAR_TYPE == "meter"
    assert order.PAYMENT == "alipay"
    assert order.final_payment == "alipay"
    order._ios_pay = Mock(return_value=True)
    assert order._ios_complete_payment("meter-alipay")
    order._ios_pay.assert_called_once_with("meter-alipay", payment="alipay")
