"""安卓统一登录的页面矩阵及调用合同回归，不连接设备或发送短信。"""

import re
from unittest.mock import Mock
import xml.etree.ElementTree as ET

import pytest

from jryg_hk_android import JRYG_android_login as login
from jryg_hk_android.JRYG_android_passenger import AndroidPassengerBase
from jryg_hk_android.JRYG_android_order import AndroidOrderMixin
from jryg_hk_android.JRYG_scenarios import android_scenarios

PACKAGE = "com.sunlightmobility.client"


def node(text="", resource="", kind="android.widget.TextView", **attrs):
    return ET.Element("node", {"class": kind, "text": text, "resource-id": PACKAGE + ":id/" + resource if resource else "",
                               "bounds": "[10,10][200,100]", "displayed": "true", "enabled": "true",
                               "clickable": "true", **attrs})


def page(kind, account="****5678"):
    root = ET.Element("hierarchy")
    if kind == "privacy":
        root.extend([node("使用者協議與私隱政策", "loading_title"), node("同意", "tv_button_agree"), node("不同意")])
    elif kind == "permission_intro":
        root.extend([node("我們需要獲取以下權限，系統將以彈窗提示徵求您的授權：", "tv_title"),
                     node("地理位置權限", "title"), node("去授權", "tv_confirm")])
    elif kind == "permission":
        root.append(node("使用應用程式時", **{"resource-id": "com.android.permissioncontroller:id/permission_allow_foreground_only_button"}))
    elif kind == "permission_unknown":
        root.append(node("未知系統權限"))
    elif kind == "home":
        root.extend([node("您從哪裡出發", "tv_start_address"), node("我的"), node("主頁")])
    elif kind in ("mine", "mine_unlogged"):
        root.extend([node("我的行程"), node("聯繫客服"), node("主頁"),
                     node("登錄/註冊" if kind == "mine_unlogged" else account, "tv_mine_name")])
    elif kind == "address_search":
        root.extend([node("北角", "et_search", "android.widget.EditText"), node("", "back", "android.widget.ImageView")])
    elif kind == "phone":
        root.extend([node("", "phone_num", "android.widget.EditText"),
                     node("", "agree_img", "android.widget.ImageView", checked="false", selected="false"),
                     node("", "rl_next", "android.widget.RelativeLayout")])
    elif kind == "code":
        region = node("", "verify_code", "android.widget.RelativeLayout")
        region.append(node("", kind="android.widget.EditText"))
        root.append(region)
    elif kind == "guide":
        root.append(node("Got It"))
    elif kind in ("advertisement", "obstruction"):
        container = node("", kind="android.widget.FrameLayout", clickable="false", bounds="[0,0][1080,2400]")
        pager = node("", kind="androidx.viewpager.widget.ViewPager", clickable="false", bounds="[200,600][850,1500]")
        pager.append(node("", kind="android.widget.ImageView", clickable="false", bounds="[200,600][850,1500]"))
        container.append(pager)
        if kind == "advertisement":
            container.append(node("", kind="android.widget.ImageView", bounds="[490,1700][580,1790]"))
        root.append(container)
    elif kind == "route":
        root.extend([node("北角地鐵站", "tv_start_address"), node("確認呼叫"), node("我的")])
    elif kind == "business":
        root.extend([node("確認支付5HKD"), node("我的"), node("同意")])
    elif kind == "terminal_unpaid":
        root.extend([node("打錶的士行程結束", "tv_status_name"),
                     node("訂單編號 26B6P6AWECNY", "tv_order_no"),
                     node("確認支付 5 HKD", "tv_pay"),
                     node("", "iv_arrow_back", "android.widget.ImageView")])
    elif kind == "unrelated_agree":
        root.extend([node("同意"), node("《私隱政策》"), node("未知頁")])
    return root


