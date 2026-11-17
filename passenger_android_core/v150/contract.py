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
PAYMENT_COLLECTION_ONLINE = 1   # 1:线上支付
PAYMENT_COLLECTION_OFFLINE = 2  # 2:线下支付（现金）
BUSINESS_TAXI = 1
CONTACT_LIMIT = 3
CONTACT_NAME_LIMIT = 15
PAYMENT_ORDER = ("AlipayHK", "Octopus", "Card")
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
    """计算可选择的最小和最大预约时间范围。

    返回 (earliest, latest) 元组，最早时间向上取整到5分钟，
    最晚时间向下取整到5分钟，确保落在合法刻度内。
    """
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
    """检查配置中是否有预约用车服务入口，返回入口可见性、标题和图标。"""
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
    """预约订单草稿状态机：记录起点、终点、已确认/临时时间。

    草稿在打开时间选择器时产生 temporary_time，确认后转为 confirmed_time，
    关闭选择器后清除 temporary_time。所有状态变更返回新实例（不可变）。
    """
    start: str = ""
    destination: str = ""
    confirmed_time: object = None
    temporary_time: object = None

    def open_picker(self, now, configured_min=None):
        """打开时间选择器，初始值为已确认时间或合法范围最早值。"""
        initial = self.confirmed_time
        if initial is None or not validate_booking_time(now, initial, configured_min)[0]:
            initial = selectable_booking_range(now, configured_min)[0]
        return replace(self, temporary_time=initial)

    def close_picker(self):
        """关闭时间选择器，清除临时时间。"""
        return replace(self, temporary_time=None)

    def confirm_picker(self, now, configured_min=None):
        """确认时间选择；合法则更新 confirmed_time 并清除临时时间，非法返回错误信息。"""
        valid, message = validate_booking_time(now, self.temporary_time, configured_min)
        if not valid:
            return self, message
        return replace(self, confirmed_time=self.temporary_time, temporary_time=None), ""

    def confirm_page(self, now, configured_min=None):
        """确认页状态：blocked（缺起点/终点）、open_picker（未选时间）、vehicle_page（可进入车型页）。"""
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
    """报价请求标识：地址、时间、代次和业务类型的唯一组合，用于判断是否复用旧报价。"""
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
    """预约终点栏显示：有值时显示终点，无值时显示占位提示。"""
    return selected_destination or "想去哪裡"


def vehicle_page_view(use_time):
    """预约复用车型页但只增加预约时间栏，不提供即时/预约互切。"""
    return {"reuse_instant_layout": True, "booking_time": use_time, "business_switch": False}


def quote_response_applies(current, response):
    """地址、时间、代次和业务类型均一致时才接受报价响应。"""
    return current == response


def estimate_request(start, destination, use_time=None):
    """构建询价请求体；预约订单附加 use_time，即时订单不带。"""
    payload = {"start": start, "destination": destination}
    if use_time:
        payload["use_time"] = use_time
    return payload


def estimate_order_type(use_time):
    """根据 use_time 返回订单类型：有值为预约，无值为即时。"""
    return PASSENGER_BOOKING if use_time else PASSENGER_INSTANT


def estimate_cache_value(car_type, use_time=None):
    """构建询价缓存值，按车型和预约时间区分。"""
    return {"car_type": car_type, "use_time": use_time or ""}


def create_request(estimate_ids):
    """外部创建仅接收一个estimate_list元素，不发送use_time/order_type。"""
    if len(estimate_ids) != 1:
        raise ValueError("estimate_list_must_contain_one")
    return {"estimate_list": [{"estimate_id": estimate_ids[0]}]}


def booking_create_policy(car_type, use_time):
    """预约订单创建策略：按车型和是否预约决定预付、调度、超时提示等行为。"""
    if car_type not in ("charter", "meter"):
        raise ValueError("unknown_car_type")
    return {
        "skip_fixed_unpaid_cleanup": bool(use_time),
        "prepayment": False if use_time else car_type == "charter",
        "dispatch_immediately": bool(use_time),
        "pay_timeout_message": False if use_time else car_type == "charter",
    }


