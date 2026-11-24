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
    assert passenger._ios_ensure_logged_in() is True
    passenger.client.send_keys.assert_not_called()


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


def test_passenger_login_cache_skips_repeated_page_checks(passenger):
    passenger.monitor.inspect.side_effect = [HOME, HOME, LOGGED]
    assert passenger._ios_ensure_logged_in() is True
    checks = passenger.monitor.inspect.call_count
    passenger.monitor.click_text.reset_mock()
    passenger._ios_ui_login = Mock(side_effect=AssertionError("must reuse login"))
    for _ in range(3):
        assert passenger._ios_ensure_logged_in() is True
    assert passenger.monitor.inspect.call_count == checks
    passenger.monitor.click_text.assert_not_called()
    passenger.client.send_keys.assert_not_called()
    passenger._ios_ui_login.assert_not_called()


def test_passenger_login_cache_does_not_compare_account(passenger, monkeypatch):
    passenger.monitor.inspect.return_value = page("****0000", "我的行程")
    assert passenger._ios_ensure_logged_in() is True
    monkeypatch.setenv("HK_PASSENGER_MOBILE", "34567890")
    passenger.monitor.reset_mock()
    assert passenger._ios_ensure_logged_in() is True
    passenger.monitor.inspect.assert_not_called()
    passenger.monitor.click_text.assert_not_called()


def test_cached_login_still_checks_foreground(passenger):
    passenger._passenger_verified_phone = PHONE
    passenger.client.http.get.return_value = SimpleNamespace(value={"bundleId": BUNDLE_ID})
    with pytest.raises(RuntimeError, match="不在前台"):
        passenger._ios_ensure_logged_in()
    passenger.monitor.inspect.assert_not_called()
    passenger.client.send_keys.assert_not_called()


@pytest.mark.parametrize("current", [MINE_UNLOGGED, PHONE_PAGE, CODE_PAGE])
def test_explicit_login_page_invalidates_cached_state(passenger, current):
    passenger._passenger_verified_phone = PHONE
    passenger.monitor.inspect.return_value = current
    assert passenger._ios_is_login_page() is True
    assert passenger._passenger_verified_phone is None
    passenger._ios_ui_login = Mock(return_value=False)
    assert passenger._ios_ensure_logged_in() is False
    passenger._ios_ui_login.assert_called_once()


def test_guest_home_label_does_not_invalidate_cached_login(passenger):
    passenger._passenger_verified_phone = PHONE
    passenger.monitor.inspect.return_value = HOME
    assert passenger._ios_is_login_page() is False
    assert passenger._passenger_verified_phone == PHONE


@pytest.mark.parametrize("failure", ["missing_home", "timeout"])
def test_login_cache_not_saved_when_return_home_fails(passenger, failure):
    passenger.monitor.inspect.return_value = LOGGED
    if failure == "missing_home":
        passenger.monitor.click_text.return_value = False
    else:
        passenger.monitor.wait_for.side_effect = AssertionError("timeout")
    with pytest.raises((RuntimeError, AssertionError)):
        passenger._ios_ensure_logged_in()
    assert passenger._passenger_verified_phone is None


def test_login_cache_reset_for_new_case(passenger):
    passenger._passenger_verified_phone = PHONE
    assert getattr(iOSBase(), "_passenger_verified_phone", None) is None
    passenger.setup_method()
    assert passenger._passenger_verified_phone is None
    passenger.monitor.inspect.return_value = LOGGED
    assert passenger._ios_ensure_logged_in() is True
    passenger.monitor.inspect.assert_called_once()


@pytest.mark.parametrize("method", ["_ios_ensure_logged_in", "_ios_ui_login"])
def test_active_order_records_login_without_personal_center(passenger, method):
    passenger.monitor.inspect.return_value = page("訂單進行中")
    assert getattr(passenger, method)() is True
    assert passenger._passenger_verified_phone == PHONE
    passenger.monitor.click_text.assert_not_called()
    passenger.client.send_keys.assert_not_called()


@pytest.mark.parametrize("current", [HOME, page("確認呼叫")])
def test_login_state_machine_reuses_confirmed_login(passenger, current):
    passenger._passenger_verified_phone = PHONE
    passenger.monitor.inspect.return_value = current
    assert passenger._ios_ui_login() is True
    passenger.monitor.click_text.assert_not_called()
    passenger.client.send_keys.assert_not_called()


