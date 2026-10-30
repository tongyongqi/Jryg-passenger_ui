"""页面监控器的离线回归测试，不连接手机或真实 WDA 服务。

使用最小 XML 页面树和 Mock 模拟页面切换、HTTP 返回及点击操作，
覆盖页面状态识别、测试账号匹配、弹窗恢复、请求超时和失败现场保存。
"""

# 用模拟对象替代 HTTP 请求、页面读取和真机点击。
from unittest.mock import Mock
# XML 属性转义，确保包含引号等字符的测试文本仍能组成合法页面树。
from xml.sax.saxutils import quoteattr

import pytest
# 使用 requests 的超时异常模拟 WDA 不可用。
import requests

from jryg_hk_ios.JRYG_page_monitor import IOSPage, IOSPageMonitor


def page(*texts):
    """将若干文本包装为可见 StaticText 节点，返回 IOSPage 测试快照。

    :param texts: 页面上依次出现的文本；不传文本时构造空页面。
    :return: 可用于状态识别和账号匹配的 IOSPage 实例。
    """
    # 每个文本生成一个可见节点，保留传入顺序以复现页面文本提取。
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
    # 同时包含广告关闭标识和首页文案，用于检查两类页面特征的判定优先级。
    (("icon hd gb", "想去哪裡？"), "activity_popup"),
    ((), "unknown"),
])
def test_page_states(texts, state):
    """按不同简繁体页面文案验证登录页、个人中心、首页和未知状态。

    :param texts: 参数化的可见页面文本。
    :param state: 该场景期望识别出的页面状态。
    """
    assert page(*texts).state == state


# 同时覆盖完整账号、不同星号掩码、可见数字不匹配及非账号文本。
@pytest.mark.parametrize("account,expected", [
    ("****1727", True), ("11****27", True), ("11001727", True),
    ("****9927", False), ("22001727", False), ("其他文本1727", False),
])
def test_account_requires_all_visible_digits_to_match(account, expected):
    """账号掩码可以匹配任意数字，但长度和所有可见数字必须匹配测试手机号。"""
    # 不允许只凭手机号尾号判断为同一账号。
    assert page(account, "我的行程").matches_account("11001727") is expected


def test_hidden_code_title_is_not_a_code_page():
    """隐藏验证码标题不能覆盖当前可见手机号输入页的状态。"""
    # 保留旧页面的隐藏标题，模拟页面切换时控件树中的残留节点。
    current = IOSPage("<App><Text label='請輸入驗證碼' visible='false'/>"
                      "<Button label='取得驗證碼' visible='true'/></App>")
    assert current.state == "login_phone_input"


def test_popup_closes_and_checks_transition(tmp_path):
    """关闭广告后必须再次读取页面，确认已切换到首页。"""
    monitor = IOSPageMonitor("http://127.0.0.1:8100", tmp_path)
    popup = IOSPage("<App><Button label='icon hd gb' x='182' y='639' width='29' height='29'/></App>")
    # 三次读取依次用于判断广告、定位关闭按钮、确认关闭后的首页。
    monitor.inspect = Mock(side_effect=[popup, popup, page("想去哪裡？")])
    client = Mock()
    monitor.dismiss_activity_popup(client)
    # 中心坐标取整数，且首页出现后不能重复点击关闭按钮。
    client.click.assert_called_once_with(196, 653)
    assert monitor.inspect.call_count == 3
    monitor.close()


def test_wait_timeout_fails_and_saves_xml_even_without_screenshot(tmp_path):
    """等待超时且截图接口不可用时，仍保存已有 XML 并报告最后页面状态。"""
    monitor = IOSPageMonitor("http://127.0.0.1:8100", tmp_path)
    # 预存一次广告页面快照；后续截图请求模拟网络超时。
    monitor.last_page = page("icon hd gb")
    monitor._get = Mock(side_effect=requests.Timeout("offline"))
    # timeout=0 立即进入超时分支，不依赖真实时间流逝。
    with pytest.raises(AssertionError, match="activity_popup"):
        monitor.wait_for("waiting", lambda current: False, timeout=0)
    # tmp_path 由 pytest 提供，失败截图不能阻止页面树落盘。
    assert len(list(tmp_path.glob("*.xml"))) == 1
    monitor.close()


