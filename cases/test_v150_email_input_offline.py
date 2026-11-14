# 编写时间：2026-11-10
# 本期功能：V1.5.0 邮箱输入链路离线回归 — 格式校验不连接设备
"""邮箱输入链路回归：不连接设备，不保存邮箱，不发送收据。"""

from unittest.mock import Mock
import xml.etree.ElementTree as ET

import pytest

from jryg_hk_android.JRYG_android_ui import normalized_tree
from jryg_hk_android.JRYG_v150_device_steps import V150DeviceSteps


def immediate(predicate, message, timeout=3):
    """同步断言：predicate 立即为 True 否则抛 TimeoutError，替代 _wait 轮询。"""
    if not predicate():
        raise TimeoutError(message)
    return True


@pytest.fixture
def case():
    """构造一个 Mock 了 client/driver/element 的 V150DeviceSteps 实例供离线测试用。"""
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
    """原生输入框：click→clear→send_keys 各执行一次，空值不 send_keys，不回退 ADB。"""
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
    """输入框数量不唯一（0 或 2）时抛 RuntimeError 且不执行任何写入。"""
    instance, element, _ = case
    instance.client.driver.find_elements.return_value = [element] * count
    with pytest.raises(RuntimeError, match="必须唯一"):
        instance._v150_input_email(None, "user@example.com")
    element.click.assert_not_called()
    element.send_keys.assert_not_called()


@pytest.mark.parametrize("attribute", ["is_displayed", "is_enabled"])
def test_hidden_or_disabled_input_does_not_write(case, attribute):
    """输入框不可见或不可用时抛 RuntimeError 且不执行写入。"""
    instance, element, _ = case
    getattr(element, attribute).return_value = False
    with pytest.raises(RuntimeError, match="必须唯一"):
        instance._v150_input_email(None, "user@example.com")
    element.send_keys.assert_not_called()


def test_missing_focus_does_not_clear_or_write(case):
    """输入框未获焦点时抛 TimeoutError 且不执行 clear 或 send_keys。"""
    instance, element, attributes = case
    attributes["focused"] = "false"
    with pytest.raises(TimeoutError, match="焦点"):
        instance._v150_input_email(None, "user@example.com")
    element.clear.assert_not_called()
    element.send_keys.assert_not_called()


def test_failed_clear_does_not_write(case):
    """clear 返回 None（视为清空失败）时抛 TimeoutError 且不 send_keys、不回退 ADB。"""
    instance, element, _ = case
    element.clear.side_effect = None
    with pytest.raises(TimeoutError, match="清空失败"):
        instance._v150_input_email(None, "user@example.com")
    element.send_keys.assert_not_called()
    instance._v150_adb.assert_not_called()


def test_clear_exception_is_not_treated_as_empty(case):
    """clear 抛异常时向上传播 RuntimeError，不静默吞掉也不继续 send_keys。"""
    instance, element, _ = case
    element.clear.side_effect = RuntimeError("clear failed")
    with pytest.raises(RuntimeError, match="clear failed"):
        instance._v150_input_email(None, "user@example.com")
    element.send_keys.assert_not_called()


def test_duplicate_or_trimmed_input_fails_without_retry(case):
    """send_keys 偷偷 strip 了值导致原样回读不匹配时抛 TimeoutError 且不回退 ADB。"""
    instance, element, _ = case
    element.send_keys.side_effect = lambda value: setattr(element, "text", value.strip())
    with pytest.raises(TimeoutError, match="原样回读"):
        instance._v150_input_email(None, "  user@example.com  ")
    element.send_keys.assert_called_once_with("  user@example.com  ")
    instance._v150_adb.assert_not_called()


@pytest.mark.parametrize("value", ["", "請輸入電子郵箱", "  user@example.com  "])
def test_native_text_is_preserved_without_placeholder_guessing(case, value):
    """读取邮箱原生文案时保留原始值，不猜测 placeholder 也不 trim。"""
    instance, element, _ = case
    element.text = value
    assert instance._v150_native_email_value() == value


def test_missing_read_is_not_empty(case):
    """读取邮箱文案返回 None 时抛 RuntimeError 而非当作空字符串。"""
    instance, element, _ = case
    element.text = None
    with pytest.raises(RuntimeError, match="读取失败"):
        instance._v150_native_email_value()


def tree(*items):
    """用 ElementTree 构造一个归一化 UI 树，每项为 (text, class) 用于页面类型测试。"""
    root = ET.Element("hierarchy")
    for text, cls in items:
        ET.SubElement(root, cls, {
            "class": cls, "text": text, "bounds": "[10,10][500,120]", "displayed": "true",
        })
    return normalized_tree(ET.tostring(root, encoding="unicode"), "com.sunlightmobility.client")


