"""安卓目标订单筛选；非目标单结束行程后继续听单，不替其他乘客付款。"""

from copy import copy
import re
import subprocess
import time
import xml.etree.ElementTree as ET

from .JRYG_android_order import AndroidDriverUIFlow, AndroidOrderBase
from ui_framework.JRYG_driver_ui import (
    ACTION_LABELS, DriverUIFlow, RESUMABLE_PHASES,
    amount, find_label, read_order_no, visible_nodes,
)
from ui_framework.JRYG_logger import logger


def order_numbers(root):
    return {value for node in visible_nodes(root)
            for value in re.findall(r"\b[A-Z0-9]{12}\b", node.get("label", ""))
            if any(c.isdigit() for c in value) and any(c.isalpha() for c in value)}


def unique_order(root):
    values = order_numbers(root)
    if len(values) != 1:
        raise RuntimeError("安卓当前订单号缺失或不唯一，禁止判断目标订单")
    return values.pop()


def passenger_status_orders(log_output):
    """只提取乘客 App 自身当前订单状态请求中的合法订单号。"""
    return {value for value in re.findall(
        r"https?://[^\s]+/passenger/order/status\?order_no=([A-Z0-9]{12})(?:[&#\s]|$)",
        log_output or "",
    ) if any(char.isdigit() for char in value) and any(char.isalpha() for char in value)}


def is_active_passenger_order(root):
    """仅在乘客进行中订单页已显示唯一状态和已分配车辆时允许绑定日志订单号。"""
    nodes = visible_nodes(root)
    status = [node for node in nodes
              if node.get("resource-id", "").split("/")[-1] == "tv_status_name"
              and node.get("label", "").strip()]
    cars = [node for node in nodes
            if node.get("resource-id", "").split("/")[-1] == "tv_car_number"
            and node.get("label", "").strip()]
    return len(status) == 1 and len(cars) == 1