def can_create(active_instant, active_booking, requested):
    """判断能否创建新订单：对应类型无活跃订单时允许创建。"""
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
    """预约呼叫中页面展示：状态文案、预计描述和预约时间摘要。"""
    return {
        "status": "正在為您預約車輛",
        "description": "預計很快會有司機為您接單",
        "summary": f"預約{use_time}出發",
        "car_type": car_type,
    }


def cancellation_return_target(source):
    """取消订单后返回目标页面：车型页、首页或行程列表。"""
    targets = {"vehicle": "vehicle_page", "home": "home", "journey_list": "journey_list"}
    if source not in targets:
        raise ValueError("unknown_source")
    return targets[source]


def cancellation_view(timeout, order_no, car_type, use_time, start, destination):
    """取消订单页面展示：超时取消和用户主动取消有不同的状态文案。"""
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
    """首页订单卡片：0个不展示，1个展示单卡跳行程详情，多个展示列表入口。"""
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
    """行程列表卡片：按订单类型展示预约/即时标签和时间。"""
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
    """安全中心入口在指定页面是否可见。"""
    return page in SAFETY_ENTRY_PAGES


def safety_entry_action(logged_in):
    """安全中心入口动作：已登录跳H5页，未登录跳登录页。"""
    return "safety_h5" if logged_in else "login"


def safety_center_url(config):
    """校验安全中心H5的URL前缀和来源。"""
    url = config.get("safety_center_url") or ""
    if not url:
        return "", "load_failed"
    parts = urlsplit(url)
    if parts.query or parts.fragment:
        raise ValueError("safety_url_must_not_have_business_params")
    return url, ""


def get_order_no(order_context=None):
    """从订单上下文中提取订单号。"""
    return (order_context or {}).get("order_no", "")


def get_safety_phone(config):
    """获取安全专线电话号码。"""
    return config.get("safety_phone") or ""


def call_phone_result(can_open):
    """拨号结果映射：能打开拨号盘返回YES，否则NO。"""
    return "YES" if can_open else "NO"


def location_authority(status, location_services=True, user_allows=None):
    """定位权限判断：综合系统定位服务、应用授权状态和用户选择。"""
    if not location_services or status in ("restricted", "denied"):
        return "NO"
    if status in ("authorized_when_in_use", "authorized_always"):
        return "YES"
    if status == "not_determined":
        return "YES" if user_allows else "NO"
    raise ValueError("unknown_location_status")


def location_updated(success, lng="", lat="", detail="", name=""):
    """定位更新结果：成功返回经纬度和地址，失败返回空值。"""
    if not success:
        return {"lng": "", "lat": "", "address": ""}
    return {"lng": lng, "lat": lat, "address": detail or name}


def emergency_page_location(state, address=""):
    """根据安全中心页面状态返回位置信息。"""
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
    """紧急联系人数据类。"""
    contact_id: int
    owner_id: int
    name: str
    phone: str
    auto_share: int = 0
    area_code: str = "+852"