class Native:
    def __init__(self, driver, element):
        self.driver = driver
        self.element = element
        self.id = str(id(element))
        driver.elements[self.id] = self

    @property
    def text(self):
        return self.element.get("text", "")

    def get_attribute(self, key):
        return self.element.get(key, "")

    def is_displayed(self):
        return self.element.get("displayed") == "true"

    def is_enabled(self):
        return self.element.get("enabled") == "true"

    def click(self):
        name = self.element.get("resource-id", "").split("/")[-1] or self.text
        self.driver.actions.append(("click", name))
        if name == "tv_button_agree":
            self.driver.set_page("permission")
        elif name == "tv_confirm":
            self.driver.set_page("permission")
        elif "permission_allow" in name:
            self.driver.set_page("advertisement")
        elif self.driver.kind == "advertisement":
            self.driver.set_page("guide")
        elif name == "Got It":
            self.driver.set_page("home")
        elif name == "我的":
            self.driver.set_page("mine" if self.driver.authenticated else "mine_unlogged")
        elif name in ("主頁", "back", "iv_arrow_back"):
            self.driver.set_page("home")
        elif self.text == "登錄/註冊":
            self.driver.set_page("phone")
        elif name == "agree_img":
            self.element.set("checked", "true")
        elif name == "rl_next" and not self.driver.stalled:
            self.driver.set_page("code")

    def clear(self):
        self.driver.actions.append(("clear", "field"))
        self.element.set("text", "")

    def send_keys(self, value):
        self.driver.actions.append(("input", "code" if self.driver.kind == "code" else "mobile"))
        self.element.set("text", "wrong" if self.driver.bad_readback else value)
        if self.driver.kind == "code" and not self.driver.stalled:
            self.driver.authenticated = True
            self.driver.set_page("home")


class Driver:
    def __init__(self, kind="privacy", *, authenticated=False):
        self.authenticated = authenticated
        self.actions = []
        self.stalled = False
        self.bad_readback = False
        self.account = "****5678"
        self.elements = {}
        self.settings = {"waitForIdleTimeout": 10000, "waitForSelectorTimeout": 10000}
        self.settings_updates = []
        self.replace_calls = []
        self.set_page(kind)

    def get_settings(self):
        return dict(self.settings)

    def update_settings(self, settings):
        self.settings_updates.append(dict(settings))
        self.settings.update(settings)

    def execute_script(self, command, arguments):
        assert command == "mobile: replaceElementValue"
        assert self.settings["waitForIdleTimeout"] == 0
        self.replace_calls.append(dict(arguments))
        field = self.elements[arguments["elementId"]]
        field.element.set("text", "")
        field.send_keys(arguments["text"])

    def set_page(self, kind):
        self.kind = kind
        self.root = page(kind, self.account)
        self.current_package = "com.android.permissioncontroller" if kind in ("permission", "permission_unknown") else PACKAGE
        self.current_activity = "YGUVerificationCodeActivity" if kind == "code" else "YGUHomeActivity"

    @property
    def page_source(self):
        return ET.tostring(self.root, encoding="unicode")

    def activate_app(self, package):
        assert package == PACKAGE
        self.actions.append(("activate", package))

    def find_elements(self, by, path):
        assert by == "xpath"
        element = self.root
        for index in re.findall(r"\*\[(\d+)\]", path):
            element = list(element)[int(index) - 1]
        return [Native(self, element)]


@pytest.fixture
def passenger(monkeypatch):
    monkeypatch.delenv("HK_PASSENGER_MOBILE", raising=False)
    monkeypatch.delenv("HK_PASSENGER_UI_CODE", raising=False)
    monkeypatch.setattr(login.time, "sleep", lambda seconds: None)
    instance = AndroidPassengerBase()
    instance.android_settings = {"packages": {"passenger_hk": PACKAGE},
                                 "login": {"mobile": "12345678", "code": "123456", "timeout": 0.02}}
    driver = Driver()
    instance.client = Mock(driver=driver)
    instance.client.app_activate.side_effect = driver.activate_app
    return instance, driver


@pytest.mark.parametrize("kind", ["privacy", "permission_intro", "permission", "advertisement", "guide", "home", "phone", "code", "mine_unlogged"])
def test_any_known_entry_flows_to_verified_login_and_home(passenger, kind):
    instance, driver = passenger
    driver.set_page(kind)
    result = instance.login_passenger("offline")
    assert result.verified and result.page == "home" and result.authenticated_now
    assert driver.kind == "home"
    assert len([action for action in driver.actions if action == ("click", "rl_next")]) <= 1
    assert len([action for action in driver.actions if action == ("input", "code")]) == 1
    assert instance._android_login_driver is driver


