"""绑定真实订单、目标司机及完成终态；任何未知状态均不得判为通过。

本模块是订单侧的“证据层”：
  - 明确区分“已创建”“已被目标司机接单”“已完成且已支付”三种证据强度。
  - 只对本次绑定的那一笔订单做写操作，防止误伤他人订单。
  - 所有超时、未知状态、缺少字段一律抛 OrderValidationError，禁止降级放行。
"""

import logging
import time
from dataclasses import dataclass

logger = logging.getLogger("JRYG_HK_ios")


class OrderValidationError(AssertionError):
    """订单硬校验失败异常，继承 AssertionError 便于被 pytest 直接识别为失败。"""


def require(condition, message):
    """硬校验断言：条件不成立立即抛错，附带可读原因。"""
    if not condition:
        raise OrderValidationError(message)


def number(value, field):
    """把字段转为整数，类型错误或缺失时抛错，不接受 bool 与浮点。"""
    require(not isinstance(value, bool), f"{field} 类型错误")
    require(isinstance(value, (int, str)), f"缺少有效字段 {field}")
    try:
        return int(value)
    except ValueError:
        raise OrderValidationError(f"{field} 不是整数") from None


def order_id(value):
    """校验并返回订单号字符串，禁止空值或非字符串。"""
    require(isinstance(value, str) and bool(value.strip()), "缺少真实 order_no")
    return value.strip()


@dataclass(frozen=True)
class CompletedOrder:
    """已完成订单的证据快照（不可变）。"""

    order_no: str        # 订单号
    driver_id: str       # 目标司机 ID（11000005）
    passenger_status: int  # 乘客端订单状态（5 = 已完成）
    driver_status: int    # 司机端订单状态（8 = 行程完成）
    pay_status: int       # 支付状态（1 = 已支付）