def validate_contact_input(name, phone, own_phone, existing_count, contact_id=0, auto_share=0):
    """校验紧急联系人输入合法性。"""
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
    """紧急联系人存储管理器，支持增删改查和自动分享。"""
    def __init__(self, contacts=()):
        """初始化实例。"""
        self.contacts = list(contacts)

    def save(self, owner_id, contact_id, name, phone, own_phone, auto_share=0):
        """保存或更新紧急联系人。"""
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
        """删除紧急联系人。"""
        before = len(self.contacts)
        self.contacts = [item for item in self.contacts if not (item.owner_id == owner_id and item.contact_id == contact_id)]
        if len(self.contacts) == before:
            raise ValueError("contact_not_found")

    def share(self, owner_id, contact_id, auto_share):
        """设置联系人自动分享开关。"""
        if auto_share not in (0, 1):
            raise ValueError("auto_share_must_be_0_or_1")
        for index, contact in enumerate(self.contacts):
            if contact.owner_id == owner_id and contact.contact_id == contact_id:
                self.contacts[index] = replace(contact, auto_share=auto_share)
                return self.contacts[index]
        raise ValueError("contact_not_found")

    def enable_auto_share_for_all(self):
        """开启全部联系人自动分享。"""
        if not self.contacts:
            raise ValueError("請添加緊急聯絡人")
        self.contacts = [replace(item, auto_share=1) for item in self.contacts]

    def disable_auto_share_for_all(self):
        """关闭全部联系人自动分享。"""
        self.contacts = [replace(item, auto_share=0) for item in self.contacts]

    def auto_share_enabled(self):
        """检查是否有任意联系人开启了自动分享。"""
        return any(item.auto_share == 1 for item in self.contacts)

    def trip_share_recipients(self):
        """获取行程分享接收人列表。"""
        return [item.phone for item in self.contacts if item.auto_share == 1]

    def alarm_recipients(self):
        """获取报警接收人列表。"""
        return [item.phone for item in self.contacts]


def mask_contact_phone(phone):
    """对联系人手机号做掩码处理。"""
    return "****" + phone[-4:]


# ---------------------------------------------------------------------------
# 邮箱与电子收据
# 邮箱管理的空字符串表示删除；收据发送的空邮箱则必须拦截，二者不能混用。
# 收据任务按order_no幂等，财务系统未明确受理时不能标记为发送成功。
# ---------------------------------------------------------------------------
def normalize_email(value):
    """校验并归一化邮箱格式，非法时抛ValueError。"""
    normalized = (value or "").strip()
    if not normalized:
        return ""
    if normalized.count("@") != 1:
        raise ValueError("郵箱格式不正確")
    local, domain = normalized.split("@")
    if not local or not domain or "." not in domain or any(ch.isspace() for ch in normalized):
        raise ValueError("郵箱格式不正確")
    # 域名不能以点开头或结尾，不能有连续点
    if domain.startswith(".") or domain.endswith(".") or ".." in domain:
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
    """从存储值解析邮箱，空值返回空字符串。"""
    return value or ""


def receipt_controls(notices, button_control):
    """从通知和按钮控件中提取收据弹框状态。"""
    prompt_count = sum(1 for item in notices if item.get("id") == "email_setting_prompt")
    return {
        "set_and_send": prompt_count > 0,
        "set_and_send_count": min(prompt_count, 1),
        "send_trip_info": bool((button_control or {}).get("send_trip_info")),
    }


def receipt_request(entry, order_no, saved_email="", input_email=None):
    """构造收据发送请求体。"""
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
    """判断收据发送是否成功。"""
    remaining = [item for item in notices if item.get("id") != "email_setting_prompt"]
    return {
        "notices": remaining,
        "button_control": dict(button_control),
        "refresh_user_info": "email" in request_payload,
        "toast": "已發送，稍後查看",
    }


def receipt_failure_state(notices, button_control, draft_email, saved_email):
    """判断收据发送是否失败。"""
    return {
        "notices": list(notices),
        "button_control": dict(button_control),
        "draft_email": draft_email,
        "saved_email": saved_email,
        "toast": None,
    }


def receipt_auto_eligible(order):
    """判断订单是否满足自动发送收据条件。"""
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
    """根据车型返回收据事件来源。"""
    if car_type == "charter":
        return "order_status_machine"
    if car_type == "meter":
        return "order_pay_success"
    raise ValueError("unsupported_car_type")


def receipt_rate_allowed(previous_send_times, now):
    """根据上次发送时间判断是否超过频率限制。"""
    recent = [item for item in previous_send_times if now - item < timedelta(minutes=1)]
    return len(recent) < 2


