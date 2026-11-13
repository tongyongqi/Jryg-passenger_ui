"""香港乘客端 V1.5.0 文档契约的纯内存离线模型。

表达需求文档、服务侧设计文档、订单中心技术方案、XMind及用户确认的规则。
预约下单下限按2026-11-11最新要求为29分钟，默认选时配置和原文档提示不变。
不连接设备、不访问网络、不调用 Appium/ADB，不补写文档未定义的枚举或错误码。
"""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from urllib.parse import urlsplit
import re


# ---------------------------------------------------------------------------
# 文档常量
# 配置缺省仍为30分钟；2026-11-11确认的下单校验范围为29分钟（含）至72小时（含）。
# 乘客侧预约类型6、订单中心预约实时计价类型16、联系人最多3名。
# ---------------------------------------------------------------------------
BOOKING_MIN_FALLBACK = 30
BOOKING_MIN_ALLOWED = 29
BOOKING_MAX_MINUTES = 72 * 60
BOOKING_TIMEOUT_MINUTES = 20
PASSENGER_INSTANT = 5
PASSENGER_BOOKING = 6
ORDER_CENTER_BOOKING = 16
PAYMENT_COLLECTION_ONLINE = 1
BUSINESS_TAXI = 1
CONTACT_LIMIT = 3
CONTACT_NAME_LIMIT = 15
PAYMENT_ORDER = ("AlipayHK", "WeChatPay", "Octopus", "Card")
SAFETY_ENTRY_PAGES = {
    "home", "instant_vehicle", "booking_vehicle", "instant_calling", "booking_calling",
    "pickup", "in_trip", "bill_pending", "unpaid", "paid", "cancelled",
}


# ---------------------------------------------------------------------------
# 预约入口、时间选择与草稿状态
# 对应公共技术文档6.1、服务侧设计7.1及BOOK-AC01~03。
# ---------------------------------------------------------------------------
def effective_min_booking_interval(value):
    """缺失、类型错误、布尔值或非正整数回退30分钟。"""
    return value if type(value) is int and value > 0 else BOOKING_MIN_FALLBACK


def booking_validation_minimum(configured_min=None):
    """默认30分钟配置按最新29分钟下限校验，其他显式配置保留原约定。"""
    minimum = effective_min_booking_interval(configured_min)
    return BOOKING_MIN_ALLOWED if minimum == BOOKING_MIN_FALLBACK else minimum


def ceil_five_minutes(value):
    """时间选择范围首端向上取整到5分钟刻度，不丢失秒或微秒造成倒退。"""
    rounded = value.replace(second=0, microsecond=0)
    if rounded < value:
        rounded += timedelta(minutes=1)
    return rounded + timedelta(minutes=(-rounded.minute) % 5)


def floor_five_minutes(value):
    """时间选择范围末端向下取整到5分钟刻度。"""
    return value.replace(minute=value.minute - value.minute % 5, second=0, microsecond=0)


def selectable_booking_range(now, configured_min=None):
    minimum = effective_min_booking_interval(configured_min)
    return (
        ceil_five_minutes(now + timedelta(minutes=minimum)),
        floor_five_minutes(now + timedelta(minutes=BOOKING_MAX_MINUTES)),
    )


def validate_booking_time(now, use_time, configured_min=None):
    """按原始时间差校验闭区间，不取整；保留文档约定的错误提示文本。"""
    minimum = booking_validation_minimum(configured_min)
    delta = use_time - now
    if delta < timedelta(minutes=minimum):
        display_minimum = effective_min_booking_interval(configured_min)
        return False, f"預約時間不足{display_minimum}分鐘，請重新選擇"
    if delta > timedelta(minutes=BOOKING_MAX_MINUTES):
        return False, "booking_time_exceeds_72_hours"
    return True, ""


def format_use_time(value):
    """外部use_time格式为yyyy-MM-dd HH:mm:ss，时区由调用上下文保证为香港。"""
    return value.strftime("%Y-%m-%d %H:%M:%S")


def booking_entry(config):
    for service in config.get("services") or []:
        if service.get("type") == "booking":
            return {
                "visible": True,
                "title": service.get("title") or "預約用車",
                "icon": service.get("icon") or "local_booking_icon",
            }
    return {"visible": False, "title": None, "icon": None}


def booking_entry_action(logged_in):
    """未登录仅进入登录页，不在登录后自动续办。"""
    return "booking_page" if logged_in else "login_only"