def test_settings_entry_is_not_email_editor_or_mine(case):
    """设定页含「電子郵箱」入口但非邮箱编辑页：page_type=settings，page_ready=False。"""
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
    """邮箱编辑页含空 EditText + 保存按钮：page_type=email_settings，page_ready=True。"""
    instance, _, _ = case
    instance._passenger_root = Mock(return_value=tree(
        ("電子郵箱", "android.view.View"), ("", "android.widget.EditText"),
        ("保存", "android.widget.Button"),
    ))
    assert instance._v150_current_page_type() == "email_settings"
    assert instance._v150_email_page_ready()


def test_reopen_leaves_draft_and_opens_persisted_value(case):
    """从邮箱编辑页返回设定页再进入时用 back+click 而非重启 App，读到持久化值。"""
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
    """toast 未消失时不点击入口（防误触）；toast 消失后正常进入邮箱编辑页。"""
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
    """输入失败（原样回读不匹配）时不执行保存操作。"""
    instance, _, _ = case
    instance.v150_email_read_current = Mock(return_value="old@example.com")
    instance.v150_email_type = Mock(side_effect=RuntimeError("原样回读失败"))
    instance.v150_email_click_save = Mock()
    with pytest.raises(RuntimeError, match="原样回读失败"):
        instance.v150_email_save(email="user@example.com")
    instance.v150_email_click_save.assert_not_called()


def test_save_reads_only_after_return_and_reopen(case):
    """保存流程顺序：read→type→save→reopen→read，API 日志抓取各一次。"""
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


# ---------------------------------------------------------------------------
# 邮箱格式校验全面覆盖：normalize_email 的合法/非法边界
# 规则：必须包含且仅包含一个 @，@ 前后都不能为空，@ 后的域名中至少要有一个 .
# ---------------------------------------------------------------------------

from jryg_hk_android.JRYG_v150_contract import normalize_email

# --- 合法邮箱 ---
VALID_EMAILS = [
    "user@example.com",                         # 标准格式
    "  user@example.com  ",                     # 前后空格（strip 后合法）
    "",                                         # 空字符串（表示删除邮箱，返回空）
    "   ",                                      # 纯空格（strip 后为空，表示删除）
    "o'connor+tag@example.com",                 # 含单引号和加号
    "x" * 80 + "@example.com",                  # 超长 local 部分
    "a@b.c",                                    # 最短合法格式
    "user.name@example.com",                    # local 含点号
    "user_name@example.com",                    # local 含下划线
    "user-name@example.com",                    # local 含连字符
    "user@sub.example.com",                     # 多级域名
    "user@example.co.uk",                       # 多级域名 ccTLD
    "USER@EXAMPLE.COM",                         # 全大写
    "User@Example.Com",                         # 混合大小写
    "123@example.com",                          # local 纯数字
    "user@123.com",                             # 域名纯数字
    "a.b@c.d",                                  # local 和域名都含点
    "test+filter@gmail.com",                    # Gmail 别名格式
    "user@example.io",                          # 短 TLD
    "a@x.io",                                   # 最短多级
    "\tuser@example.com",                       # 前置制表符（strip 后合法）
    "user@example.com\n",                       # 后置换行符（strip 后合法）
    "user@example.com\r",                       # 后置回车符（strip 后合法）
]

# --- 非法邮箱 ---
INVALID_EMAILS = [
    "no-at",                                    # 无 @
    "no-at-sign.com",                           # 有 . 无 @
    "@example.com",                             # @ 前为空
    "user@",                                    # @ 后为空
    "a@b@c.com",                                # 多个 @（两个）
    "user@@example.com",                        # 连续 @@
    "a@b@c@d.com",                              # 多个 @（三个）
    "user@example",                             # 域名无点
    "user@.com",                                # 域名以点开头
    "user@example.",                            # 域名以点结尾
    "user@.example.com",                        # 域名第一段为空
    "user@example..com",                        # 域名连续点
    "us er@example.com",                        # local 含内部空格
    "user@ example.com",                        # @ 后有空格
    "user@example .com",                        # 域名含内部空格
]


@pytest.mark.parametrize("email", VALID_EMAILS, ids=lambda v: v[:30].strip().replace(" ", "_") or "empty")
def test_valid_email_passes_normalize(email):
    """合法邮箱经 normalize_email 后不抛异常且返回去空格后的值。"""
    result = normalize_email(email)
    assert result == email.strip()


@pytest.mark.parametrize("email", INVALID_EMAILS, ids=lambda v: repr(v)[:30] or "empty")
def test_invalid_email_rejected_by_normalize(email):
    """非法邮箱经 normalize_email 必须抛 ValueError。"""
    with pytest.raises(ValueError, match="郵箱格式不正確"):
        normalize_email(email)
