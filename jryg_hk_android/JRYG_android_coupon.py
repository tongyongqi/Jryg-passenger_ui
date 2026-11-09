"""Android 优惠券公共动作；规则断言留在用例，指定券不以其他券兜底。"""

import re
import time
import xml.etree.ElementTree as ET

from .JRYG_android_passenger import AndroidPassengerBase
from . import JRYG_ios_ui_elements as E

TARGET_PATTERN = ".*折扣最高折扣.*|.*111.*|.*老人折扣.*|.*100元.*|.*100.*"
ALL_COUPONS_PATTERN = TARGET_PATTERN + "|.*元.*|.*HKD.*|.*折.*"


class AndroidCouponMixin:
    """提供优惠券选择、状态回读及收银台往返动作，规则断言由场景负责。"""

    def open_coupon_list(self):
        """确认乘客在前台后打开优惠券列表，未找到入口则停止。"""
        self._assert_passenger_foreground()
        self._click_text(["優惠券", "优惠券", "抵扣"])
        time.sleep(3)

    def select_coupons(self, *, policy="all", target_keywords=None):
        """all选择匹配券，target按候选精确文案选择唯一券；去重后返回所选文案。

        指定券缺失或重复时直接失败，不替换成其他券；返回值供后续保留状态核验。
        """
        if policy not in ("all", "target"):
            raise ValueError("优惠券选择策略只能为 all 或 target")
        if policy == "target" and not target_keywords:
            raise ValueError("指定优惠券必须提供目标文案")
        self.open_coupon_list()
        if policy == "target":
            candidates = []
            for keyword in target_keywords:
                matches = self.client(text=keyword).find_elements()
                if matches:
                    candidates = matches
                    break
            if len(candidates) != 1:
                raise RuntimeError("指定优惠券缺失或不唯一，禁止以其他券替代")
        else:
            candidates = self.client(textMatches=ALL_COUPONS_PATTERN).find_elements()
            if not candidates:
                raise RuntimeError("优惠券列表没有匹配券，停止而非记录已选择")
        labels = []
        seen = set()
        for candidate in candidates:
            identity = candidate.native.id
            if identity in seen:
                continue
            seen.add(identity)
            labels.append(candidate.label)
            candidate.click()
            time.sleep(1.5)
        self.confirm_coupon_selection()
        return tuple(labels)

    def confirm_coupon_selection(self):
        """通过精确确认文案提交列表选择，不把点击当作保留状态核验。"""
        self._click_text(["確定", "确定", "確認", "确认", "使用"], exact=True)
        time.sleep(3)

    def selected_coupons_retained(self, labels):
        """核验每张目标券唯一且容器暴露勾选状态，存在但未选中不能算保留。

        最多向上查四层，并避免跨越其他券容器；未暴露状态抛错，未保留返回False。
        """
        if not labels:
            raise ValueError("缺少先前选择的优惠券标识，不能核验保留状态")
        self._assert_passenger_foreground()
        root = ET.fromstring(self.client.driver.page_source)
        parents = {child: parent for parent in root.iter() for child in parent}
        for label in set(labels):
            matches = [node for node in root.iter() if node.get("text") == label
                       and node.get("displayed", "true") != "false"]
            if len(matches) != 1:
                return False
            container = matches[0]
            recognized = False
            selected = False
            for _ in range(4):
                if container is None:
                    break
                other_coupons = {node.get("text") for node in container.iter()
                                 if node.get("text") and re.fullmatch(ALL_COUPONS_PATTERN, node.get("text"))}
                if len(other_coupons) > 1:
                    break
                states = [node for node in container.iter() if node.get("displayed", "true") != "false"
                          and (node.get("checkable") == "true" or node.get("selected") == "true")]
                if states:
                    recognized = True
                    selected = any(node.get("checked") == "true" or node.get("selected") == "true" for node in states)
                    break
                container = parents.get(container)
            if not recognized:
                raise RuntimeError("优惠券选择状态未暴露，不能把列表中存在当作已保留")
            if not selected:
                return False
        return True

    def return_to_quote(self):
        """从列表尝试返回/确认文案，缺少按钮则系统返回；此处未断言估价页。"""
        if not self._click_text(["返回", "確定", "确定", "確認", "确认", "使用"], exact=True, required=False):
            self.client.back()
        time.sleep(3)

    def resume_passenger_app(self, *, background_wait=5):
        """将乘客App退后台再恢复并确认前台，优惠券是否保留由调用方回读。"""
        self.client.home()
        time.sleep(background_wait)
        self.client.app_activate(E.PASSENGER_BUNDLE_ID)
        time.sleep(6)
        self._assert_passenger_foreground()

    def open_prepaid_cashier(self, tag="coupon"):
        """确认呼叫后等待真实预付收银台，不在此方法确认支付并呼叫。"""
        self._ios_click_confirm_call(tag)
        self._wait(lambda: any(keyword in text for text in self._ios_get_all_texts(self.client)
                              for keyword in E.CASHIER_PAGE_KEYWORDS), "未进入真实预付收银台")

    def close_prepaid_cashier(self):
        """系统返回关闭收银台，须出现确认呼叫文案才能认为回到估价页。"""
        self.client.back()
        self._wait(lambda: self.client(textContains="確認呼叫").exists, "关闭收银台后未返回估价页")


class AndroidCouponBase(AndroidCouponMixin, AndroidPassengerBase):
    """优惠券用例与登录/路线/订单共用乘客 UI 步骤。"""