@dataclass(frozen=True)
class BookingDraft:
    start: str = ""
    destination: str = ""
    confirmed_time: object = None
    temporary_time: object = None

    def open_picker(self, now, configured_min=None):
        initial = self.confirmed_time
        if initial is None or not validate_booking_time(now, initial, configured_min)[0]:
            initial = selectable_booking_range(now, configured_min)[0]
        return replace(self, temporary_time=initial)

    def close_picker(self):
        return replace(self, temporary_time=None)

    def confirm_picker(self, now, configured_min=None):
        valid, message = validate_booking_time(now, self.temporary_time, configured_min)
        if not valid:
            return self, message
        return replace(self, confirmed_time=self.temporary_time, temporary_time=None), ""

    def confirm_page(self, now, configured_min=None):
        if not self.start:
            return "blocked", "請選擇起點"
        if not self.destination:
            return "blocked", "請選擇終點"
        if self.confirmed_time is None:
            return "open_picker", "請選擇預約時間"
        valid, message = validate_booking_time(now, self.confirmed_time, configured_min)
        return ("vehicle_page", "") if valid else ("open_picker", message)


# ---------------------------------------------------------------------------
# 地址、询价身份、创建与预约订单展示
# 报价必须绑定地址、预约时间、请求代次和业务类型；任何一项变化都淘汰旧响应。
# 外部创建仅传一个estimate_id，不额外猜测use_time/order_type创建字段。
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class QuoteIdentity:
    start: str
    destination: str
    use_time: str
    generation: int
    booking: bool


def booking_start_display(state, selected_start=""):
    """预约起点栏按PRD展示首页同步值、定位异常、未开通城市和定位中状态。"""
    states = {
        "unavailable": "無法取得位置，請輸入起點",
        "unsupported_city": "當前城市暫未開通服務",
        "loading": "正在獲取上車地點...",
    }
    if state == "ready":
        return selected_start
    return states[state]


def booking_destination_display(selected_destination=""):
    return selected_destination or "想去哪裡"


def vehicle_page_view(use_time):
    """预约复用车型页但只增加预约时间栏，不提供即时/预约互切。"""
    return {"reuse_instant_layout": True, "booking_time": use_time, "business_switch": False}


def quote_response_applies(current, response):
    """地址、时间、代次和业务类型均一致时才接受报价响应。"""
    return current == response


def estimate_request(start, destination, use_time=None):
    payload = {"start": start, "destination": destination}
    if use_time:
        payload["use_time"] = use_time
    return payload


def estimate_order_type(use_time):
    return PASSENGER_BOOKING if use_time else PASSENGER_INSTANT


def estimate_cache_value(car_type, use_time=None):
    return {"car_type": car_type, "use_time": use_time or ""}


def create_request(estimate_ids):
    """外部创建仅接收一个estimate_list元素，不发送use_time/order_type。"""
    if len(estimate_ids) != 1:
        raise ValueError("estimate_list_must_contain_one")
    return {"estimate_list": [{"estimate_id": estimate_ids[0]}]}


def booking_create_policy(car_type, use_time):
    if car_type not in ("charter", "meter"):
        raise ValueError("unknown_car_type")
    return {
        "skip_fixed_unpaid_cleanup": bool(use_time),
        "prepayment": False if use_time else car_type == "charter",
        "dispatch_immediately": bool(use_time),
        "pay_timeout_message": False if use_time else car_type == "charter",
    }


def can_create(active_instant, active_booking, requested):
    if requested == "instant":
        return active_instant == 0
    if requested == "booking":
        return active_booking == 0
    raise ValueError("unknown_order_type")


def create_response_action(code, order_no="", action=None):
    """10505且有订单号沿用两按钮提醒；其他响应不扩展处理。"""
    if code != 10505 or not order_no:
        return {"handled": False}
    if action is None:
        return {"handled": True, "modal": True, "outside_dismiss": False, "back_dismiss": False}
    if action == "later":
        return {"handled": True, "target": "current_page"}
    if action == "finish":
        return {"handled": True, "target": "existing_order_detail", "order_no": order_no}
    raise ValueError("unknown_action")


def booking_call_view(car_type, use_time):
    return {
        "status": "正在為您預約車輛",
        "description": "預計很快會有司機為您接單",
        "summary": f"預約{use_time}出發",
        "car_type": car_type,
    }


