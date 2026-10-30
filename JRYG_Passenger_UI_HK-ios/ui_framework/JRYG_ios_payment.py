"""香港iOS乘客UI共用支付：后付渠道选择、银行卡/OTP、Alipay HK及返回App。

仅操作当前WDA设备，不登录司机接口、不提交司机账单。支付步骤提交不代表
订单到账；调用方仍需核验订单支付状态。预付已打开支付页时不重复确认或返回首页。
订单用例经_ios_complete_payment委托_ios_pay，包车预付通过submitted阶段复用；
公共启动和地址设置不在支付模块内执行，避免付款阶段重新启动或重新下单。
"""

import re
import time

from ui_framework.JRYG_logger import logger


class HKIOSPaymentMixin:
    """由iOSBase继承，所有香港iOS用例共享同一支付入口。"""

    def _ios_pay(self, tag, payment, *, stage="postpaid"):
        """共用入口：payment 为 bankcard/alipay；stage 为 postpaid/submitted。

        postpaid：当前费用页选择渠道、确认支付、完成渠道步骤、返回首页。
        submitted：调用方已确认预付并打开渠道页，只执行渠道步骤，不重复确认、
        不返回首页，保留原银行卡表单是否出现的返回值供下单流程判断。
        不读取或改写下单PAYMENT，不操作司机页面，最终到账由订单调用方核验。
        """
        if payment not in ("bankcard", "alipay"):
            raise ValueError(f"{tag}: 共用支付只支持bankcard或alipay")
        if stage not in ("postpaid", "submitted"):
            raise ValueError(f"{tag}: 支付阶段只能为postpaid或submitted")
        if stage == "postpaid":
            self._ios_select_postpaid_channel(tag, payment)
        if payment == "bankcard":
            submitted = self._ios_fill_bank_card_form(tag)
            if stage == "submitted":
                return submitted
            if not submitted:
                raise RuntimeError(f"{tag}: 银行卡表单未提交，停止流程，不记录支付成功")
            logger.info(f"【{tag}】银行卡及3DS步骤已提交，最终到账待司机同订单核验")
            self._ios_back_to_home(tag)
        elif stage == "submitted":
            self._ios_complete_alipay_payment(tag, return_home=False)
        else:
            self._ios_complete_alipay_payment(tag)
        return True

    def _ios_select_postpaid_channel(self, tag, payment):
        """仅用于后付费用页，不能替代下单可选服务或预付确认支付并呼叫。"""
        label = "信用卡或扣帳卡" if payment == "bankcard" else "Alipay HK"
        texts = self._ios_get_all_texts(self.client)
        if not any(label in text for text in texts):
            raise RuntimeError(f"{tag}: 未找到{label}支付选项，禁止选择其他方式代替")
        pay_opt = self.client(textContains=label)
        exists = pay_opt.exists
        if not (exists() if callable(exists) else exists):
            pattern = ".*信用卡.*|.*扣帳卡.*" if payment == "bankcard" else ".*Alipay HK.*"
            pay_opt = self.poco(textMatches=pattern)
            exists = pay_opt.exists
        if not (exists() if callable(exists) else exists):
            raise RuntimeError(f"{tag}: {label}支付控件不可用，停止支付")
        pay_opt.click()
        logger.info(f"【{tag}】已选择'{label}'")
        time.sleep(2)
        pay_btn = self.poco(textMatches=".*確認支付.*|.*确认支付.*")
        if pay_btn.exists():
            pay_btn.click()
        else:
            pay_wda = self.client(textContains="確認支付")
            if pay_wda.exists:
                pay_wda.click()
            else:
                self.client.click(196, 789)
        time.sleep(5)

    def _ios_complete_alipay_payment(self, tag, *, return_home=True):
        """原Alipay HK流程：Safari Pay Now → SUCCESS → 返回商户/App。"""
        self._ios_wait_and_close_safari_alert(tag)
        if not self._ios_safari_click_by_text("Pay Now", 196, 460, allow_fallback=False):
            raise RuntimeError(f"{tag}: 未定位到Alipay HK Pay Now，停止支付，不重复点击")
        time.sleep(5)
        for _ in range(15):
            texts = self._ios_get_all_texts(self.client)
            if any(re.search(r"\b(?:FAILED|FAILURE|UNSUCCESSFUL|CANCELLED)\b", t, re.IGNORECASE)
                   or any(kw in t for kw in ("支付失敗", "支付失败", "付款失敗", "付款失败", "支付已取消")) for t in texts):
                self._ios_screenshot("alipay_payment_failed.png")
                raise RuntimeError(f"{tag}: Alipay HK支付失败或取消，停止流程")
            if any(re.search(r"\bSUCCESS\b", t, re.IGNORECASE) for t in texts):
                logger.info(f"【{tag}】Alipay HK页面确认SUCCESS，待司机同订单到账核验")
                break
            self._ios_wait_and_close_safari_alert(tag)
            time.sleep(2)
        else:
            self._ios_screenshot("alipay_payment_unconfirmed.png")
            raise TimeoutError(f"{tag}: Alipay HK支付未确认SUCCESS，不返回首页冒充成功")
        time.sleep(2)
        for _ in range(3):
            texts = self._ios_get_all_texts(self.client)
            if not any("打開" in t or "打开" in t for t in texts):
                break
            open_label = "打開" if any("打開" in t for t in texts) else "打开"
            self._ios_safari_click_by_text(open_label, 336, 429, exact=True)
            logger.info(f"【{tag}】已点击'{open_label}'返回 App")
            time.sleep(3)
        texts = self._ios_get_all_texts(self.client)
        if any("Return to Merchant" in t for t in texts):
            self._ios_safari_click_by_text("Return to Merchant", 196, 385)
            time.sleep(3)
            texts = self._ios_get_all_texts(self.client)
            if any("打開" in t or "打开" in t for t in texts):
                open_label = "打開" if any("打開" in t for t in texts) else "打开"
                self._ios_safari_click_by_text(open_label, 336, 429, exact=True)
                time.sleep(5)
        if return_home:
            self._ios_back_to_home(tag)

    def _ios_wait_and_close_safari_alert(self, tag, wait_seconds=12):
        """每次识别网址无效弹窗后动态点好，连续3秒无弹窗才允许继续支付。

        弹窗次数不固定；12秒内未稳定消失或好按钮定位失败则停止，不盲点付款。
        页面读取失败也不视为弹窗已消失。返回值仅表示是否关闭过弹窗。
        """
        alert_kw = ("打不开", "网址无效", "無法連接", "Safari浏览器打不开")
        deadline = time.monotonic() + wait_seconds
        clear_since = None
        closed = False
        while time.monotonic() < deadline:
            texts = self._ios_get_all_texts(self.client)
            if any(any(k in t for k in alert_kw) for t in texts):
                clear_since = None
                if not self._ios_safari_click_by_text("好", 338, 440, exact=True, allow_fallback=False):
                    raise RuntimeError(f"{tag}: Safari弹窗好按钮未定位，停止支付")
                logger.info(f"【{tag}】已动态坐标点击 Safari 弹窗'好'")
                closed = True
            elif texts:
                if clear_since is None:
                    clear_since = time.monotonic()
                if time.monotonic() - clear_since >= 3:
                    return closed
            else:
                clear_since = None
            time.sleep(0.5)
        raise TimeoutError(f"{tag}: Safari弹窗未稳定消失，停止支付")

    def _ios_safari_click_by_text(self, text_kw, fallback_x, fallback_y, exact=False, allow_fallback=True):
        """Safari按可见元素坐标点击；付款禁用兜底，返回False时禁止外层重复点击。"""
        try:
            src = self._ios_get_source_xml()
            if text_kw == "Pay Now" and any(
                'name="SFDialogView"' in match.group(0) and 'visible="false"' not in match.group(0)
                for match in re.finditer(r'<XCUIElementType\w+[^>]*>', src)
            ):
                return False
            for match in re.finditer(r'<XCUIElementType\w+[^>]*>', src):
                node = match.group(0)
                label = re.search(r'label="([^"]*)"', node)
                if not label:
                    continue
                if (label.group(1) != text_kw) if exact else (text_kw not in label.group(1)):
                    continue
                visible = re.search(r'visible="(\w+)"', node)
                if visible and visible.group(1) != "true":
                    continue
                coordinates = [re.search(r'\b' + key + r'="(\d+)"', node)
                               for key in ("x", "y", "width", "height")]
                if not all(coordinates):
                    continue
                x, y, width, height = [int(value.group(1)) for value in coordinates]
                if width <= 0 or height <= 0 or 'enabled="false"' in node:
                    continue
                try:
                    self.client.click(x + width // 2, y + height // 2)
                    logger.info(f"  >> Safari 坐标点击 '{text_kw}'")
                    return True
                except Exception as exc:
                    logger.warning(f"  >> Safari 坐标点击 '{text_kw}' 点击异常: {exc}")
                    if not allow_fallback:
                        return False
        except Exception as exc:
            logger.warning(f"  >> Safari 坐标点击 '{text_kw}' 异常: {exc}")
        if not allow_fallback:
            return False
        try:
            self.client.click(fallback_x, fallback_y)
        except Exception as exc:
            logger.warning(f"  >> Safari 兜底坐标点击失败: {exc}")
        return False

    def _ios_back_to_home(self, tag):
        """复用原返回首页步骤，不修改司机状态或再次提交付款。"""
        for _ in range(5):
            texts = self._ios_get_all_texts(self.client)
            if any("想去哪裡" in t or "主頁" in t for t in texts):
                logger.info(f"【{tag}】已返回首页")
                return True
            back_wda = self.client(xpath='//XCUIElementTypeImage[contains(@name,"navi_arrow_left")]')
            if back_wda.exists:
                back_wda.click()
            else:
                self.client.click(34, 82)
            time.sleep(3)
        logger.warning(f"【{tag}】未能返回首页（重试 5 次仍非首页）")
        car = getattr(self, "CAR_TYPE", "passenger")
        payment = getattr(self, "PAYMENT", "payment")
        self._ios_screenshot(f"JRYG_{car}_{payment}_back_home_fail.png")
        return False