@pytest.fixture
def charter_flow(passenger, monkeypatch):
    monkeypatch.setenv("HK_DRIVER_UI_STOP_AFTER", "submitted")
    monkeypatch.setattr("ui_framework.JRYG_order_flow.time.sleep", Mock())
    flow = TestOrderBase()
    flow.setup_method()
    flow.CAR_TYPE, flow.PAYMENT = "charter", "alipay"
    flow.LOGIN_PHONE, flow.LOGIN_CODE = PHONE, CODE
    flow.client, flow.poco, flow.monitor = passenger.client, passenger.poco, passenger.monitor
    flow.resuming_order = False
    flow.driver_ui = Mock(last_phase="submitted", order_no="offline-order")
    events = []
    flow.client.session.side_effect = lambda _bundle: events.append("launch")
    flow.client.alert.accept.side_effect = lambda: events.append("permissions")
    flow.client.return_value.exists = False
    flow.monitor.inspect.side_effect = [HOME, HOME, LOGGED, page("等待接单")]
    flow.monitor.click_text.side_effect = lambda _client, *labels: events.append(labels[0]) or True
    flow.monitor.wait_for.return_value = HOME
    flow._ios_dismiss_privacy_agreement = Mock()
    flow._ios_prepare_passenger_app = Mock(wraps=flow._ios_prepare_passenger_app)
    flow._ios_ensure_logged_in = Mock(wraps=flow._ios_ensure_logged_in)
    flow._driver_ui_go_online = Mock(side_effect=lambda _tag: events.append("driver_online"))
    flow._ios_get_all_texts = Mock(side_effect=[HOME.texts, HOME.texts, ["確認支付並呼叫"]])
    flow._ios_search_address = Mock(side_effect=lambda is_start, address: events.append(
        ("start" if is_start else "end", address)))
    root = ET.Element("XCUIElementTypeApplication", bundleId=PASSENGER_BUNDLE_ID)
    for marker, text in (("start", "铜锣湾地铁站D2出口"), ("end", "大谭郊野公园")):
        container = ET.SubElement(root, "XCUIElementTypeOther", name="maannotationview")
        ET.SubElement(container, "XCUIElementTypeImage", name=f"slm_icon_anno_{marker}", visible="true")
        ET.SubElement(container, "XCUIElementTypeStaticText", label=text, visible="true")
    flow.client.source.return_value = ET.tostring(root, encoding="unicode")
    flow._ios_select_car_type = Mock(side_effect=lambda _tag, car_type: events.append(("car", car_type)))
    flow._ios_click_confirm_call = Mock(side_effect=lambda _tag: events.append("call"))
    flow._ios_select_payment = Mock(side_effect=lambda _tag, payment: events.append(("payment", payment)))
    flow._ios_click_confirm_pay = Mock(side_effect=lambda _tag: events.append("confirm_pay"))
    flow._ios_pay = Mock(side_effect=lambda _tag, payment, stage: events.append(("pay", payment, stage)))
    flow._ios_wait_order_result = Mock(side_effect=lambda *_args, **_kwargs: events.append("order_success") or "success")
    flow._driver_ui_grab_and_flow = Mock(side_effect=lambda _tag: events.append("driver_trip"))
    flow._ios_back_to_home = Mock(side_effect=lambda _tag: events.append("finish_home"))
    flow.driver_ui.wait_completed.side_effect = lambda: events.append("verify_same_order")
    flow._ios_screenshot = Mock()
    flow._ios_complete_payment = Mock()
    return flow, events


@pytest.mark.parametrize("has_permission_dialog", [True, False])
def test_charter_alipay_one_launch_login_and_order_sequence(charter_flow, has_permission_dialog):
    flow, events = charter_flow
    if not has_permission_dialog:
        def no_permission_dialog():
            events.append("permissions")
            raise RuntimeError("no alert")
        flow.client.alert.accept.side_effect = no_permission_dialog
    flow.test_order_flow()
    assert events == [
        "driver_online", "launch", "permissions", "我的", "主頁",
        ("start", "铜锣湾地铁站D2出口"), ("end", "大谭郊野公园"), ("car", "charter"),
        "call", ("payment", "alipay"), "confirm_pay", ("pay", "alipay", "submitted"),
        "order_success", "driver_trip", "finish_home", "verify_same_order",
    ]
    flow._ios_prepare_passenger_app.assert_called_once()
    flow._ios_ensure_logged_in.assert_called_once()
    flow.client.session.assert_called_once_with(PASSENGER_BUNDLE_ID)
    flow.client.home.assert_called_once()
    flow.client.alert.accept.assert_called_once()
    flow.client.send_keys.assert_not_called()
    assert flow._passenger_verified_phone == PHONE
    assert flow._ios_call_route_key == ("铜锣湾地铁站D2出口", "大谭郊野公园")
    assert flow.completed_order_no == "offline-order"
    flow._ios_pay.assert_called_once()
    flow._ios_complete_payment.assert_not_called()