class AndroidTargetDriverUIFlow(AndroidDriverUIFlow):
    """独立安卓司机场景，不修改既有司机状态机或内置业务快照。"""

    def __init__(self, args, client=None, settings=None):
        super().__init__(args, client)
        self.settings = settings or {}
        self.target_order_no = None
        self.non_target_results = []
        self.handling_non_target = False

    def read_active_order(self):
        root = self.root()
        phase = self.detect_phase(root)
        self._check_device_availability(phase)
        if phase not in RESUMABLE_PHASES:
            raise RuntimeError("安卓司机不在当前订单，禁止读取任意历史订单号")
        values = order_numbers(root)
        if values:
            return unique_order(root)
        expand = find_label(root, ("展開", "展开"))
        if expand is None:
            raise RuntimeError("安卓当前行程缺少订单号及展开入口，未推进订单")
        self.act(root, ("展開", "展开"))
        try:
            deadline = min(self.deadline, time.monotonic() + self.args.step_timeout)
            while time.monotonic() < deadline:
                detail = self.root()
                values = order_numbers(detail)
                if values:
                    return unique_order(detail)
                time.sleep(self.args.interval)
            raise TimeoutError("安卓展开详情未显示唯一订单号，未推进行程")
        finally:
            self.client.back()
            self.wait_for({phase})

    def _run_remaining(self, deadline, *, stop_after="submitted"):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("安卓目标订单总超时，未继续接单或提交账单")
        original = self.args
        self.args = copy(original)
        self.args.stop_after = stop_after
        self.args.timeout = remaining
        self.args.dispatch_timeout = min(original.dispatch_timeout, remaining)
        self.args.step_timeout = min(original.step_timeout, remaining)
        try:
            DriverUIFlow.run(self)
        finally:
            self.args = original
        if time.monotonic() >= deadline:
            raise TimeoutError("安卓目标订单总超时，停止后续操作")

    def accept_and_identify(self, deadline):
        self.deadline = deadline
        self._activate_driver_app()
        root, phase = self.wait_for(set(RESUMABLE_PHASES) | {"online", "offline", "offer"})
        if phase not in RESUMABLE_PHASES:
            self._run_remaining(deadline, stop_after="accepted")
        current = self.read_active_order()
        if current in self.completed_before_run:
            raise RuntimeError("安卓司机接到已经处理的旧订单，停止重复流转")
        if self.order_no is not None and self.order_no != current:
            raise RuntimeError("安卓当前订单已切换，停止串单流转")
        self.order_no = current
        self.resume_phase = self.last_phase = self.detect_phase(self.root())
        self.awaiting_new_order = False
        return current

    def submit_bill(self, root):
        if self.handling_non_target:
            fields = [n for n in visible_nodes(root) if n.tag == "XCUIElementTypeTextField"
                      and n.get("placeholderValue") == "請輸入車費"]
            self.args.car_type = "meter" if fields else "charter"
            if not fields:
                self.args.fare = self.args.surcharge = None
            texts = {n.get("label", "") for n in visible_nodes(root)}
            self.args.payment = "cash" if texts.intersection({"現金", "現金支付", "现金", "现金支付"}) else "online"
        super().submit_bill(root)

    def finish_non_target(self, deadline):
        current = self.order_no or self.read_active_order()
        if current == self.target_order_no:
            raise RuntimeError("目标订单不能按非目标订单处理")
        settings = self.settings.get("driver") or {}
        fare = amount(str(settings.get("non_target_fare", settings.get("fare", "5"))))
        surcharge = amount(str(settings.get("non_target_surcharge", "0")))
        tail = settings.get("non_target_passenger_tail") or None
        if tail is not None and (not isinstance(tail, str) or re.fullmatch(r"\d{4}", tail) is None):
            raise ValueError("安卓非目标乘客尾号必须单独配置四位数字字符串")
        phase = self.detect_phase(self.root())
        original = self.args
        self.args = copy(original)
        self.args.fare, self.args.surcharge, self.args.tail = fare, surcharge, tail
        self.args.cash_collected = settings.get("non_target_cash_collected") is True
        self.order_no = current
        self.awaiting_new_order = False
        self.resume_phase = phase
        self.handling_non_target = True
        try:
            self._run_remaining(deadline)
            root = self.root()
            phase = self.detect_phase(root)
            if phase not in ("unpaid", "complete"):
                raise RuntimeError("非目标订单行程未结束，禁止继续接单")
            read_order_no(root, expected=current)
            self.non_target_results.append({"order_no": current, "phase": phase})
            logger.info("安卓非目标订单 %s 行程已结束，支付状态=%s；不替该乘客支付", current, phase)
        finally:
            self.args = original
            self.handling_non_target = False

    def return_to_listening(self, deadline):
        if time.monotonic() >= deadline:
            raise TimeoutError("安卓等待目标单总超时，未继续接单")
        self.deadline = deadline
        root = self.root()
        phase = self.detect_phase(root)
        if phase not in ("unpaid", "complete") or not self.order_no:
            raise RuntimeError("非目标单未结束，禁止返回听单")
        read_order_no(root, expected=self.order_no)
        previous = self.order_no
        if find_label(root, ("返回首頁",)) is not None:
            self.act(root, ("返回首頁",))
            root, phase = self.wait_for({"online", "offer", "offline"})
        elif phase == "complete":
            self.back_from_paid_detail(root)
            root, phase = self.wait_for_entry_page()
        else:
            raise RuntimeError("非目标未支付完成页缺少返回首页入口，禁止盲目返回")
        if phase == "offline":
            self.act(root, ACTION_LABELS["offline"])
            root, phase = self.wait_for({"online", "offer"})
        if phase not in ("online", "offer"):
            raise RuntimeError("非目标订单结束后未回到听单，不能继续接目标单")
        self.completed_before_run.add(previous)
        self.order_no = self.resume_phase = self.bill_total = None
        self.awaiting_new_order = True
        self.last_phase = phase

    def run(self):
        if self.target_order_no is None:
            return super().run()
        if (not isinstance(self.target_order_no, str) or not re.fullmatch(r"[A-Z0-9]{12}", self.target_order_no)
                or not any(c.isdigit() for c in self.target_order_no) or not any(c.isalpha() for c in self.target_order_no)):
            raise ValueError("安卓目标订单号无效，未接单")
        deadline = time.monotonic() + self.args.timeout
        maximum = (self.settings.get("order_validation") or {}).get("max_attempts", 5)
        if not isinstance(maximum, int) or isinstance(maximum, bool) or maximum < 0:
            raise ValueError("安卓非目标订单上限必须为非负整数")
        handled = 0
        while time.monotonic() < deadline:
            current = self.accept_and_identify(deadline)
            if current == self.target_order_no:
                logger.info("安卓司机接单命中乘客目标订单：%s", current)
                self._run_remaining(deadline)
                if self.order_no != self.target_order_no:
                    raise RuntimeError("安卓目标订单流转结果不一致")
                return
            if handled >= maximum:
                raise RuntimeError("安卓非目标订单达到处理上限，未接到目标单")
            logger.info("安卓司机接到非目标订单 %s，目标=%s；结束后继续听单", current, self.target_order_no)
            self.finish_non_target(deadline)
            self.return_to_listening(deadline)
            handled += 1
        raise TimeoutError("安卓等待目标订单总超时，未重新下单或取消目标单")