def test_policy_permission_ad_guide_then_login_sequence(passenger):
    instance, driver = passenger
    instance.ensure_passenger_login("offline")
    clicks = [value for action, value in driver.actions if action == "click"]
    assert clicks[:4] == ["tv_button_agree", "permission_allow_foreground_only_button", "", "Got It"]
    assert "不同意" not in clicks
    assert clicks.count("rl_next") == 1
    assert driver.actions.count(("input", "mobile")) == 1


def test_already_logged_in_does_not_send_code_and_second_call_is_idempotent(passenger):
    instance, driver = passenger
    driver.authenticated = True
    driver.set_page("home")
    result = instance.login_passenger()
    assert result.verified and not result.authenticated_now
    assert not any(action == "input" for action, _ in driver.actions)
    before = len(driver.actions)
    assert instance.ensure_passenger_login()
    assert driver.actions[before:] == []


@pytest.mark.parametrize("mask", ["****5678", "12****78", "12345678", "+852 ****5678"])
def test_masked_or_full_expected_account_is_verified(passenger, mask):
    instance, driver = passenger
    driver.account = mask
    driver.set_page("mine")
    assert instance.login_passenger(target="current").page == "mine"


@pytest.mark.parametrize("mask", ["****0000", "********", "not-an-account"])
def test_wrong_or_unverifiable_account_never_continues(passenger, mask):
    instance, driver = passenger
    driver.account = mask
    driver.set_page("mine")
    with pytest.raises(RuntimeError, match="账号"):
        instance.login_passenger()
    assert not any(action == "input" for action, _ in driver.actions)
    assert ("click", "主頁") not in driver.actions


@pytest.mark.parametrize("kind", ["business", "route", "obstruction", "permission_unknown"])
def test_protected_or_unknown_obstruction_is_not_clicked(passenger, kind):
    instance, driver = passenger
    driver.set_page(kind)
    with pytest.raises(RuntimeError):
        instance.login_passenger()
    assert driver.actions == ([("activate", PACKAGE)] if kind == "permission_unknown" else [])


@pytest.mark.parametrize("kind", ["unknown", "unrelated_agree"])
def test_unknown_page_never_clicks_generic_agree(passenger, kind):
    instance, driver = passenger
    driver.set_page(kind)
    with pytest.raises(TimeoutError):
        instance.login_passenger()
    assert driver.actions == []


def test_wrong_foreground_stops_without_clicking(passenger):
    instance, driver = passenger
    driver.current_package = "com.sunlightmobility.driver"
    with pytest.raises(RuntimeError, match="前台"):
        instance.login_passenger(launch=False)
    assert driver.actions == []


@pytest.mark.parametrize("kind", ["client", "proxy", "socket"])
def test_source_timeout_is_reported_once_without_business_actions(passenger, monkeypatch, kind):
    from selenium.common.exceptions import WebDriverException
    from urllib3.exceptions import ReadTimeoutError
    instance, driver = passenger
    failures = {
        "client": ReadTimeoutError(None, "/session/test/source", "read timeout=20"),
        "proxy": WebDriverException("Could not proxy command: timeout of 15000ms exceeded"),
        "socket": TimeoutError("socket timed out"),
    }
    getter = Mock(side_effect=failures[kind])
    monkeypatch.setattr(type(driver), "page_source", property(getter))
    with pytest.raises(RuntimeError, match="页面树读取超时") as error:
        instance.login_passenger(launch=False)
    assert error.value.__cause__ is failures[kind]
    assert getter.call_count == 1
    assert driver.actions == []
    assert instance._android_login_driver is None


def test_non_timeout_webdriver_error_is_not_hidden(passenger, monkeypatch):
    from selenium.common.exceptions import WebDriverException
    instance, driver = passenger
    failure = WebDriverException("invalid session id")
    monkeypatch.setattr(type(driver), "page_source", property(Mock(side_effect=failure)))
    with pytest.raises(WebDriverException) as error:
        instance.login_passenger(launch=False)
    assert error.value is failure
    assert driver.actions == []


def test_code_is_not_reentered_when_result_is_uncertain(passenger):
    instance, driver = passenger
    driver.set_page("code")
    driver.stalled = True
    with pytest.raises(TimeoutError):
        instance.login_passenger()
    assert driver.actions.count(("input", "code")) == 1