def test_charter_login_failure_blocks_entire_order_flow(charter_flow):
    flow, _events = charter_flow
    flow._ios_ensure_logged_in = Mock(return_value=False)
    with pytest.raises(RuntimeError, match="自动登录失败"):
        flow.test_order_flow()
    flow._ios_prepare_passenger_app.assert_called_once()
    flow._ios_ensure_logged_in.assert_called_once()
    flow._ios_search_address.assert_not_called()
    flow._ios_select_car_type.assert_not_called()
    flow._ios_click_confirm_call.assert_not_called()
    flow._ios_pay.assert_not_called()


def test_charter_payment_uncertain_never_relaunches_or_repays(charter_flow):
    flow, _events = charter_flow
    flow._ios_pay.side_effect = RuntimeError("payment result unknown")
    with pytest.raises(RuntimeError, match="payment result unknown"):
        flow.test_order_flow()
    flow._ios_prepare_passenger_app.assert_called_once()
    flow._ios_ensure_logged_in.assert_called_once()
    flow._ios_click_confirm_call.assert_called_once()
    flow._ios_click_confirm_pay.assert_called_once()
    flow._ios_pay.assert_called_once()
    flow._driver_ui_grab_and_flow.assert_not_called()
    flow.driver_ui.wait_completed.assert_not_called()
    assert flow.completed_order_no is None


def payment_page(*texts, attr="label", hidden=(), disabled=(), bundle=PASSENGER_BUNDLE_ID):
    root = ET.Element("XCUIElementTypeApplication", bundleId=bundle)
    for text in texts:
        kind = "XCUIElementTypeButton" if text == "確認選擇" else "XCUIElementTypeStaticText"
        ET.SubElement(root, kind, **{attr: text, "visible": "true", "enabled": "true"})
    for text in hidden:
        ET.SubElement(root, "XCUIElementTypeStaticText", label=text, visible="false", enabled="true")
    for text in disabled:
        ET.SubElement(root, "XCUIElementTypeStaticText", label=text, visible="true", enabled="false")
    return IOSPage(ET.tostring(root, encoding="unicode"))


@pytest.fixture
def meter_payment(monkeypatch):
    from itertools import count
    from ui_framework import JRYG_ios_ui_elements as elements

    ticks = count(step=0.1)
    monkeypatch.setattr("ui_framework.JRYG_ios_ui_base.time.monotonic", lambda: next(ticks))
    monkeypatch.setattr("ui_framework.JRYG_ios_ui_base.time.sleep", Mock())
    monkeypatch.setattr(elements, "ROUTE_PAYMENT_WAIT_TIMEOUT", 2)
    flow = TestOrderBase()
    flow.CAR_TYPE, flow.PAYMENT = "meter", "alipay"
    flow.client = Mock()
    flow.poco = Mock()
    flow.poco.return_value.exists.return_value = False
    flow.monitor = Mock()
    flow._ios_ensure_monitor = Mock(return_value=flow.monitor)
    flow._ios_pay = Mock()
    flow._ios_click_confirm_call = Mock()
    flow._ios_click_confirm_pay = Mock()
    flow._ios_screenshot = Mock()
    return flow


@pytest.mark.parametrize("entry", ["支付方式", "可選服務", "可选服务"])
@pytest.mark.parametrize("attr", ["label", "name", "value"])
def test_meter_payment_new_and_old_entry_waits_for_sheet(meter_payment, entry, attr):
    from ui_framework import JRYG_ios_ui_elements as elements

    flow = meter_payment
    route = payment_page(f"{entry}：本次已選擇電子支付，請行程結束後支付", "確認呼叫", attr=attr)
    sheet = payment_page("請選擇本單支付方式", "Alipay HK", "確認選擇", attr=attr)
    selected = payment_page(f"{entry}：本次已選擇Alipay HK，請行程結束後支付", "確認呼叫", attr=attr)
    flow.monitor.inspect.side_effect = [route, route, sheet, sheet, sheet, selected]
    flow._ios_select_payment("meter", "alipay")
    calls = [call.kwargs["xpath"] for call in flow.client.call_args_list]
    assert calls[0] == elements.ROUTE_PAYMENT_ENTRY_XPATH
    assert f'@{attr}="Alipay HK"' in calls[1]
    assert f'@{attr}="確認選擇"' in calls[2]
    assert len(calls) == 3
    assert flow.monitor.inspect.call_count == 6
    assert flow.final_payment == "alipay"
    flow._ios_pay.assert_not_called()
    flow._ios_click_confirm_call.assert_not_called()
    flow._ios_click_confirm_pay.assert_not_called()