def cancellation_return_target(source):
    targets = {"vehicle": "vehicle_page", "home": "home", "journey_list": "journey_list"}
    if source not in targets:
        raise ValueError("unknown_source")
    return targets[source]


def cancellation_view(timeout, order_no, car_type, use_time, start, destination):
    return {
        "status": "訂單已取消",
        "message": "抱歉，暫無司機接單" if timeout else "你的訂單已取消",
        "order_no": order_no,
        "copyable": True,
        "copy_toast": "复制成功",
        "car_type": car_type,
        "order_type": "預約",
        "use_time": use_time,
        "start": start,
        "destination": destination,
    }


def timeout_cancel_due(elapsed, status):
    """后端仅在仍为待接单且已满20分钟时取消。"""
    return status == "waiting_driver" and elapsed >= timedelta(minutes=BOOKING_TIMEOUT_MINUTES)


def home_order_card(orders):
    count = len(orders)
    if count == 0:
        return {"visible": False}
    if count == 1:
        return {"visible": True, "count": 1, "destination": orders[0]["destination"], "target": "journey"}
    return {"visible": True, "count": count, "destination": None, "target": "journey_list"}


def launch_auto_target(orders):
    """只有即时进行中订单触发启动自动跳转，预约订单不触发。"""
    return "instant_order" if any(item["kind"] == "instant" for item in orders) else None


def journey_card(order):
    return {
        "order_type": "預約" if order["kind"] == "booking" else "即時",
        "display_time": order["use_time"] if order["kind"] == "booking" else order["created_at"],
        "status": order["status"],
        "start": order["start"],
        "destination": order["destination"],
    }


# ---------------------------------------------------------------------------
# 安全中心与JSBridge
# 对应公共技术文档6.3及SAFE-AC01~09；这里仅建模返回值，不执行真实拨号或定位。
# ---------------------------------------------------------------------------
def safety_entry_visible(page):
    return page in SAFETY_ENTRY_PAGES


def safety_entry_action(logged_in):
    return "safety_h5" if logged_in else "login"


def safety_center_url(config):
    url = config.get("safety_center_url") or ""
    if not url:
        return "", "load_failed"
    parts = urlsplit(url)
    if parts.query or parts.fragment:
        raise ValueError("safety_url_must_not_have_business_params")
    return url, ""


def get_order_no(order_context=None):
    return (order_context or {}).get("order_no", "")


def get_safety_phone(config):
    return config.get("safety_phone") or ""


def call_phone_result(can_open):
    return "YES" if can_open else "NO"


def location_authority(status, location_services=True, user_allows=None):
    if not location_services or status in ("restricted", "denied"):
        return "NO"
    if status in ("authorized_when_in_use", "authorized_always"):
        return "YES"
    if status == "not_determined":
        return "YES" if user_allows else "NO"
    raise ValueError("unknown_location_status")


def location_updated(success, lng="", lat="", detail="", name=""):
    if not success:
        return {"lng": "", "lat": "", "address": ""}
    return {"lng": lng, "lat": lat, "address": detail or name}


def emergency_page_location(state, address=""):
    messages = {
        "loading": "正在獲取位置信息...",
        "failed": "無法獲取當前位置信息",
        "disabled": "無法獲取當前位置信息",
    }
    return address if state == "success" else messages[state]


# ---------------------------------------------------------------------------
# 紧急联系人与自动分享
# ContactStore模拟服务侧按user_id隔离、最多3人、0/1分享状态及删除联动，不做持久化。
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Contact:
    contact_id: int
    owner_id: int
    name: str
    phone: str
    auto_share: int = 0
    area_code: str = "+852"


def validate_contact_input(name, phone, own_phone, existing_count, contact_id=0, auto_share=0):
    normalized_name = (name or "").strip()
    if not normalized_name:
        raise ValueError("請填寫聯絡人")
    if len(normalized_name) > CONTACT_NAME_LIMIT:
        raise ValueError("contact_name_too_long")
    if not phone:
        raise ValueError("請填寫電話")
    # App 端电话输入框 maxlength=15，接受 8~15 位纯数字（含内地11位手机号）
    if not re.fullmatch(r"\d{8,15}", phone):
        raise ValueError("手機號碼格式不正確")
    if phone == own_phone[-8:]:
        raise ValueError("本人不可作為緊急聯絡人")
    if auto_share not in (0, 1):
        raise ValueError("auto_share_must_be_0_or_1")
    if not contact_id and existing_count >= CONTACT_LIMIT:
        raise ValueError("最多可新增3個聯絡人")
    return normalized_name