def test_sms_is_not_sent_twice_when_phone_page_does_not_advance(passenger):
    instance, driver = passenger
    driver.set_page("phone")
    driver.stalled = True
    with pytest.raises(TimeoutError):
        instance.login_passenger()
    assert driver.actions.count(("click", "rl_next")) == 1
    assert driver.actions.count(("input", "mobile")) == 1


@pytest.mark.parametrize("missing", [None, "rv_car_list", "btn_call", "iv_arrow_back"])
def test_native_car_estimate_without_start_address_requires_exact_page_markers(passenger, missing):
    instance, driver = passenger
    root = ET.Element("hierarchy")
    for name in ("rv_car_list", "btn_call", "iv_arrow_back"):
        if name != missing:
            root.append(node(text="確認呼叫" if name == "btn_call" else "", resource=name))
    root.append(node(text="包車價的士", resource="tv_car_type_name"))
    assert instance._login_classify(root, PACKAGE) == ("route" if missing is None else "unknown")
    assert driver.actions == []


def test_native_estimate_page_returns_home_without_submitting_order(passenger):
    instance, driver = passenger
    driver.authenticated = True
    driver.root = ET.Element("hierarchy")
    for name in ("rv_car_list", "btn_call", "iv_arrow_back"):
        driver.root.append(node(text="確認呼叫" if name == "btn_call" else "", resource=name))
    driver.kind = "route"

    def back():
        driver.actions.append(("back", driver.kind))
        driver.set_page("home")

    driver.back = Mock(side_effect=back)
    assert instance.login_passenger().verified
    driver.back.assert_called_once_with()
    assert driver.kind == "home"
    assert driver.actions[0] == ("back", "route")
    assert ("click", "btn_call") not in driver.actions
    assert not any(action == "input" for action, _ in driver.actions)


def test_terminal_unpaid_returns_home_once_without_payment_or_cancel(passenger):
    instance, driver = passenger
    driver.authenticated = True
    driver.set_page("terminal_unpaid")
    assert instance._login_classify(driver.root, PACKAGE) == "terminal_unpaid"
    assert instance.login_passenger().verified
    assert driver.actions.count(("click", "iv_arrow_back")) == 1
    assert not any(value in ("tv_pay", "確認支付 5 HKD", "取消訂單") for _, value in driver.actions)
    assert driver.kind == "home"


@pytest.mark.parametrize("missing", ["tv_status_name", "tv_order_no", "tv_pay", "iv_arrow_back"])
def test_terminal_unpaid_requires_all_unique_native_markers(passenger, missing):
    instance, driver = passenger
    root = page("terminal_unpaid")
    for item in list(root):
        if item.get("resource-id", "").endswith("/" + missing):
            root.remove(item)
    assert instance._login_classify(root, PACKAGE) != "terminal_unpaid"
    assert driver.actions == []


def test_terminal_unpaid_duplicate_back_is_not_operated(passenger):
    instance, driver = passenger
    driver.set_page("terminal_unpaid")
    driver.root.append(node("", "iv_arrow_back", "android.widget.ImageView"))
    assert instance._login_classify(driver.root, PACKAGE) == "business"
    with pytest.raises(RuntimeError, match="订单或路线页"):
        instance.login_passenger()
    assert driver.actions == []


def test_terminal_unpaid_does_not_repeat_unconfirmed_back(passenger):
    instance, driver = passenger
    driver.authenticated = True
    driver.set_page("terminal_unpaid")
    native = Mock()
    instance._login_native = Mock(return_value=native)
    with pytest.raises(RuntimeError, match="单次返回未确认"):
        instance.login_passenger()
    native.click.assert_called_once_with()


def test_route_payment_description_is_not_terminal_unpaid(passenger):
    instance, driver = passenger
    root = ET.Element("hierarchy")
    root.extend([node("支付方式：本次已選擇電子支付，請行程結束後支付"),
                 node("", "rv_car_list"), node("確認呼叫", "btn_call"),
                 node("", "iv_arrow_back", "android.widget.ImageView")])
    assert instance._login_classify(root, PACKAGE) == "route"
    assert driver.actions == []