@pytest.mark.parametrize("phase", ["entry", "panel", "returned"])
def test_meter_payment_timeout_stops_without_reclicking(meter_payment, phase):
    flow = meter_payment
    route = payment_page("支付方式：本次已選擇電子支付", "確認呼叫")
    sheet = payment_page("請選擇本單支付方式", "Alipay HK", "確認選擇")
    prefixes = {"entry": [], "panel": [route], "returned": [route, sheet, sheet]}
    prefix = iter(prefixes[phase])
    fallback = payment_page("服務偏好", "確認呼叫") if phase == "entry" else route if phase == "panel" else sheet
    flow.monitor.inspect.side_effect = lambda **_kwargs: next(prefix, fallback)
    with pytest.raises(AssertionError, match="未就绪"):
        flow._ios_select_payment("meter", "alipay")
    assert flow.client.return_value.click.call_count == {"entry": 0, "panel": 1, "returned": 3}[phase]
    flow.monitor.capture.assert_called_once()
    flow._ios_click_confirm_call.assert_not_called()
    flow._ios_pay.assert_not_called()


@pytest.mark.parametrize("unavailable", ["description_only", "hidden", "disabled"])
def test_meter_payment_never_treats_description_as_alipay_option(meter_payment, unavailable):
    flow = meter_payment
    extras = {"hidden": ("Alipay HK",)} if unavailable == "hidden" else {"disabled": ("Alipay HK",)} if unavailable == "disabled" else {}
    sheet = payment_page("請選擇本單支付方式", "電子支付", "支持Alipay HK、信用卡或扣帳卡", "確認選擇", **extras)
    flow.monitor.inspect.return_value = sheet
    with pytest.raises(AssertionError, match="无可用支付选项.*不更换最终支付渠道"):
        flow._ios_select_payment("meter", "alipay")
    flow.client.assert_not_called()
    flow.monitor.capture.assert_called_once()
    assert flow.PAYMENT == flow.final_payment == "alipay"


def test_meter_payment_foreground_guard_stops_all_clicks(meter_payment):
    flow = meter_payment
    flow.monitor.inspect.return_value = payment_page("支付方式", bundle="com.apple.springboard")
    with pytest.raises(RuntimeError, match="不在前台"):
        flow._ios_select_payment("meter", "alipay")
    flow.client.assert_not_called()


def test_meter_payment_missing_clickable_entry_is_not_channel_failure(meter_payment):
    flow = meter_payment
    flow.monitor.inspect.return_value = payment_page("支付方式：本次已選擇電子支付", "確認呼叫")
    flow.client.return_value.exists = False
    with pytest.raises(AssertionError, match="支付面板未打开"):
        flow._ios_select_payment("meter", "alipay")
    flow.client.return_value.click.assert_not_called()
    flow.monitor.capture.assert_called_once()


@pytest.mark.parametrize("channel", ["alipay", "bankcard"])
def test_charter_cashier_still_selects_direct_channel(meter_payment, channel):
    flow = meter_payment
    flow.CAR_TYPE = "charter"
    flow._ios_select_meter_payment = Mock(side_effect=AssertionError("must not enter route sheet"))
    flow._ios_get_all_texts = Mock(return_value=["預付車費", "信用卡", "Alipay HK", "確認支付並呼叫"])
    option = Mock(exists=True)
    absent = Mock(exists=False)
    label = "Alipay HK" if channel == "alipay" else "信用卡"
    flow.client.side_effect = lambda **kwargs: option if label in kwargs.get("xpath", "") else absent
    flow._ios_select_payment("charter", channel)
    option.click.assert_called_once()
    absent.click.assert_not_called()
    flow._ios_select_meter_payment.assert_not_called()
    flow._ios_pay.assert_not_called()


def grouped_payment_page(description="支持Alipay HK、信用卡或扣帳卡", visible="true", enabled="true"):
    page = payment_page("請選擇本單支付方式", "現金支付", "確認選擇")
    cell = ET.SubElement(page.root, "XCUIElementTypeCell", visible=visible, enabled=enabled)
    ET.SubElement(cell, "XCUIElementTypeStaticText", label="電子支付", visible=visible, enabled=enabled)
    ET.SubElement(cell, "XCUIElementTypeStaticText", label=description, visible=visible, enabled=enabled)
    return IOSPage(ET.tostring(page.root, encoding="unicode"))


