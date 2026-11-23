"""香港乘客端 V1.6.0 预约业务规则的纯内存离线模型。

对应需求点 6（预约规则）、需求点 7（预约支付与优惠券）、需求点 8（呼叫与取消），
以及技术方案 7.2（下单支付分流、优惠券、服务偏好与并行订单）。

不连接设备、不访问网络，不补写文档未定义的枚举或错误码。
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from .contract import (
    CANCEL_REFUND_NOTICE,
    ORDER_TYPE_BOOKING,
    ORDER_TYPE_INSTANT,
    CarTypeEntry,
    CarTypeCatalog,
    resolve_payment_collection_mode,
)


# ---------------------------------------------------------------------------
# 文档常量
# ---------------------------------------------------------------------------
BOOKING_MIN_MINUTES = 30
BOOKING_MAX_MINUTES = 72 * 60

#: 接单后取消次数每日上限（当日累计取消达到该值后限制新建预约）
BOOKING_DAILY_CANCEL_LIMIT = 5

#: 司机位置暴露时限：出发时间前 N 分钟内才下发司机位置
DRIVER_LOCATION_EXPOSURE_MINUTES = 20

#: 呼叫超时自动取消：出发时间前 N 分钟
BOOKING_DISPATCH_TIMEOUT_MINUTES = 10

#: 分享有效期
SHARE_VALID_HOURS_AFTER_ACCEPT = 72
SHARE_INVALID_HOURS_AFTER_END = 12

#: 取消次数统计开关（capp.booking_cancel_limit_enabled）
BOOKING_CANCEL_LIMIT_ENABLED_KEY = "booking_cancel_limit_enabled"


# ---------------------------------------------------------------------------
# 预约时间规则
# ---------------------------------------------------------------------------
def validate_booking_time(now: datetime, use_time: datetime) -> Tuple[bool, str]:
    """校验预约出发时间。

    范围为当前时间后 30 分钟至 72 小时（闭区间）。
    以起点当地时间为准，由调用方保证 now/use_time 使用同一时区。

    :return: (是否合法, 错误提示)
    """
    delta = use_time - now
    if delta < timedelta(minutes=BOOKING_MIN_MINUTES):
        return False, f"預約時間不足{BOOKING_MIN_MINUTES}分鐘，請重新選擇"
    if delta > timedelta(minutes=BOOKING_MAX_MINUTES):
        return False, "預約時間不可超過72小時"
    return True, ""


def booking_time_bounds(now: datetime) -> Tuple[datetime, datetime]:
    """返回可预约时间范围的最早与最晚时间（闭区间）。"""
    return (now + timedelta(minutes=BOOKING_MIN_MINUTES),
            now + timedelta(minutes=BOOKING_MAX_MINUTES))


def derive_order_type(use_time: datetime, now: datetime) -> int:
    """从报价缓存的 use_time 派生 order_type。

    use_time 距当前时间不足预约下限按即时（5）处理，否则为预约（6）。
    """
    if use_time - now < timedelta(minutes=BOOKING_MIN_MINUTES):
        return ORDER_TYPE_INSTANT
    return ORDER_TYPE_BOOKING


def is_booking_time(use_time: datetime, now: datetime) -> bool:
    """判断 use_time 是否构成预约业务。"""
    return derive_order_type(use_time, now) == ORDER_TYPE_BOOKING


# ---------------------------------------------------------------------------
# 出发时间入口与报价刷新（需求点 5）
# ---------------------------------------------------------------------------
@dataclass
class DepartureTimeState:
    """出发时间选择状态。

    :param now_selected:   是否选中「現在出發」。
    :param use_time:       预约出发时间（now_selected 为 False 时有效）。
    :param last_quote_use_time: 上次询价对应的 use_time，用于判断是否需刷新报价。
    """
    now_selected: bool = True
    use_time: Optional[datetime] = None
    last_quote_use_time: Optional[datetime] = None

    def select_now(self) -> "DepartureTimeState":
        """选择「現在出發」，切回即时业务。"""
        return DepartureTimeState(
            now_selected=True,
            use_time=None,
            last_quote_use_time=self.last_quote_use_time,
        )

    def select_time(self, use_time: datetime) -> "DepartureTimeState":
        """选择预约时间，切到预约业务。"""
        return DepartureTimeState(
            now_selected=False,
            use_time=use_time,
            last_quote_use_time=self.last_quote_use_time,
        )

    @property
    def order_type(self) -> int:
        """当前业务类型：5=即时，6=预约。"""
        return ORDER_TYPE_INSTANT if self.now_selected else ORDER_TYPE_BOOKING

    def needs_requote(self) -> bool:
        """出发时间实际变化后需刷新报价；选项未变化不刷新。"""
        if self.now_selected:
            # 即时业务以「现在」为基准，无法感知秒级变化，用哨兵值比较
            return self.last_quote_use_time is not None and \
                self.last_quote_use_time != self.use_time
        if self.use_time is None:
            return False
        return self.last_quote_use_time != self.use_time

    def mark_requoted(self, use_time: Optional[datetime] = None) -> "DepartureTimeState":
        """记录已按给定 use_time 询价。"""
        return DepartureTimeState(
            now_selected=self.now_selected,
            use_time=self.use_time,
            last_quote_use_time=use_time if use_time is not None else self.use_time,
        )


def departure_time_entry_visible(booking_entry_enabled: bool) -> bool:
    """车型选择页出发时间入口与首页预约入口共用开关。

    关闭后不展示该入口，无法从即时切换至预约业务。
    """
    return bool(booking_entry_enabled)


# ---------------------------------------------------------------------------
# 服务偏好（需求点 5 / 7）
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ServicePreference:
    """服务偏好集合。

    :param children: 儿童服务。
    :param pet:      宠物服务。
    """
    children: bool = False
    pet: bool = False

    @property
    def is_empty(self) -> bool:
        """是否未选择任何偏好。"""
        return not self.children and not self.pet


def merge_service_preference(current: ServicePreference,
                             children: Optional[bool] = None,
                             pet: Optional[bool] = None) -> ServicePreference:
    """切换出发时间后保留已选服务偏好。

    仅覆盖显式传入的项，None 表示保持原值。
    """
    return ServicePreference(
        children=current.children if children is None else bool(children),
        pet=current.pet if pet is None else bool(pet),
    )


def validate_service_preference(preference: ServicePreference) -> Tuple[bool, str]:
    """校验服务偏好白名单。

    当前版本 children / pet 均为受支持项，返回 (True, "")。
    """
    if preference.children and not isinstance(preference.children, bool):
        return False, "invalid_children_flag"
    if preference.pet and not isinstance(preference.pet, bool):
        return False, "invalid_pet_flag"
    return True, ""


def service_preference_to_params(preference: ServicePreference) -> List[int]:
    """将服务偏好转换为订单扩展与派单参数。

    :return: 参数 id 列表，children 与 pet 按固定顺序输出。
    """
    params: List[int] = []
    if preference.children:
        params.append(1)
    if preference.pet:
        params.append(2)
    return params


# ---------------------------------------------------------------------------
# 优惠券口径（需求点 7 / 技术方案 7.2）
# ---------------------------------------------------------------------------
def coupon_supported(entry: CarTypeEntry, is_booking: bool) -> bool:
    """判断车型在当前业务下是否支持优惠券。

    - 预约业务全部车型不支持优惠券。
    - 即时业务网约车与即时出租车一致，均支持。
    """
    if is_booking:
        return False
    return True


def coupon_assess_params(order_type: int) -> Dict[str, int]:
    """构造询价匹配优惠券入参（新增 order_type）。

    即时业务使用 ServiceType=OrderTypeReal，当前时间进行券匹配。
    """
    return {"order_type": order_type}


def reject_coupon_for_booking(order_type: int, coupon_code: Optional[str]) -> None:
    """预约订单携带优惠券时在调用订单中心前拒绝。

    :raises ValueError: 预约订单携带 coupon_code。
    """
    if order_type == ORDER_TYPE_BOOKING and coupon_code:
        raise ValueError("預約用車不支持使用優惠券")


def estimate_coupon_list_payload(order_type: int) -> Dict:
    """构造询价优惠券列表入参（新增 order_type）。

    预约业务返回空可用结果，不调用优惠券匹配。
    """
    return {"order_type": order_type, "coupons": []}


def coupon_display_scope(order_type: int, logged_in: bool) -> str:
    """优惠信息展示口径。

    - 预约业务不展示优惠入口数据。
    - 即时业务未登录 / 预估详情 / 费用详情沿用即时出租车展示口径。
    """
    if order_type == ORDER_TYPE_BOOKING:
        return "none"
    if not logged_in:
        return "instant_taxi_guest"
    return "instant_taxi"


# ---------------------------------------------------------------------------
# 并行订单与取消限制（需求点 6 / 技术方案 7.2）
# ---------------------------------------------------------------------------
@dataclass
class BookingCreateContext:
    """预约创建校验上下文。

    :param user_id:                 下单用户 id（锁键）。
    :param now:                     当前时间。
    :param use_time:                预约出发时间。
    :param active_booking_count:    进行中预约订单数量。
    :param active_instant_count:    进行中即时订单数量。
    :param today_cancel_count:      当日预约取消次数。
    :param cancel_limit_enabled:    取消次数统计开关。
    """
    user_id: int
    now: datetime
    use_time: datetime
    active_booking_count: int = 0
    active_instant_count: int = 0
    today_cancel_count: int = 0
    cancel_limit_enabled: bool = True


@dataclass
class BookingCreateCheck:
    """预约创建校验结果。

    :param ok:       是否通过。
    :param reason:   失败原因标识。
    :param message:  面向用户的提示。
    """
    ok: bool
    reason: str = ""
    message: str = ""

    def __bool__(self) -> bool:
        return self.ok


BOOKING_REASON_TIME_INVALID = "booking_time_invalid"
BOOKING_REASON_ACTIVE_EXISTS = "active_booking_exists"
BOOKING_REASON_CANCEL_LIMIT = "daily_cancel_limit_reached"
BOOKING_REASON_COUPON = "booking_coupon_rejected"
BOOKING_REASON_PAYMENT_MODE = "payment_mode_invalid"


def check_booking_create(context: BookingCreateContext,
                         coupon_code: Optional[str] = None,
                         requested_online: bool = True,
                         car_type_code: str = "chartered_taxi",
                         catalog: Optional[CarTypeCatalog] = None) -> BookingCreateCheck:
    """执行预约创建前的全部校验。

    锁内依次复核预约时间和进行中预约；
    ``booking_cancel_limit_enabled=true`` 时再校验每日取消次数，
    为 false 时完全跳过该统计及限制。

    即时与预约分别查询，互不占用对方的并行额度。

    :raises ValueError: 车型编码不存在（内部错误）。
    """
    # 1) 预约时间复核
    valid, message = validate_booking_time(context.now, context.use_time)
    if not valid:
        return BookingCreateCheck(False, BOOKING_REASON_TIME_INVALID, message)

    # 2) 优惠券拒绝（调用订单中心前）
    if coupon_code:
        return BookingCreateCheck(
            False, BOOKING_REASON_COUPON, "預約用車不支持使用優惠券")

    # 3) 支付模式：一口价预约只接受线上预付
    try:
        resolve_payment_collection_mode(
            car_type_code, True, requested_online, catalog)
    except ValueError:
        return BookingCreateCheck(
            False, BOOKING_REASON_PAYMENT_MODE,
            "一口價訂單僅支持線上預付支付")

    # 4) 进行中预约订单：一笔
    if context.active_booking_count > 0:
        return BookingCreateCheck(
            False, BOOKING_REASON_ACTIVE_EXISTS,
            "已有進行中的預約訂單，請先完成或取消")

    # 5) 每日取消次数（开关开启时才校验）
    if context.cancel_limit_enabled:
        if context.today_cancel_count >= BOOKING_DAILY_CANCEL_LIMIT:
            return BookingCreateCheck(
                False, BOOKING_REASON_CANCEL_LIMIT,
                "當日預約取次已達上限，暫時無法建立預約訂單")

    return BookingCreateCheck(True)


def booking_lock_key(user_id: int) -> str:
    """返回预约创建锁键。

    沿用 CappCreateBookingOrderLock，锁键为下单用户 ID。
    """
    return f"capp_booking_order_lock_{user_id}"


def cancel_limit_applies(cancel_limit_enabled: bool) -> bool:
    """取消次数限制是否生效。

    开关为 false 时完全跳过该统计及限制。
    """
    return bool(cancel_limit_enabled)


def cancel_order_allowed(cancel_limit_enabled: bool,
                         today_cancel_count: int) -> Tuple[bool, str]:
    """校验取消操作是否被允许。

    预约达到每日上限不阻止取消——既有预约订单仍可取消，
    限制仅作用于新建预约订单。
    """
    if cancel_limit_enabled and today_cancel_count >= BOOKING_DAILY_CANCEL_LIMIT:
        return True, ""
    return True, ""


# ---------------------------------------------------------------------------
# 呼叫与取消提示（需求点 8）
# ---------------------------------------------------------------------------
def dispatch_timeout_at(use_time: datetime) -> datetime:
    """返回呼叫超时自动取消时刻。

    采用派单侧「出发时间前 10 分钟」规则。
    """
    return use_time - timedelta(minutes=BOOKING_DISPATCH_TIMEOUT_MINUTES)


def cancel_page_notice(is_paid_advance: bool) -> str:
    """返回取消页提示文案。

    预付订单取消页增加「已支付款項將按原有途徑退還至您的帳戶」提示。
    """
    return CANCEL_REFUND_NOTICE if is_paid_advance else ""


def driver_location_exposed(use_time: datetime, now: datetime) -> bool:
    """判断是否下发司机位置。

    距预约出发时间大于 20 分钟时不展示司机位置，
    进入出发前 20 分钟后展示司机位置及接驾路线。
    """
    return use_time - now <= timedelta(minutes=DRIVER_LOCATION_EXPOSURE_MINUTES)


def driver_location_placeholder_text() -> str:
    """司机位置未暴露时的地图浮框文案。"""
    return "出發前20分鐘可查看司機位置"


# ---------------------------------------------------------------------------
# 车型选择栏三段式高度（需求点 4）
# ---------------------------------------------------------------------------
CAR_SELECTOR_STATE_DEFAULT = "default"
CAR_SELECTOR_STATE_EXPANDED = "expanded"
CAR_SELECTOR_STATE_COLLAPSED = "collapsed"

CAR_SELECTOR_STATES = (
    CAR_SELECTOR_STATE_DEFAULT,
    CAR_SELECTOR_STATE_EXPANDED,
    CAR_SELECTOR_STATE_COLLAPSED,
)

ENDPOINT_NAME_MAX_LENGTH = 10


def truncate_endpoint_name(name: str) -> str:
    """起终点名称最多展示 10 个字，超出部分以省略号代替。"""
    if name is None:
        return ""
    if len(name) <= ENDPOINT_NAME_MAX_LENGTH:
        return name
    return name[:ENDPOINT_NAME_MAX_LENGTH] + "..."


def car_selector_next_state(current: str, direction: str) -> str:
    """车型选择栏上下滑动切换高度状态。

    :param current:   当前状态。
    :param direction: ``up`` 或 ``down``。
    :raises ValueError: 状态或方向非法。
    """
    if current not in CAR_SELECTOR_STATES:
        raise ValueError(f"未知车型栏状态：{current}")
    if direction not in ("up", "down"):
        raise ValueError(f"未知滑动方向：{direction}")
    order = [CAR_SELECTOR_STATE_COLLAPSED, CAR_SELECTOR_STATE_DEFAULT,
             CAR_SELECTOR_STATE_EXPANDED]
    index = order.index(current)
    if direction == "up":
        index = min(index + 1, len(order) - 1)
    else:
        index = max(index - 1, 0)
    return order[index]


def show_endpoint_in_selector(state: str) -> bool:
    """展开状态下，车型选择栏顶部展示起终点信息。"""
    return state == CAR_SELECTOR_STATE_EXPANDED


# ---------------------------------------------------------------------------
# 消息栏与一口价弹框（需求点 10）
# ---------------------------------------------------------------------------
def order_messages(is_taxi: bool, is_fixed_price: bool) -> List[Dict]:
    """构造已接单页消息提示栏内容。

    - 消息1（纸质发票）仅出租车车型展示。
    - 消息2（一口价附加费）全部一口价订单展示。
    - 多条消息按 3 秒间隔轮播。

    :return: [{"text": ..., "clickable": ...}, ...]
    """
    from .contract import MESSAGE_FIXED_PRICE, MESSAGE_INVOICE

    messages: List[Dict] = []
    if is_taxi:
        messages.append({"text": MESSAGE_INVOICE, "clickable": False})
    if is_fixed_price:
        messages.append({"text": MESSAGE_FIXED_PRICE, "clickable": True})
    return messages


def carousel_interval_seconds(message_count: int) -> int:
    """消息轮播间隔秒数；仅一条消息不轮播返回 0。"""
    return 3 if message_count > 1 else 0


# ---------------------------------------------------------------------------
# 接口入参/出参构造（服务端接口契约）
# ---------------------------------------------------------------------------
def estimate_request_params(origin, destination, order_type=5,
                             car_types=None, city_id=514):
    """构造询价接口 /passenger/order/estimate 入参。

    兼容网约车、预约一口价：car_types 为 order-service 询价所需的
    ``[{"business_type","order_type","car_type_id"}]`` 列表。
    """
    params = {
        "origin": origin,
        "destination": destination,
        "order_type": order_type,
        "city_id": city_id,
    }
    if car_types is not None:
        params["car_types"] = car_types
    return params


def order_create_params(order_type, car_type_code, estimate_id,
                        payment_collection_mode, coupon_code=None,
                        service_preference_ids=None, use_time=None,
                        business_type=None, car_type_id=None,
                        car_types=None):
    """构造创建订单 /passenger/order/create 入参。

    兼容网约车、预约一口价：
    - order_type: 5=即时，6=预约
    - payment_collection_mode: 1=线上先付，2=线下后付
    - 预约订单不携带 coupon_code
    - car_types: order-service /order-service/capp/hk/order/create 所需的
      ``[{"business_type","order_type","car_type_id"}]`` 嵌套数组。
      传入时写入 car_types 字段，同时仍保留扁平 car_type/business_type 供 BFF 层使用。
    """
    params = {
        "order_type": order_type,
        "car_type": car_type_code,
        "estimate_id": estimate_id,
        "payment_collection_mode": payment_collection_mode,
    }
    if business_type is not None:
        params["business_type"] = business_type
    if car_type_id is not None:
        params["car_type_id"] = car_type_id
    if car_types is not None:
        params["car_types"] = car_types
    if coupon_code and order_type == ORDER_TYPE_INSTANT:
        params["coupon_code"] = coupon_code
    if service_preference_ids:
        params["service_preference_ids"] = service_preference_ids
    if use_time and order_type == ORDER_TYPE_BOOKING:
        params["use_time"] = use_time
    return params


def order_pay_params(order_no, pay_type=1, business_type=None,
                     order_type=None):
    """构造创建支付单 /passenger/order/pay 入参。

    兼容网约车、预约一口价，支付成功后进入可派单。
    """
    params = {"order_no": order_no, "pay_type": pay_type}
    if business_type is not None:
        params["business_type"] = business_type
    if order_type is not None:
        params["order_type"] = order_type
    return params


def trip_send_params(order_no, email, order_type=None):
    """构造主动收据 /passenger/order/tripSend 入参。

    兼容网约车和预约，复用归属、支付状态、邮箱及 30 秒防重规则。
    """
    params = {"order_no": order_no, "email": email}
    if order_type is not None:
        params["order_type"] = order_type
    return params


def trip_send_dedup_key(order_no, email):
    """主动收据 30 秒防重键。"""
    return f"trip_send_{order_no}_{email}"


def order_cancel_params(order_no, order_type=None, cancel_reason=None):
    """构造取消订单 /passenger/order/cancel 入参。

    兼容预约达到每日上限不阻止取消。
    """
    params = {"order_no": order_no}
    if order_type is not None:
        params["order_type"] = order_type
    if cancel_reason is not None:
        params["cancel_reason"] = cancel_reason
    return params


def order_status_response(order_status, order_type=6, use_time=None,
                          now=None, driver_location=None):
    """构造订单状态 /passenger/order/status 出参。

    order_status=100（司机已接单，待服务）时，预约用车时间>20m
    司机位置不下发（driver_location=None）。
    """
    from .fulfillment_contract import ORDER_STATUS_ACCEPTED
    resp = {"order_status": order_status, "order_type": order_type}
    if order_status == ORDER_STATUS_ACCEPTED and order_type == 6:
        if use_time and now:
            from .booking_contract import driver_location_exposed
            if not driver_location_exposed(use_time, now):
                resp["driver_location"] = None
                return resp
        resp["driver_location"] = driver_location
    else:
        resp["driver_location"] = driver_location
    return resp


def order_detail_response(order_status, order_type=6, order_cancel_reason=None,
                          **kwargs):
    """构造订单详情 /passenger/order/detail 出参。

    兼容网约车、预约一口价、预约预付取消结果增加原路退款提示。
    order_status=100 表示司机已接单。
    出参含 order_cancel_reason。
    """
    resp = {"order_status": order_status, "order_type": order_type}
    resp.update(kwargs)
    if order_cancel_reason is not None:
        resp["order_cancel_reason"] = order_cancel_reason
    return resp


def share_order_status_response(order_status, order_type=6, accepted_at=None,
                                trip_ended_at=None, now=None):
    """构造分享订单状态 /passenger/share/orderStatus 出参。

    同订单状态，预约未完成订单分享有效期 72h。
    """
    from .fulfillment_contract import share_state
    resp = {"order_status": order_status, "order_type": order_type}
    if order_type == 6 and accepted_at:
        state = share_state(accepted_at, trip_ended_at, now or datetime.now())
        resp["share_state"] = state
    return resp


def share_order_detail_response(order_status, order_type=6,
                               order_cancel_reason=None, accepted_at=None,
                               trip_ended_at=None, now=None, **kwargs):
    """构造分享订单详情 /passenger/share/orderDetail 出参。

    同订单详情，预约未完成订单分享有效期 72h。
    出参含 order_cancel_reason。
    """
    from .fulfillment_contract import share_state
    resp = {"order_status": order_status, "order_type": order_type}
    resp.update(kwargs)
    if order_cancel_reason is not None:
        resp["order_cancel_reason"] = order_cancel_reason
    if order_type == 6 and accepted_at:
        state = share_state(accepted_at, trip_ended_at, now or datetime.now())
        resp["share_state"] = state
    return resp


def agent_order_create_params(order_levels, order_type=6, city_id=514,
                              agent_id=None, user_id=None):
    """构造预约下单 /order/v1/agent/order/create 入参。

    支持入参 order_levels（一单多车型数据存储）。

    :param order_levels: [{"order_level_id","order_level_name","estimate_id",
        "estimate_amount","estimate_distance","estimate_duration",
        "coupon_code","coupon_amount","is_agent_coupon","coupon_remark",
        "business_type"}, ...]
    """
    params = {
        "order_type": order_type,
        "order_levels": order_levels,
        "city_id": city_id,
    }
    if agent_id is not None:
        params["agent_id"] = agent_id
    if user_id is not None:
        params["user_id"] = user_id
    return params


def order_level_entry(order_level_id, order_level_name, estimate_id,
                      estimate_amount, estimate_distance, estimate_duration,
                      coupon_code="", coupon_amount=0, is_agent_coupon=0,
                      coupon_remark="", business_type=1):
    """构造 order_levels 数组的单条条目。"""
    return {
        "order_level_id": order_level_id,
        "order_level_name": order_level_name,
        "estimate_id": estimate_id,
        "estimate_amount": estimate_amount,
        "estimate_distance": estimate_distance,
        "estimate_duration": estimate_duration,
        "coupon_code": coupon_code,
        "coupon_amount": coupon_amount,
        "is_agent_coupon": is_agent_coupon,
        "coupon_remark": coupon_remark,
        "business_type": business_type,
    }


def child_list_params(main_order_no, order_type=6):
    """构造获取子订单编号 /order/v1/agent/order/main/child/list 入参。

    支持 order_type=6 的预约订单。
    """
    return {"main_order_no": main_order_no, "order_type": order_type}


def agent_cancel_params(order_no, order_type=6, cancel_reason=None):
    """构造订单取消 /order/v1/agent/order/cancel 入参。

    支持 order_type=6 的预约订单。
    """
    params = {"order_no": order_no, "order_type": order_type}
    if cancel_reason is not None:
        params["cancel_reason"] = cancel_reason
    return params


def driver_bind_params(order_no, driver_id, business_type=None,
                       order_type=None):
    """构造司机接单（绑单）/order/v1/agent/driver/main/create 入参。"""
    params = {"order_no": order_no, "driver_id": driver_id}
    if business_type is not None:
        params["business_type"] = business_type
    if order_type is not None:
        params["order_type"] = order_type
    return params


def bind_info_params(order_no):
    """构造绑单查询 /order/v1/agent/order/main/bind/info 入参。"""
    return {"order_no": order_no}

