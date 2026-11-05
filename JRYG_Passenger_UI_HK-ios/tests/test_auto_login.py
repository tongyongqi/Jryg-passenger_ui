from types import SimpleNamespace
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET

import pytest

from ui_framework.JRYG_driver_ui import BUNDLE_ID, DriverUIFlow, parser
from ui_framework.JRYG_ios_ui_base import iOSBase
from ui_framework.JRYG_ios_ui_elements import PASSENGER_BUNDLE_ID
from ui_framework.JRYG_order_flow import TestOrderBase
from ui_framework.JRYG_page_monitor import IOSPage


PHONE = "23456789"
CODE = "654321"


@pytest.fixture(autouse=True)
def unlocked_device(monkeypatch):
    monkeypatch.setattr("ui_framework.JRYG_ios_ui_base.ensure_unlocked", Mock(return_value=False))
    monkeypatch.setattr("ui_framework.JRYG_driver_ui.ensure_unlocked", Mock(return_value=False))


@pytest.mark.parametrize("source", ["config", "environment", "argument"])
def test_driver_login_settings_priority(monkeypatch, source):
    from ui_framework.JRYG_config import SETTINGS

    monkeypatch.setitem(SETTINGS, "driver", {"mobile": PHONE, "code": CODE})
    monkeypatch.delenv("HK_DRIVER_MOBILE", raising=False)
    monkeypatch.delenv("HK_DRIVER_UI_CODE", raising=False)
    expected = (PHONE, CODE)
    arguments = []
    if source in ("environment", "argument"):
        monkeypatch.setenv("HK_DRIVER_MOBILE", "34567890")
        monkeypatch.setenv("HK_DRIVER_UI_CODE", "765432")
        expected = ("34567890", "765432")
    if source == "argument":
        arguments = ["--mobile", "45678901", "--code", "876543"]
        expected = ("45678901", "876543")
    args = parser(wda_url="http://example.invalid").parse_args(arguments)
    assert (args.mobile, args.code) == expected


@pytest.fixture
def driver(monkeypatch):
    monkeypatch.delenv("HK_DRIVER_MOBILE", raising=False)
    monkeypatch.delenv("HK_DRIVER_UI_CODE", raising=False)
    flow = DriverUIFlow(parser(wda_url="http://example.invalid").parse_args([]), Mock())
    flow.args.mobile, flow.args.code = PHONE, CODE
    flow._activate_driver_app = Mock()
    flow.act = Mock()
    return flow


@pytest.mark.parametrize("phase,method", [("login", "login"), ("code", "enter_code")])
def test_driver_calls_existing_login_and_rereads(driver, phase, method):
    first, second = ET.Element("login"), ET.Element("home")
    driver.wait_for_entry_page = Mock(side_effect=[(first, phase), (second, "online")])
    driver.login = Mock()
    driver.enter_code = Mock()
    assert driver.ensure_online(resume_existing=True) is False
    getattr(driver, method).assert_called_once_with(first)
    assert driver.wait_for_entry_page.call_count == 2
    driver.act.assert_not_called()
    assert driver.awaiting_new_order


def test_driver_already_online_skips_login_without_credentials(driver):
    driver.args.mobile = driver.args.code = None
    driver.wait_for_entry_page = Mock(return_value=(ET.Element("home"), "online"))
    driver.login = Mock()
    driver.enter_code = Mock()
    assert driver.ensure_online() is False
    driver.login.assert_not_called()
    driver.enter_code.assert_not_called()
    driver.act.assert_not_called()


def test_driver_login_restores_existing_order_without_go_online(driver):
    driver.wait_for_entry_page = Mock(side_effect=[(ET.Element("login"), "login"), (ET.Element("trip"), "pickup")])
    driver.login = Mock()
    assert driver.ensure_online(resume_existing=True) is True
    assert driver.resume_phase == "pickup"
    driver.act.assert_not_called()


def test_driver_login_then_goes_online_once(driver):
    driver.wait_for_entry_page = Mock(side_effect=[(ET.Element("login"), "login"), (ET.Element("home"), "offline")])
    driver.login = Mock()
    driver.wait_for = Mock(return_value=(ET.Element("home"), "online"))
    assert driver.ensure_online() is False
    driver.login.assert_called_once()
    driver.act.assert_called_once()


def test_driver_login_not_completed_stops_actions(driver):
    driver.wait_for_entry_page = Mock(return_value=(ET.Element("login"), "login"))
    driver.login = Mock()
    with pytest.raises(RuntimeError, match="未成功"):
        driver.ensure_online()
    driver.login.assert_called_once()
    driver.act.assert_not_called()