@pytest.mark.parametrize("channel", ["alipay", "bankcard", "epayment", "cash"])
def test_recorded_meter_group_preserves_final_channel(meter_payment, channel):
    flow = meter_payment
    flow.PAYMENT = channel
    sheet = grouped_payment_page()
    summary = "現金支付" if channel == "cash" else "電子支付"
    selected = payment_page(f"支付方式：本次已選擇{summary}，請行程結束後支付", "確認呼叫")
    flow.monitor.inspect.side_effect = [sheet, sheet, selected]
    flow._ios_select_payment("meter", channel)
    calls = [call.kwargs["xpath"] for call in flow.client.call_args_list]
    assert f'@label="{summary}"' in calls[0]
    assert '@label="確認選擇"' in calls[1]
    assert len(calls) == 2
    assert flow.PAYMENT == channel
    assert flow.final_payment == ("bankcard" if channel == "epayment" else channel)
    flow._ios_click_confirm_call.assert_not_called()
    flow._ios_click_confirm_pay.assert_not_called()
    flow._ios_pay.assert_not_called()


@pytest.mark.parametrize("unavailable", ["unsupported", "negative", "outside_cell", "hidden", "disabled", "disabled_channel"])
def test_meter_group_must_explicitly_support_requested_channel(meter_payment, unavailable):
    description = "支持信用卡或扣帳卡" if unavailable == "unsupported" else "支持信用卡，不支持Alipay HK" if unavailable == "negative" else "支持Alipay HK、信用卡或扣帳卡"
    sheet = grouped_payment_page(
        "支持信用卡" if unavailable == "outside_cell" else description,
        visible="false" if unavailable == "hidden" else "true",
        enabled="false" if unavailable == "disabled" else "true")
    if unavailable == "outside_cell":
        ET.SubElement(sheet.root, "XCUIElementTypeStaticText", label="支持Alipay HK", visible="true", enabled="true")
    if unavailable == "disabled_channel":
        ET.SubElement(sheet.root, "XCUIElementTypeStaticText", label="Alipay HK", visible="true", enabled="false")
    sheet = IOSPage(ET.tostring(sheet.root, encoding="unicode"))
    flow = meter_payment
    flow.monitor.inspect.return_value = sheet
    with pytest.raises(AssertionError, match="无可用支付选项"):
        flow._ios_select_payment("meter", "alipay")
    flow.client.assert_not_called()
    flow.monitor.capture.assert_called_once()
    assert flow.PAYMENT == flow.final_payment == "alipay"


def test_meter_group_order_still_pays_alipay_only_after_driver_trip(charter_flow):
    from ui_framework import JRYG_ios_ui_elements as elements

    flow, events = charter_flow
    flow.CAR_TYPE, flow.PAYMENT = "meter", "alipay"
    entry = Mock(exists=True)
    flow.client.side_effect = lambda **kwargs: entry if kwargs.get("xpath") == elements.ROUTE_PAYMENT_ENTRY_XPATH else flow.client.return_value
    sheet = grouped_payment_page()
    route = payment_page("支付方式：本次已選擇電子支付", "確認呼叫")
    flow.monitor.inspect.side_effect = [HOME, HOME, LOGGED, route, sheet, sheet, route, page("等待接单")]
    flow.monitor.click_text.side_effect = lambda _client, *labels: events.append(labels[0]) or True
    def select_payment(tag, payment):
        iOSBase._ios_select_payment(flow, tag, payment)
        events.append(("payment", payment))
    flow._ios_select_payment = Mock(side_effect=select_payment)
    flow._ios_wait_current_payment = Mock(side_effect=lambda _tag: events.append("wait_bill"))
    flow._ios_complete_payment = Mock(side_effect=lambda tag: TestOrderBase._ios_complete_payment(flow, tag))
    flow._ios_pay.side_effect = lambda _tag, payment: events.append(("postpay", payment))
    flow.driver_ui.last_phase = "unpaid"
    flow.test_order_flow()
    assert events == [
        "driver_online", "launch", "permissions", "我的", "主頁",
        ("start", "铜锣湾地铁站D2出口"), ("end", "大谭郊野公园"), ("car", "meter"),
        ("payment", "alipay"), "call", "order_success", "driver_trip", "wait_bill",
        ("postpay", "alipay"), "verify_same_order",
    ]
    flow._ios_click_confirm_pay.assert_not_called()
    flow._ios_pay.assert_called_once_with("打錶的士+Alipay HK", payment="alipay")
    flow._ios_ensure_logged_in.assert_called_once()
    flow._ios_click_confirm_call.assert_called_once()
    assert flow.PAYMENT == flow.final_payment == "alipay"
    assert flow.completed_order_no == "offline-order"
    entry.click.assert_called_once()


