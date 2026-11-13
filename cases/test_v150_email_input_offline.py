# 编写时间：2026-11-10
# 本期功能：V1.5.0 邮箱输入链路离线回归 — 格式校验不连接设备
"""邮箱输入链路回归：不连接设备，不保存邮箱，不发送收据。"""

from unittest.mock import Mock
import xml.etree.ElementTree as ET

import pytest

from jryg_hk_android.JRYG_android_ui import normalized_tree
from jryg_hk_android.JRYG_v150_device_steps import V150DeviceSteps


def immediate(predicate, message, timeout=3):
    if not predicate():
        raise TimeoutError(message)
    return True


@pytest.fixture
def case():
    instance = V150DeviceSteps()
    instance.client = Mock()
    instance._assert_passenger_foreground = Mock()
    instance._wait = immediate
    instance._v150_adb = Mock(side_effect=AssertionError("禁止切换为 ADB 输入"))
    element = Mock()
    element.text = "old@example.com"
    element.is_displayed.return_value = True
    element.is_enabled.return_value = True
    attributes = {"focused": "true", "showingHintText": "false", "resource-id": ""}
    element.get_attribute.side_effect = attributes.get
    element.clear.side_effect = lambda: setattr(element, "text", "")
    element.send_keys.side_effect = lambda value: setattr(element, "text", element.text + value)
    instance.client.driver.find_elements.return_value = [element]
    return instance, element, attributes


@pytest.mark.parametrize("value", [
    "user@example.com", "  user@example.com  ", "", "invalid-email", "a@b@c.com",
    "o'connor+tag@example.com", "x" * 80 + "@example.com",
])
def test_native_input_clears_and_writes_exactly_once(case, value):
    instance, element, _ = case
    node = ET.Element("XCUIElementTypeTextField")
    assert instance._v150_input_email(node, value) == value
    element.click.assert_called_once_with()
    element.clear.assert_called_once_with()
    if value:
        element.send_keys.assert_called_once_with(value)
    else:
        element.send_keys.assert_not_called()
    instance._v150_adb.assert_not_called()
    instance.client.dismiss_keyboard.assert_called_once_with()


@pytest.mark.parametrize("count", [0, 2])
def test_ambiguous_or_missing_input_does_not_write(case, count):
    instance, element, _ = case
    instance.client.driver.find_elements.return_value = [element] * count
    with pytest.raises(RuntimeError, match="必须唯一"):
        instance._v150_input_email(None, "user@example.com")
    element.click.assert_not_called()
    element.send_keys.assert_not_called()


@pytest.mark.parametrize("attribute", ["is_displayed", "is_enabled"])
def test_hidden_or_disabled_input_does_not_write(case, attribute):
    instance, element, _ = case
    getattr(element, attribute).return_value = False
    with pytest.raises(RuntimeError, match="必须唯一"):
        instance._v150_input_email(None, "user@example.com")
    element.send_keys.assert_not_called()


def test_missing_focus_does_not_clear_or_write(case):
    instance, element, attributes = case
    attributes["focused"] = "false"
    with pytest.raises(TimeoutError, match="焦点"):
        instance._v150_input_email(None, "user@example.com")
    element.clear.assert_not_called()
    element.send_keys.assert_not_called()


def test_failed_clear_does_not_write(case):
    instance, element, _ = case
    element.clear.side_effect = None
    with pytest.raises(TimeoutError, match="清空失败"):
        instance._v150_input_email(None, "user@example.com")
    element.send_keys.assert_not_called()
    instance._v150_adb.assert_not_called()


def test_clear_exception_is_not_treated_as_empty(case):
    instance, element, _ = case
    element.clear.side_effect = RuntimeError("clear failed")
    with pytest.raises(RuntimeError, match="clear failed"):
        instance._v150_input_email(None, "user@example.com")
    element.send_keys.assert_not_called()


def test_duplicate_or_trimmed_input_fails_without_retry(case):
    instance, element, _ = case
    element.send_keys.side_effect = lambda value: setattr(element, "text", value.strip())
    with pytest.raises(TimeoutError, match="原样回读"):
        instance._v150_input_email(None, "  user@example.com  ")
    element.send_keys.assert_called_once_with("  user@example.com  ")
    instance._v150_adb.assert_not_called()