def test_formatted_phone_readback_matches_exact_digits(passenger):
    instance, driver = passenger
    driver.set_page("phone")
    native = Native(driver, list(driver.root)[0])
    original = native.send_keys
    native.send_keys = lambda value: original(value[:4] + " " + value[4:])
    resolve = instance._login_native
    instance._login_native = lambda root, element: native if element.get("resource-id", "").endswith("/phone_num") else resolve(root, element)
    instance._login_submit_phone(driver.root)
    assert driver.actions.count(("click", "rl_next")) == 1


def test_phone_readback_failure_cannot_send_sms(passenger):
    instance, driver = passenger
    driver.set_page("phone")
    driver.bad_readback = True
    with pytest.raises(RuntimeError, match="不重复"):
        instance.login_passenger()
    assert ("click", "rl_next") not in driver.actions


@pytest.mark.parametrize("kind", ["business", "route", "terminal_unpaid"])
def test_verified_current_page_resumes_without_navigation(passenger, kind):
    instance, driver = passenger
    instance._android_login_driver = driver
    driver.set_page(kind)
    assert instance.login_passenger(launch=False, target="current").page == kind
    assert driver.actions == []


def test_expired_login_invalidates_previous_verified_state(passenger):
    instance, driver = passenger
    instance._android_login_driver = driver
    driver.set_page("phone")
    driver.stalled = True
    with pytest.raises(TimeoutError):
        instance.login_passenger()
    assert instance._android_login_driver is None


@pytest.mark.parametrize("kind", ["home", "phone", "code"])
def test_current_target_returns_home_after_temporary_account_verification(passenger, kind):
    instance, driver = passenger
    driver.set_page(kind)
    assert instance.login_passenger(target="current").page == "home"
    assert driver.kind == "home"


def test_startup_only_does_not_send_sms_or_login(passenger):
    instance, driver = passenger
    assert instance.prepare_passenger_app(timeout=0.02) == "home"
    assert not any(action == "input" for action, _ in driver.actions)
    assert ("click", "我的") not in driver.actions


def test_all_login_compatibility_methods_delegate_to_one_wrapper(passenger):
    instance, _ = passenger
    instance.login_passenger = Mock(return_value=login.AndroidLoginResult(True, "home"))
    assert instance.ensure_passenger_login("plain")
    assert instance._ios_ui_login("retry")
    assert instance._ios_ensure_logged_in("existing")
    assert instance.login_passenger.call_count == 3
    instance.login_passenger.assert_any_call("plain")
    instance.login_passenger.assert_any_call("retry", launch=False, target="current")
    instance.login_passenger.assert_any_call("existing", launch=False, target="current")


def test_six_order_scenarios_inherit_same_login_implementation():
    for case in android_scenarios():
        assert case.login_passenger is login.AndroidLoginMixin.login_passenger
        assert case.ensure_passenger_login is login.AndroidLoginMixin.ensure_passenger_login


def test_failed_login_cannot_continue_route(passenger):
    instance, _ = passenger
    instance.ensure_passenger_login = Mock(return_value=False)
    instance._ios_configure_addresses = Mock()
    with pytest.raises(RuntimeError, match="登录未核验"):
        instance.prepare_passenger_route()
    instance._ios_configure_addresses.assert_not_called()


def test_order_cleanup_delegates_to_login_before_business_steps():
    instance = AndroidOrderMixin()
    calls = []
    instance.login_passenger = lambda *args, **kwargs: calls.append((args, kwargs)) or True
    instance.client = Mock()
    instance._ios_get_all_texts = Mock(return_value=[])
    instance._clear_waiting_order = Mock()
    instance._ui_cleanup_ongoing_order("order")
    assert calls == [(("order",), {})]
    instance._clear_waiting_order.assert_called_once_with("order")


def test_android_config_uses_confirmed_hong_kong_test_account(monkeypatch):
    from jryg_hk_android.JRYG_shared_ios import shared_settings
    monkeypatch.delenv("HK_PASSENGER_MOBILE", raising=False)
    monkeypatch.delenv("HK_PASSENGER_UI_CODE", raising=False)
    instance = AndroidPassengerBase()
    instance.android_settings = shared_settings()
    config = instance.android_settings["login"]
    assert config["country_code"] == "852"
    assert config["mobile_length"] == 11
    assert instance._login_credentials()[0] == "11018251727"