class ReceiptTaskStore:
    """服务侧文档7.5：order_no唯一任务及财务受理结果状态。"""
    def __init__(self):
        """初始化实例。"""
        self.tasks = {}

    def create_once(self, order_no, source):
        """创建一次性收据请求。"""
        if order_no in self.tasks:
            return self.tasks[order_no], False
        self.tasks[order_no] = {"order_no": order_no, "source": source, "status": "PENDING"}
        return self.tasks[order_no], True

    def finance_result(self, order_no, response=None, transport_error=False):
        """获取财务系统收据发送结果。"""
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
# 收银台
# 仅过滤服务端已开启方式并保持文档顺序；SDK回调不等于最终支付成功。
# ---------------------------------------------------------------------------
def cashier_methods(enabled):
    """返回收银台可用支付方式列表。"""
    enabled_set = set(enabled)
    return [item for item in PAYMENT_ORDER if item in enabled_set]


def payment_result_after_sdk(sdk_result, server_result=None):
    """SDK回调不直接作为订单最终支付状态，继续查询服务端结果。"""
    if server_result in ("paid", "failed", "cancelled"):
        return server_result
    return "processing"


def payment_detail_method(actual_method):
    """从支付明细解析实际支付方式。"""
    if actual_method not in PAYMENT_ORDER:
        raise ValueError("unknown_payment_method")
    return actual_method


# ---------------------------------------------------------------------------
# 订单中心type16技术契约
# 预约后付费type16与即时type5共用实时库；新增字段可选且只允许1/2，缺省保持0。
# 改造要点：
#   ① /agent/order/create 补 payment_collection_mode、business_type 透传
#   ② /user/unfinished/order 不支持 type16，由 /user/unfinished/list 替代
# ---------------------------------------------------------------------------
ORDER_TYPE_REALTIME_INSTANT = 5
ORDER_TYPE_BOOKING_REALTIME = 16


def order_center_create(order_type, payment_collection_mode=None, business_type=None):
    """下单接口：创建type5/type16订单并存储到对应库。"""
    def checked(value):
        """checked方法。"""
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
    """查询接口：返回订单详情含两新字段。"""
    return {
        "order_type": order["order_type"],
        "payment_collection_mode": order["payment_collection_mode"],
        "business_type": order["business_type"],
    }


def unfinished_list(orders, order_types=None):
    """未完成列表：按order_types过滤并按use_time DESC排序。"""
    selected = list(orders)
    if order_types is not None:
        selected = [item for item in selected if item["order_type"] in order_types]
    return sorted(selected, key=lambda item: item["use_time"], reverse=True)[:5]


def unfinished_list_error(circuit_open):
    """返回熔断状态下的错误码。"""
    return "ErrQueryOrderPassengerServingPolardbBreak" if circuit_open else None


def active_order_visible(order):
    """判断订单是否在列表中可见。"""
    return not (order.get("cancelled") or (order.get("completed") and order.get("paid")))


def status_info_hk(order):
    """返回订单状态和支付状态。"""
    return {"order_status": order["order_status"], "pay_status": order["pay_status"]}


def order_status_mq(order):
    """构造MQ消息体，携带两新字段。"""
    return {
        "payment_collection_mode": order["payment_collection_mode"],
        "business_type": order["business_type"],
    }


def create_params_validate(payment_collection_mode=None, business_type=None):
    """校验 create 接口两新字段的合法性：可选，仅允许 1 或 2，缺省保持 0。

    非法值（如 3）抛 ValueError，合法值原样返回，None 返回 0。
    """
    def checked(value):
        """checked方法。"""
        if value is None:
            return 0
        if value not in (1, 2):
            raise ValueError("omitempty_oneof_1_2")
        return value
    return {
        "payment_collection_mode": checked(payment_collection_mode),
        "business_type": checked(business_type),
    }