def test_meter_prefers_independent_alipay_when_group_also_exists(meter_payment):
    sheet = grouped_payment_page()
    ET.SubElement(sheet.root, "XCUIElementTypeStaticText", label="Alipay HK", visible="true", enabled="true")
    sheet = IOSPage(ET.tostring(sheet.root, encoding="unicode"))
    selected = payment_page("支付方式：本次已選擇Alipay HK，請行程結束後支付", "確認呼叫")
    flow = meter_payment
    flow.monitor.inspect.side_effect = [sheet, sheet, selected]
    flow._ios_select_payment("meter", "alipay")
    calls = [call.kwargs["xpath"] for call in flow.client.call_args_list]
    assert '@label="Alipay HK"' in calls[0]
    assert len(calls) == 2
    assert not any('@label="電子支付"' in xpath for xpath in calls)


def test_grouped_meter_postpayment_still_refuses_non_alipay_channel(meter_payment):
    flow = meter_payment
    flow.monitor.inspect.return_value = payment_page("行程結束", "電子支付", "信用卡或扣帳卡", "確認支付")
    with pytest.raises(RuntimeError, match="未找到Alipay HK支付选项"):
        iOSBase._ios_pay(flow, "meter", payment=flow.final_payment)
    flow.client.assert_not_called()
    assert flow.PAYMENT == flow.final_payment == "alipay"


@pytest.mark.parametrize("failure", ["支付失敗", "支付失败", "訂單已取消", "订单已取消"])
def test_current_payment_failure_keeps_exact_snapshot_and_never_pays(meter_payment, failure):
    flow = meter_payment
    flow.PAYMENT, flow.FINAL_PAYMENT = "epayment", "alipay"
    flow.driver_ui = Mock(order_no="26B4JX7WECNW")
    current = payment_page(failure, "確認支付")
    def inspect(**_kwargs):
        flow.monitor.last_page = current
        return current
    flow.monitor.inspect.side_effect = inspect
    flow.monitor.capture.return_value = "local-diagnostic"
    with pytest.raises(RuntimeError, match=f"命中=.*{failure}.*司机订单=26B4JX7WECNW"):
        flow._ios_wait_current_payment("epayment-alipay")
    flow.monitor.capture.assert_called_once_with("current_payment_failed_or_cancelled")
    assert flow.monitor.last_page is current
    flow.monitor.inspect.assert_called_once()
    flow.client.assert_not_called()
    flow._ios_pay.assert_not_called()
    flow._ios_click_confirm_pay.assert_not_called()
    assert flow.final_payment == "alipay"


@pytest.mark.parametrize("amount", ["0.10HKD", "5HKD", "999HKD"])
def test_current_payment_waits_real_page_without_amount_comparison(meter_payment, amount):
    flow = meter_payment
    flow.monitor.inspect.side_effect = [payment_page("行程結束"), payment_page(amount, "確認支付", hidden=("訂單已取消",))]
    flow._ios_wait_current_payment("meter")
    assert flow.monitor.inspect.call_count == 2
    flow._ios_screenshot.assert_called_once_with("epayment_current_before_payment.png")
    flow.monitor.capture.assert_not_called()
    flow._ios_pay.assert_not_called()
    flow.client.assert_not_called()


def test_current_payment_unknown_page_times_out_with_evidence(meter_payment, monkeypatch):
    from ui_framework.JRYG_config import SETTINGS

    monkeypatch.setitem(SETTINGS, "order_validation", {"completion_timeout": 0.5})
    flow = meter_payment
    flow.monitor.inspect.return_value = payment_page("想去哪裡", "主頁")
    with pytest.raises(TimeoutError, match="不跳过支付"):
        flow._ios_wait_current_payment("meter")
    flow.monitor.capture.assert_called_once_with("current_payment_page_timeout")
    flow._ios_pay.assert_not_called()
    flow.client.assert_not_called()


def test_current_payment_foreground_guard_saves_wrong_app_and_stops(meter_payment):
    flow = meter_payment
    flow.monitor.inspect.return_value = payment_page("確認支付", bundle=BUNDLE_ID)
    with pytest.raises(RuntimeError, match="乘客App不在前台"):
        flow._ios_wait_current_payment("meter")
    flow.monitor.capture.assert_called_once_with("current_payment_not_foreground")
    flow.client.assert_not_called()
    flow._ios_pay.assert_not_called()


def test_current_payment_read_error_does_not_become_cancellation(meter_payment):
    flow = meter_payment
    error = RuntimeError("page read failed")
    flow.monitor.inspect.side_effect = error
    with pytest.raises(RuntimeError) as caught:
        flow._ios_wait_current_payment("meter")
    assert caught.value is error
    flow.monitor.capture.assert_called_once_with("current_payment_page_read_failed")
    flow._ios_pay.assert_not_called()