@pytest.mark.parametrize("account", ["11018251727", "110****1727", "*******1727", "+852 110****1727", "110 1825 1727"])
def test_explicit_eleven_digit_hk_test_account_can_complete_login(passenger, account):
    instance, driver = passenger
    instance.android_settings["login"].update(country_code="852", mobile="11018251727", mobile_length=11)
    driver.account = account
    driver.set_page("phone")
    assert instance.login_passenger().verified
    assert driver.kind == "home"
    assert driver.actions.count(("input", "mobile")) == 1
    assert driver.actions.count(("input", "code")) == 1


@pytest.mark.parametrize("account", ["11018251728", "110****1728", "****1727", "***********", "+86 11018251727"])
def test_old_wrong_or_other_country_account_cannot_verify_as_hk_test_account(passenger, account):
    instance, driver = passenger
    instance.android_settings["login"].update(country_code="852", mobile="11018251727", mobile_length=11)
    driver.account = account
    driver.set_page("mine")
    with pytest.raises(RuntimeError, match="账号"):
        instance.login_passenger()
    assert ("click", "主頁") not in driver.actions
    assert not any(action == "input" for action, _ in driver.actions)


def test_eleven_digit_account_requires_explicit_length_config(passenger):
    instance, _ = passenger
    instance.android_settings["login"]["mobile"] = "11018251727"
    with pytest.raises(RuntimeError, match="8位"):
        instance._login_credentials()


@pytest.mark.parametrize("length", [True, "11", 9, 10, 12])
def test_invalid_hk_mobile_length_is_not_silently_accepted(passenger, length):
    instance, _ = passenger
    instance.android_settings["login"]["mobile_length"] = length
    with pytest.raises(RuntimeError, match="长度"):
        instance._login_credentials()


def test_hk_test_account_does_not_implicitly_change_country(passenger):
    instance, _ = passenger
    instance.android_settings["login"].update(country_code="86", mobile="11018251727", mobile_length=11)
    with pytest.raises(RuntimeError, match="区号"):
        instance._login_credentials()


def test_truncated_test_mobile_cannot_submit_sms(passenger):
    instance, driver = passenger
    instance.android_settings["login"].update(country_code="852", mobile="11018251727", mobile_length=11)
    driver.set_page("phone")
    native = Native(driver, list(driver.root)[0])
    original = native.send_keys
    native.send_keys = lambda value: original(value[:8])
    resolve = instance._login_native
    instance._login_native = lambda root, element: native if element.get("resource-id", "").endswith("/phone_num") else resolve(root, element)
    with pytest.raises(RuntimeError, match="不重复"):
        instance.login_passenger()
    assert ("click", "rl_next") not in driver.actions


@pytest.mark.parametrize("entry", ["login", "startup"])
def test_switch_from_driver_waits_through_launcher_before_reading_page(passenger, monkeypatch, entry):
    instance, driver = passenger
    driver.authenticated = True
    driver.set_page("home")
    driver.current_package = "com.sunlightmobility.driver"
    packages = iter(["com.android.launcher", PACKAGE])
    sleeps = []

    def advance(seconds):
        sleeps.append(driver.current_package)
        driver.current_package = next(packages, PACKAGE)

    monkeypatch.setattr(login.time, "sleep", advance)
    snapshot = instance._login_snapshot

    def guarded_snapshot():
        assert driver.current_package == PACKAGE
        return snapshot()

    instance._login_snapshot = Mock(side_effect=guarded_snapshot)
    if entry == "login":
        assert instance.login_passenger().verified
    else:
        assert instance.prepare_passenger_app() == "home"
    assert sleeps[:2] == ["com.sunlightmobility.driver", "com.android.launcher"]
    assert driver.actions.count(("activate", PACKAGE)) == 1
    assert not any(action == "input" for action, _ in driver.actions)


@pytest.mark.parametrize("entry", ["login", "startup"])
def test_failed_switch_times_out_without_reading_other_app_or_clicking(passenger, entry):
    instance, driver = passenger
    instance.android_settings["login"]["launch_timeout"] = 0.01
    driver.current_package = "com.sunlightmobility.driver"
    instance._login_snapshot = Mock()
    with pytest.raises(TimeoutError, match="未切到前台"):
        if entry == "login":
            instance.login_passenger()
        else:
            instance.prepare_passenger_app()
    instance._login_snapshot.assert_not_called()
    assert driver.actions == [("activate", PACKAGE)]