def order_list_visible(order_type, status="in_progress"):
    """订单列表对 type16 的可见性：进行中、待支付、已完成均支持。

    - 进行中：Booking ZSet + 实时库，type16 命中实时库分支
    - 待支付：GetNeedPayOrderInfoByMap 含 16
    - 已完成：OTS order_list_hot 显式含 16
    """
    if order_type not in (ORDER_TYPE_REALTIME_INSTANT, ORDER_TYPE_BOOKING_REALTIME):
        raise ValueError("order_type_must_be_5_or_16")
    valid_statuses = ("in_progress", "unpaid", "completed")
    if status not in valid_statuses:
        raise ValueError(f"status_must_be_one_of_{valid_statuses}")
    if status == "in_progress":
        return "realtime_zset"
    if status == "unpaid":
        return "need_pay_map"
    return "ots_terms"


def unfinished_order_legacy(order_type):
    """旧接口 /user/unfinished/order 对 type16 的处理：不写入，直接 return。

    证据：OrderType != 5 直接 return；兜底 SQL 硬编码 order_type = 5。
    返回 rejected=True 表示该接口不支持此类型。
    """
    if order_type == ORDER_TYPE_REALTIME_INSTANT:
        return {"supported": True, "reason": None}
    return {"supported": False, "reason": "OrderType_not_5_direct_return"}


def cancellation_cleanup(order_type):
    """取消订单后从未完成列表清理：create/cancel/status/driver 各调用点成对写删。

    type16 走实时库路径，取消后与即时单一致从 unfinished/list 消失。
    """
    if order_type not in (ORDER_TYPE_REALTIME_INSTANT, ORDER_TYPE_BOOKING_REALTIME):
        raise ValueError("order_type_must_be_5_or_16")
    return {
        "removed_from_unfinished_list": True,
        "removed_from_unfinished_order": True,
        "removed_from_order_list_in_progress": True,
        "cleanup_path": "realtime" if order_type == ORDER_TYPE_BOOKING_REALTIME else "realtime",
    }


def order_show_fields(order):
    """show 接口返回的两新字段：依赖 create 写入，show 已有输出能力。

    改造前两字段为 0；改造后返回 create 传入的真实值。
    """
    return {
        "order_type": order["order_type"],
        "payment_collection_mode": order.get("payment_collection_mode", 0),
        "business_type": order.get("business_type", 0),
    }


# ---------------------------------------------------------------------------
# §7.1.1 询价链路：use_time→dep_time→order_type 映射与时间范围校验
# passenger-api 按 HK 时区解析非空 use_time 规范化为 YYYY-MM-DD HH:mm:ss，
# 以 API 服务端时刻校验 30m<=use_time-now<=72h，失败直接返回不调订单服务。
# passenger-api RPC 将规范化后的 use_time 映射到内部 dep_time；
# order-service 根据 dep_time 是否为空派生即时或预约 order_type，不重复校验时间。
# ---------------------------------------------------------------------------
def normalize_use_time(raw, now):
    """将 use_time 规范化为 YYYY-MM-DD HH:mm:ss 字符串。

    空值返回空字符串（即时询价）；非空值按香港时区解析并格式化。
    解析失败返回 None 表示非法格式。
    """
    if not raw:
        return ""
    if isinstance(raw, datetime):
        return raw.strftime("%Y-%m-%d %H:%M:%S")
    try:
        parsed = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return None
    return parsed.strftime("%Y-%m-%d %H:%M:%S")