@pytest.mark.parametrize("phase", ["unpaid", "complete", "pickup"])
def test_unpaid_driver_evidence_saved_before_returning_to_passenger(meter_payment, monkeypatch, phase):
    flow = meter_payment
    stop = "accepted" if phase == "pickup" else "submitted"
    monkeypatch.setenv("HK_DRIVER_UI_STOP_AFTER", stop)
    flow.driver_runtime = SimpleNamespace(wda_url="http://example.invalid")
    flow.driver_ui = Mock(last_phase=phase, order_no="26B4JX7WECNW")
    flow._driver_ui_grab_and_flow("meter")
    flow.driver_ui.run.assert_called_once()
    if phase == "unpaid":
        flow.driver_ui.snapshot.assert_called_once_with("bill_submitted_unpaid_before_passenger_payment")
    else:
        flow.driver_ui.snapshot.assert_not_called()
    flow._ios_pay.assert_not_called()
    flow.client.assert_not_called()


@pytest.mark.parametrize("batch", [False, True])
def test_batch_new_order_guard_does_not_resume_previous_failed_trip(driver, batch):
    flow = TestOrderBase()
    flow.batch_new_order_only = batch
    flow._resolve_driver_runtime = Mock(return_value=SimpleNamespace(wda_url="http://example.invalid"))
    flow._create_driver_flow = Mock(return_value=driver)
    flow._ios_pay = Mock()
    driver.wait_for_entry_page = Mock(return_value=(ET.Element("trip"), "destination"))
    driver.snapshot = Mock()
    if batch:
        with pytest.raises(RuntimeError, match="已有行程.*未自动取消"):
            flow._driver_ui_go_online("next-case")
        assert driver.resume_phase is None
        assert not driver.awaiting_new_order
    else:
        flow._driver_ui_go_online("standalone")
        assert flow.resuming_order
        assert driver.resume_phase == "destination"
    driver.act.assert_not_called()
    flow._ios_pay.assert_not_called()


def test_retry_reopens_passenger_app_once_before_login_and_order(charter_flow):
    flow, events = charter_flow
    flow.batch_retry = True
    flow.test_order_flow()
    flow._ios_prepare_passenger_app.assert_called_once()
    flow.client.home.assert_called_once()
    flow.client.session.assert_called_once_with(PASSENGER_BUNDLE_ID)
    assert events.index("launch") < events.index("我的") < events.index("call")
    assert flow.retry_safe is False


def test_preorder_login_failure_remains_safe_to_retry(charter_flow):
    flow, _events = charter_flow
    flow._ios_ensure_logged_in = Mock(return_value=False)
    with pytest.raises(RuntimeError, match="自动登录失败"):
        flow.test_order_flow()
    assert flow.retry_safe is True
    flow._ios_click_confirm_call.assert_not_called()
    flow._ios_pay.assert_not_called()


@pytest.mark.parametrize("car_type,payment", [("charter", "alipay"), ("meter", "cash")])
def test_retry_is_disabled_before_first_call_even_if_tap_raises(charter_flow, car_type, payment):
    flow, _events = charter_flow
    flow.CAR_TYPE, flow.PAYMENT = car_type, payment
    flow._click_call_and_check_login_then_retry = Mock(side_effect=RuntimeError("uncertain call"))
    flow._charter_click_call_and_select_payment = Mock(side_effect=RuntimeError("uncertain call"))
    with pytest.raises(RuntimeError, match="uncertain call"):
        flow.test_order_flow()
    assert flow.retry_safe is False
    flow._ios_pay.assert_not_called()


@pytest.mark.parametrize("label", ["取消訂單", "未完成訂單", "確認支付", "行程結束"])
def test_retry_reopened_app_never_cancels_or_pays_existing_order(label):
    flow = TestOrderBase()
    flow.client = Mock()
    flow.retry_safe = True
    flow.batch_retry = True
    flow._ios_prepare_passenger_app = Mock()
    flow._ios_ensure_logged_in = Mock(return_value=True)
    flow._ios_get_all_texts = Mock(return_value=[label])
    flow._ios_click_dialog_button = Mock()
    flow._ios_pay = Mock()
    with pytest.raises(RuntimeError, match="重试检测到遗留订单"):
        flow._ui_cleanup_ongoing_order("retry")
    assert flow.retry_safe is False
    flow._ios_prepare_passenger_app.assert_called_once()
    flow._ios_click_dialog_button.assert_not_called()
    flow._ios_pay.assert_not_called()


@pytest.mark.parametrize("payment,stage", [("bankcard", "postpaid"), ("alipay", "postpaid"),
                                           ("bankcard", "submitted"), ("alipay", "submitted")])
