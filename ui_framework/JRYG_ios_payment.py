"""香港iOS乘客UI共用支付：后付渠道选择、银行卡/OTP、Alipay HK及返回App。

仅操作当前WDA设备，不登录司机接口、不提交司机账单。支付步骤提交不代表
订单到账；调用方仍需核验订单支付状态。预付已打开支付页时不重复确认或返回首页。
订单用例经_ios_complete_payment委托_ios_pay，包车预付通过submitted阶段复用；
公共启动和地址设置不在支付模块内执行，避免付款阶段重新启动或重新下单。
"""

import re
import time

from ui_framework.JRYG_logger import logger
from ui_framework.JRYG_device_guard import DeviceUnlockError


class AlipayPaymentTapUncertainError(RuntimeError):
    """付款点击已发出但响应异常，调用方只能等待结果，不能再次提交。"""


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
        self.retry_safe = False
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

    def _ios_wait_postpaid_control(self, tag, label, *, confirm=False):
        """15秒内只读等待真实可用控件，不把瞬时缺失当失败或用其他渠道代替。"""
        from ui_framework.JRYG_ios_ui_elements import PASSENGER_BUNDLE_ID

        monitor = self._ios_ensure_monitor()
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            page = monitor.inspect(timeout=max(0.1, deadline - time.monotonic()))
            if page.root.get("bundleId") != PASSENGER_BUNDLE_ID:
                monitor.capture("postpaid_not_foreground")
                raise RuntimeError(f"{tag}: 后付费用页不在乘客前台，未发起付款")
            if page.has("支付失敗", "支付失败", "付款失敗", "付款失败", "訂單已取消", "订单已取消"):
                monitor.capture("postpaid_failed_or_cancelled")
                raise RuntimeError(f"{tag}: 当前订单支付失败或取消，停止付款")
            nodes = []
            if not page.has_type("Alert") and page.has("行程結束", "行程结束"):
                for node in page.nodes:
                    if node.get("enabled") != "true":
                        continue
                    values = [node.get(key, "").strip() for key in ("label", "name")]
                    if confirm:
                        matched = node.tag == "XCUIElementTypeButton" and any(
                            re.fullmatch(r"(?:確認支付|确认支付)(?:\s*\d+(?:\.\d+)?\s*HKD)?", value)
                            for value in values)
                    else:
                        matched = node.tag in ("XCUIElementTypeStaticText", "XCUIElementTypeButton") and label in values
                    if matched:
                        nodes.append(node)
            if len(nodes) == 1:
                node = nodes[0]
                predicates = " or ".join(f'@{key}="{node.get(key)}"' for key in ("label", "name") if node.get(key))
                return f'//{node.tag}[@visible="true" and @enabled="true" and ({predicates})]'
            time.sleep(min(0.5, max(0, deadline - time.monotonic())))
        monitor.capture("postpaid_control_timeout")
        raise RuntimeError(f"{tag}: 未找到{label}支付选项或唯一可用控件，禁止选择其他方式或坐标代替")

    def _ios_select_postpaid_channel(self, tag, payment):
        """仅用于后付费用页；渠道及确认支付各单次点击，响应异常不重复提交。"""
        label = "信用卡或扣帳卡" if payment == "bankcard" else "Alipay HK"
        option = self._ios_wait_postpaid_control(tag, label)
        self.client(xpath=option).click()
        logger.info(f"【{tag}】已选择'{label}'")
        confirm = self._ios_wait_postpaid_control(tag, "確認支付", confirm=True)
        self.client(xpath=confirm).click()
        time.sleep(5)

    def _ios_wait_and_click_alipay_pay_now(self, tag, wait_seconds=90):
        """慢网络下有界等待可用付款控件，期间关闭重复弹窗；只发出一次付款点击。

        空白页、控件未出现/禁用、取树失败可继续等；点击响应异常只等待支付结果。
        90秒为加载与弹窗清理的共同预算，不重新下单、刷新页面或使用固定坐标。
        """
        deadline = time.monotonic() + wait_seconds
        next_log = time.monotonic()
        logger.info(f"【{tag}】等待Alipay HK支付页加载，最多{wait_seconds}秒，不重复确认支付")
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            try:
                self._ios_wait_and_close_safari_alert(tag, wait_seconds=remaining)
            except TimeoutError as exc:
                self._ios_screenshot("alipay_page_load_timeout.png")
                raise TimeoutError(f"{tag}: 等待Alipay HK支付页超时（{wait_seconds}秒）：{exc}") from exc
            if time.monotonic() >= deadline:
                break
            try:
                if self._ios_safari_click_by_text("Pay Now", 196, 460, allow_fallback=False):
                    return
            except AlipayPaymentTapUncertainError:
                logger.warning(f"【{tag}】Pay Now点击已发出但响应未确认，仅等待SUCCESS，不重复点击")
                return
            if time.monotonic() >= next_log:
                logger.info(f"【{tag}】Alipay HK支付页加载中，等待Pay Now可用，剩余{max(0, deadline - time.monotonic()):.0f}秒")
                next_log = time.monotonic() + 10
            time.sleep(min(1, max(0, deadline - time.monotonic())))
        self._ios_screenshot("alipay_page_load_timeout.png")
        raise TimeoutError(f"{tag}: 等待Alipay HK Pay Now超时（{wait_seconds}秒），未点击付款")

    def _ios_complete_alipay_payment(self, tag, *, return_home=True):
        """先等待Safari支付页加载并点击一次Pay Now，再确认SUCCESS并返回商户/App。"""
        self._ios_wait_and_click_alipay_pay_now(tag)
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

        弹窗次数不固定；按调用方预算等待，默认12秒，付款前共用90秒加载预算。
        好按钮暂未加载则继续等待；页面读取为空不视为已消失，不盲点付款。
        返回值仅表示是否关闭过弹窗，超过预算仍未稳定消失才抛错。
        """
        alert_kw = ("打不开", "网址无效", "無法連接", "Safari浏览器打不开")
        deadline = time.monotonic() + wait_seconds
        clear_since = None
        closed = False
        next_log = time.monotonic() + 10
        while time.monotonic() < deadline:
            texts = self._ios_get_all_texts(self.client)
            if any(any(k in t for k in alert_kw) for t in texts):
                clear_since = None
                if self._ios_safari_click_by_text("好", 338, 440, exact=True, allow_fallback=False):
                    logger.info(f"【{tag}】已动态坐标点击 Safari 弹窗'好'")
                    closed = True
            elif texts:
                if clear_since is None:
                    clear_since = time.monotonic()
                if time.monotonic() - clear_since >= 3:
                    return closed
            else:
                clear_since = None
            if time.monotonic() >= next_log:
                logger.info(f"【{tag}】等待Safari页面加载或弹窗清理，剩余{max(0, deadline - time.monotonic()):.0f}秒")
                next_log = time.monotonic() + 10
            time.sleep(min(0.5, max(0, deadline - time.monotonic())))
        raise TimeoutError(f"{tag}: Safari页面未加载或弹窗未稳定消失，停止支付")

    def _ios_safari_click_by_text(self, text_kw, fallback_x, fallback_y, exact=False, allow_fallback=True):
        """按实时XML中label和矩形定位点击，exact决定精确或包含匹配。

        Pay Now被可见Safari弹窗遮挡时不点击；付款与好按钮调用禁止坐标兜底。
        禁用兜底时False表示未发出付款点击，可继续定位；付款点击异常抛专用异常。
        allow_fallback启用时可能点击给定坐标但仍返回False，不能据此判断已定位。
        """
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
                except DeviceUnlockError:
                    raise
                except Exception as exc:
                    logger.warning(f"  >> Safari 坐标点击 '{text_kw}' 点击异常: {exc}")
                    if text_kw == "Pay Now":
                        raise AlipayPaymentTapUncertainError("Pay Now点击已发出，禁止重复提交") from exc
                    if not allow_fallback:
                        return False
        except (DeviceUnlockError, AlipayPaymentTapUncertainError):
            raise
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
            time.sleep(1)
        logger.warning(f"【{tag}】未能返回首页（重试 5 次仍非首页）")
        car = getattr(self, "CAR_TYPE", "passenger")
        payment = getattr(self, "PAYMENT", "payment")
        self._ios_screenshot(f"JRYG_{car}_{payment}_back_home_fail.png")
        return False