class ContactStore:
    def __init__(self, contacts=()):
        self.contacts = list(contacts)

    def save(self, owner_id, contact_id, name, phone, own_phone, auto_share=0):
        normalized = validate_contact_input(name, phone, own_phone, len(self.contacts), contact_id, auto_share)
        if contact_id:
            for index, contact in enumerate(self.contacts):
                if contact.contact_id == contact_id and contact.owner_id == owner_id:
                    updated = Contact(contact_id, owner_id, normalized, phone, auto_share)
                    self.contacts[index] = updated
                    return updated
            raise ValueError("contact_not_found")
        next_id = max([item.contact_id for item in self.contacts] or [0]) + 1
        contact = Contact(next_id, owner_id, normalized, phone, auto_share)
        self.contacts.append(contact)
        return contact

    def delete(self, owner_id, contact_id):
        before = len(self.contacts)
        self.contacts = [item for item in self.contacts if not (item.owner_id == owner_id and item.contact_id == contact_id)]
        if len(self.contacts) == before:
            raise ValueError("contact_not_found")

    def share(self, owner_id, contact_id, auto_share):
        if auto_share not in (0, 1):
            raise ValueError("auto_share_must_be_0_or_1")
        for index, contact in enumerate(self.contacts):
            if contact.owner_id == owner_id and contact.contact_id == contact_id:
                self.contacts[index] = replace(contact, auto_share=auto_share)
                return self.contacts[index]
        raise ValueError("contact_not_found")

    def enable_auto_share_for_all(self):
        if not self.contacts:
            raise ValueError("請添加緊急聯絡人")
        self.contacts = [replace(item, auto_share=1) for item in self.contacts]

    def disable_auto_share_for_all(self):
        self.contacts = [replace(item, auto_share=0) for item in self.contacts]

    def auto_share_enabled(self):
        return any(item.auto_share == 1 for item in self.contacts)

    def trip_share_recipients(self):
        return [item.phone for item in self.contacts if item.auto_share == 1]

    def alarm_recipients(self):
        return [item.phone for item in self.contacts]


def mask_contact_phone(phone):
    return "****" + phone[-4:]


# ---------------------------------------------------------------------------
# 邮箱与电子收据
# 邮箱管理的空字符串表示删除；收据发送的空邮箱则必须拦截，二者不能混用。
# 收据任务按order_no幂等，财务系统未明确受理时不能标记为发送成功。
# ---------------------------------------------------------------------------
def normalize_email(value):
    normalized = (value or "").strip()
    if not normalized:
        return ""
    if normalized.count("@") != 1:
        raise ValueError("郵箱格式不正確")
    local, domain = normalized.split("@")
    if not local or not domain or "." not in domain or any(ch.isspace() for ch in normalized):
        raise ValueError("郵箱格式不正確")
    return normalized


UNSET = object()


def save_email(current, submitted=UNSET):
    """字段缺失或null不修改；空白删除；合法非空保存。"""
    if submitted is UNSET or submitted is None:
        return current, "unchanged"
    normalized = normalize_email(submitted)
    return normalized, "deleted" if normalized == "" else "saved"


def email_from_storage(value):
    return value or ""


def receipt_controls(notices, button_control):
    prompt_count = sum(1 for item in notices if item.get("id") == "email_setting_prompt")
    return {
        "set_and_send": prompt_count > 0,
        "set_and_send_count": min(prompt_count, 1),
        "send_trip_info": bool((button_control or {}).get("send_trip_info")),
    }


def receipt_request(entry, order_no, saved_email="", input_email=None):
    if entry == "set_and_send":
        email = normalize_email(input_email)
        if not email:
            raise ValueError("email_required")
        return {"order_no": order_no, "email": email}
    if entry == "send_trip_info":
        if saved_email:
            return {"order_no": order_no}
        email = normalize_email(input_email)
        if not email:
            raise ValueError("email_required")
        return {"order_no": order_no, "email": email}
    raise ValueError("unknown_receipt_entry")


def receipt_success_state(notices, button_control, request_payload):
    remaining = [item for item in notices if item.get("id") != "email_setting_prompt"]
    return {
        "notices": remaining,
        "button_control": dict(button_control),
        "refresh_user_info": "email" in request_payload,
        "toast": "已發送，稍後查看",
    }