def test_public_payment_entry_disables_whole_case_retry(payment, stage):
    flow = TestOrderBase()
    flow.retry_safe = True
    flow._ios_select_postpaid_channel = Mock()
    flow._ios_fill_bank_card_form = Mock(side_effect=RuntimeError("payment unknown"))
    flow._ios_complete_alipay_payment = Mock(side_effect=RuntimeError("payment unknown"))
    with pytest.raises(RuntimeError, match="payment unknown"):
        flow._ios_pay("retry", payment, stage=stage)
    assert flow.retry_safe is False


def test_driver_preparation_failure_does_not_claim_retry_safety(charter_flow):
    flow, _events = charter_flow
    flow._driver_ui_go_online.side_effect = RuntimeError("driver state unknown")
    with pytest.raises(RuntimeError, match="driver state unknown"):
        flow.test_order_flow()
    assert flow.retry_safe is False
    flow._ios_prepare_passenger_app.assert_not_called()
    flow._ios_pay.assert_not_called()


def postpaid_page(channel="Alipay HK", *, hidden=False, disabled=False, duplicate=False,
                  bundle=PASSENGER_BUNDLE_ID, failure=None):
    root = ET.Element("XCUIElementTypeApplication", bundleId=bundle)
    ET.SubElement(root, "XCUIElementTypeStaticText", label="行程結束", visible="true", enabled="true")
    for _ in range(2 if duplicate else 1):
        ET.SubElement(root, "XCUIElementTypeStaticText", label=channel, name=channel,
                      visible="false" if hidden else "true", enabled="false" if disabled else "true")
    button = ET.SubElement(root, "XCUIElementTypeButton", label="確認支付5HKD", visible="true", enabled="true")
    ET.SubElement(button, "XCUIElementTypeStaticText", label="確認支付5HKD", visible="true", enabled="true")
    if failure:
        ET.SubElement(root, "XCUIElementTypeStaticText", label=failure, visible="true", enabled="true")
    return IOSPage(ET.tostring(root, encoding="unicode"))


@pytest.mark.parametrize("payment,label", [("alipay", "Alipay HK"), ("bankcard", "信用卡或扣帳卡")])
def test_postpaid_waits_channel_then_clicks_single_confirm_button(meter_payment, payment, label):
    flow = meter_payment
    flow.monitor.inspect.side_effect = [payment_page("行程結束"), postpaid_page(label), postpaid_page(label)]
    flow._ios_select_postpaid_channel("postpaid", payment)
    assert flow.monitor.inspect.call_count == 3
    assert flow.client.return_value.click.call_count == 2
    paths = [call.kwargs["xpath"] for call in flow.client.call_args_list]
    assert f'@label="{label}"' in paths[0]
    assert paths[1].startswith("//XCUIElementTypeButton[")
    assert "確認支付5HKD" in paths[1]
    flow.client.click.assert_not_called()
    flow.poco.assert_not_called()


@pytest.mark.parametrize("invalid", ["hidden", "disabled", "duplicate", "description"])
def test_postpaid_unavailable_channel_never_uses_fallback_or_pays(meter_payment, invalid):
    flow = meter_payment
    kwargs = {invalid: True} if invalid != "description" else {"channel": "支持Alipay HK"}
    flow.monitor.inspect.return_value = postpaid_page(**kwargs)
    with pytest.raises(RuntimeError, match="未找到Alipay HK"):
        flow._ios_select_postpaid_channel("postpaid", "alipay")
    flow.client.assert_not_called()
    flow.client.click.assert_not_called()
    flow.poco.assert_not_called()
    flow.monitor.capture.assert_called_once()


@pytest.mark.parametrize("invalid", ["foreground", "failed", "cancelled"])
def test_postpaid_foreground_and_failure_protection_precedes_click(meter_payment, invalid):
    flow = meter_payment
    flow.monitor.inspect.return_value = postpaid_page(
        bundle="com.apple.springboard" if invalid == "foreground" else PASSENGER_BUNDLE_ID,
        failure={"failed": "支付失敗", "cancelled": "訂單已取消"}.get(invalid))
    with pytest.raises(RuntimeError):
        flow._ios_select_postpaid_channel("postpaid", "alipay")
    flow.client.assert_not_called()


def test_postpaid_confirm_response_error_does_not_click_again(meter_payment):
    flow = meter_payment
    flow.monitor.inspect.return_value = postpaid_page()
    flow.client.return_value.click.side_effect = [None, OSError("response lost")]
    with pytest.raises(OSError):
        flow._ios_select_postpaid_channel("postpaid", "alipay")
    assert flow.client.return_value.click.call_count == 2
    assert flow.monitor.inspect.call_count == 2
    flow.client.click.assert_not_called()