class OrderGuard:
    """订单硬校验器：绑定唯一订单、确保目标司机接单、验证完成终态。"""

    def __init__(self, api, start_names, end_names, max_attempts=5,
                 dispatch_timeout=90, state_timeout=30, completion_timeout=90,
                 total_timeout=900, interval=2, clock=time.monotonic, sleep=time.sleep):
        """初始化校验器参数，并校验重试次数、超时与目标司机身份是否合法。"""
        # 重试次数与各级超时都必须为合法正值
        require(1 <= max_attempts <= 20, "重下单次数必须在1至20之间")
        require(all(v > 0 for v in (dispatch_timeout, state_timeout,
                                    completion_timeout, total_timeout, interval)), "超时必须为正数")
        self.api = api
        # 目标司机 ID，来自已校验的司机会话
        self.target_driver_id = str(api.driver_id)
        require(self.target_driver_id not in ("", "0", "None"), "目标司机ID未验证")
        # 允许的起点/终点名称集合
        self.start_names, self.end_names = set(start_names), set(end_names)
        self.max_attempts = max_attempts
        self.dispatch_timeout, self.state_timeout = dispatch_timeout, state_timeout
        self.completion_timeout, self.total_timeout = completion_timeout, total_timeout
        self.interval, self.clock, self.sleep = interval, clock, sleep
        # 当前绑定的订单号，所有写操作前都要核对
        self.bound_order_no = None
        # 已处理过的订单号，防止复用旧订单冒充新单
        self.seen = set()
        # 已验证完成的订单
        self.completed = []
        # 本轮总时限截止时间
        self.deadline = None

    def remaining(self):
        """返回总时限剩余秒数；已超时直接抛错，禁止继续写操作。"""
        if self.deadline is None:
            # 尚未开始计时时以总时限为准
            return self.total_timeout
        remaining = self.deadline - self.clock()
        require(remaining > 0, f"总时限已到，禁止继续写操作 order_no={self.bound_order_no}")
        return remaining

    def poll(self, description, query, predicate, timeout):
        """轮询查询直到条件满足；超时抛错，绝不把超时当作成功。"""
        deadline = self.clock() + timeout
        if self.deadline is not None:
            # 轮询期限不得超过总时限
            deadline = min(deadline, self.deadline)
        while self.clock() < deadline:
            value = query()
            if predicate(value):
                return value
            self.sleep(min(self.interval, max(0, deadline - self.clock())))
        raise OrderValidationError(f"{description}超时，order_no={self.bound_order_no}，禁止报告通过")

    def unfinished(self):
        """查询并校验未完成订单列表结构。"""
        rows = self.api.unfinished()
        require(isinstance(rows, list), "未完成订单响应缺少 list")
        require(all(isinstance(row, dict) for row in rows), "未完成订单条目格式错误")
        ids = [order_id(row.get("order_no")) for row in rows]
        # 订单号重复说明返回异常，不能继续
        require(len(ids) == len(set(ids)), "未完成订单号重复")
        return rows

    def check_route(self, row):
        """核对未完成订单的起终点与测试路线一致，不一致不得接管或取消。"""
        require(row.get("start_address") in self.start_names and
                row.get("end_address") in self.end_names,
                "未完成订单路线与测试路线不一致，禁止接管或取消")

    def status(self, no):
        """查询订单状态并校验返回的确实是该订单。"""
        no = order_id(no)
        data = self.api.status(no)
        require(isinstance(data, dict) and data.get("order_no") == no,
                "状态查询返回了其他订单或缺少order_no")
        number(data.get("order_status"), "passenger.order_status")
        return data

    def assigned_driver(self, state):
        """从状态中解析接单司机 ID；未分配司机时返回 None。"""
        value = state.get("driver_id")
        if value in (None, "", 0, "0"):
            # 还没有司机接单
            return None
        require(number(value, "driver_id") > 0, "司机ID无效")
        return str(value)

    def require_target(self, no, allow_complete=False):
        """确认订单号、订单状态与接单司机都符合预期。"""
        require(no == self.bound_order_no, "操作订单号与本次绑定订单不一致")
        state = self.status(no)
        status = number(state["order_status"], "passenger.order_status")
        require(status != -1, f"订单已取消: {no}")
        require(allow_complete or status != 5, "订单已经完成，不得再次流转")
        require(self.assigned_driver(state) == self.target_driver_id,
                f"订单{no}不是目标司机11000005接单或司机身份未知")
        return state

    def wait_assignment(self, no):
        """等待真实司机接单；期间订单被取消或完成立即失败。"""

        def assigned(state):
            """判定是否已有司机接单；期间取消或完成视为异常立即失败。"""
            require(number(state["order_status"], "order_status") not in (-1, 5),
                    "派单期间订单已取消或完成，禁止当作新单通过")
            return self.assigned_driver(state) is not None

        return self.poll("等待真实司机分配", lambda: self.status(no), assigned, self.dispatch_timeout)

    def cancel_wrong_driver(self, no):
        """取消由非目标司机接单的订单，确认取消终态后才允许再下单。"""
        state = self.status(no)
        driver = self.assigned_driver(state)
        require(no == self.bound_order_no, "禁止取消未绑定订单")
        # 只有确认是别的司机接单才允许取消
        require(driver is not None and driver != self.target_driver_id,
                "司机未知或已是目标司机，禁止错误取消")
        require(number(state["order_status"], "order_status") not in (-1, 5),
                "订单已经结束，禁止重复取消")
        logger.warning("非目标司机接单，取消 order_no=%s driver_id=%s", no, driver)
        self.api.prepare_cancel(no)
        # 取消前再查一次，确认司机与状态未变化
        latest = self.status(no)
        require(self.assigned_driver(latest) == driver and
                number(latest["order_status"], "order_status") not in (-1, 5),
                "取消前司机或订单状态已变化，停止操作")
        self.remaining()
        result = self.api.cancel(no)
        # 取消必须被服务端确认
        require(isinstance(result, dict) and result.get("canceled") is True,
                f"取消未确认成功: {no}，禁止重下单")
        # 等待订单进入已取消终态
        self.poll("确认取消终态", lambda: self.status(no),
                  lambda s: number(s["order_status"], "order_status") == -1, self.state_timeout)
        # 并确认它已从未完成列表消失
        self.poll("确认订单退出未完成列表", self.unfinished,
                  lambda rows: all(row["order_no"] != no for row in rows), self.state_timeout)
        self.seen.add(no)
        logger.info("已确认取消 order_no=%s，才允许下一次下单", no)

    def bind_new(self):
        """绑定本轮 UI 创建的唯一新订单。"""

        def candidate(rows):
            """判定未完成列表中是否唯一出现本轮可绑定的新订单。"""
            # 多笔订单时无法唯一绑定，立即停止
            require(len(rows) <= 1, "出现多笔订单，无法唯一绑定，停止操作")
            if not rows:
                return False
            self.check_route(rows[0])
            # 复用旧订单号说明拿到的是历史单，不算新单
            require(rows[0]["order_no"] not in self.seen, "复用了旧订单号，禁止当作新单")
            return True

        rows = self.poll("等待本次UI创建的唯一新订单", self.unfinished, candidate, self.state_timeout)
        self.bound_order_no = order_id(rows[0]["order_no"])
        # 立刻查一次状态，验证回包确实对应这个订单
        self.status(self.bound_order_no)
        logger.info("绑定新订单 order_no=%s", self.bound_order_no)
        return self.bound_order_no

    def verify_completed(self, no):
        """验证同一订单已由目标司机完成且已支付。"""

        def query():
            """同时取出乘客端状态、司机端状态与支付状态三个终态字段。"""
            state = self.require_target(no, allow_complete=True)
            detail = self.api.trip_detail(no)
            require(isinstance(detail, dict) and detail.get("order_no") == no,
                    "司机详情缺少当前order_no或返回了其他订单")
            order = detail.get("order")
            require(isinstance(order, dict), "司机详情缺少order")
            ds = number(order.get("order_status"), "driver.order_status")
            pay = number(order.get("pay_status"), "pay_status")
            require(ds != 9, "司机详情显示订单已取消，不是完成")
            return state, ds, pay

        # 三个终态字段必须同时满足：乘客端=5、司机端=8、支付=1
        state, ds, pay = self.poll(
            "等待同一订单已完成且已支付", query,
            lambda value: number(value[0]["order_status"], "order_status") == 5 and
            value[1] == 8 and value[2] == 1, self.completion_timeout)
        # 完成订单同样必须退出未完成列表
        self.poll("完成订单退出未完成列表", self.unfinished,
                  lambda rows: all(row["order_no"] != no for row in rows), self.state_timeout)
        result = CompletedOrder(no, self.target_driver_id, 5, ds, pay)
        logger.info("完成硬校验 order_no=%s driver_id=%s passenger_status=5 driver_status=8 pay_status=1",
                    no, self.target_driver_id)
        return result

    def run(self, place_order, finish_order, reset_ui):
        """执行一轮“下单 → 等待目标司机 → 完成订单”的硬校验流程。

        place_order  : 触发 UI 下单
        finish_order : 推进司机端服务状态直到完成
        reset_ui     : 把 UI 复位到可再次下单的状态
        """
        # 设定本轮总时限
        self.deadline = self.clock() + self.total_timeout
        rows = self.unfinished()
        # 多笔未完成订单时无法确定当前订单，禁止批量取消
        require(len(rows) <= 1, "存在多笔未完成订单，禁止批量取消或猜测当前订单")
        pending = None
        # 是否是接管的历史订单（接管单不允许当作本轮场景通过）
        existing = bool(rows)
        if rows:
            self.check_route(rows[0])
            pending = order_id(rows[0]["order_no"])
            require(pending not in self.seen, "已处理订单仍在未完成列表，停止运行")
            self.bound_order_no = pending
            logger.info("接管已有订单，不能冒充新单 order_no=%s", pending)
        for attempt in range(1, self.max_attempts + 1):
            require(self.clock() < self.deadline, "重下单总时限已到")
            if pending is None:
                # 下单前必须确认没有任何未完成订单
                require(not self.unfinished(), "仍有未完成订单，禁止重复下单")
                reset_ui()
                # 复位期间若出现新订单说明状态不一致，停止
                require(not self.unfinished(), "准备下单期间出现其他订单，停止")
                self.remaining()
                place_order()
                pending = self.bind_new()
                existing = False
            self.bound_order_no = pending
            state = self.wait_assignment(pending)
            if self.assigned_driver(state) != self.target_driver_id:
                # 非目标司机接单：先取消再重试
                self.cancel_wrong_driver(pending)
                pending = None
                if attempt < self.max_attempts:
                    self.sleep(self.interval)
                continue
            # 接管的历史订单未经本轮车型/支付方式验证，不能算场景通过
            require(not existing, "已有目标司机未完成订单，但车型和支付方式未经本轮验证；"
                    "禁止当作新场景通过，请先核实并完成该订单")
            self.require_target(pending)
            self.remaining()
            finish_order(pending)
            result = self.verify_completed(pending)
            self.seen.add(pending)
            self.completed.append(result)
            return result
        raise OrderValidationError(f"已达到{self.max_attempts}次上限，仍未由11000005完成订单；本次失败")

    def assert_all_completed(self, expected_count):
        """校验已完成订单数量与唯一性，并确保没有遗留未完成订单。"""
        require(len(self.completed) == expected_count, "缺少已验证完成的订单，禁止全部通过")
        require(len({r.order_no for r in self.completed}) == expected_count, "不同场景复用了同一订单")
        for result in self.completed:
            # 逐单重新复核终态，防止状态在收尾阶段被改动
            self.bound_order_no = result.order_no
            self.deadline = self.clock() + self.completion_timeout
            self.verify_completed(result.order_no)
        require(not self.unfinished(), "当前账号仍有未完成订单，禁止全部通过")