def estimate_time_range_check(use_time_normalized, now):
    """校验 30m <= use_time-now <= 72h（闭区间）。

    返回 (passed, reason)。空 use_time 直接通过（即时询价不校验）。
    """
    if not use_time_normalized:
        return True, ""
    try:
        parsed = datetime.strptime(use_time_normalized, "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return False, "use_time_format_invalid"
    delta = parsed - now
    if delta < timedelta(minutes=BOOKING_MIN_ALLOWED):
        return False, f"預約時間不足{BOOKING_MIN_FALLBACK}分鐘，請重新選擇"
    if delta > timedelta(minutes=BOOKING_MAX_MINUTES):
        return False, "booking_time_exceeds_72_hours"
    return True, ""


def dep_time_from_use_time(use_time_normalized):
    """passenger-api RPC 将规范化后的 use_time 映射到内部 dep_time。

    空字符串保持空（即时）；非空原样透传（预约）。
    """
    return use_time_normalized


def order_type_from_dep_time(dep_time):
    """order-service 根据 dep_time 是否为空派生 order_type。

    dep_time 非空→预约(BOOKING_ORDER_TYPE)；空→即时(REALTIME_INSTANT)。
    不重复执行时间范围校验。
    """
    return ORDER_TYPE_BOOKING_REALTIME if dep_time else ORDER_TYPE_REALTIME_INSTANT


# ---------------------------------------------------------------------------
# §7.1.2 报价缓存与有效期
# passenger-api 用 global.NsEstimate 以 estimate_id 为 key 存 car_type+use_time，
# TTL = timeout*秒；order-service 用 capp:hk:es_id:<estimate_id> 存 order_type+use_time。
# ---------------------------------------------------------------------------
def estimate_cache_ttl(timeout_seconds):
    """计算 NsEstimate 缓存 TTL。"""
    if timeout_seconds is None or timeout_seconds <= 0:
        raise ValueError("timeout_must_be_positive")
    return timeout_seconds


def order_service_cache_key(estimate_id):
    """构造 order-service 侧报价缓存 key。"""
    return f"capp:hk:es_id:{estimate_id}"


def order_service_cache_value(order_type, use_time):
    """构造 order-service 侧报价缓存 value（order_type + use_time 作为创建事实）。"""
    return {"order_type": order_type, "use_time": use_time or ""}


def read_order_service_cache(cache_value):
    """从 order-service 缓存读取 order_type/use_time 作为订单创建事实。

    缓存不存在时返回 None；存在时返回 order_type 和 use_time。
    """
    if cache_value is None:
        return None
    if not isinstance(cache_value, dict):
        return None
    return {
        "order_type": cache_value.get("order_type"),
        "use_time": cache_value.get("use_time", ""),
    }


# ---------------------------------------------------------------------------
# §7.2 创建链路：estimate_id→order_type/use_time 事实；并发限制；免预付
# passenger-api 从 NsEstimate 读 car_type+use_time（car_type 校验、use_time 跳过清理）；
# order-service 从 GetCacheEstimate 读 order_type/use_time 作为创建事实。
# ---------------------------------------------------------------------------
def passenger_api_create_check(ns_estimate_cache, car_type):
    """passenger-api 校验 NsEstimate 缓存存在且 car_type 非空。

    返回 (passed, car_type, use_time, reason)。
    """
    if ns_estimate_cache is None:
        return (False, None, None, "estimate_cache_not_found")
    if not isinstance(ns_estimate_cache, dict):
        return (False, None, None, "estimate_cache_invalid_json")
    cached_car_type = ns_estimate_cache.get("car_type", "")
    if not cached_car_type:
        return (False, None, None, "car_type_empty")
    if car_type and cached_car_type != car_type:
        return (False, cached_car_type, ns_estimate_cache.get("use_time", ""),
                "car_type_mismatch")
    return (True, cached_car_type, ns_estimate_cache.get("use_time", ""), "")


def should_cancel_fixed_unpaid(use_time):
    """passenger-api 根据 use_time 是否为空决定是否执行 cancelFixedUnpayOrder。

    空值（即时）→执行清理；非空（预约）→跳过清理。
    use_time 不传入 order-service，不作为订单事实。
    """
    return not bool(use_time)


def order_service_transform(car_types_estimate_ids, cache_lookup, user_id):
    """order-service transform：对每个 estimate_id 调 GetCacheEstimate。

    校验缓存存在、用户一致、所有报价 order_type/use_time 一致，
    然后写入 OrderCreateParam.OrderType/UseTime。

    返回 (order_type, use_time, errors) 或 (None, None, errors)。
    """
    if not car_types_estimate_ids:
        return (None, None, ["no_estimate_ids"])
    if len(car_types_estimate_ids) != 1:
        return (None, None, ["estimate_list_must_contain_one"])
    estimate_id = car_types_estimate_ids[0]
    cache = cache_lookup(estimate_id) if cache_lookup else None
    parsed = read_order_service_cache(cache)
    if parsed is None:
        return (None, None, [f"cache_not_found:{estimate_id}"])
    # 用户一致性校验
    cached_user_id = cache.get("user_id") if isinstance(cache, dict) else None
    if cached_user_id is not None and cached_user_id != user_id:
        return (None, None, [f"user_mismatch:{cached_user_id}!={user_id}"])
    return (parsed["order_type"], parsed["use_time"], [])


def order_cancel_limit_applies(order_type):
    """OrderCancelLimit 只对即时(type5)执行；预约(type16)不受即时取消次数限制。"""
    return order_type == ORDER_TYPE_REALTIME_INSTANT


def order_unfinished_limit_check(order_type, active_instant, active_booking):
    """OrderUnfinishedLimit 按类型查询：即时只占即时额度，预约只占预约额度，各1笔。"""
    if order_type == ORDER_TYPE_REALTIME_INSTANT:
        return active_instant == 0
    if order_type == ORDER_TYPE_BOOKING_REALTIME:
        return active_booking == 0
    raise ValueError("unknown_order_type")


def booking_dispatch_policy(order_type):
    """预约创建强制 skipDispatch=false、不发 OrderPayTimeout、不等待预付。

    即时订单继续按当前 skipDispatch、预付及支付超时逻辑执行。
    """
    if order_type == ORDER_TYPE_BOOKING_REALTIME:
        return {
            "skip_dispatch": False,
            "send_pay_timeout": False,
            "wait_prepayment": False,
            "dispatch_immediately": True,
        }
    if order_type == ORDER_TYPE_REALTIME_INSTANT:
        return {
            "skip_dispatch": None,  # 按当前逻辑
            "send_pay_timeout": None,
            "wait_prepayment": None,
            "dispatch_immediately": False,
        }
    raise ValueError("unknown_order_type")


def estimate_cache_after_create(car_type):
    """创建成功后按计费类型处理报价缓存：非打表缓存删除，打表缓存保留。"""
    if car_type == "meter":
        return {"action": "keep", "reason": "meter_keeps_estimate_cache"}
    return {"action": "delete", "reason": "non_meter_deletes_estimate_cache"}


# ---------------------------------------------------------------------------
# §7.3 取消链路：主动取消 + 20分钟超时取消 + 幂等
# 预约取消使用即时用车统一取消链，不新增预约专用接口。
# ---------------------------------------------------------------------------
def cancel_entry_source(user_initiated):
    """预约取消入口：乘客主动→/passenger/order/cancel；超时→schedulingTimeout→order_cancel_common。"""
    return "user_cancel" if user_initiated else "dispatch_timeout"


def cancel_handler(source, order_type, order_status):
    """取消 Handler 兼容 BOOKING_ORDER_TYPE 的校验逻辑。

    返回 (allowed, handler, reason)。
    - user_cancel: OrderCancelByCappHandler，校验订单归属+状态+重复取消
    - dispatch_timeout: OrderCancelByDispatchTimeoutHandler，校验仍为待接单
    """
    if order_type not in (ORDER_TYPE_REALTIME_INSTANT, ORDER_TYPE_BOOKING_REALTIME):
        return (False, None, "unknown_order_type")
    if source == "user_cancel":
        if order_status == "cancelled":
            return (True, "OrderCancelByCappHandler", "idempotent_already_cancelled")
        if order_status in ("waiting_driver", "pending"):
            return (True, "OrderCancelByCappHandler", "")
        return (False, "OrderCancelByCappHandler", f"invalid_status:{order_status}")
    if source == "dispatch_timeout":
        if order_status != "waiting_driver":
            return (False, "OrderCancelByDispatchTimeoutHandler",
                    f"not_waiting_driver:{order_status}")
        return (True, "OrderCancelByDispatchTimeoutHandler", "")
    return (False, None, "unknown_cancel_source")


def cancel_idempotent(order_status, order_exists=True):
    """已接单/已取消/订单不存在/重复回调按即时链路幂等语义处理。"""
    if not order_exists:
        return {"handled": True, "result": "order_not_found_idempotent"}
    if order_status == "cancelled":
        return {"handled": True, "result": "already_cancelled_idempotent"}
    return {"handled": False, "result": "proceed"}


# ---------------------------------------------------------------------------
# §7.3.3 passenger-service 状态机兼容
# 消费标准 order_status_machine 取消事件，兼容 BOOKING_ORDER_TYPE。
# ---------------------------------------------------------------------------
def order_status_consume_accepts(order_type, from_status, to_status):
    """OrderStatusConsume 接受预约订单从待接单进入取消状态的事件。"""
    if order_type == ORDER_TYPE_BOOKING_REALTIME:
        return from_status == "waiting_driver" and to_status == "cancelled"
    if order_type == ORDER_TYPE_REALTIME_INSTANT:
        return True  # 即时按当前逻辑全接受
    return False


def order_status_push_msg(order_type, cancel_type, dispatch_timeout_source):
    """OrderStatusPushMsgConsume 根据预约类型+系统取消+派单超时映射文案。

    系统取消+派单超时→预约呼叫超时文案；乘客主动取消→乘客取消文案。
    """
    if order_type != ORDER_TYPE_BOOKING_REALTIME:
        return "passenger_cancel"
    if cancel_type == "system" and dispatch_timeout_source:
        return "booking_dispatch_timeout"
    if cancel_type == "system":
        return "system_cancel"
    return "passenger_cancel"


def order_status_coupon_consume(order_type, cancel_type):
    """OrderStatusCouponConsume 使用当前优惠券返还和解锁逻辑处理预约取消。"""
    if order_type not in (ORDER_TYPE_REALTIME_INSTANT, ORDER_TYPE_BOOKING_REALTIME):
        return {"handled": False, "reason": "unknown_order_type"}
    return {"handled": True, "action": "refund_and_unlock"}


def order_status_send_sms(order_type, cancel_type, dispatch_timeout_source):
    """OrderStatusSendSmsConsume 按当前取消短信规则处理预约事件。"""
    if order_type not in (ORDER_TYPE_REALTIME_INSTANT, ORDER_TYPE_BOOKING_REALTIME):
        return {"send": False, "reason": "unknown_order_type"}
    if cancel_type == "system" and dispatch_timeout_source:
        return {"send": True, "template": "booking_dispatch_timeout_sms"}
    if cancel_type == "user":
        return {"send": True, "template": "user_cancel_sms"}
    return {"send": True, "template": "system_cancel_sms"}


# ---------------------------------------------------------------------------
# §7.7 优惠券降级依赖
# 查询失败不影响基础报价返回，但必须记录错误指标和日志，响应不展示优惠结果。
# 预约使用即时券 service_type=5，券计算基准为询价当前时间。
# ---------------------------------------------------------------------------
COUPON_SERVICE_TYPE_INSTANT = 5


def coupon_service_type(order_type):
    """预约使用即时券 service_type=5。"""
    if order_type in (ORDER_TYPE_BOOKING_REALTIME, ORDER_TYPE_REALTIME_INSTANT):
        return COUPON_SERVICE_TYPE_INSTANT
    raise ValueError("unknown_order_type")


def coupon_degradation(coupon_query_success, base_quote):
    """优惠券为降级依赖：查询失败不影响基础报价返回。"""
    if coupon_query_success:
        return {"base_quote": base_quote, "coupon_applied": True, "error": None}
    return {
        "base_quote": base_quote,
        "coupon_applied": False,
        "error": "coupon_query_failed",
        "error_logged": True,
        "metric_recorded": True,
        "coupon_displayed": False,
    }