@pytest.mark.parametrize("mobile,code", [(None, CODE), ("invalid", CODE), (PHONE, None), (PHONE, "bad")])
def test_driver_bad_settings_no_sms_or_login_click(driver, mobile, code):
    driver.args.mobile, driver.args.code = mobile, code
    driver.wait_for_entry_page = Mock(return_value=(ET.Element("login"), "login"))
    driver.fill = Mock()
    with pytest.raises(RuntimeError, match="HK_DRIVER"):
        driver.ensure_online()
    driver.fill.assert_not_called()
    driver.act.assert_not_called()
    driver.client.send_keys.assert_not_called()


def test_driver_registration_entry_opens_then_uses_login_fields(driver):
    entry = ET.fromstring('<root><XCUIElementTypeButton label="登錄/註冊" visible="true" /></root>')
    form = ET.fromstring('<root><XCUIElementTypeTextField placeholderValue="請輸入手機號碼" visible="true" /></root>')
    driver.deadline = 100
    driver.root = Mock(return_value=form)
    driver.fill = Mock()
    driver.dismiss_keyboard = Mock()
    driver.wait_for = Mock(return_value=(ET.Element("code"), "code"))
    driver.enter_code = Mock()
    with patch("ui_framework.JRYG_driver_ui.time.monotonic", return_value=10):
        driver.login(entry)
    driver.fill.assert_called_once_with(form, "請輸入手機號碼", PHONE)
    assert [call.args[1] for call in driver.act.call_args_list] == [("登錄/註冊",), ("下一步",)]
    driver.enter_code.assert_called_once()


def test_driver_code_submitted_once_without_business_action(driver):
    root = ET.fromstring('<root>' + '<XCUIElementTypeCell x="0" y="0" width="20" height="20" visible="true" />' * 6 + '</root>')
    driver.wait_for = Mock()
    driver.enter_code(root)
    driver.client.click.assert_called_once()
    driver.client.send_keys.assert_called_once_with(CODE)
    driver.act.assert_not_called()
    assert "destination" in driver.wait_for.call_args.args[0]


@pytest.fixture
def passenger(monkeypatch):
    monkeypatch.delenv("HK_PASSENGER_MOBILE", raising=False)
    monkeypatch.delenv("HK_PASSENGER_UI_CODE", raising=False)
    flow = iOSBase()
    flow.LOGIN_PHONE, flow.LOGIN_CODE = PHONE, CODE
    flow.client = Mock()
    flow.client.http.get.return_value = SimpleNamespace(value={"bundleId": PASSENGER_BUNDLE_ID})
    flow.monitor = Mock()
    flow.monitor.click_text.return_value = True
    flow._ios_screenshot = Mock()
    flow.poco = Mock()
    flow.poco.return_value.exists.return_value = False
    return flow


def page(*labels):
    root = ET.Element("root")
    for label in labels:
        ET.SubElement(root, "XCUIElementTypeStaticText", label=label)
    return IOSPage(ET.tostring(root, encoding="unicode"))


HOME = page("想去哪裡")
MINE_UNLOGGED = page("登錄/註冊")
PHONE_PAGE = page("請輸入手機號", "取得驗證碼")
CODE_PAGE = page("請輸入驗證碼")
LOGGED = page("****6789", "我的行程")


def test_passenger_guest_home_login_once_then_verifies_account(passenger):
    passenger.monitor.inspect.side_effect = [HOME, MINE_UNLOGGED, PHONE_PAGE, CODE_PAGE, HOME, LOGGED]
    with patch("ui_framework.JRYG_ios_ui_base.time.sleep"):
        assert passenger._ios_ui_login(tag="offline") is True
    assert passenger._passenger_verified_phone == PHONE
    assert [call.args[0] for call in passenger.client.send_keys.call_args_list] == [PHONE, CODE]
    assert [call.args[1] for call in passenger.monitor.click_text.call_args_list] == [
        "我的", "登錄/註冊", "取得驗證碼", "我的", "主頁"
    ]


def test_passenger_logged_home_verifies_without_input(passenger):
    passenger.monitor.inspect.side_effect = [HOME, HOME, LOGGED]
    assert passenger._ios_ensure_logged_in() is True
    passenger.client.send_keys.assert_not_called()
    assert passenger._passenger_verified_phone == PHONE