@pytest.mark.parametrize("value", ["", "請輸入電子郵箱", "  user@example.com  "])
def test_native_text_is_preserved_without_placeholder_guessing(case, value):
    instance, element, _ = case
    element.text = value
    assert instance._v150_native_email_value() == value


def test_missing_read_is_not_empty(case):
    instance, element, _ = case
    element.text = None
    with pytest.raises(RuntimeError, match="读取失败"):
        instance._v150_native_email_value()


def tree(*items):
    root = ET.Element("hierarchy")
    for text, cls in items:
        ET.SubElement(root, cls, {
            "class": cls, "text": text, "bounds": "[10,10][500,120]", "displayed": "true",
        })
    return normalized_tree(ET.tostring(root, encoding="unicode"), "com.sunlightmobility.client")


def test_settings_entry_is_not_email_editor_or_mine(case):
    instance, _, _ = case
    instance._passenger_root = Mock(return_value=tree(
        ("設定", "android.view.View"), ("私隱中心", "android.view.View"),
        ("電子郵箱", "android.view.View"),
    ))
    assert instance._v150_current_page_type() == "settings"
    assert not instance._v150_email_page_ready()
    with pytest.raises(RuntimeError, match="不在邮箱管理页"):
        instance.v150_email_read_current()


def test_normalized_empty_field_is_email_editor(case):
    instance, _, _ = case
    instance._passenger_root = Mock(return_value=tree(
        ("電子郵箱", "android.view.View"), ("", "android.widget.EditText"),
        ("保存", "android.widget.Button"),
    ))
    assert instance._v150_current_page_type() == "email_settings"
    assert instance._v150_email_page_ready()


def test_reopen_leaves_draft_and_opens_persisted_value(case):
    instance, _, _ = case
    instance._v150_current_page_type = Mock(side_effect=["email_settings", "settings", "email_settings"])
    instance._passenger_root = Mock(return_value=tree(("電子郵箱", "android.view.View")))
    instance._v150_email_page_ready = Mock(return_value=True)
    instance.v150_open_email_settings = Mock(side_effect=AssertionError("不能重启应用"))
    assert instance._v150_reopen_email_page() == "email_settings"
    instance.client.driver.back.assert_called_once_with()
    instance.client.click.assert_called_once()


@pytest.mark.parametrize("clears", [True, False])
def test_reopen_does_not_click_under_toast_overlay(case, clears):
    instance, _, _ = case
    instance._v150_current_page_type = Mock(side_effect=["settings", "email_settings"])
    instance._passenger_root = Mock(return_value=tree(("電子郵箱", "android.view.View")))
    instance._v150_toast_texts = Mock(side_effect=[{"保存成功"}, set() if clears else {"保存成功"}])
    instance._v150_email_page_ready = Mock(return_value=True)
    if clears:
        assert instance._v150_reopen_email_page() == "email_settings"
        instance.client.click.assert_called_once()
    else:
        with pytest.raises(TimeoutError, match="全屏提示未消失"):
            instance._v150_reopen_email_page()
        instance.client.click.assert_not_called()


def test_input_failure_prevents_save(case):
    instance, _, _ = case
    instance.v150_email_read_current = Mock(return_value="old@example.com")
    instance.v150_email_type = Mock(side_effect=RuntimeError("原样回读失败"))
    instance.v150_email_click_save = Mock()
    with pytest.raises(RuntimeError, match="原样回读失败"):
        instance.v150_email_save(email="user@example.com")
    instance.v150_email_click_save.assert_not_called()


def test_save_reads_only_after_return_and_reopen(case):
    instance, _, _ = case
    events = []
    instance.v150_email_read_current = Mock(side_effect=lambda tag: events.append("read") or "user@example.com")
    instance.v150_email_type = Mock(side_effect=lambda *args: events.append("type"))
    instance.v150_email_click_save = Mock(side_effect=lambda tag: events.append("save"))
    instance._v150_current_page_type = Mock(return_value="settings")
    instance._v150_reopen_email_page = Mock(side_effect=lambda tag: events.append("reopen"))
    instance._v150_email_start_api_capture = Mock(return_value="12345")
    instance._v150_email_collect_api_log = Mock(return_value={"captured": True})
    assert instance.v150_email_save(email="user@example.com") == "user@example.com"
    assert events == ["read", "type", "save", "reopen", "read"]
    instance._v150_email_start_api_capture.assert_called_once()
    instance._v150_email_collect_api_log.assert_called_once()
