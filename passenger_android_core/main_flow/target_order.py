"""安卓目标订单流程；只允许已绑定同单的动作，非目标或身份缺失立即停止。"""

from copy import copy
from decimal import Decimal
import re
import subprocess
import time
import xml.etree.ElementTree as ET

from passenger_android_core.main_flow.order import AndroidDriverUIFlow, AndroidOrderBase, read_android_fixed_fare
from passenger_android_core.JRYG_driver_ui import (
    ACTION_LABELS, DriverUIFlow, RESUMABLE_PHASES,
    amount, find_label, node_text, read_order_no, visible_nodes,
)
from passenger_android_core.JRYG_logger import logger


def order_numbers(root):
    """从页面树提取所有合法的12位订单号，返回去重集合。"""
    return {value for node in visible_nodes(root)
            for value in re.findall(r"\b[A-Z0-9]{12}\b", node.get("label", ""))
            if any(c.isdigit() for c in value) and any(c.isalpha() for c in value)}


def unique_order(root):
    """获取唯一目标订单号，缺失或不唯一时抛出异常。"""
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
        """初始化目标订单流程，设置目标订单号、非目标结果列表和处理标记。"""
        super().__init__(args, client)
        self.settings = settings or {}
        self.target_order_no = None
        self.non_target_results = []
        self.handling_non_target = False

    def _read_bill_action_snapshot(self, root):
        """回读实际提交页面，未知支付标识或未核实金额直接阻断。"""
        if self.order_no != self.target_order_no or not self.target_order_no:
            raise RuntimeError("账单必须绑定当前目标订单")
        read_order_no(root, expected=self.target_order_no, excluded=self.completed_before_run)
        cash = frozenset(node_text(node) for node in visible_nodes(root)) & {
            "現金", "現金支付", "现金", "现金支付"}
        if self.args.payment == "cash":
            if not cash or self.args.cash_collected is not True:
                raise RuntimeError("现金支付标识或实际收款确认缺失，禁止提交账单")
        elif self.args.payment == "online":
            if cash:
                raise RuntimeError("页面显示现金支付，与绑定支付方式不符")
            raise RuntimeError("线上支付账单正向标识尚未核实，禁止用未显示现金代替支付方式确认")
        else:
            raise RuntimeError("账单支付方式未知，禁止提交")
        if not isinstance(self.bill_total, Decimal) or not self.bill_total.is_finite():
            raise RuntimeError("缺少已核对的账单合计，禁止提交")
        if self.args.car_type == "charter":
            fare = read_android_fixed_fare(root)
            surcharge = Decimal("0")
            if self.args.fare is not None and fare != Decimal(amount(self.args.fare)):
                raise RuntimeError("包车车费与显式预期不一致")
            if self.args.surcharge is not None and Decimal(amount(self.args.surcharge)) != 0:
                raise RuntimeError("包车固定价不允许非零附加费")
        elif self.args.car_type == "meter":
            if self.args.fare is None:
                raise RuntimeError("打表车费缺少显式预期")
            fare = Decimal(amount(self.field(root, "請輸入車費").get("value", "")))
            surcharge = Decimal(amount(self.field(root, "請輸入附加費").get("value", "")))
            expected_surcharge = Decimal("0") if self.args.surcharge is None else Decimal(amount(self.args.surcharge))
            if fare != Decimal(amount(self.args.fare)) or surcharge != expected_surcharge:
                raise RuntimeError("打表车费或附加费在提交前不符合预期")
        else:
            raise RuntimeError("未知计价类型，禁止提交账单")
        if fare + surcharge != self.bill_total:
            raise RuntimeError("账单金额在提交前发生变化，禁止收款")
        return fare, surcharge, self.args.payment, cash

    @staticmethod
    def _check_navigation_target(root, labels):
        """导航同样要求唯一可用控件，不因无业务副作用而点击首个候选。"""
        targets = [node for node in visible_nodes(root)
                   if node_text(node) in labels and node.get("enabled") != "false"]
        if len(targets) != 1:
            raise RuntimeError("导航控件缺失、不可用或不唯一，停止点击")

    def _read_target_identity(self, root):
        """详情读号沿用既有解析，只接受本轮目标号，不把任意详情号当凭据。"""
        current = unique_order(root)
        if current != self.target_order_no or current in self.completed_before_run:
            raise RuntimeError("详情订单不是本轮目标订单，禁止后续操作")
        return current

    def _check_action_context(self, root, labels, *, submitting=False):
        """校验实际动作所用页面；接单及账单结果未知时不重放。"""
        if self.handling_non_target:
            raise RuntimeError("正在处理非目标订单，禁止操作")
        if labels == ACTION_LABELS["offline"] and self.target_order_no is None:
            if self.order_no is not None or self.detect_phase(root) != "offline":
                raise RuntimeError("出车页面或订单绑定状态已变化，停止操作")
            return
        startup_return = ("返回首頁", "返回", "ca_icon_back_black", "ca icon back black")
        if labels == startup_return and self.target_order_no is None:
            if self.order_no is not None or self.detect_phase(root) != "complete":
                raise RuntimeError("仅允许退出启动前已支付完成订单，禁止处理未付或取消状态")
            previous = read_order_no(root, expected=getattr(self, "_paid_exit_order_no", None))
            if previous not in self.completed_before_run:
                raise RuntimeError("返回前订单未登记为启动前已完成订单")
            self._check_navigation_target(root, labels)
            return
        if not self.target_order_no:
            raise RuntimeError("未绑定目标订单，禁止操作")
        if self.order_no is not None and self.order_no != self.target_order_no:
            raise RuntimeError("当前绑定订单与目标订单不一致，禁止操作")
        if labels == ("我的行程",):
            if (self.order_no != self.target_order_no
                    or self.awaiting_new_order
                    or self.order_no in self.completed_before_run):
                raise RuntimeError("未绑定本轮已接单订单，禁止进入历史核验")
            if self.detect_phase(root) not in ("online", "offer", "offline"):
                raise RuntimeError("必须在司机首页进入我的行程，页面状态已变化")
            self._check_navigation_target(root, labels)
            return
        if labels == ("展開", "展开"):
            if self.detect_phase(root) not in RESUMABLE_PHASES:
                raise RuntimeError("展开订单详情前状态已变化")
            if order_numbers(root):
                self._read_target_identity(root)
            self._check_navigation_target(root, labels)
            return
        read_order_no(root, expected=self.target_order_no, excluded=self.completed_before_run)
        if labels == ("返回首頁",):
            if (self.order_no != self.target_order_no or self.awaiting_new_order
                    or self.detect_phase(root) not in ("unpaid", "complete")):
                raise RuntimeError("仅允许从本轮同单完成页返回首页")
            self._check_navigation_target(root, labels)
            return
        action = ("accept" if labels == self.accept_labels else
                  "bill" if labels == ACTION_LABELS["bill"] else None)
        if action is not None:
            submitted = getattr(self, "_target_submissions", set())
            key = (self.target_order_no, action)
            if key in submitted:
                raise RuntimeError("目标订单接单或账单已发起，禁止重复提交")
            baseline = getattr(self, "_bill_action_snapshot", None)
            if action == "bill" and (baseline is not None or submitting):
                if baseline is None or self._read_bill_action_snapshot(root) != baseline:
                    raise RuntimeError("账单金额或支付标识在页面刷新后变化，禁止提交")
            if submitting:
                self._target_submissions = submitted | {key}

    def act(self, root, labels):
        """每次重读及最终提交都核对同单；账单还需核对金额与支付标识。"""
        self._check_action_context(root, labels)
        if labels == ACTION_LABELS["bill"]:
            self._bill_action_snapshot = self._read_bill_action_snapshot(root)
        startup_exit = (labels == ("返回首頁", "返回", "ca_icon_back_black", "ca icon back black")
                        and self.target_order_no is None)
        if startup_exit:
            self._paid_exit_order_no = read_order_no(root)
        try:
            current = self.root()
            return super().act(current, labels)
        finally:
            if labels == ACTION_LABELS["bill"]:
                self._bill_action_snapshot = None
            if startup_exit:
                self._paid_exit_order_no = None

    def read_active_order(self):
        """读取司机当前活跃订单号，必要时展开详情页获取。"""
        root = self.root()
        phase = self.detect_phase(root)
        self._check_device_availability(phase)
        if phase not in RESUMABLE_PHASES:
            raise RuntimeError("安卓司机不在当前订单，禁止读取任意历史订单号")
        values = order_numbers(root)
        if values:
            return self._read_target_identity(root)
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
                    return self._read_target_identity(detail)
                time.sleep(self.args.interval)
            raise TimeoutError("安卓展开详情未显示唯一订单号，未推进行程")
        finally:
            self.client.back()
            self.wait_for({phase})

    def _run_remaining(self, deadline, *, stop_after="submitted"):
        """在剩余时间内执行司机端流程，按stop_after指定停止阶段。"""
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
        """先从页面确认目标订单号，再允许接单；无法识别时不操作。"""
        if not self.target_order_no:
            raise RuntimeError("未绑定乘客目标订单，禁止接单")
        self.deadline = deadline
        self._activate_driver_app()
        root, phase = self.wait_for(set(RESUMABLE_PHASES) | {"offer"})
        read_order_no(root, expected=self.target_order_no, excluded=self.completed_before_run)
        if phase == "offer":
            self._run_remaining(deadline, stop_after="accepted")
        current = self.read_active_order()
        if current != self.target_order_no:
            raise RuntimeError("当前订单不是乘客目标订单，禁止继续履约")
        if current in self.completed_before_run:
            raise RuntimeError("安卓司机接到已经处理的旧订单，停止重复流转")
        if self.order_no is not None and self.order_no != current:
            raise RuntimeError("安卓当前订单已切换，停止串单流转")
        self.order_no = current
        self.resume_phase = self.last_phase = self.detect_phase(self.root())
        self.awaiting_new_order = False
        return current

    def submit_bill(self, root):
        """仅为已绑定的目标订单提交账单。"""
        if self.handling_non_target or not self.target_order_no or self.order_no != self.target_order_no:
            raise RuntimeError("非目标或未绑定订单，禁止提交账单")
        self._check_action_context(root, ACTION_LABELS["bill"])
        current = self.root()
        self._check_action_context(current, ACTION_LABELS["bill"])
        super().submit_bill(current)

    def finish_non_target(self, deadline):
        """非目标订单不属于本轮处理范围。"""
        raise RuntimeError("禁止推进非目标订单、提交账单或继续听单")

    def return_to_listening(self, deadline):
        """非目标订单结束后返回听单状态。"""
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
        """仅执行已绑定目标订单；没有目标或出现错单立即停止。"""
        if (not isinstance(self.target_order_no, str) or not re.fullmatch(r"[A-Z0-9]{12}", self.target_order_no)
                or not any(c.isdigit() for c in self.target_order_no) or not any(c.isalpha() for c in self.target_order_no)):
            raise ValueError("安卓目标订单号无效，未接单")
        deadline = time.monotonic() + self.args.timeout
        current = self.accept_and_identify(deadline)
        if current != self.target_order_no:
            raise RuntimeError("非目标订单，禁止推进或继续接其他订单")
        self._run_remaining(deadline)
        if self.order_no != self.target_order_no:
            raise RuntimeError("安卓目标订单流转结果不一致")