def test_verified_login_still_waits_after_switching_to_driver(passenger, monkeypatch):
    instance, driver = passenger
    driver.authenticated = True
    driver.set_page("home")
    instance._android_login_driver = driver
    driver.current_package = "com.sunlightmobility.driver"
    monkeypatch.setattr(login.time, "sleep", lambda seconds: setattr(driver, "current_package", PACKAGE))
    assert instance.login_passenger().verified
    assert driver.actions == [("activate", PACKAGE)]


def test_switch_can_land_on_system_permission_then_continue_login(passenger):
    instance, driver = passenger
    driver.current_package = "com.sunlightmobility.driver"

    def activate(package):
        driver.actions.append(("activate", package))
        driver.set_page("permission")

    instance.client.app_activate.side_effect = activate
    assert instance.login_passenger().verified
    assert ("click", "permission_allow_foreground_only_button") in driver.actions


@pytest.mark.parametrize("timeout", [0, -1, True, "30"])
def test_invalid_launch_timeout_rejected_before_activation(passenger, timeout):
    instance, driver = passenger
    instance.android_settings["login"]["launch_timeout"] = timeout
    with pytest.raises(ValueError, match="launch_timeout"):
        instance.login_passenger()
    assert driver.actions == []


@pytest.mark.parametrize("kind,value", [("phone", "12345678"), ("code", "123456")])
def test_login_native_input_replaces_once_and_restores_idle_wait(passenger, kind, value):
    instance, driver = passenger
    driver.set_page(kind)
    field_node = next(node for node in driver.root.iter() if "EditText" in node.get("class", ""))
    field_node.set("text", "old")
    field = Native(driver, field_node)
    field.click = Mock(side_effect=AssertionError("输入不应先点击"))
    field.clear = Mock(side_effect=AssertionError("输入不应独立清空"))
    instance._login_replace_text(field, value)
    assert driver.replace_calls == [{"elementId": field.id, "text": value}]
    assert driver.settings_updates == [{"waitForIdleTimeout": 0}, {"waitForIdleTimeout": 10000}]
    assert driver.settings["waitForSelectorTimeout"] == 10000
    assert field.text == value
    field.click.assert_not_called()
    field.clear.assert_not_called()


def test_correct_existing_mobile_is_not_cleared_or_reentered(passenger):
    instance, driver = passenger
    driver.set_page("phone")
    list(driver.root)[0].set("text", "1234 5678")
    instance._login_submit_phone(driver.root)
    assert driver.replace_calls == []
    assert driver.settings_updates == []
    assert driver.actions.count(("click", "rl_next")) == 1
    assert not any(action == "input" for action, _ in driver.actions)


def test_input_timeout_after_server_applied_text_does_not_send_sms_or_retry(passenger):
    instance, driver = passenger
    driver.set_page("phone")
    original = driver.execute_script

    def uncertain(command, arguments):
        original(command, arguments)
        raise TimeoutError("read timeout=20")

    driver.execute_script = Mock(side_effect=uncertain)
    with pytest.raises(RuntimeError, match="不重复"):
        instance.login_passenger()
    assert driver.execute_script.call_count == 1
    assert list(driver.root)[0].get("text") == "12345678"
    assert ("click", "rl_next") not in driver.actions
    assert driver.settings["waitForIdleTimeout"] == 10000


def test_replacement_failure_restores_idle_wait_and_never_falls_back(passenger):
    instance, driver = passenger
    driver.set_page("phone")
    driver.execute_script = Mock(side_effect=RuntimeError("native replacement failed"))
    with pytest.raises(RuntimeError, match="不重复"):
        instance.login_passenger()
    driver.execute_script.assert_called_once()
    assert driver.settings["waitForIdleTimeout"] == 10000
    assert ("click", "rl_next") not in driver.actions
    assert not any(action == "input" for action, _ in driver.actions)


def test_native_input_does_not_change_unconfirmed_settings(passenger):
    instance, driver = passenger
    driver.set_page("phone")
    del driver.settings["waitForIdleTimeout"]
    driver.execute_script = Mock()
    with pytest.raises(RuntimeError, match="不重复"):
        instance.login_passenger()
    driver.execute_script.assert_not_called()
    assert ("click", "rl_next") not in driver.actions