class AndroidTargetOrderBase(AndroidOrderBase):
    __test__ = False

    def _create_driver_flow(self, args):
        return AndroidTargetDriverUIFlow(args, client=self.clients[self.driver_runtime.udid], settings=self.order_settings)

    def _driver_ui_go_online(self, tag):
        self.target_order_no = None
        self.legacy_order_no = None
        super()._driver_ui_go_online(tag)
        if self.resuming_order:
            deadline = time.monotonic() + (self.order_settings.get("order_validation") or {}).get("total_timeout", 900)
            self.driver_ui.deadline = deadline
            self.driver_ui.finish_non_target(deadline)
            self.legacy_order_no = self.driver_ui.order_no
            self.resuming_order = False
            logger.info("安卓司机遗留订单 %s 已结束；保留同单绑定，先由乘客完成付款和到账核验，再继续新下单",
                        self.legacy_order_no)

    @staticmethod
    def _passenger_page_texts(root):
        return {node.get("text") or node.get("content-desc") or "" for node in root.iter()}

    def _complete_legacy_passenger_order(self, tag):
        order_no = self._read_passenger_target()
        if self.legacy_order_no and self.legacy_order_no != order_no:
            raise RuntimeError("乘客未完成订单与司机遗留订单不是同一订单，禁止付款或继续新下单")
        if self.driver_ui.order_no:
            if self.driver_ui.order_no != order_no:
                raise RuntimeError("司机当前绑定订单与乘客未完成订单不一致，禁止付款")
            root = self.driver_ui.root()
            phase = self.driver_ui.detect_phase(root)
            if phase not in ("unpaid", "complete"):
                raise RuntimeError("司机遗留订单尚未结束，禁止乘客付款")
            read_order_no(root, expected=order_no)
        else:
            phase = self.driver_ui.bind_existing_history_order(order_no)
        self.legacy_order_no = order_no
        if phase == "unpaid":
            self.client.app_activate(self.order_settings["packages"]["passenger_hk"])
            if self._read_passenger_target() != order_no:
                raise RuntimeError("乘客付款页订单号发生变化，禁止提交遗留订单付款")
            submitted = getattr(self, "_legacy_payment_submitted", set())
            if order_no in submitted:
                raise RuntimeError("遗留订单付款已发起，禁止重复提交")
            self._ios_wait_current_payment(tag)
            submitted.add(order_no)
            self._legacy_payment_submitted = submitted
            self._ios_complete_payment(tag)
        else:
            self._ios_back_to_home(tag)
        self.driver_ui.wait_completed()
        completed = self.driver_ui.order_no
        if completed != order_no or self.driver_ui.last_phase != "complete":
            raise RuntimeError("遗留订单未完成同单已支付核验，禁止继续新下单")
        deadline = time.monotonic() + (self.order_settings.get("order_validation") or {}).get("total_timeout", 900)
        self.driver_ui.return_to_listening(deadline)
        self.legacy_completed_order_no = completed
        self.legacy_order_no = None
        logger.info("安卓遗留订单 %s 已完成且已支付并返回听单；继续后续新订单流程", completed)

    def _ui_cleanup_ongoing_order(self, tag):
        """未完成弹窗必须去完成；同单支付到账后才允许进入后续下单。"""
        self._login_activate_app()
        deadline = time.monotonic() + (self.order_settings.get("order_validation") or {}).get("state_timeout", 30)
        clicked = False
        while time.monotonic() < deadline:
            page, root = self._login_snapshot()
            texts = self._passenger_page_texts(root)
            unfinished = any("未完成" in text and ("訂單" in text or "订单" in text) for text in texts)
            if unfinished:
                if clicked:
                    raise RuntimeError("安卓未完成订单‘去完成’单次点击未生效，未重复点击或继续下单")
                if not self._ios_click_dialog_button(["去完成", "去處理", "去处理"], wait_after=1):
                    raise RuntimeError("Android 未定位遗留订单‘去完成’入口，停止后续流程")
                clicked = True
                continue
            if page == "terminal_unpaid":
                self._complete_legacy_passenger_order(tag)
                return
            if self.legacy_order_no or clicked:
                if page == "business":
                    time.sleep(1)
                    continue
                raise RuntimeError("安卓遗留订单未进入唯一付款页，禁止取消、付款或继续新下单")
            return super()._ui_cleanup_ongoing_order(tag)
        raise TimeoutError("安卓未完成订单未在时限内进入付款页，未取消或继续新下单")

    def _adb(self, *arguments):
        udid = self.order_settings["device"]["udid"]
        command = ["adb", "-s", udid, *arguments]
        try:
            return subprocess.run(command, capture_output=True, text=True, timeout=10, check=True).stdout
        except (OSError, subprocess.SubprocessError) as exc:
            raise RuntimeError("安卓无法只读获取乘客当前订单日志，未接单") from exc

    def _start_passenger_order_log(self):
        package = self.order_settings["packages"]["passenger_hk"]
        pid = self._adb("shell", "pidof", "-s", package).strip()
        if re.fullmatch(r"\d+", pid) is None:
            raise RuntimeError("安卓乘客 App 进程不唯一或不存在，未接单")
        self._adb("logcat", "-c")
        return pid

    def _fresh_passenger_orders(self, pid):
        output = self._adb("logcat", "-d", f"--pid={pid}", "-v", "brief")
        return passenger_status_orders(output)

    @staticmethod
    def _validate_passenger_target_page(root):
        texts = {node.get("label", "") for node in visible_nodes(root)}
        if any(keyword in text for text in texts
               for keyword in ("已取消", "訂單已超時", "订单已超时", "支付失敗", "支付失败")):
            raise RuntimeError("安卓乘客目标订单已取消、超时或失败，未重新下单")
        if texts.intersection({"我的行程", "行程記錄", "歷史訂單"}):
            raise RuntimeError("安卓乘客当前是历史列表，禁止用历史订单当目标")

    def _read_passenger_target(self):
        self._assert_passenger_foreground()
        root = ET.fromstring(self.client.source())
        self._validate_passenger_target_page(root)
        if order_numbers(root):
            return unique_order(root)
        pid = self._start_passenger_order_log()
        deadline = time.monotonic() + (self.order_settings.get("order_validation") or {}).get("state_timeout", 30)
        while time.monotonic() < deadline:
            self._assert_passenger_foreground()
            root = ET.fromstring(self.client.source())
            self._validate_passenger_target_page(root)
            if order_numbers(root):
                return unique_order(root)
            if is_active_passenger_order(root):
                values = self._fresh_passenger_orders(pid)
                if len(values) > 1:
                    raise RuntimeError("安卓乘客当前页出现多个新鲜状态订单号，禁止判断目标订单")
                if values:
                    target = values.pop()
                    logger.info("安卓乘客进行中页面与 App 新鲜状态请求绑定唯一目标订单：%s", target)
                    return target
            time.sleep(1)
        raise TimeoutError("安卓乘客当前页及 App 新鲜状态请求均未显示唯一目标订单号，未接单")

    def _driver_ui_grab_and_flow(self, tag):
        self.target_order_no = self._read_passenger_target()
        self.driver_ui.target_order_no = self.target_order_no
        super()._driver_ui_grab_and_flow(tag)
        if self.driver_ui.order_no != self.target_order_no:
            raise AssertionError("安卓司机接单结果不是本次乘客目标订单")

    def _run_order_flow(self):
        super()._run_order_flow()
        if not self.target_order_no or self.completed_order_no != self.target_order_no:
            raise AssertionError("安卓已完成订单不是本次乘客目标订单，不能判定通过")
