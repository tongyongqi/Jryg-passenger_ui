"""主流程双端登录态策略，不修改公共登录模块或账号配置。

依据：2026-11-23 用户要求司机、乘客只判断是否登录，不比对配置手机号。
页面依据：当日失败现场个人中心包含 tv_mine_name、“我的行程”及“聯繫客服”。
司机登录态沿用 ensure_online 的真实页面阶段识别；已登录不重新登录。
不使用目标手机号及其配置车牌映射过滤下单；同订单、资金与旧单保护不变。
"""

import os
import re
import time
import xml.etree.ElementTree as ET

from passenger_android_core import JRYG_android_ui_elements as E
from passenger_android_core.JRYG_logger import logger


class MainFlowLoginStateMixin:
    """双端仅确认登录态，下单不以配置手机号一致性作为前置。"""

    def _place_order_with_expected_driver(self, tag, pay_label):
        """兼容主流程调用入口；下单一次，不进行手机号或目标账号筛选。

        保留原路线、车型和支付步骤；已登录态由调用前的双端准备步骤确认。
        接单页面观察只证明当前页面就绪，同订单履约/付款仍由原步骤核验。
        点击呼叫后若出现"未完成訂單"弹窗，先处理遗留订单再重新下单一次。
        """
        if self.CAR_TYPE not in ("meter", "charter"):
            raise ValueError("主流程计价类型必须为 meter 或 charter")
        if getattr(self, "_main_flow_placement_started", False):
            raise RuntimeError("本场景已进入下单步骤，禁止重复下单或支付")
        self._main_flow_placement_started = True
        logger.info("【%s】使用双端当前登录态继续下单，不比较手机号或配置目标账号", tag)
        ordered = self._attempt_single_placement(tag, pay_label)
        if ordered == "ongoing_order":
            logger.info("【%s】检测到遗留订单弹窗，处理后重新下单一次", tag)
            self._main_flow_placement_started = False
            self._main_flow_placement_started = True
            ordered = self._attempt_single_placement(tag, pay_label)
        if ordered is not True:
            raise AssertionError(f"{tag} UI 下单未确认成功，停止，不重复提交")
        self._android_screenshot(f"JRYG_{self.CAR_TYPE}_{self.PAYMENT}_03_order_success.png")
        timeout = (self.order_settings.get("order_validation") or {}).get("state_timeout", 30)
        identity = self._wait(
            self._passenger_assigned_driver,
            "主流程乘客订单页未出现唯一接单状态和车辆，停止，不取消或重新下单",
            timeout=timeout,
        )
        if not isinstance(identity, dict):
            raise TypeError("接单页面观察必须返回字段字典")
        for field in ("status", "car_number"):
            if field not in identity:
                raise RuntimeError(f"接单页面观察缺少 {field} 字段")
            if not isinstance(identity[field], str) or not identity[field].strip():
                raise RuntimeError(f"接单页面观察的 {field} 类型或内容无效")
        self.assigned_driver_identity = identity
        logger.info("【%s】已观察到接单页面，继续司机步骤；此观察不代表同订单履约或付款已通过", tag)

    def _attempt_single_placement(self, tag, pay_label):
        """执行一次路线设置、车型选择和呼叫；返回 True、False 或 ongoing_order。"""
        self._android_launch_setup_and_addresses(
            tag, E.DEFAULT_START_ADDRESS, E.DEFAULT_END_ADDRESS)
        self._android_screenshot(f"JRYG_{self.CAR_TYPE}_{self.PAYMENT}_01_car_select.png")
        self._android_select_car_type(tag, car_type=self.CAR_TYPE)
        self._android_screenshot(f"JRYG_{self.CAR_TYPE}_{self.PAYMENT}_02_selected.png")
        if self.CAR_TYPE == "meter":
            self._android_select_payment(tag, payment=self.PAYMENT)
            ordered = self._click_call_and_check_login_then_retry(tag)
        else:
            ordered = self._charter_click_call_and_select_payment(tag)
        if ordered == "ongoing_order":
            self._android_handle_unfinished_order_popup(tag)
            self._reset_submission_flags()
            return "ongoing_order"
        if ordered is not True:
            if self._android_detect_unfinished_order_popup():
                logger.info("【%s】呼叫后检测到遗留订单弹窗，处理后重新下单", tag)
                self._android_handle_unfinished_order_popup(tag)
                self._reset_submission_flags()
                return "ongoing_order"
        return ordered

    def _reset_submission_flags(self):
        """重置公共代码的单次提交标记，允许遗留订单处理后重新下单。"""
        for attr in ("_call_submission_started", "_prepayment_submission_started"):
            if getattr(self, attr, False):
                setattr(self, attr, False)

    def _android_detect_unfinished_order_popup(self):
        """检查当前页面是否为'未完成訂單'弹窗。"""
        try:
            root = ET.fromstring(self.client.source(format="xml"))
        except Exception:
            return False
        texts = [(n.get("text") or "").strip() for n in root.iter()]
        return any("未完成" in t and "訂單" in t for t in texts)

    def _click_call_and_check_login_then_retry(self, tag):
        """覆盖公共代码：ongoing_order 返回值不报错，传递给上层处理遗留订单。"""
        self._submit_call_once(tag)
        if self._android_is_login_page():
            raise RuntimeError("呼叫后进入登录页，订单创建结果未核实，禁止登录后自动重放")
        result = self._android_wait_order_result(tag, max_checks=15)
        if result == "success":
            return True
        if result == "ongoing_order":
            logger.info("【%s】检测到遗留订单弹窗，返回 ongoing_order 由上层处理", tag)
            return "ongoing_order"
        raise RuntimeError(
            "确认呼叫未获得成功结果（%s），停止并保留现场；禁止换终点、取消或重新呼叫" % result)

    def _charter_click_call_and_select_payment(self, tag):
        """覆盖公共代码：ongoing_order 返回值不报错，传递给上层处理遗留订单。

        公共代码在 _submit_call_once 后等待结果，ongoing_order 会导致 RuntimeError。
        此处在调用公共代码前预检：如果点击呼叫后出现遗留订单弹窗，先返回 ongoing_order；
        否则正常调用公共代码完成完整预付流程。
        """
        # 先检查当前是否已有遗留订单弹窗（可能在阶段1未处理完）
        if self._android_detect_unfinished_order_popup():
            logger.info("【%s】包车呼叫前检测到遗留订单弹窗，返回 ongoing_order", tag)
            return "ongoing_order"
        # 调用公共代码；如果内部因 ongoing_order 报错，捕获并返回
        try:
            return super()._charter_click_call_and_select_payment(tag)
        except RuntimeError as exc:
            if "ongoing_order" in str(exc) or "未确认本次预付页面" in str(exc):
                if self._android_detect_unfinished_order_popup():
                    logger.info("【%s】包车呼叫后检测到遗留订单弹窗，返回 ongoing_order", tag)
                    return "ongoing_order"
            raise

    def _android_estimate_route_identity(self, root):
        """1.4.0 Android 询价页无 tv_start_address/tv_destination 控件时跳过 OCR 回退。

        公共代码在该情况下导入不存在的 JRYG_android_route_ocr 模块导致崩溃；
        主流程用例已通过搜索页确认起终点，此处不重复校验，返回 None 让调用方接受已有路线。
        """
        def address(resource_names):
            values = []
            for node in self._login_visible(root):
                rid = (node.get("resource-id") or "").split("/")[-1]
                if rid in resource_names:
                    text = (node.get("text") or node.get("label") or node.get("content-desc") or "").strip()
                    if text:
                        values.append(text)
            return values[0] if len(values) == 1 and values[0] else None
        start = address(("tv_start_address",))
        end = address(("tv_destination",))
        if start and end:
            return start, end
        return None

    def _android_wait_current_payment(self, tag):
        """切回乘客 App 后等待费用页推送，超时才去"我的行程"找待支付订单。

        司机端确认账单后切回乘客端，App 通常自动弹出费用页（含"確認支付 X HKD"）。
        先等待推送 15 秒；如果没弹出费用页，再导航到"我的行程"点击待支付订单。
        """
        from decimal import Decimal
        settings = self.order_settings.get("driver") or {}
        expected = self.driver_ui.bill_total
        if expected is None:
            expected = Decimal(str(os.environ.get("HK_ORDER_AMOUNT", settings.get("fare", "5")))) + Decimal(
                str(os.environ.get("HK_OTHER_AMOUNT", settings.get("surcharge", "0"))))
        timeout = (self.order_settings.get("order_validation") or {}).get("completion_timeout", 90)
        deadline = time.monotonic() + timeout
        last_navigate_time = time.monotonic()  # 先等推送，15秒后才导航
        while time.monotonic() < deadline:
            texts = self._android_get_all_texts(self.client)
            if any(kw in t for t in texts for kw in ("支付失敗", "支付失败", "訂單已取消", "订单已取消")):
                raise RuntimeError(f"{tag}: 乘客订单支付失败或取消，停止操作")
            for text in texts:
                match = re.search(r"(?:確認支付|确认支付)\s*([0-9]+(?:\.[0-9]+)?)\s*HKD", text)
                if match:
                    assert Decimal(match.group(1)) == expected, f"{tag}: 付款金额与司机账单不一致，禁止提交"
                    self._android_screenshot("epayment_current_before_payment.png")
                    logger.info("【%s】已确认乘客付款金额 %s HKD", tag, expected)
                    return
            if time.monotonic() - last_navigate_time > 15:
                last_navigate_time = time.monotonic()
                logger.info("【%s】未等到费用页推送，导航到我的行程查找待支付订单", tag)
                self._android_open_pending_order_card(tag)
            time.sleep(1)
        raise TimeoutError(f"{tag}: 未等到带金额的确认支付页面，不跳过支付")

    def _android_handle_unfinished_order_popup(self, tag):
        """处理"您還有未完成的訂單"弹窗：点击"去完成"进入费用页，完成支付后返回首页。

        存在待支付订单时不阻止流程，直接进入支付。完成后返回首页让上层重新下单。
        """
        logger.info(f"【{tag}】检测到未完成订单弹窗，点击'去完成'进入费用页")
        go_clicked = self._android_click_dialog_button(
            ["去完成", "去處理", "去处理"], tag=tag, fallback_coord=(259, 482), wait_after=3)
        if not go_clicked:
            logger.warning(f"【{tag}】未找到'去完成'按钮，尝试关闭弹窗后继续")
            self._android_click_dialog_button(
                ["稍後再說", "稍后再说", "關閉", "关闭"], tag=tag, fallback_coord=None, wait_after=2)
            return
        time.sleep(3)
        texts = self._android_get_all_texts(self.client)
        if any("確認支付" in t or "确认支付" in t for t in texts):
            logger.info(f"【{tag}】已进入费用页，完成遗留订单支付后返回首页")
            self._android_pay(tag, payment=self.final_payment)
            self._android_back_to_home(tag)
            return
        if any("取消訂單" in t or "取消订单" in t for t in texts):
            logger.info(f"【{tag}】遗留订单仍在进行中，返回让司机端推进行程")
            return
        logger.info(f"【{tag}】去完成后页面未识别，继续流程")

    def _android_open_pending_order_card(self, tag):
        """进入"我的行程"并点击状态为"待支付"的订单卡片，直接进入支付流程。

        存在待支付订单时不报错，直接点击进入费用页完成支付。
        返回 True 表示已执行一次导航点击。
        """
        try:
            root = ET.fromstring(self.client.source(format="xml"))
        except Exception as exc:
            logger.warning("【%s】读取乘客页面树失败：%s", tag, exc)
            return False
        has_order_list = any(
            (node.get("resource-id") or "").split("/")[-1] == "rl_order_item_layout"
            for node in root.iter()
        )
        if not has_order_list:
            logger.info("【%s】当前不在我的行程列表，先导航到该页面", tag)
            self._android_navigate_to_trip_list(tag)
            try:
                root = ET.fromstring(self.client.source(format="xml"))
            except Exception as exc:
                logger.warning("【%s】导航后读取页面树失败：%s", tag, exc)
                return False
        cards = []
        for node in root.iter():
            if (node.get("resource-id") or "").split("/")[-1] != "rl_order_item_layout":
                continue
            fields = {}
            for child in node.iter():
                rid = (child.get("resource-id") or "").split("/")[-1]
                if rid and rid not in fields:
                    text = (child.get("text") or child.get("label") or "").strip()
                    fields[rid] = text
            status = fields.get("tv_type_order")
            if status in ("待支付", "待付款"):
                cards.append((node, fields))
        if not cards:
            return False
        # 存在多个待支付订单时点击第一个，不阻止流程
        node, fields = cards[0]
        logger.info("【%s】我的行程中存在待支付订单 %s %s，金额 %s，直接进入支付",
                    tag, fields.get("tv_guid_date", ""),
                    fields.get("tv_info_guid", ""), fields.get("tv_guid_money", ""))
        coords = self._android_node_center(node)
        if not coords:
            logger.warning("【%s】待支付订单卡片无可用坐标，跳过本次点击", tag)
            return False
        self.client.driver.tap([coords])
        time.sleep(2)
        logger.info("【%s】已点击待支付订单卡片，等待费用页加载", tag)
        return True

    @staticmethod
    def _android_parse_bounds_center(bounds):
        """从 Android bounds="[x1,y1][x2,y2]" 解析中心坐标。"""
        match = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
        if not match:
            return None
        x1, y1, x2, y2 = map(int, match.groups())
        return ((x1 + x2) // 2, (y1 + y2) // 2)

    @classmethod
    def _android_node_center(cls, node):
        """获取节点中心坐标。

        Appium source(format="xml") 经 normalized_tree 转换后，bounds 属性被拆为
        x/y/width/height 属性，不再保留原生 bounds。优先用这些属性计算中心；
        父节点无坐标时用子控件坐标的最小外接矩形中心。
        """
        # 优先尝试原生 bounds 属性（uiautomator dump 场景）
        bounds = node.get("bounds")
        if bounds:
            center = cls._android_parse_bounds_center(bounds)
            if center:
                return center
        # 尝试 normalized_tree 的 x/y/width/height 属性
        x = node.get("x")
        y = node.get("y")
        w = node.get("width")
        h = node.get("height")
        if x is not None and y is not None and w is not None and h is not None:
            try:
                xi, yi, wi, hi = int(x), int(y), int(w), int(h)
                if wi > 0 and hi > 0:
                    return (xi + wi // 2, yi + hi // 2)
            except ValueError:
                pass
        # 父节点无坐标时，用子控件坐标的外接矩形中心
        xs, ys = [], []
        for child in node.iter():
            # 子控件 bounds 属性
            cb = child.get("bounds")
            if cb:
                m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", cb)
                if m:
                    x1, y1, x2, y2 = map(int, m.groups())
                    xs.extend([x1, x2])
                    ys.extend([y1, y2])
                    continue
            # 子控件 x/y/width/height 属性
            cx = child.get("x")
            cy = child.get("y")
            cw = child.get("width")
            ch = child.get("height")
            if cx is not None and cy is not None and cw is not None and ch is not None:
                try:
                    cxi, cyi, cwi, chi = int(cx), int(cy), int(cw), int(ch)
                    if cwi > 0 and chi > 0:
                        xs.extend([cxi, cxi + cwi])
                        ys.extend([cyi, cyi + chi])
                except ValueError:
                    pass
        if not xs or not ys:
            return None
        return ((min(xs) + max(xs)) // 2, (min(ys) + max(ys)) // 2)

    def _android_navigate_to_trip_list(self, tag):
        """从任意乘客页面导航到"我的行程"列表页。

        路径：返回首页 → 点击底部"我的"tab → 点击"我的行程"。
        每步校验页面变化，不盲点坐标，不操作订单或支付。
        """
        self._android_back_to_home(tag)
        time.sleep(1)
        clicked = self._click_text(["我的"], exact=True, required=False)
        if not clicked:
            raise RuntimeError(f"{tag}: 首页未找到'我的'tab，无法进入我的行程")
        time.sleep(2)
        clicked = self._click_text(["我的行程"], exact=True, required=False)
        if not clicked:
            raise RuntimeError(f"{tag}: 我的页面未找到'我的行程'入口")
        time.sleep(2)
        logger.info("【%s】已导航到我的行程列表", tag)

    def _login_verify_account(self, root):
        """兼容公共登录流程的钩子；确认已登录个人中心，不读取登录凭据。"""
        expected_package = self.order_settings["packages"]["passenger_hk"]
        package = self.client.driver.current_package
        if package != expected_package:
            raise RuntimeError("主流程乘客App不在前台，无法确认登录态")
        if self._login_classify(root, package) != "mine":
            raise RuntimeError("主流程未确认已登录个人中心，不能继续下单")
        name_id = expected_package + ":id/tv_mine_name"
        names = [node for node in self._login_visible(root)
                 if node.get("resource-id") == name_id]
        if len(names) != 1:
            raise RuntimeError("主流程个人中心登录态控件缺失或不唯一，不能继续下单")
        label = (names[0].get("text") or names[0].get("content-desc") or "").strip()
        if not label or label in self.LOGIN_LABELS:
            raise RuntimeError("主流程个人中心仍显示未登录入口，不能继续下单")
        # 不调用 _login_credentials，不比对手机号、尾号或掩码，也不记录账号内容。
        # 公共 login_passenger 随后设置本次会话登录标记并按原流程返回首页。