def receipt_failure_state(notices, button_control, draft_email, saved_email):
    return {
        "notices": list(notices),
        "button_control": dict(button_control),
        "draft_email": draft_email,
        "saved_email": saved_email,
        "toast": None,
    }


def receipt_auto_eligible(order):
    return all((
        order.get("region") == "HK",
        order.get("order_type") == PASSENGER_INSTANT,
        order.get("order_status") == 13,
        order.get("pay_status") == 2,
        order.get("payment_collection_mode") == PAYMENT_COLLECTION_ONLINE,
        order.get("belongs_to_passenger") is True,
        order.get("car_type") in ("charter", "meter"),
        bool(normalize_email(order.get("email", ""))),
    ))


def receipt_event_source(car_type):
    if car_type == "charter":
        return "order_status_machine"
    if car_type == "meter":
        return "order_pay_success"
    raise ValueError("unsupported_car_type")


def receipt_rate_allowed(previous_send_times, now):
    recent = [item for item in previous_send_times if now - item < timedelta(minutes=1)]
    return len(recent) < 2


class ReceiptTaskStore:
    """服务侧文档7.5：order_no唯一任务及财务受理结果状态。"""
    def __init__(self):
        self.tasks = {}

    def create_once(self, order_no, source):
        if order_no in self.tasks:
            return self.tasks[order_no], False
        self.tasks[order_no] = {"order_no": order_no, "source": source, "status": "PENDING"}
        return self.tasks[order_no], True

    def finance_result(self, order_no, response=None, transport_error=False):
        task = self.tasks[order_no]
        if transport_error:
            task["status"] = "UNKNOWN"
        elif response.get("code") == 10000 and response.get("accepted") is True:
            task["status"] = "ACCEPTED"
            task["request_id"] = response.get("request_id")
        elif response.get("temporary") is True:
            task["status"] = "RETRYABLE_FAILED"
        else:
            task["status"] = "PERMANENT_FAILED"
        return task


# ---------------------------------------------------------------------------
# 收银台与WeChatPay
# 仅过滤服务端已开启方式并保持文档顺序；SDK回调不等于最终支付成功。
# ---------------------------------------------------------------------------
def cashier_methods(enabled):
    enabled_set = set(enabled)
    return [item for item in PAYMENT_ORDER if item in enabled_set]


def wechat_launch(installed):
    return "launch_wechat" if installed else "請安裝應用"


def payment_result_after_sdk(sdk_result, server_result=None):
    """SDK回调不直接作为订单最终支付状态，继续查询服务端结果。"""
    if server_result in ("paid", "failed", "cancelled"):
        return server_result
    return "processing"


def payment_detail_method(actual_method):
    if actual_method not in PAYMENT_ORDER:
        raise ValueError("unknown_payment_method")
    return actual_method


# ---------------------------------------------------------------------------
# 订单中心type16技术契约
# 预约后付费type16与即时type5共用实时库；新增字段可选且只允许1/2，缺省保持0。
# ---------------------------------------------------------------------------
def order_center_create(order_type, payment_collection_mode=None, business_type=None):
    def checked(value):
        if value is None:
            return 0
        if value not in (1, 2):
            raise ValueError("omitempty_oneof_1_2")
        return value
    return {
        "order_type": order_type,
        "payment_collection_mode": checked(payment_collection_mode),
        "business_type": checked(business_type),
        "storage": "realtime" if order_type in (5, 16) else "booking",
    }


def order_center_show(order):
    return {
        "order_type": order["order_type"],
        "payment_collection_mode": order["payment_collection_mode"],
        "business_type": order["business_type"],
    }


def unfinished_list(orders, order_types=None):
    selected = list(orders)
    if order_types is not None:
        selected = [item for item in selected if item["order_type"] in order_types]
    return sorted(selected, key=lambda item: item["use_time"], reverse=True)[:5]


def unfinished_list_error(circuit_open):
    return "ErrQueryOrderPassengerServingPolardbBreak" if circuit_open else None


def active_order_visible(order):
    return not (order.get("cancelled") or (order.get("completed") and order.get("paid")))


def status_info_hk(order):
    return {"order_status": order["order_status"], "pay_status": order["pay_status"]}


def order_status_mq(order):
    return {
        "payment_collection_mode": order["payment_collection_mode"],
        "business_type": order["business_type"],
    }