def test_passenger_logged_mine_skips_login_method(passenger):
    passenger.monitor.inspect.return_value = LOGGED
    passenger._ios_ui_login = Mock()
    assert passenger._ios_ensure_logged_in() is True
    passenger._ios_ui_login.assert_not_called()
    passenger.client.send_keys.assert_not_called()


@pytest.mark.parametrize("current", [MINE_UNLOGGED, PHONE_PAGE, CODE_PAGE])
def test_passenger_unlogged_delegates_existing_method(passenger, current):
    passenger.monitor.inspect.return_value = current
    passenger._ios_ui_login = Mock(return_value=True)
    assert passenger._ios_ensure_logged_in(tag="check") is True
    passenger._ios_ui_login.assert_called_once_with(tag="check")


def test_passenger_other_account_stops_without_switching(passenger):
    passenger.monitor.inspect.return_value = page("****0000", "我的行程")
    with pytest.raises(RuntimeError, match="不匹配"):
        passenger._ios_ensure_logged_in()
    passenger.client.send_keys.assert_not_called()
    passenger.monitor.click_text.assert_not_called()


def test_passenger_unknown_not_assumed_logged_in(passenger):
    passenger.monitor.inspect.return_value = page("未知页面")
    assert passenger._ios_ensure_logged_in() is False
    passenger.monitor.click_text.assert_not_called()


def test_passenger_wrong_foreground_no_credential_input(passenger):
    passenger.client.http.get.return_value = SimpleNamespace(value={"bundleId": BUNDLE_ID})
    with pytest.raises(RuntimeError, match="不在前台"):
        passenger._ios_ensure_logged_in()
    passenger.monitor.inspect.assert_not_called()
    passenger.client.send_keys.assert_not_called()


def test_passenger_sms_timeout_does_not_resend(passenger):
    passenger.monitor.inspect.return_value = PHONE_PAGE
    passenger.monitor.wait_for.side_effect = AssertionError("timeout")
    with patch("ui_framework.JRYG_ios_ui_base.time.sleep"):
        assert passenger._ios_ui_login() is False
    passenger.client.send_keys.assert_called_once_with(PHONE)
    passenger.monitor.click_text.assert_called_once()


def test_passenger_code_timeout_does_not_reenter_or_log_code(passenger, caplog):
    passenger.monitor.inspect.return_value = CODE_PAGE
    passenger.monitor.wait_for.side_effect = AssertionError("timeout")
    with caplog.at_level("INFO"), patch("ui_framework.JRYG_ios_ui_base.time.sleep"):
        assert passenger._ios_ui_login() is False
    passenger.client.send_keys.assert_called_once_with(CODE)
    assert CODE not in caplog.text
    assert PHONE not in caplog.text


def test_passenger_input_transport_failure_not_retried(passenger):
    passenger.monitor.inspect.return_value = CODE_PAGE
    passenger.client.send_keys.side_effect = OSError("connection lost")
    with pytest.raises(OSError):
        passenger._ios_ui_login()
    passenger.client.send_keys.assert_called_once()


def test_passenger_settings_can_be_overridden(passenger, monkeypatch):
    monkeypatch.setenv("HK_PASSENGER_MOBILE", "34567890")
    monkeypatch.setenv("HK_PASSENGER_UI_CODE", "765432")
    passenger.monitor.inspect.side_effect = [PHONE_PAGE, CODE_PAGE, page("****7890", "我的行程")]
    with patch("ui_framework.JRYG_ios_ui_base.time.sleep"):
        assert passenger._ios_ui_login() is True
    assert [call.args[0] for call in passenger.client.send_keys.call_args_list] == ["34567890", "765432"]


def test_login_failure_blocks_address_configuration(passenger):
    passenger._ios_prepare_passenger_app = Mock()
    passenger._ios_ensure_logged_in = Mock(return_value=False)
    passenger._ios_configure_addresses = Mock()
    with pytest.raises(RuntimeError, match="自动登录失败"):
        passenger._ios_launch_setup_and_addresses("check", "start", "end")
    passenger._ios_configure_addresses.assert_not_called()


def test_login_failure_blocks_cleanup_before_any_order_action():
    flow = TestOrderBase()
    flow._ios_prepare_passenger_app = Mock()
    flow._ios_ensure_logged_in = Mock(return_value=False)
    flow._ios_get_all_texts = Mock()
    flow._ios_click_dialog_button = Mock()
    with pytest.raises(RuntimeError, match="自动登录失败"):
        flow._ui_cleanup_ongoing_order("check")
    flow._ios_get_all_texts.assert_not_called()
    flow._ios_click_dialog_button.assert_not_called()
