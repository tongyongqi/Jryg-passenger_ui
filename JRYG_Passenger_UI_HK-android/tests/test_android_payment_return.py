"""安卓支付成功后的返回App弹窗；不连接设备或提交付款。"""

from unittest.mock import Mock
import xml.etree.ElementTree as ET

import pytest

from jryg_hk_android.JRYG_android_payment import AndroidPaymentBase


def node(resource, text="", kind="android.widget.TextView", description=""):
    return ET.Element(kind, {"class": kind, "text": text, "content-desc": description,
                            "resource-id": resource, "bounds": "[10,10][200,100]",
                            "enabled": "true", "displayed": "true"})


def dialog():
    root = ET.Element("hierarchy")
    root.append(node("com.vivo.browser:id/alertTitle", "当前网页请求打开陽光出行应用"))
    button = node("android:id/button1", kind="android.widget.Button", description="打开")
    button.append(node("com.vivo.browser:id/vbutton_title", "打开"))
    root.append(button)
    root.append(node("android:id/button2", kind="android.widget.Button", description="取消"))
    return root


@pytest.fixture
def payment():
    case = AndroidPaymentBase()
    case.client = Mock()
    case.client.driver.current_package = "com.vivo.browser"
    case.client.driver.page_source = ET.tostring(dialog(), encoding="unicode")
    element = Mock()
    element.label = "打开"
    element.native.get_attribute.return_value = "android.widget.Button"
    case.client.return_value.find_elements.return_value = [element]
    return case, element


def test_native_open_button_ignores_duplicate_child_label(payment):
    case, element = payment
    assert case._ios_safari_click_by_text("打开", 336, 429, exact=True)
    case.client.assert_called_once_with(resourceId="android:id/button1")
    element.click.assert_called_once_with()
    case.client.click.assert_not_called()


@pytest.mark.parametrize("target", ["当前网页请求打开陽光司機版应用", "打开其他应用"])
def test_wrong_target_app_is_not_opened(payment, target):
    case, element = payment
    root = dialog()
    root[0].set("text", target)
    case.client.driver.page_source = ET.tostring(root, encoding="unicode")
    with pytest.raises(RuntimeError, match="目标不符"):
        case._ios_safari_click_by_text("打开", 0, 0, exact=True)
    element.click.assert_not_called()
    case.client.assert_not_called()


@pytest.mark.parametrize("change", ["missing", "duplicate", "disabled", "hidden", "wrong_label", "wrong_class"])
def test_dialog_button_must_be_unique_visible_enabled(payment, change):
    case, element = payment
    root = dialog()
    if change == "missing":
        root.remove(root[1])
    elif change == "duplicate":
        root.append(node("android:id/button1", kind="android.widget.Button", description="打开"))
    else:
        key, value = {"disabled": ("enabled", "false"), "hidden": ("displayed", "false"),
                      "wrong_label": ("content-desc", "取消"), "wrong_class": ("class", "android.widget.TextView")}[change]
        root[1].set(key, value)
    case.client.driver.page_source = ET.tostring(root, encoding="unicode")
    with pytest.raises(RuntimeError, match="确认按钮"):
        case._ios_safari_click_by_text("打开", 0, 0, exact=True)
    element.click.assert_not_called()


def test_changed_native_button_is_not_clicked(payment):
    case, element = payment
    element.label = "取消"
    with pytest.raises(RuntimeError, match="已改变"):
        case._ios_safari_click_by_text("打开", 0, 0, exact=True)
    element.click.assert_not_called()


def test_uncertain_open_click_is_not_retried(payment):
    case, element = payment
    element.click.side_effect = RuntimeError("lost response")
    with pytest.raises(RuntimeError, match="禁止重复点击或支付"):
        case._ios_safari_click_by_text("打开", 0, 0, exact=True)
    element.click.assert_called_once_with()


def test_normal_payment_controls_still_require_uniqueness(payment):
    case, _ = payment
    case.client.source.return_value = "<XCUIElementTypeApplication/>"
    case.client.return_value.find_elements.return_value = [Mock(), Mock()]
    with pytest.raises(RuntimeError, match="支付控件不唯一"):
        case._ios_safari_click_by_text("Pay Now", 0, 0)
    case.client.driver.page_source = Mock()
    case.client.assert_called_once_with(text="Pay Now")
