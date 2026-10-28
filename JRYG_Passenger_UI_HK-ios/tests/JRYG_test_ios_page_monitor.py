"""不连接手机的页面判定、超时与自动恢复回归。"""

from unittest.mock import Mock
from xml.sax.saxutils import quoteattr

import pytest
import requests

from jryg_hk_ios.JRYG_page_monitor import IOSPage, IOSPageMonitor


def page(*texts):
    return IOSPage("<App>" + "".join(
        f"<XCUIElementTypeStaticText label={quoteattr(text)} visible='true'/>"
        for text in texts
    ) + "</App>")


@pytest.mark.parametrize("texts,state", [
    (("取得驗證碼", "請輸入手機號"), "login_phone_input"),
    (("获取验证码",), "login_phone_input"),
    (("請輸入驗證碼", "60秒後重新發送"), "login_code_input"),
    (("登錄/註冊", "我的行程"), "mine_unlogged"),
    (("11****27", "我的行程"), "mine_logged"),
    (("****1727", "我的行程"), "mine_logged"),
    (("11001727", "我的行程"), "mine_logged"),
    (("我的行程", "會員"), "unknown"),
    (("想去哪裡？", "當前城市暫未開通服務"), "home_unlogged"),
    (("icon hd gb", "想去哪裡？"), "activity_popup"),
    ((), "unknown"),
])
def test_page_states(texts, state):
    assert page(*texts).state == state


@pytest.mark.parametrize("account,expected", [
    ("****1727", True), ("11****27", True), ("11001727", True),
    ("****9927", False), ("22001727", False), ("其他文本1727", False),
])
def test_account_requires_all_visible_digits_to_match(account, expected):
    assert page(account, "我的行程").matches_account("11001727") is expected


def test_hidden_code_title_is_not_a_code_page():
    current = IOSPage("<App><Text label='請輸入驗證碼' visible='false'/>"
                      "<Button label='取得驗證碼' visible='true'/></App>")
    assert current.state == "login_phone_input"


def test_popup_closes_and_checks_transition(tmp_path):
    monitor = IOSPageMonitor("http://127.0.0.1:8100", tmp_path)
    popup = IOSPage("<App><Button label='icon hd gb' x='182' y='639' width='29' height='29'/></App>")
    monitor.inspect = Mock(side_effect=[popup, popup, page("想去哪裡？")])
    client = Mock()
    monitor.dismiss_activity_popup(client)
    client.click.assert_called_once_with(196, 653)
    assert monitor.inspect.call_count == 3
    monitor.close()


def test_wait_timeout_fails_and_saves_xml_even_without_screenshot(tmp_path):
    monitor = IOSPageMonitor("http://127.0.0.1:8100", tmp_path)
    monitor.last_page = page("icon hd gb")
    monitor._get = Mock(side_effect=requests.Timeout("offline"))
    with pytest.raises(AssertionError, match="activity_popup"):
        monitor.wait_for("waiting", lambda current: False, timeout=0)
    assert len(list(tmp_path.glob("*.xml"))) == 1
    monitor.close()


def test_delayed_popup_can_be_recovered_during_wait(tmp_path):
    monitor = IOSPageMonitor("http://127.0.0.1:8100", tmp_path)
    home = page("想去哪裡？")
    monitor.inspect = Mock(side_effect=[page(), page("icon hd gb"), home])
    dismiss = Mock()
    result = monitor.wait_for(
        "home", lambda current: current.state == "home_unlogged", interval=0,
        recover=lambda current: dismiss() if current.state == "activity_popup" else None,
    )
    assert result is home
    dismiss.assert_called_once()
    monitor.close()


def test_http_requests_are_bounded_and_ignore_proxy_for_usb(tmp_path):
    monitor = IOSPageMonitor("http://127.0.0.1:8100", tmp_path)
    assert monitor.http.trust_env is False
    response = Mock()
    response.json.return_value = {"value": "<App/>"}
    monitor.http.get = Mock(return_value=response)
    assert monitor.inspect().state == "unknown"
    monitor.http.get.assert_called_once_with(
        "http://127.0.0.1:8100/source?format=xml", timeout=(3, 12))
    monitor.close()


def test_click_uses_visible_element_bounds_and_exact_label(tmp_path):
    monitor = IOSPageMonitor("http://127.0.0.1:8100", tmp_path)
    monitor.inspect = Mock(return_value=IOSPage(
        "<App><Button label='不同意' x='10' y='10' width='40' height='20'/>"
        "<Button label='同意' visible='false' x='30' y='10' width='40' height='20'/>"
        "<Button label='同意' x='100' y='700' width='80' height='30'/></App>"))
    client = Mock()
    assert monitor.click_text(client, "同意")
    client.click.assert_called_once_with(140, 715)
    assert all(isinstance(value, int) for value in client.click.call_args.args)
    monitor.close()


def test_missing_visible_control_does_not_click_coordinates(tmp_path):
    monitor = IOSPageMonitor("http://127.0.0.1:8100", tmp_path)
    monitor.inspect = Mock(return_value=page("unknown"))
    client = Mock()
    assert not monitor.click_text(client, "我的")
    client.click.assert_not_called()
    monitor.close()


def test_wda_error_is_not_treated_as_page(tmp_path):
    monitor = IOSPageMonitor("http://127.0.0.1:8100", tmp_path)
    response = Mock()
    response.json.return_value = {"value": {"error": "invalid session id"}}
    monitor.http.get = Mock(return_value=response)
    with pytest.raises(RuntimeError, match="WDA 页面请求失败"):
        monitor.inspect()
    monitor.close()
