"""香港乘客端 V1.6.0 履约状态、分享安全与通知的纯内存离线模型。

对应需求点 8（呼叫与取消提示）、需求点 9（预约接单后履约状态机）、
需求点 10（一口价弹框与消息栏）、需求点 11（预约通知/收据）、
需求点 12（安全能力与分享）、需求点 13（我的行程）。

不连接设备、不访问网络，不补写文档未定义的枚举。
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from .booking_contract import (
    SHARE_INVALID_HOURS_AFTER_END,
    SHARE_VALID_HOURS_AFTER_ACCEPT,
    driver_location_exposed,
)
from .contract import BOOKING_LABEL, ORDER_TYPE_BOOKING


# ---------------------------------------------------------------------------
# 订单状态
# ---------------------------------------------------------------------------
# 乘客侧订单状态（/passenger/order/status、/passenger/order/detail）
ORDER_STATUS_WAITING = 0        # 待派单
ORDER_STATUS_ACCEPTED = 100     # 司机已接单（预约业务为待服务）
ORDER_STATUS_PICKED_UP = 101    # 已上车
ORDER_STATUS_ARRIVED = 102      # 到达起点
ORDER_STATUS_IN_TRIP = 103      # 送驾中
ORDER_STATUS_BILL_PENDING = 104  # 待确认账单
ORDER_STATUS_UNPAID = 105       # 待支付
ORDER_STATUS_PAID = 106         # 已支付
ORDER_STATUS_CANCELLED = 107    # 已取消

#: 订单中心取消原因
ORDER_CANCEL_REASON_DISPATCH_TIMEOUT = "dispatch_timeout"
ORDER_CANCEL_REASON_PASSENGER_CANCEL = "passenger_cancel"
ORDER_CANCEL_REASON_DRIVER_CANCEL = "driver_cancel"


@dataclass(frozen=True)
class OrderStatusInfo:
    """订单状态信息。

    :param order_status:      订单状态码。
    :param order_type:        5=即时，6=预约。
    :param driver_location_visible: 是否下发司机位置。
    """
    order_status: int
    order_type: int
    driver_location_visible: bool = True


def resolve_booking_status(accepted_at: Optional[datetime],
                           driver_pickup_at: Optional[datetime],
                           arrived_at: Optional[datetime],
                           in_trip_at: Optional[datetime],
                           bill_pushed_at: Optional[datetime],
                           paid_at: Optional[datetime],
                           use_time: Optional[datetime] = None,
                           now: Optional[datetime] = None,
                           cancelled: bool = False,
                           unpaid_at: Optional[datetime] = None) -> OrderStatusInfo:
    """解析预约订单当前状态。

    状态流转：
    司机接单 -> 待服务(100)；司机侧开始接驾 -> 接驾(101)；
    到达起点 -> 到达起点(102)；送驾 -> 送驾(103)；
    推送账单 -> 待确认账单(104)；待支付(105)；已支付(106)。

    :param cancelled: 订单已取消。
    :param unpaid_at:  进入待支付状态的时间点（可与 bill_pushed_at 同时）。
    :raises ValueError: 状态时间顺序矛盾（接驾早于接单等）。
    """
    if cancelled:
        return OrderStatusInfo(ORDER_STATUS_CANCELLED, 6, False)

    ordered = [
        (accepted_at, ORDER_STATUS_ACCEPTED),
        (driver_pickup_at, ORDER_STATUS_PICKED_UP),
        (arrived_at, ORDER_STATUS_ARRIVED),
        (in_trip_at, ORDER_STATUS_IN_TRIP),
        (bill_pushed_at, ORDER_STATUS_BILL_PENDING),
        (unpaid_at, ORDER_STATUS_UNPAID),
        (paid_at, ORDER_STATUS_PAID),
    ]
    present = [(t, s) for t, s in ordered if t is not None]
    for index in range(1, len(present)):
        if present[index][0] < present[index - 1][0]:
            raise ValueError("订单状态时间顺序矛盾")

    if not present:
        return OrderStatusInfo(ORDER_STATUS_WAITING, 6, False)

    _, status = present[-1]

    # 司机位置暴露：出发时间前 20 分钟内才下发
    visible = True
    if status == ORDER_STATUS_ACCEPTED and use_time and now:
        visible = driver_location_exposed(use_time, now)
    return OrderStatusInfo(status, 6, visible)


# ---------------------------------------------------------------------------
# 待服务 / 接驾 状态文案
# ---------------------------------------------------------------------------
def waiting_service_main_text(use_time: datetime) -> str:
    """待服务状态主文案：「預約成功，2026-11-13 20:25 出發」。"""
    return f"預約成功，{format_departure_time(use_time)} 出發"


def waiting_service_sub_text() -> str:
    """待服务状态副文案。"""
    return "出發前20分鐘可查看司機位置"


def pickup_main_text() -> str:
    """接驾状态主文案。"""
    return "司機正趕來接您"


def pickup_sub_text(use_time: datetime) -> str:
    """接驾状态副文案。"""
    return f"{format_departure_time(use_time)} 出發，請您提前前往上車地點等候"


def format_departure_time(value: datetime) -> str:
    """出发时间展示格式：yyyy-MM-dd HH:mm。"""
    return value.strftime("%Y-%m-%d %H:%M")


def booking_label_visible(order_type: int) -> bool:
    """「預約用車」标签仅预约业务展示。"""
    return order_type == 6


def business_label(order_type: int) -> str:
    """业务标签文案；即时业务返回空串。"""
    return BOOKING_LABEL if order_type == 6 else ""


# ---------------------------------------------------------------------------
# 预约可用状态分组（需求点 13：我的行程）
# ---------------------------------------------------------------------------
GROUP_BOOKING = "booking"        # 預約中
GROUP_WAITING_SERVICE = "waiting_service"  # 待服務
GROUP_IN_SERVICE = "in_service"  # 服務中
GROUP_UNPAID = "unpaid"          # 待支付
GROUP_COMPLETED = "completed"    # 已完成
GROUP_CANCELLED = "cancelled"    # 已取消


def trip_group_of(order_status: int, order_type: int) -> str:
    """按订单状态返回「我的行程」分组。

    - 進行中：預約中、待服務（已接單待接駕）、服務中（已接單接駕、到達起點、
      送駕、行程結束待推送帳單）。
    - 待支付：待支付。
    - 已完成：已完成（完單已支付）、已取消（呼叫超時取消 / 接單前取消 / 接單後取消）。

    PRD 明确「已接单待接驾态展示为待服务」，接驾后即进入服务中。
    """
    if order_status == ORDER_STATUS_WAITING:
        return GROUP_BOOKING
    if order_status == ORDER_STATUS_ACCEPTED:
        return GROUP_WAITING_SERVICE
    if order_status in (ORDER_STATUS_PICKED_UP, ORDER_STATUS_ARRIVED,
                         ORDER_STATUS_IN_TRIP, ORDER_STATUS_BILL_PENDING):
        return GROUP_IN_SERVICE
    if order_status == ORDER_STATUS_UNPAID:
        return GROUP_UNPAID
    if order_status == ORDER_STATUS_PAID:
        return GROUP_COMPLETED
    if order_status == ORDER_STATUS_CANCELLED:
        return GROUP_CANCELLED
    return GROUP_COMPLETED


def home_card_visible(order_status: int, order_type: int) -> bool:
    """首页进行中订单卡片可见状态。

    预约业务新增：已接单待接驾、接驾、到达起点、送驾。
    """
    if order_type == 6:
        return order_status in (
            ORDER_STATUS_ACCEPTED,
            ORDER_STATUS_PICKED_UP,
            ORDER_STATUS_ARRIVED,
            ORDER_STATUS_IN_TRIP,
        )
    return order_status in (
        ORDER_STATUS_ACCEPTED,
        ORDER_STATUS_PICKED_UP,
        ORDER_STATUS_ARRIVED,
        ORDER_STATUS_IN_TRIP,
    )


# ---------------------------------------------------------------------------
# 分享（需求点 12）
# ---------------------------------------------------------------------------
SHARE_STATE_VALID = "valid"
SHARE_STATE_EXPIRED = "expired"

#: 分享落地页支持展示的状态
SHARE_SUPPORTED_STATUS = (
    ORDER_STATUS_ACCEPTED,
    ORDER_STATUS_PICKED_UP,
    ORDER_STATUS_ARRIVED,
    ORDER_STATUS_IN_TRIP,
    ORDER_STATUS_PAID,
    ORDER_STATUS_CANCELLED,
)


def share_supported(order_status: int) -> bool:
    """该订单状态是否支持行程分享。

    待服务、接驾、到达起点、送驾、行程结束支持主动分享。
    """
    return order_status in SHARE_SUPPORTED_STATUS


def share_expire_at(accepted_at: Optional[datetime],
                    trip_ended_at: Optional[datetime]) -> Optional[datetime]:
    """返回分享失效时刻。

    - 接单后分享有效时限 72 小时。
    - 行程结束后 12 小时进入失效状态（取两者较早者）。
    """
    candidates = []
    if accepted_at:
        candidates.append(accepted_at + timedelta(hours=SHARE_VALID_HOURS_AFTER_ACCEPT))
    if trip_ended_at:
        candidates.append(trip_ended_at + timedelta(hours=SHARE_INVALID_HOURS_AFTER_END))
    if not candidates:
        return None
    return min(candidates)


def share_state(accepted_at: Optional[datetime],
                trip_ended_at: Optional[datetime],
                now: datetime) -> str:
    """判断分享状态是否有效。"""
    expire_at = share_expire_at(accepted_at, trip_ended_at)
    if expire_at is None:
        return SHARE_STATE_VALID
    return SHARE_STATE_VALID if now < expire_at else SHARE_STATE_EXPIRED


# ---------------------------------------------------------------------------
# 安全中心与自动分享（需求点 12）
# ---------------------------------------------------------------------------
AUTO_SHARE_TRIGGER_ARRIVED = "arrived_at_origin"

#: 触发 999 报警时的行程短信，无论是否开启自动分享均发送
EMERGENCY_ALWAYS_SEND_SMS = True


def auto_share_trigger(status_code: int) -> Optional[str]:
    """返回自动分享行程短信的触发时机。

    预约业务自动分享时机调整为到达起点；
    即时业务沿用既有时机（此处不展开即时细节，返回 None）。
    """
    if status_code == ORDER_STATUS_ARRIVED:
        return AUTO_SHARE_TRIGGER_ARRIVED
    return None


def emergency_sms_required(auto_share_enabled: bool) -> bool:
    """999 报警时是否发送行程短信。

    无论是否开启自动分享均发送。
    """
    return EMERGENCY_ALWAYS_SEND_SMS or auto_share_enabled


def safety_entry_visible(order_type: int) -> bool:
    """预约与即时业务均展示安全中心入口。"""
    return order_type in (5, 6)


# ---------------------------------------------------------------------------
# 短信通知（需求点 11）
# ---------------------------------------------------------------------------
SMS_TEMPLATE_DRIVER_ACCEPTED_BOOKING = (
    "【陽光出行】司機{1}已接單，預約出發時間為{2}"
)
SMS_TEMPLATE_DRIVER_CANCEL = "【陽光出行】司機已取消本次行程，您可嘗試重新下單。"
SMS_TEMPLATE_TRIP_ENDED = (
    "【陽光出行】行程已結束，請您帶好隨身物品，開門時注意側後方來車。"
)


def driver_accepted_sms(driver_plate: str, use_time: datetime) -> str:
    """生成司机接单短信（预约业务新增模板）。

    模板占位符沿用 PRD 的 ``{1}``/``{2}`` 编号形式。

    :param driver_plate: 司机车牌号。
    :param use_time:     预约出发时间。
    """
    return (SMS_TEMPLATE_DRIVER_ACCEPTED_BOOKING
            .replace("{1}", driver_plate)
            .replace("{2}", format_departure_time(use_time)))


def driver_cancel_sms() -> str:
    """司机取消订单短信（复用即时模板）。"""
    return SMS_TEMPLATE_DRIVER_CANCEL


def trip_ended_sms() -> str:
    """行程结束短信（复用即时模板）。"""
    return SMS_TEMPLATE_TRIP_ENDED


# ---------------------------------------------------------------------------
# 收据（需求点 11）
# ---------------------------------------------------------------------------
RECEIPT_AUTO_SEND_TYPES = (5, 6)


def receipt_supported(order_type: int) -> bool:
    """预约与即时业务均支持收据。"""
    return order_type in RECEIPT_AUTO_SEND_TYPES


def receipt_auto_send_eligible(order_type: int, paid: bool,
                               email: Optional[str] = None) -> bool:
    """完单后是否自动发送收据邮件。

    - 需已支付。
    - 需已配置邮箱。
    - 预约与即时业务都支持。
    """
    return receipt_supported(order_type) and paid and bool(email)


def receipt_manual_send_allowed(order_type: int, paid: bool,
                                email: Optional[str] = None) -> bool:
    """乘客主动发送收据是否允许。"""
    return receipt_supported(order_type) and paid and bool(email)


def receipt_fixed_entry_visible(order_type: int) -> bool:
    """完单页固定【發送行程收據】入口可见性。"""
    return receipt_supported(order_type)


# ---------------------------------------------------------------------------
# 评价（需求点 11）
# ---------------------------------------------------------------------------
def evaluation_supported(order_type: int) -> bool:
    """预约与即时业务均支持评价。"""
    return order_type in (5, 6)


# ---------------------------------------------------------------------------
# 订单中心查询（需求点 13 / 接口）
# ---------------------------------------------------------------------------
def unfinished_list_params(order_type: int) -> Dict:
    """服务中订单列表查询入参。"""
    return {"order_type": order_type}


def unfinished_order_params(order_type: int) -> Dict:
    """服务中订单查询入参。"""
    return {"order_type": order_type}


def cancel_count_params(order_type: int) -> Dict:
    """取消订单次数查询入参。

    即时与预约分别查询，互不占用对方的并行额度。
    """
    return {"order_type": order_type}


# ---------------------------------------------------------------------------
# 预付取消退款提示（需求点 8）
# ---------------------------------------------------------------------------
def cancel_refund_notice_required(is_paid_advance: bool,
                                  order_type: int = 6) -> bool:
    """预付订单取消页是否展示原路退款提示。"""
    return bool(is_paid_advance)


# ---------------------------------------------------------------------------
# 派单与 MQ（技术方案）
# ---------------------------------------------------------------------------
BUSINESS_RIDE_HAILING = 2


def should_dispatch_after_payment(business_type: int, order_type: int) -> bool:
    """支付完成后是否发单。

    - business_type=2（网约车）：order_type=5（即时）发单，order_type=6（预约）不发单。
    - 出租车即时（order_type=5）发单；预约不发单。
    """
    if order_type == ORDER_TYPE_BOOKING:
        return False
    return True


PAY_BROADCAST_TOPIC = "topic_cashier_trade_order_pay_broadcast"
PAY_BROADCAST_CONSUMER_GROUP = "consumer_group_order_service_trade_order_pay_broadcast"
PAY_BROADCAST_FORWARD_TOPIC = "topic_order_service_order_pay_broadcast"
PAY_BROADCAST_FORWARD_DELAY_SECONDS = 1
PASSENGER_PAY_CONSUMER_GROUP = "consumer_group_passenger_service_trade_order_pay_broadcast"


@dataclass
class OrderPaySyncMessage:
    """支付完成转发 MQ 消息体。

    对应技术方案给出的 OrderPaySyncMessage 结构。
    """
    order_id: int = 0
    order_no: str = ""
    trade_no: str = ""
    order_type: int = 5
    city_id: int = 0
    agent_id: int = 0
    is_paid_advance: bool = False
    pay_channel_name: str = ""
    pay_amount: int = 0
    total_discount_amount: int = 0
    discount_amount: int = 0
    agent_discount_amount: int = 0
    premium_amount: int = 0
    voucher_amount: int = 0
    voucher_id: str = ""
    pay_type: int = 1
    company_trade_no: str = ""
    company_pay_agent: int = 0
    business_type: int = 1

    def to_dict(self) -> Dict:
        """转为 MQ 消息 JSON 结构（不含 EventID）。"""
        return {
            "order_id": self.order_id,
            "order_no": self.order_no,
            "trade_no": self.trade_no,
            "order_type": self.order_type,
            "city_id": self.city_id,
            "agent_id": self.agent_id,
            "is_paid_advance": self.is_paid_advance,
            "pay_channel_name": self.pay_channel_name,
            "pay_amount": self.pay_amount,
            "total_discount_amount": self.total_discount_amount,
            "discount_amount": self.discount_amount,
            "agent_discount_amount": self.agent_discount_amount,
            "premium_amount": self.premium_amount,
            "voucher_amount": self.voucher_amount,
            "voucher_id": self.voucher_id,
            "pay_type": self.pay_type,
            "company_trade_no": self.company_trade_no,
            "company_pay_agent": self.company_pay_agent,
            # business_type 不在文档定义的 18 字段中，不写入 MQ JSON；
            # 仅保留在 dataclass 上供 should_dispatch() 内部逻辑使用。
        }

    def should_dispatch(self) -> bool:
        """该消息是否应触发派单。"""
        return should_dispatch_after_payment(self.business_type, self.order_type)


# MQ 消息字段清单（对应文档 OrderPaySyncMessage struct）
ORDER_PAY_SYNC_FIELDS = (
    "order_id", "order_no", "trade_no", "order_type", "city_id",
    "agent_id", "is_paid_advance", "pay_channel_name", "pay_amount",
    "total_discount_amount", "discount_amount", "agent_discount_amount",
    "premium_amount", "voucher_amount", "voucher_id", "pay_type",
    "company_trade_no", "company_pay_agent",
)


def build_pay_sync_message(order_id, order_no, trade_no, order_type=5,
                           city_id=0, agent_id=0, is_paid_advance=False,
                           pay_channel_name="", pay_amount=0,
                           total_discount_amount=0, discount_amount=0,
                           agent_discount_amount=0, premium_amount=0,
                           voucher_amount=0, voucher_id="", pay_type=1,
                           company_trade_no="", company_pay_agent=0,
                           business_type=1) -> OrderPaySyncMessage:
    """构造支付完成转发 MQ 消息。

    Topic: topic_cashier_trade_order_pay_broadcast
    Consumer: consumer_group_order_service_trade_order_pay_broadcast
    转发 Topic: topic_order_service_order_pay_broadcast (延时 1s)
    """
    return OrderPaySyncMessage(
        order_id=order_id,
        order_no=order_no,
        trade_no=trade_no,
        order_type=order_type,
        city_id=city_id,
        agent_id=agent_id,
        is_paid_advance=is_paid_advance,
        pay_channel_name=pay_channel_name,
        pay_amount=pay_amount,
        total_discount_amount=total_discount_amount,
        discount_amount=discount_amount,
        agent_discount_amount=agent_discount_amount,
        premium_amount=premium_amount,
        voucher_amount=voucher_amount,
        voucher_id=voucher_id,
        pay_type=pay_type,
        company_trade_no=company_trade_no,
        company_pay_agent=company_pay_agent,
        business_type=business_type,
    )


def passenger_pay_consumer_topic() -> str:
    """passenger-service 消费 topic_order_service_order_pay_broadcast。"""
    return PAY_BROADCAST_FORWARD_TOPIC



# ---------------------------------------------------------------------------
# V1.6.0 版本准入（技术方案 7.2）
# ---------------------------------------------------------------------------
CONTRACT_VERSION_TAG = "hk_passenger_contract_version"
CONTRACT_VERSION_VALUE = "1.6.0"


def _parse_version(version: str) -> tuple:
    """将点分版本号解析为可比较的整数元组，如 '1.10.0' → (1, 10, 0)。"""
    parts = []
    for part in version.split("."):
        try:
            parts.append(int(part))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def hit_v160(grayscale_enabled: bool, agent_id: int,
             client_version: str, gray_scope_agent_ids: List[int],
             gray_min_version: str = "") -> bool:
    """判断是否命中 V1.6.0。

    新订单必须同时满足总开关开启和现有 strategy.Gray.HitCheck 灰度命中。
    灰度以请求 agent_id 为 scope、客户端版本为 condition。
    """
    if not grayscale_enabled:
        return False
    if gray_scope_agent_ids and agent_id not in gray_scope_agent_ids:
        return False
    if gray_min_version and _parse_version(client_version) < _parse_version(gray_min_version):
        return False
    return True


def contract_version_tag(hit: bool) -> Optional[str]:
    """命中时写入订单附加信息的版本标记。"""
    return CONTRACT_VERSION_VALUE if hit else None


def legacy_compatible_order(order_type: int, is_new_car_type: bool,
                            hit_v160_flag: bool) -> bool:
    """新老版本兼容判定。

    新老版本兼容开关启用时，仅限制老版本创建新增网约车订单；
    既有出租车即时、预约下单不受影响。
    """
    if order_type == 5 and not is_new_car_type:
        return True
    if not hit_v160_flag:
        # 未命中 V1.6.0 时，老版本不得创建新增网约车订单
        return not is_new_car_type
    return True
