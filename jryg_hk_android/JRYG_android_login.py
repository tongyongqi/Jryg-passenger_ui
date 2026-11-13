"""安卓乘客启动与登录状态机，所有登录入口复用同一流程。"""

from dataclasses import dataclass
import os
import re
import time
import warnings
import xml.etree.ElementTree as ET


@dataclass(frozen=True)
class AndroidLoginResult:
    verified: bool
    page: str
    authenticated_now: bool = False

    def __bool__(self):
        return self.verified


class AndroidLoginMixin:
    PRIVACY_TITLES = ("使用者協議與私隱政策", "使用者隐私协议政策", "使用者隱私協議政策",
                      "用户协议与隐私政策", "用戶協議與私隱政策")
    LOGIN_LABELS = ("登錄/註冊", "登录/注册", "登入/註冊")
    HOME_LABELS = ("主頁", "首頁", "首页")
    PERMISSION_PACKAGES = ("com.android.permissioncontroller", "com.google.android.permissioncontroller")
    PERMISSION_BUTTONS = ("permission_allow_foreground_only_button", "permission_allow_one_time_button",
                          "permission_allow_button", "permission_allow_selected_button")

    @staticmethod
    def _login_visible(root):
        result = []

        def visit(node, parent_visible=True):
            bounds = re.fullmatch(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]", node.get("bounds", ""))
            area = bounds and int(bounds[3]) > int(bounds[1]) and int(bounds[4]) > int(bounds[2])
            visible = parent_visible and node.get("displayed", "true") != "false"
            if visible and area:
                result.append(node)
            for child in node:
                visit(child, visible)

        visit(root)
        return result

    def _login_snapshot(self):
        driver = self.client.driver
        package = driver.current_package
        expected = self.order_settings["packages"]["passenger_hk"]
        if package != expected and package not in self.PERMISSION_PACKAGES:
            raise RuntimeError("安卓登录前台不是乘客App或已识别权限页，停止操作")
        try:
            root = ET.fromstring(driver.page_source)
        except Exception as exc:
            from selenium.common.exceptions import TimeoutException, WebDriverException
            from urllib3.exceptions import MaxRetryError, ReadTimeoutError
            transport_timeout = isinstance(exc, (TimeoutException, MaxRetryError, ReadTimeoutError, TimeoutError))
            proxy_timeout = isinstance(exc, WebDriverException) and any(
                text in str(exc).lower() for text in ("timeout of", "timed out", "read timeout"))
            if not transport_timeout and not proxy_timeout:
                raise
            self._android_login_driver = None
            self._android_login_mobile = None
            raise RuntimeError(
                f"安卓乘客页面树读取超时，前台包={package}；"
                "Appium/UiAutomator2未及时返回页面，未重复读页、发送验证码、取消或提交订单") from exc
        return self._login_classify(root, package), root

    def _login_classify(self, root, package, activity=""):
        nodes = self._login_visible(root)
        texts = {node.get("text") or node.get("content-desc") or "" for node in nodes}
        ids = {node.get("resource-id", "").split("/")[-1] for node in nodes}
        if any(node.get("resource-id", "").split(":")[0] in self.PERMISSION_PACKAGES
               and node.get("resource-id", "").split("/")[-1] in self.PERMISSION_BUTTONS for node in nodes):
            return "permission"
        if package in self.PERMISSION_PACKAGES:
            return "permission_unknown"
        if "tv_button_agree" in ids and texts.intersection(self.PRIVACY_TITLES):
            return "privacy"
        if {"tv_title", "tv_confirm"}.issubset(ids) and "去授權" in texts and any(
                "我們需要獲取以下權限" in text or "我们需要获取以下权限" in text for text in texts):
            return "permission_intro"
        if "et_search" in ids and "back" in ids:
            return "address_search"
        if "phone_num" in ids:
            return "phone"
        if "verify_code" in ids or "VerificationCode" in activity:
            return "code"
        status = [node for node in nodes if node.get("resource-id", "").split("/")[-1] == "tv_status_name"
                  and (node.get("text") or node.get("content-desc") or "").strip().endswith(("行程結束", "行程结束"))]
        orders = {value for node in nodes if node.get("resource-id", "").split("/")[-1] == "tv_order_no"
                  for value in re.findall(r"\b[A-Z0-9]{12}\b", node.get("text") or node.get("content-desc") or "")
                  if any(char.isdigit() for char in value) and any(char.isalpha() for char in value)}
        pay = [node for node in nodes if node.get("resource-id", "").split("/")[-1] == "tv_pay"
               and (node.get("text") or node.get("content-desc") or "").strip().startswith(("確認支付", "确认支付"))]
        backs = [node for node in nodes if node.get("resource-id", "").split("/")[-1] == "iv_arrow_back"]
        cancelled = texts.intersection({"取消訂單", "取消订单"})
        if len(status) == len(orders) == len(pay) == len(backs) == 1 and not cancelled:
            return "terminal_unpaid"
        if any(any(keyword in text for keyword in ("確認支付", "确认支付", "費用明細", "费用明细",
                                                   "取消訂單", "取消订单", "未完成訂單", "未完成订单",
                                                   "Verify & Proceed", "Pay Now")) for text in texts):
            return "business"
        if ("我的行程" in texts or "我的行程" in " ".join(texts)) and any(
                label in texts for label in ("聯繫客服", "联系客服", "《私隱政策》", "私隱政策")):
            return "mine_unlogged" if texts.intersection(self.LOGIN_LABELS) else "mine"
        if self._login_ad_close(root) is not None:
            return "advertisement"
        if any("ViewPager" in node.get("class", "") for node in nodes):
            return "obstruction"
        if texts.intersection(("Got It", "立即體驗", "立即体验")):
            return "guide"
        if texts.intersection(("確認呼叫", "确认呼叫")) and (
                "tv_start_address" in ids or {"rv_car_list", "btn_call", "iv_arrow_back"}.issubset(ids)):
            return "route"
        if "tv_start_address" in ids or ("我的" in texts and texts.intersection(self.HOME_LABELS)):
            return "home"
        if texts.intersection(self.LOGIN_LABELS):
            return "mine_unlogged"
        return "unknown"

    def _login_ad_close(self, root):
        nodes = self._login_visible(root)
        identified = [node for node in nodes if node.get("resource-id", "").split("/")[-1]
                      in ("iv_cancel", "iv_close") and node.get("clickable") == "true"]
        pagers = [node for node in nodes if "ViewPager" in node.get("class", "")]
        if len(identified) == 1 and pagers:
            return identified[0]
        if len(pagers) != 1:
            return None
        parents = {child: parent for parent in root.iter() for child in parent}
        container = parents.get(pagers[0])
        if container is None:
            return None
        candidates = [node for node in self._login_visible(container)
                      if node.get("class", "").endswith("ImageView") and node.get("clickable") == "true"
                      and not node.get("text") and not node.get("content-desc")]
        if len(candidates) != 1 or candidates[0] in list(pagers[0].iter()):
            return None
        pager_bounds = list(map(int, re.findall(r"-?\d+", pagers[0].get("bounds", ""))))
        close_bounds = list(map(int, re.findall(r"-?\d+", candidates[0].get("bounds", ""))))
        if len(pager_bounds) != 4 or len(close_bounds) != 4 or close_bounds[1] < pager_bounds[3]:
            return None
        return candidates[0]

    def _login_native(self, root, node):
        parents = {child: parent for parent in root.iter() for child in parent}
        parts = []
        target = node
        while node is not root:
            parent = parents[node]
            parts.append(f"/*[{list(parent).index(node) + 1}]")
            node = parent
        path = "/*" + "".join(reversed(parts))
        matches = self.client.driver.find_elements("xpath", path)
        if len(matches) != 1 or not matches[0].is_displayed() or not matches[0].is_enabled():
            raise RuntimeError("安卓登录控件缺失、不唯一或不可操作")
        native = matches[0]
        for key in ("resource-id", "class", "text", "content-desc"):
            if target.get(key) and native.get_attribute(key) != target.get(key):
                raise RuntimeError("安卓登录页面已变化，禁止点击旧控件")
        return native

    def _login_find(self, root, *, ids=(), texts=()):
        package = self.order_settings["packages"]["passenger_hk"]
        nodes = [node for node in self._login_visible(root) if node.get("enabled", "true") != "false"]
        matches = [node for node in nodes if node.get("resource-id") in {package + ":id/" + name for name in ids}]
        if not matches:
            matches = [node for node in nodes if (node.get("text") or node.get("content-desc")) in texts]
        if len(matches) != 1:
            raise RuntimeError("安卓登录所需控件未唯一识别，停止自动流转")
        return matches[0]

    def _login_startup_action(self, page, root):
        if page == "privacy":
            self._login_native(root, self._login_find(root, ids=("tv_button_agree",))).click()
        elif page == "permission_intro":
            self._login_native(root, self._login_find(root, ids=("tv_confirm",), texts=("去授權",))).click()
        elif page == "permission":
            nodes = self._login_visible(root)
            for name in self.PERMISSION_BUTTONS:
                matches = [node for node in nodes if node.get("resource-id", "").split(":")[0]
                           in self.PERMISSION_PACKAGES and node.get("resource-id", "").split("/")[-1] == name]
                if len(matches) == 1:
                    self._login_native(root, matches[0]).click()
                    return
            raise RuntimeError("安卓系统权限允许按钮无法唯一识别")
        elif page == "guide":
            self._login_native(root, self._login_find(root, texts=("Got It", "立即體驗", "立即体验"))).click()
        elif page == "advertisement":
            self._login_native(root, self._login_ad_close(root)).click()
        else:
            raise RuntimeError("安卓启动遮挡无法识别，未盲点或返回")

    def _login_activate_app(self):
        package = self.order_settings["packages"]["passenger_hk"]
        driver = self.client.driver
        config = self.order_settings.get("login") or {}
        timeout = config.get("launch_timeout", 30)
        if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0:
            raise ValueError("安卓乘客启动launch_timeout必须为正数")
        if driver.current_package == package:
            return
        self.client.app_activate(package)
        deadline = time.monotonic() + timeout
        foreground = None
        while time.monotonic() < deadline:
            foreground = driver.current_package
            if foreground == package or foreground in self.PERMISSION_PACKAGES:
                return
            time.sleep(0.5)
        raise TimeoutError(
            f"安卓乘客App在{timeout}秒内未切到前台，当前包={foreground}；"
            "未读取其他App页面、点击控件或发送验证码")

    def prepare_passenger_app(self, tag="passenger", *, launch=True, timeout=30):
        if launch:
            self._login_activate_app()
        deadline = time.monotonic() + timeout
        acted = set()
        while time.monotonic() < deadline:
            page, root = self._login_snapshot()
            if page in ("privacy", "permission_intro", "permission", "guide", "advertisement"):
                key = (page, ET.tostring(root))
                if key not in acted:
                    acted.add(key)
                    self._login_startup_action(page, root)
            elif page in ("permission_unknown", "obstruction"):
                raise RuntimeError("安卓启动存在未识别权限或遮挡，停止自动流转")
            elif page != "unknown":
                return page
            time.sleep(0.5)
        raise TimeoutError("安卓启动页面未就绪，未执行登录或订单操作")

    def _login_credentials(self):
        config = self.order_settings.get("login") or {}
        mobile = os.environ.get("HK_PASSENGER_MOBILE") or config.get("mobile") or self.LOGIN_PHONE
        code = os.environ.get("HK_PASSENGER_UI_CODE") or config.get("code") or self.LOGIN_CODE
        if config.get("country_code", "852") != "852":
            raise RuntimeError("当前安卓香港登录仅支持+852区号，未自动切换区号")
        length = config.get("mobile_length", 8)
        if isinstance(length, bool) or not isinstance(length, int) or length not in (8, 11):
            raise RuntimeError("香港手机号长度必须为8位，测试账号需显式配置为11位")
        if not isinstance(mobile, str) or not re.fullmatch(rf"[0-9]{{{length}}}", mobile):
            raise RuntimeError(f"香港乘客登录手机号必须是{length}位数字，未截断号码")
        if not isinstance(code, str) or not re.fullmatch(r"\d{6}", code):
            raise RuntimeError("香港乘客登录验证码必须是6位数字")
        return mobile, code

    def _login_replace_text(self, field, value):
        """只向已确认原生输入框整段写入一次，临时关闭空闲等待并恢复。"""
        driver = self.client.driver
        if driver.current_package != self.order_settings["packages"]["passenger_hk"]:
            raise RuntimeError("安卓登录输入前台已变化，未输入")
        if "EditText" not in field.get_attribute("class"):
            raise RuntimeError("安卓登录目标不是原生输入框，未输入")
        if re.sub(r"\s+", "", field.text or "") == value:
            return
        settings = driver.get_settings()
        if "waitForIdleTimeout" not in settings:
            raise RuntimeError("UiAutomator2空闲等待设置未确认，未输入")
        original = settings["waitForIdleTimeout"]
        try:
            driver.update_settings({"waitForIdleTimeout": 0})
            driver.execute_script("mobile: replaceElementValue", {"elementId": field.id, "text": value})
        finally:
            try:
                driver.update_settings({"waitForIdleTimeout": original})
            except Exception:
                warnings.warn("安卓登录输入后空闲等待设置恢复失败，请检查Appium会话", RuntimeWarning)

    def _login_submit_phone(self, root):
        mobile, _ = self._login_credentials()
        field = self._login_native(root, self._login_find(root, ids=("phone_num",)))
        self._login_replace_text(field, mobile)
        if re.sub(r"\s+", "", field.text or "") != mobile:
            raise RuntimeError("安卓手机号回读未确认，未取得验证码")
        self.client.dismiss_keyboard()
        _, root = self._login_snapshot()
        agree = self._login_native(root, self._login_find(root, ids=("agree_img",)))
        if agree.get_attribute("checked") != "true" and agree.get_attribute("selected") != "true":
            agree.click()
        _, root = self._login_snapshot()
        button = self._login_find(root, ids=("rl_next",), texts=("取得驗證碼", "获取验证码", "取得驗証碼"))
        self._login_native(root, button).click()

    def _login_submit_code(self, root):
        _, code = self._login_credentials()
        nodes = self._login_visible(root)
        region = [node for node in nodes if node.get("resource-id") ==
                  self.order_settings["packages"]["passenger_hk"] + ":id/verify_code"]
        fields = [node for node in nodes if "EditText" in node.get("class", "")]
        if region:
            if len(region) != 1:
                raise RuntimeError("安卓验证码输入区域不唯一")
            fields = [node for node in fields if node in list(region[0].iter())]
        if len(fields) == 1:
            field = self._login_native(root, fields[0])
            self._login_replace_text(field, code)
        elif not fields and len(region) == 1:
            self._login_native(root, region[0]).click()
            for digit in code:
                self.client.driver.press_keycode(7 + int(digit))
        else:
            raise RuntimeError("安卓验证码输入框无法唯一定位，未输入验证码")

    def _login_verify_account(self, root):
        mobile, _ = self._login_credentials()
        mode = (self.order_settings.get("login") or {}).get("account_mask_mode", "length_preserving")
        if mode not in ("length_preserving", "fixed_tail4"):
            raise RuntimeError("安卓账号掩码模式未确认，未继续登录流程")
        account_id = self.order_settings["packages"]["passenger_hk"] + ":id/tv_mine_name"
        values = []
        for node in self._login_visible(root):
            text = (node.get("text") or node.get("content-desc") or "").strip()
            text = re.sub(r"^\+852\s*", "", text)
            text = re.sub(r"\s+", "", text)
            if re.fullmatch(rf"[0-9*•]{{{len(mobile)}}}", text):
                values.append(text)
            elif (mode == "fixed_tail4" and len(mobile) == 11
                  and node.get("resource-id") == account_id and re.fullmatch(r"[*•]{4}[0-9]{4}", text)):
                values.append("*" * (len(mobile) - 4) + text[-4:])
        if len(values) != 1 or not any(char.isdigit() for char in values[0]):
            raise RuntimeError("安卓个人中心账号未唯一识别，不能认定已登录")
        if any(actual not in ("*", "•", expected) for actual, expected in zip(values[0], mobile)):
            raise RuntimeError("安卓个人中心不是指定测试账号，未切换账号或继续订单")

    def login_passenger(self, tag="passenger", *, launch=True, target="home", timeout=None):
        """打开App并按当前页流转，成功核验账号后回首页或保留当前业务页。"""
        if target not in ("home", "current"):
            raise ValueError("安卓登录target只能是home或current")
        config = self.order_settings.get("login") or {}
        budget = config.get("timeout", 90) if timeout is None else timeout
        if not isinstance(budget, (int, float)) or isinstance(budget, bool) or budget <= 0:
            raise ValueError("安卓登录timeout必须为正数")
        if launch:
            self._login_activate_app()
        deadline = time.monotonic() + budget
        verified = getattr(self, "_android_login_driver", None) is self.client.driver
        authenticated = False
        submitted = set()
        acted = set()
        entry_page = None
        while time.monotonic() < deadline:
            page, root = self._login_snapshot()
            if entry_page is None and page not in ("privacy", "permission_intro", "permission", "guide", "advertisement", "unknown"):
                entry_page = page
            if page in ("phone", "code", "mine_unlogged"):
                verified = False
                self._android_login_driver = None
            if page in ("home", "route", "business", "terminal_unpaid") and verified:
                if target == "current" or page == "home":
                    return AndroidLoginResult(True, page, authenticated)
            if page == "terminal_unpaid" and target == "home":
                if ("terminal_unpaid_back",) in acted:
                    raise RuntimeError("安卓遗留未支付页单次返回未确认，未重复返回、取消或支付")
                acted.add(("terminal_unpaid_back",))
                back = self._login_find(root, ids=("iv_arrow_back",))
                self._login_native(root, back).click()
                time.sleep(0.5)
                continue
            if page == "route" and target == "home":
                ids = {node.get("resource-id", "").split("/")[-1] for node in self._login_visible(root)}
                if {"rv_car_list", "btn_call", "iv_arrow_back"}.issubset(ids):
                    if ("native_estimate_back",) in acted:
                        raise RuntimeError("安卓车型估价页单次返回未确认，未重复返回或提交呼叫")
                    acted.add(("native_estimate_back",))
                    self.client.driver.back()
                    time.sleep(0.5)
                    continue
            if page in ("business", "route", "terminal_unpaid"):
                raise RuntimeError("安卓当前为订单或路线页且无法安全完成登录核验，未取消、重新呼叫或支付")
            if page in ("obstruction", "permission_unknown"):
                raise RuntimeError("安卓登录存在未识别遮挡，停止自动流转")
            key = (page, authenticated, ET.tostring(root))
            if page == "unknown" or key in acted:
                time.sleep(0.5)
                continue
            acted.add(key)
            if page in ("privacy", "permission_intro", "permission", "guide", "advertisement"):
                self._login_startup_action(page, root)
            elif page == "address_search":
                self._login_native(root, self._login_find(root, ids=("back",))).click()
            elif page == "home":
                self._login_native(root, self._login_find(root, texts=("我的",))).click()
            elif page == "mine_unlogged":
                self._login_native(root, self._login_find(root, texts=self.LOGIN_LABELS)).click()
            elif page == "mine":
                self._login_verify_account(root)
                verified = True
                self._android_login_driver = self.client.driver
                if target == "current" and entry_page == "mine":
                    return AndroidLoginResult(True, page, authenticated)
                self._login_native(root, self._login_find(root, texts=self.HOME_LABELS)).click()
            elif page in ("phone", "code"):
                if page not in submitted:
                    submitted.add(page)
                    try:
                        if page == "phone":
                            self._login_submit_phone(root)
                        else:
                            self._login_submit_code(root)
                            authenticated = True
                    except Exception as exc:
                        raise RuntimeError("安卓登录输入或提交未确认，不重复发送验证码或重复输入") from exc
            time.sleep(0.5)
        raise TimeoutError(f"安卓登录{budget}秒内未完成账号及目标页面核验，未继续订单流程")

    def ensure_passenger_login(self, tag="passenger"):
        return bool(self.login_passenger(tag))

    def _android_is_login_page(self):
        """检测当前是否在乘客登录页；支付渠道返回后短暂等待乘客App恢复前台。"""
        expected = self.order_settings["packages"]["passenger_hk"]
        for _ in range(5):
            try:
                return self._login_snapshot()[0] in ("phone", "code")
            except RuntimeError:
                package = self.client.driver.current_package
                if package != expected and package not in self.PERMISSION_PACKAGES:
                    self.client.app_activate(expected)
                    time.sleep(1)
                    continue
                raise
        return self._login_snapshot()[0] in ("phone", "code")

    def _android_ui_login(self, tag=""):
        return bool(self.login_passenger(tag, launch=False, target="current"))

    def _android_ensure_logged_in(self, tag=""):
        return bool(self.login_passenger(tag, launch=False, target="current"))

    def _dismiss_passenger_popups(self, max_rounds=3, wait_after=1):
        return self.prepare_passenger_app(launch=False, timeout=max(10, max_rounds * (wait_after + 1)))

    def _android_prepare_passenger_app(self, tag, launch_wait=3, alert_wait=1):
        return self.prepare_passenger_app(tag, timeout=max(30, launch_wait + alert_wait))
