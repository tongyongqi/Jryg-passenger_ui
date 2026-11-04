"""Android 公共支付步骤；银行卡、OTP、Alipay 不重复提交。

共用渠道入口来自iOS，设备定位由Android实现；渠道提交不能替代司机同单到账。
"""

import re
import xml.etree.ElementTree as ET

from .JRYG_android_passenger import AndroidPassengerBase
from .JRYG_android_ui import AndroidElement, normalized_tree
from ui_framework import JRYG_ios_ui_elements as E
from ui_framework.JRYG_ios_payment import AlipayPaymentTapUncertainError, HKIOSPaymentMixin
from ui_framework.JRYG_ios_ui_base import iOSBase
from ui_framework.JRYG_logger import logger


class AndroidOTPNotReadyError(RuntimeError):
    """OTP页面切换或键盘重排暂未就绪，只允许只读等待。"""


class AndroidPaymentMixin:
    """适配Android卡表单与支付宝页面，保留共享入口的预付/后付区分。"""

    _ios_pay = HKIOSPaymentMixin._ios_pay

    def _ios_select_postpaid_channel(self, tag, payment):
        """后付费用页选择指定渠道并确认，不适用于预付确认并呼叫。"""
        self._click_text(E.BANKCARD_KEYWORDS if payment == "bankcard" else ["Alipay HK"])
        self._click_text(["確認支付"])

    def _android_cvv_field(self):
        return self._android_labelled_card_field(["CVV"])

    def _android_labelled_card_field(self, placeholders):
        """浮动标签导致hint清空时按同父标签定位，禁止按输入框顺序猜测。"""
        labels = {
            ("CVV",): ("CVV", "CVV 碼", "CVV码", "CVV Code"),
            ("卡號", "卡号", "Card Number"): ("卡號", "卡号", "Card Number"),
            ("月 / 年", "月/年", "MM/YY", "Expiry"): ("有效期", "Expiry", "Expiry Date"),
            ("持卡人姓名", "Name"): ("持卡人姓名", "Name", "Cardholder Name"),
        }.get(tuple(placeholders))
        if labels is None:
            return []
        root = self._android_payment_guard()
        texts = {node.get("text") or node.get("content-desc") or "" for node in root.iter()}
        if not any(keyword in text for keyword in E.BANK_PAGE_KEYWORDS for text in texts):
            raise RuntimeError(f"Android {placeholders[0]}当前不是信用卡表单，禁止填写")
        condition = " or ".join(f"@text='{label}'" for label in labels)
        locator = (
            "//*[@class='android.webkit.WebView']//*[@class='android.widget.TextView' and "
            f"({condition})]"
            "/parent::*[count(*[@class='android.widget.EditText'])=1]/*[@class='android.widget.EditText']"
        )
        fields = self.client.driver.find_elements("xpath", locator)
        if not fields:
            return []
        if (len(fields) != 1 or not fields[0].is_displayed() or not fields[0].is_enabled()
                or fields[0].get_attribute("class") != "android.widget.EditText"):
            raise RuntimeError(f"Android {placeholders[0]}同容器输入框不唯一或不可用，禁止填写")
        return [AndroidElement(self.client, fields[0])]

    def _fill_payment_field(self, placeholders, value):
        """等待唯一匹配字段，清空后填写并收键盘，不输出付款数据。"""
        def locate():
            """按可见输入框label或hint匹配候选占位文案，返回有限列表。"""
            fields = self.client(className="android.widget.EditText").find_elements()
            matched = [field for field in fields if any(
                placeholder.lower() in (field.label + " " + (field.native.get_attribute("hint") or "")).lower()
                for placeholder in placeholders)]
            if not matched:
                return self._android_labelled_card_field(placeholders)
            return matched
        fields = self._wait(locate, f"Android 支付输入框未定位：{placeholders}", timeout=15)
        if len(fields) != 1:
            raise RuntimeError("Android 支付输入框不唯一，禁止填写及提交")
        fields[0].set_text(value)
        self.client.dismiss_keyboard()

    def _ios_fill_bank_card_form(self, tag):
        """依次提交卡表单和OTP，等待离开验证页；True仅表示渠道步骤结束。"""
        self._wait(lambda: any(keyword in text for text in self._ios_get_all_texts(self.client)
                              for keyword in E.BANK_PAGE_KEYWORDS), "Android 银行卡表单未出现", timeout=15)
        for placeholders, value in (
            (["卡號", "卡号", "Card Number"], E.TEST_CARD_NUMBER),
            (["月 / 年", "月/年", "MM/YY", "Expiry"], E.TEST_CARD_EXPIRY),
            (["CVV"], E.TEST_CARD_CVV), (["持卡人姓名", "Name"], E.TEST_CARD_HOLDER),
        ):
            self._fill_payment_field(placeholders, value)
        def pay_ready():
            self._android_payment_guard()
            return self.client(textContains="請支付").exists
        self._wait(pay_ready, "Android卡表单收键盘后支付按钮5秒内未就绪，未提交付款", timeout=5)
        try:
            self._click_text(["請支付"])
        except Exception as exc:
            raise RuntimeError("Android卡支付点击响应未确认，禁止重复提交付款") from exc
        self._ios_handle_otp_page(tag)
        return True

    _ios_otp_value_confirmed = staticmethod(iOSBase._ios_otp_value_confirmed)

    @staticmethod
    def _android_otp_form(root, *, require_button=True):
        """输入阶段允许验证按钮被键盘遮挡，提交阶段必须有唯一可见验证按钮。"""
        def visible(node):
            bounds = re.fullmatch(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]", node.get("bounds", ""))
            if not bounds or node.get("displayed", "true") != "true":
                return False
            x1, y1, x2, y2 = map(int, bounds.groups())
            return x2 > x1 and y2 > y1

        fields = [node for node in root.iter() if "EditText" in node.get("class", node.tag) and visible(node)]
        if not fields:
            raise AndroidOTPNotReadyError("Android OTP输入框暂未展示")
        if len(fields) != 1 or fields[0].get("enabled") != "true":
            raise RuntimeError("Android OTP输入框缺失、不唯一或不可输入")
        parents = {child: parent for parent in root.iter() for child in parent}
        form = parents.get(fields[0])
        titles = {"Sandbox Test Page", "One-Time Password (OTP)"}
        while form is not None:
            texts = {node.get("text") or node.get("content-desc") or "" for node in form.iter()}
            if titles.issubset(texts):
                break
            form = parents.get(form)
        if form is None:
            raise AndroidOTPNotReadyError("Android OTP同表单沙箱标题暂未就绪")
        ancestor = form
        while ancestor is not None and not ancestor.get("class", ancestor.tag).endswith("WebView"):
            ancestor = parents.get(ancestor)
        if ancestor is None:
            raise RuntimeError("Android OTP不在已确认WebView表单内")
        buttons = [node for node in form.iter()
                   if (node.get("text") or node.get("content-desc")) == "Verify & Proceed"]
        if len(buttons) > 1:
            raise RuntimeError("Android OTP同表单验证按钮不唯一")
        if require_button and (not buttons or not visible(buttons[0])):
            raise AndroidOTPNotReadyError("Android OTP同表单验证按钮暂未可见")

        field_path = "//*[@class='android.webkit.WebView']//*[@class='android.widget.EditText' and @hint='e.g. 123456']"
        button_path = (
            "//*[@class='android.webkit.WebView']//*[@class='android.widget.Button' and "
            "(@text='Verify & Proceed' or @content-desc='Verify & Proceed')]"
        )
        return field_path, button_path if buttons else None, "e.g. 123456"

    def _android_payment_guard(self, *, allow_browser=False, tolerate_loading=False):
        """检查支付前台、系统弹窗及失败文案；不会授权、切换应用或点击业务控件。"""
        package = self.client.driver.current_package
        allowed = {self.order_settings["packages"]["passenger_hk"]}
        if allow_browser:
            allowed.update({"com.android.chrome", "com.android.browser"})
        if package not in allowed:
            raise RuntimeError("Android 支付App不在前台，停止，不重复提交")
        try:
            source = self.client.driver.page_source
            root = normalized_tree(source, package)
        except Exception:
            if tolerate_loading:
                return None
            raise RuntimeError("Android 支付控件树读取失败，不重复提交") from None
        if any(node.tag == "XCUIElementTypeAlert" and node.get("visible") == "true" for node in root.iter()):
            raise RuntimeError("Android 支付页面存在弹窗，停止，不重复提交")
        texts = [node.get("label", "") for node in root.iter()
                 if node.get("visible") == "true" and node.tag != "XCUIElementTypeTextField" and node.get("label")]
        failures = ("Payment Failed", "Incorrect OTP", "Authentication Failed",
                    "支付失敗", "支付失败", "驗證失敗", "验证失败")
        if any(re.search(r"\b(?:FAILED|FAILURE|UNSUCCESSFUL|CANCELLED)\b", text, re.I)
               or any(keyword in text for keyword in failures) for text in texts):
            raise RuntimeError("Android UI 支付失败，禁止重复提交")
        return ET.fromstring(source)

    def _android_otp_controls(self, previous=None, *, require_button=False, root=None):
        root = root if root is not None else self._android_payment_guard()
        field_path, button_path, placeholder = self._android_otp_form(
            root, require_button=require_button or previous is None)
        fields = self.client.driver.find_elements("xpath", field_path)
        if not fields:
            raise AndroidOTPNotReadyError("Android OTP真实输入控件暂未就绪")
        if len(fields) != 1 or not fields[0].is_enabled():
            raise RuntimeError("Android OTP真实输入控件不唯一或不可用")
        if not fields[0].is_displayed():
            raise AndroidOTPNotReadyError("Android OTP真实输入控件暂未可见")
        field = fields[0]
        if field.get_attribute("hint") != placeholder:
            raise RuntimeError("Android OTP输入框精确占位标识不符")
        if previous is not None and field.id != previous.id:
            raise RuntimeError("Android OTP输入控件已变化，禁止重新输入或提交")
        button = None
        if require_button:
            buttons = self.client.driver.find_elements("xpath", button_path)
            if (len(buttons) != 1 or not buttons[0].is_displayed() or not buttons[0].is_enabled()
                    or (buttons[0].text or buttons[0].get_attribute("content-desc")) != "Verify & Proceed"):
                raise RuntimeError("Android OTP精确验证按钮不唯一或不可用")
            button = buttons[0]
        return field, button, placeholder

    def _android_wait_otp_ready(self, tag):
        def ready():
            root = self._android_payment_guard(tolerate_loading=True)
            if root is None:
                return False
            try:
                return self._android_otp_controls(root=root)
            except Exception:
                return False
        logger.info("【%s】Android只读等待同表单唯一可用OTP框，最多30秒", tag)
        return self._wait(ready, f"{tag}: Android OTP框30秒内未就绪，未清空、输入或提交", timeout=30)

    def _android_wait_otp_value(self, field, expected, tag, *, clearing=False):
        def confirmed():
            try:
                _, _, placeholder = self._android_otp_controls(field)
                value = field.text
            except AndroidOTPNotReadyError:
                return False
            except Exception as exc:
                raise RuntimeError(f"{tag}: Android OTP目标控件或回读异常，不提交验证") from exc
            if clearing:
                return value in ("", placeholder)
            return self._ios_otp_value_confirmed(value, expected, placeholder)
        self._wait(confirmed, f"{tag}: Android OTP回读未确认，禁止提交验证", timeout=5)

    def _android_wait_same_otp_controls(self, field, tag, *, require_button=False):
        def ready():
            try:
                return self._android_otp_controls(field, require_button=require_button)
            except AndroidOTPNotReadyError:
                return False
        return self._wait(ready, f"{tag}: Android OTP页面重排5秒内未就绪，未继续操作", timeout=5)

    def _ios_handle_otp_page(self, tag):
        """与iOS相同门禁：就绪→同元素清空回读→输入回读→复核→单次提交。"""
        field, _, placeholder = self._android_wait_otp_ready(tag)
        code = E.OTP_DEFAULT_CODE
        if not isinstance(code, str) or not code.strip() or code == placeholder:
            raise RuntimeError("Android OTP配置无效，禁止输入或提交")
        try:
            field.click()
        except Exception as exc:
            raise RuntimeError(f"{tag}: Android OTP聚焦响应未确认，未清空、输入或提交") from exc
        self._android_wait_same_otp_controls(field, tag)
        try:
            field.clear()
        except Exception as exc:
            raise RuntimeError(f"{tag}: Android OTP清空失败，未输入或提交") from exc
        self._android_wait_otp_value(field, None, tag, clearing=True)
        logger.info("【%s】Android OTP清空回读通过（内容不记录）", tag)
        try:
            field.send_keys(code)
        except Exception:
            raise RuntimeError(f"{tag}: Android OTP输入响应未确认，不重复输入或提交") from None
        self._android_wait_otp_value(field, code, tag)
        logger.info("【%s】Android OTP实际值回读一致（内容不记录）", tag)
        try:
            self.client.dismiss_keyboard()
            _, button, _ = self._android_wait_same_otp_controls(field, tag, require_button=True)
            if not self._ios_otp_value_confirmed(field.text, code, placeholder):
                raise RuntimeError("OTP提交前输入已变化")
        except Exception as exc:
            raise RuntimeError(f"{tag}: Android OTP提交前核验失败，禁止提交") from exc
        try:
            button.click()
        except Exception:
            raise RuntimeError(f"{tag}: Android 验证点击已发出但响应未确认，不重复提交") from None
        logger.info("【%s】Android OTP提交前核验通过，单次点击Verify & Proceed", tag)
        self._wait_payment_exit(E.OTP_PAGE_KEYWORDS, require_success=False)

    def _wait_payment_exit(self, page_keywords, require_success):
        """要求显式成功或按参数允许退出原支付页，失败文案始终优先拒绝。"""
        def finished():
            """区分失败、SUCCESS及页面退出；空页面不能当作支付步骤完成。"""
            root = self._android_payment_guard(allow_browser=True, tolerate_loading=True)
            if root is None:
                return False
            texts = [node.get("text") or node.get("content-desc") or "" for node in root.iter()
                     if node.get("displayed", "true") == "true" and "EditText" not in node.get("class", node.tag)]
            texts = [text for text in texts if text.strip()]
            failure = ("FAILED", "FAILURE", "UNSUCCESSFUL", "CANCELLED", "Payment Failed",
                       "Incorrect OTP", "Authentication Failed", "支付失敗", "支付失败", "驗證失敗", "验证失败")
            if any(re.search(r"\b(?:FAILED|FAILURE|UNSUCCESSFUL|CANCELLED)\b", text, re.I)
                   or any(keyword in text for keyword in failure[4:]) for text in texts):
                raise RuntimeError("Android UI 支付失败，禁止重复提交")
            if any(re.search(r"\bSUCCESS\b", text, re.I) or "交易成功" in text for text in texts):
                return True
            if any(keyword in text for text in texts for keyword in ("查詢結果中", "查询结果中")):
                return False
            if any(node.get("resource-id", "").endswith(":id/tip_loading")
                   and node.get("displayed", "true") == "true" for node in root.iter()):
                return False
            return bool(texts) and not require_success and not any(
                keyword in text for text in texts for keyword in page_keywords)
        self._wait(finished, "Android 支付结果未确认，禁止冒充通过", timeout=45)
        self._click_text(["打開", "打开"], exact=True, required=False)

    _ios_wait_and_click_alipay_pay_now = HKIOSPaymentMixin._ios_wait_and_click_alipay_pay_now
    _ios_wait_and_close_safari_alert = HKIOSPaymentMixin._ios_wait_and_close_safari_alert
    _ios_complete_alipay_payment = HKIOSPaymentMixin._ios_complete_alipay_payment

    def _android_open_passenger_dialog(self, label):
        """标题确认返回乘客App，按原生确认按钮ID排除同文案子节点。"""
        driver = self.client.driver
        package = driver.current_package
        if package not in ("com.vivo.browser", "com.android.chrome", "com.android.browser"):
            return None
        root = ET.fromstring(driver.page_source)
        nodes = self._login_visible(root)
        titles = [node for node in nodes if node.get("resource-id", "").split("/")[-1] == "alertTitle"]
        if not titles:
            return None
        texts = [(node.get("text") or node.get("content-desc") or "") for node in titles]
        if len(titles) != 1 or not any(name in texts[0] for name in ("陽光出行", "阳光出行")):
            raise RuntimeError("Android打开应用弹窗目标不符，禁止点击")
        buttons = [node for node in nodes if node.get("resource-id") == "android:id/button1"]
        if (len(buttons) != 1 or buttons[0].get("class", buttons[0].tag) != "android.widget.Button"
                or (buttons[0].get("text") or buttons[0].get("content-desc")) != label
                or buttons[0].get("enabled") != "true"):
            raise RuntimeError("Android返回乘客App的确认按钮缺失、不唯一或不可用")
        elements = self.client(resourceId="android:id/button1").find_elements()
        if (len(elements) != 1 or elements[0].label != label
                or elements[0].native.get_attribute("class") != "android.widget.Button"):
            raise RuntimeError("Android返回App弹窗已改变，禁止点击")
        try:
            elements[0].click()
        except Exception as exc:
            raise RuntimeError("Android返回App点击响应未确认，禁止重复点击或支付") from exc
        logger.info("Android已单次点击返回乘客App的原生确认按钮")
        return True

    def _ios_safari_click_by_text(self, text_kw, fallback_x, fallback_y, exact=False, allow_fallback=True):
        """兼容共享浏览器接口，只点击原生唯一控件，任何场景均不使用iOS兜底坐标。"""
        if text_kw in ("打開", "打开") and exact:
            handled = self._android_open_passenger_dialog(text_kw)
            if handled is not None:
                return handled
        if text_kw == "Pay Now":
            exact = True
        try:
            if text_kw == "Pay Now":
                root = self.client.source(format="xml")
                if "XCUIElementTypeAlert" in root:
                    return False
            elements = self.client(**{"text" if exact else "textContains": text_kw}).find_elements()
        except Exception:
            return False
        if len(elements) > 1:
            raise RuntimeError("Android 支付控件不唯一，禁止点击")
        if not elements:
            return False
        try:
            elements[0].click()
        except Exception as exc:
            if text_kw == "Pay Now":
                raise AlipayPaymentTapUncertainError("Pay Now点击已发出，禁止重复提交") from exc
            return False
        return True


class AndroidPaymentBase(AndroidPaymentMixin, AndroidPassengerBase):
    """独立支付用例同样复用公共设备和乘客操作。"""