def test_delayed_popup_can_be_recovered_during_wait(tmp_path):
    """等待期间晚出现的广告可触发恢复回调，恢复后继续等待目标首页。"""
    monitor = IOSPageMonitor("http://127.0.0.1:8100", tmp_path)
    home = page("想去哪裡？")
    # 模拟未识别页面 → 广告弹窗 → 首页，不使用真实页面请求。
    monitor.inspect = Mock(side_effect=[page(), page("icon hd gb"), home])
    dismiss = Mock()
    result = monitor.wait_for(
        "home", lambda current: current.state == "home_unlogged", interval=0,
        recover=lambda current: dismiss() if current.state == "activity_popup" else None,
    )
    # 返回满足条件的原始快照，且仅广告状态调用一次恢复函数。
    assert result is home
    dismiss.assert_called_once()
    monitor.close()


def test_http_requests_are_bounded_and_ignore_proxy_for_usb(tmp_path):
    """本地 WDA 请求不读取环境代理，并明确限制连接及读取超时。"""
    monitor = IOSPageMonitor("http://127.0.0.1:8100", tmp_path)
    assert monitor.http.trust_env is False
    # 用空页面响应替代真实 HTTP 请求，验证请求地址和超时参数。
    response = Mock()
    response.json.return_value = {"value": "<App/>"}
    monitor.http.get = Mock(return_value=response)
    assert monitor.inspect().state == "unknown"
    # requests 的超时元组分别表示连接超时 3 秒、读取超时 12 秒。
    monitor.http.get.assert_called_once_with(
        "http://127.0.0.1:8100/source?format=xml", timeout=(3, 12))
    monitor.close()


def test_click_uses_visible_element_bounds_and_exact_label(tmp_path):
    """精确匹配可见的同意按钮，排除不同意及隐藏同名控件。"""
    monitor = IOSPageMonitor("http://127.0.0.1:8100", tmp_path)
    # 并列构造文本干扰项、隐藏同名项和实际可点击的同意按钮。
    monitor.inspect = Mock(return_value=IOSPage(
        "<App><Button label='不同意' x='10' y='10' width='40' height='20'/>"
        "<Button label='同意' visible='false' x='30' y='10' width='40' height='20'/>"
        "<Button label='同意' x='100' y='700' width='80' height='30'/></App>"))
    client = Mock()
    assert monitor.click_text(client, "同意")
    # 有效按钮中心为 (100+80/2, 700+30/2)，点击参数必须转换为整数。
    client.click.assert_called_once_with(140, 715)
    assert all(isinstance(value, int) for value in client.click.call_args.args)
    monitor.close()


def test_missing_visible_control_does_not_click_coordinates(tmp_path):
    """未发现目标可见控件时返回 False，不进行猜测性的坐标点击。"""
    monitor = IOSPageMonitor("http://127.0.0.1:8100", tmp_path)
    monitor.inspect = Mock(return_value=page("unknown"))
    client = Mock()
    assert not monitor.click_text(client, "我的")
    # 查找失败不能产生点击副作用。
    client.click.assert_not_called()
    monitor.close()


def test_wda_error_is_not_treated_as_page(tmp_path):
    """WDA 返回会话错误时抛异常，不能将错误对象当作正常页面解析。"""
    monitor = IOSPageMonitor("http://127.0.0.1:8100", tmp_path)
    response = Mock()
    # 即使 HTTP 返回可解析的 JSON，value.error 也表示 WDA 请求失败。
    response.json.return_value = {"value": {"error": "invalid session id"}}
    monitor.http.get = Mock(return_value=response)
    with pytest.raises(RuntimeError, match="WDA 页面请求失败"):
        monitor.inspect()
    monitor.close()