class AndroidTargetOrderBase(AndroidOrderBase):
    """安卓目标订单基类，协调乘客端与司机端完成目标订单筛选和流转。"""
    __test__ = False

    def _create_driver_flow(self, args):
        """创建司机端目标订单流程实例并传入配置。"""
        return AndroidTargetDriverUIFlow(args, client=self.clients[self.driver_runtime.udid], settings=self.order_settings)

    def _driver_ui_go_online(self, tag):
        """准备新订单；司机遗留行程由公共前置检查拒绝。"""
        self.target_order_no = None
        self.legacy_order_no = None
        super()._driver_ui_go_online(tag)
        if self.resuming_order:
            raise RuntimeError("司机遗留订单未获本轮授权，禁止接续")

    @staticmethod
    def _passenger_page_texts(root):
        """提取乘客端页面树中所有节点的文本或content-desc，返回集合。"""
        return {node.get("text") or node.get("content-desc") or "" for node in root.iter()}

    def _complete_legacy_passenger_order(self, tag):
        """遗留订单不属于新场景的自动付款范围。"""
        raise RuntimeError("遗留订单未确认本轮归属与付款授权，禁止自动支付")

    def _ui_cleanup_ongoing_order(self, tag):
        """目标场景同样只检查前置，不自动处理遗留订单。"""
        return super()._ui_cleanup_ongoing_order(tag)

    def _adb(self, *arguments):
        """以指定设备执行只读ADB命令并返回标准输出。"""
        udid = self.order_settings["device"]["udid"]
        command = ["adb", "-s", udid, *arguments]
        try:
            return subprocess.run(command, capture_output=True, text=True, timeout=10, check=True).stdout
        except (OSError, subprocess.SubprocessError) as exc:
            raise RuntimeError("安卓无法只读获取乘客当前订单日志，未接单") from exc

    def _start_passenger_order_log(self):
        """获取乘客App进程ID并清空logcat缓存，准备订单状态日志抓取。"""
        pid = self._v150_passenger_pid("target_order")
        self._adb("logcat", "-c")
        return pid

    def _fresh_passenger_orders(self, pid):
        """按进程ID抓取最新logcat并提取乘客当前订单状态请求中的订单号。"""
        output = self._adb("logcat", "-d", f"--pid={pid}", "-v", "brief")
        return passenger_status_orders(output)

    @staticmethod
    def _validate_passenger_target_page(root):
        """校验乘客端当前页不是已取消、超时、失败或历史列表。"""
        texts = {node.get("label", "") for node in visible_nodes(root)}
        if any(keyword in text for text in texts
               for keyword in ("已取消", "訂單已超時", "订单已超时", "支付失敗", "支付失败")):
            raise RuntimeError("安卓乘客目标订单已取消、超时或失败，未重新下单")
        if texts.intersection({"我的行程", "行程記錄", "歷史訂單"}):
            raise RuntimeError("安卓乘客当前是历史列表，禁止用历史订单当目标")

    def _read_passenger_target(self):
        """读取乘客端目标订单号，优先从页面提取，必要时通过日志抓取。"""
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
        """读取乘客目标订单后驱动司机端抢单并执行流程。"""
        self.target_order_no = self._read_passenger_target()
        self.driver_ui.target_order_no = self.target_order_no
        super()._driver_ui_grab_and_flow(tag)
        if self.driver_ui.order_no != self.target_order_no:
            raise AssertionError("安卓司机接单结果不是本次乘客目标订单")

    def _run_order_flow(self):
        """执行订单流程并校验已完成订单与乘客目标订单一致。"""
        super()._run_order_flow()
        if not self.target_order_no or self.completed_order_no != self.target_order_no:
            raise AssertionError("安卓已完成订单不是本次乘客目标订单，不能判定通过")
