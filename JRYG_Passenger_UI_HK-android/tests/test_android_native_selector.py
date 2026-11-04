"""原生ID、类及文字定位回归，禁止重新转换成XPath。"""

import json
from unittest.mock import Mock, call

import pytest
from selenium.common.exceptions import StaleElementReferenceException

from jryg_hk_android.JRYG_android_ui import AndroidClient


def native(key="field", text="", description="", kind="android.widget.EditText", displayed=True, enabled=True):
    result = Mock(id=key, text=text)
    result.is_displayed.return_value = displayed
    result.is_enabled.return_value = enabled
    result.get_attribute.side_effect = lambda name: {"class": kind, "content-desc": description}.get(name, "")
    return result


def client(*items):
    driver = Mock()
    driver.find_elements.return_value = list(items)
    return AndroidClient(driver)


def test_search_field_uses_direct_native_id_without_xpath():
    field = native()
    app = client(field)
    assert app(resourceId="com.sunlightmobility.client:id/et_search").unique().native is field
    app.driver.find_elements.assert_called_once_with("id", "com.sunlightmobility.client:id/et_search")


@pytest.mark.parametrize("requested,mapped", [("android.widget.EditText", "android.widget.EditText"),
                                            ("XCUIElementTypeTextField", "android.widget.EditText")])
def test_class_locator_keeps_platform_mapping(requested, mapped):
    app = client(native(kind=mapped))
    assert len(app(className=requested).find_elements()) == 1
    app.driver.find_elements.assert_called_once_with("class name", mapped)


def test_id_with_multiple_filters_keeps_and_semantics():
    selected = native("selected", text="確認呼叫", description="立即呼叫")
    app = client(selected, native("wrong-class", text="確認呼叫", kind="android.widget.TextView"),
                 native("wrong-text", text="取消呼叫"), native("wrong-desc", text="確認呼叫", description="稍後"))
    result = app(resourceId="test:id/field", className="android.widget.EditText",
                 text="確認呼叫", textContains="立即", textMatches="確認.*").find_elements()
    assert [item.native for item in result] == [selected]
    app.driver.find_elements.assert_called_once_with("id", "test:id/field")


def test_text_and_description_branches_deduplicate_same_element_id():
    one = native("same", text="確認支付", description="確認支付")
    app = client()
    app.driver.find_elements.side_effect = [[one], [one]]
    assert app(text="確認支付").unique().native is one
    assert app.driver.find_elements.call_args_list == [
        call("-android uiautomator", 'new UiSelector().text("確認支付")'),
        call("-android uiautomator", 'new UiSelector().description("確認支付")')]


def test_two_distinct_matching_payment_controls_remain_ambiguous():
    one, two = native("one", text="確認支付"), native("two", description="確認支付")
    app = client()
    app.driver.find_elements.side_effect = [[one], [two]]
    with pytest.raises(RuntimeError, match="不唯一"):
        app(text="確認支付").click()
    one.click.assert_not_called()
    two.click.assert_not_called()


def test_exact_text_can_match_description_even_when_text_is_different():
    app = client(native(text="其他", description="我的"))
    assert app(text="我的").unique().label == "其他"


def test_contains_is_literal_and_matches_description():
    app = client(native(text="費用", description="(立即)呼叫"), native("other", text="立即呼叫"))
    assert len(app(textContains="(立即)").find_elements()) == 1
    assert all("Contains" in item.args[1] for item in app.driver.find_elements.call_args_list)


@pytest.mark.parametrize("value", ['單引號\'與"雙引號"', '反斜杠\\及\n換行', "香港大學"])
def test_native_text_selector_escapes_literals(value):
    app = client(native(text=value))
    assert app(text=value).unique()
    escaped = json.dumps(value, ensure_ascii=False)
    assert app.driver.find_elements.call_args_list == [
        call("-android uiautomator", f"new UiSelector().text({escaped})"),
        call("-android uiautomator", f"new UiSelector().description({escaped})")]


def test_regex_uses_python_fullmatch_and_text_priority():
    expected = native("coupon", text="優惠券10")
    description = native("desc", description="优惠券20")
    app = client(expected, description, native("not-full", text="前綴優惠券30"),
                 native("text-priority", text="其他", description="優惠券40"), native("empty"))
    assert [item.native for item in app(textMatches="優惠券.*|优惠券.*").find_elements()] == [expected, description]
    assert all(item.args[0] == "-android uiautomator" for item in app.driver.find_elements.call_args_list)


def test_regex_empty_string_does_not_accept_empty_text_and_description():
    assert client(native()).__call__(textMatches=".*").find_elements() == []


@pytest.mark.parametrize("displayed,enabled", [(False, True), (True, False), (False, False)])
def test_native_queries_still_filter_hidden_disabled(displayed, enabled):
    item = native(displayed=displayed, enabled=enabled)
    app = client(item)
    assert not app(resourceId="test:id/field").exists
    with pytest.raises(RuntimeError, match="缺失"):
        app(resourceId="test:id/field").click()
    item.click.assert_not_called()


def test_no_results_does_not_click_or_retry_using_xpath():
    app = client()
    with pytest.raises(RuntimeError, match="缺失"):
        app(resourceId="test:id/field").unique()
    app.driver.find_elements.assert_called_once_with("id", "test:id/field")


def test_native_query_failure_not_retried_as_xpath():
    app = client()
    app.driver.find_elements.side_effect = TimeoutError("native timeout")
    with pytest.raises(TimeoutError):
        app(resourceId="test:id/field").find_elements()
    app.driver.find_elements.assert_called_once_with("id", "test:id/field")


def test_exists_treats_stale_candidate_as_disappeared_without_requery():
    item = native()
    item.is_displayed.side_effect = StaleElementReferenceException("page changed")
    app = client(item)
    assert not app(resourceId="test:id/field").exists
    app.driver.find_elements.assert_called_once_with("id", "test:id/field")


def test_unique_propagates_stale_candidate_without_requery():
    item = native()
    item.is_displayed.side_effect = StaleElementReferenceException("page changed")
    app = client(item)
    with pytest.raises(StaleElementReferenceException):
        app(resourceId="test:id/field").unique()
    app.driver.find_elements.assert_called_once_with("id", "test:id/field")


def test_click_stale_response_is_not_retried():
    item = native()
    item.click.side_effect = StaleElementReferenceException("response uncertain")
    app = client(item)
    with pytest.raises(StaleElementReferenceException):
        app(resourceId="test:id/field").click()
    item.click.assert_called_once_with()
    app.driver.find_elements.assert_called_once_with("id", "test:id/field")


def test_empty_query_uses_native_all_candidates_without_xpath():
    app = client(native())
    assert len(app().find_elements()) == 1
    app.driver.find_elements.assert_called_once_with("-android uiautomator", "new UiSelector()")