def test_idle_restore_error_does_not_hide_original_input_timeout(passenger):
    instance, driver = passenger
    driver.set_page("phone")
    field = Native(driver, list(driver.root)[0])
    original = driver.update_settings

    def update(settings):
        if settings["waitForIdleTimeout"] != 0:
            raise RuntimeError("restore failed")
        original(settings)

    driver.update_settings = update
    driver.execute_script = Mock(side_effect=TimeoutError("input response uncertain"))
    with pytest.warns(RuntimeWarning, match="恢复失败"):
        with pytest.raises(TimeoutError, match="input response uncertain"):
            instance._login_replace_text(field, "12345678")
    driver.execute_script.assert_called_once()


def test_idle_disabled_only_during_input_not_during_later_login_actions(passenger):
    instance, driver = passenger
    assert instance.login_passenger().verified
    assert driver.settings_updates == [{"waitForIdleTimeout": 0}, {"waitForIdleTimeout": 10000},
                                       {"waitForIdleTimeout": 0}, {"waitForIdleTimeout": 10000}]
    assert driver.settings["waitForIdleTimeout"] == 10000


@pytest.mark.parametrize("account", ["****1727", "••••1727", "+852 ****1727"])
def test_explicit_fixed_tail4_mask_matches_known_eleven_digit_account_field(passenger, account):
    instance, driver = passenger
    instance.android_settings["login"].update(mobile="11018251727", mobile_length=11, account_mask_mode="fixed_tail4")
    driver.account = account
    driver.set_page("mine")
    assert instance.login_passenger().verified
    assert driver.kind == "home"
    assert not any(action == "input" for action, _ in driver.actions)


@pytest.mark.parametrize("account", ["****1728", "********", "***1727", "11011727"])
def test_fixed_tail4_mask_cannot_accept_wrong_or_unrecognizable_account(passenger, account):
    instance, driver = passenger
    instance.android_settings["login"].update(mobile="11018251727", mobile_length=11, account_mask_mode="fixed_tail4")
    driver.account = account
    driver.set_page("mine")
    with pytest.raises(RuntimeError, match="账号"):
        instance.login_passenger()
    assert ("click", "主頁") not in driver.actions


def test_fixed_tail4_mask_requires_known_account_resource(passenger):
    instance, driver = passenger
    instance.android_settings["login"].update(mobile="11018251727", mobile_length=11, account_mask_mode="fixed_tail4")
    driver.account = "****1727"
    driver.set_page("mine")
    list(driver.root)[-1].set("resource-id", PACKAGE + ":id/unknown_text")
    with pytest.raises(RuntimeError, match="账号"):
        instance.login_passenger()


def test_fixed_tail4_mask_still_rejects_duplicate_account_fields(passenger):
    instance, driver = passenger
    instance.android_settings["login"].update(mobile="11018251727", mobile_length=11, account_mask_mode="fixed_tail4")
    driver.account = "****1727"
    driver.set_page("mine")
    driver.root.append(node("****1727", "tv_mine_name"))
    with pytest.raises(RuntimeError, match="未唯一"):
        instance.login_passenger()


def test_unknown_mask_mode_stops_before_account_verification(passenger):
    instance, driver = passenger
    instance.android_settings["login"]["account_mask_mode"] = "unverified"
    driver.set_page("mine")
    with pytest.raises(RuntimeError, match="掩码模式"):
        instance.login_passenger()
    assert ("click", "主頁") not in driver.actions


def test_failed_address_search_can_return_via_identified_back_then_verify_login(passenger):
    instance, driver = passenger
    driver.authenticated = True
    driver.set_page("address_search")
    assert instance.login_passenger().verified
    assert driver.kind == "home"
    assert driver.actions.count(("click", "back")) == 1
    assert not any(action == "input" for action, _ in driver.actions)


def test_foreground_unverified_account_is_verified_without_reactivating_app(passenger):
    instance, driver = passenger
    driver.authenticated = True
    driver.set_page("home")
    assert getattr(instance, "_android_login_driver", None) is None
    assert instance.login_passenger().verified
    assert instance._android_login_driver is driver
    instance.client.app_activate.assert_not_called()
    assert ("click", "我的") in driver.actions
    assert ("click", "主頁") in driver.actions
