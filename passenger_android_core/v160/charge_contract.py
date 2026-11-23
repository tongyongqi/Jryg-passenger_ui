"""香港乘客端 V1.6.0 计费明细与计价规则的纯内存离线模型。

对应需求点 2（预估详情/费用详情增加计费明细）、需求点 3（新增计价规则页），
以及接口 ``/passenger/charge/rule``、``/passenger/estimate/detail``、
``/passenger/order/fee`` 的出参契约。

核心事实
--------
- 预估详情、费用详情和计价规则读取同一计费事实：按工作日、休息日以及
  即时、预约业务展示对应计费时段、公里段和单位价格。
- BFF 只按当前语言和 HKD 规则组装展示，不自行推导或重算计费规则。
- PRD 指定的报价及费用展示最多保留 1 位小数，末尾为 0 时不显示。
"""

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# 文档常量
# ---------------------------------------------------------------------------
FEE_ITEM_START_FARE = "起步價"
FEE_ITEM_DISTANCE = "里程費"
FEE_ITEM_DURATION = "時長費"
FEE_ITEM_LONG_DISTANCE = "遠途費"
FEE_ITEM_TOTAL = "合計"

#: 包车价士在预约业务下的费项名称调整为「總車費」
FEE_ITEM_CHARTER_TOTAL = "總車費"

DEFAULT_FEE_ITEMS = (
    FEE_ITEM_START_FARE,
    FEE_ITEM_DISTANCE,
    FEE_ITEM_DURATION,
    FEE_ITEM_LONG_DISTANCE,
    FEE_ITEM_TOTAL,
)

DAY_TYPE_WORKDAY = "workday"
DAY_TYPE_RESTDAY = "restday"

DAY_TYPE_NAMES = {
    DAY_TYPE_WORKDAY: "工作日",
    DAY_TYPE_RESTDAY: "休息日",
}

ORDER_TYPE_NAMES = {
    5: "即時用車",
    6: "預約用車",
}

CURRENCY_HKD = "HKD"


# ---------------------------------------------------------------------------
# 金额格式化
# ---------------------------------------------------------------------------
def format_amount(value) -> str:
    """格式化金额为展示字符串。

    最多保留 1 位小数，末尾为 0 时不显示（即 18.0 -> "18"，18.5 -> "18.5"）。

    :param value: 数值（int/float/Decimal/数字字符串）。
    :raises ValueError: 数值无法解析。
    """
    if value is None or value == "":
        raise ValueError("金额不能为空")
    try:
        amount = Decimal(str(value))
    except Exception as exc:
        raise ValueError(f"金额非法：{value}") from exc
    quantized = amount.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    if quantized == quantized.to_integral_value():
        return str(int(quantized))
    return str(quantized)


def format_amount_with_unit(value, unit: str = CURRENCY_HKD) -> str:
    """格式化金额并追加单位，如 "18 HKD"。"""
    return f"{format_amount(value)} {unit}"


# ---------------------------------------------------------------------------
# 计费事实
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ChargeRuleItem:
    """计价规则中的单个费项。

    :param title:  费项标题（起步價 / 里程費 / 時長費 / 遠途費）。
    :param desc:   描述，如「超過n公里-n公里」「普通時段 00:00-10:00」。
    :param value:  单位价格或数值。
    """
    title: str
    desc: str = ""
    value: str = ""

    def to_dict(self) -> Dict:
        return {"title": self.title, "desc": self.desc, "value": self.value}


@dataclass(frozen=True)
class ChargeRuleDay:
    """某一日期类型下的计价规则。

    :param day_type:      workday / restday。
    :param day_type_name: 日期类型名称。
    :param items:         费项列表。
    """
    day_type: str
    day_type_name: str
    items: List[ChargeRuleItem] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "day_type": self.day_type,
            "day_type_name": self.day_type_name,
            "items": [item.to_dict() for item in self.items],
        }


@dataclass(frozen=True)
class ChargeRule:
    """计价规则完整结构。

    :param car_type:      车型编码。
    :param car_type_name: 车型名称。
    :param car_type_img:  车型图片。
    :param order_type:    5=即时，6=预约。
    :param order_type_name: 业务类型名称。
    :param rules:         按日期类型分组的规则。
    """
    car_type: str
    car_type_name: str
    car_type_img: str
    order_type: int
    order_type_name: str
    rules: List[ChargeRuleDay] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "car_type": self.car_type,
            "car_type_name": self.car_type_name,
            "car_type_img": self.car_type_img,
            "order_type": self.order_type,
            "order_type_name": self.order_type_name,
            "rules": [day.to_dict() for day in self.rules],
        }

    def day_rule(self, day_type: str) -> Optional[ChargeRuleDay]:
        """按日期类型取规则。"""
        for day in self.rules:
            if day.day_type == day_type:
                return day
        return None


# ---------------------------------------------------------------------------
# 计价规则页字段组装
# ---------------------------------------------------------------------------
def build_charge_rule_payload(rule: ChargeRule) -> Dict:
    """组装 ``/passenger/charge/rule`` 出参。

    入参为 estimate_id 或 order_no，出参结构与文档一致。
    """
    return rule.to_dict()


def charge_rule_request(estimate_id: Optional[str] = None,
                        order_no: Optional[str] = None) -> Dict:
    """构造计价规则入参。

    estimate_id 与 order_no 二选一。

    :raises ValueError: 两者都未提供。
    """
    if estimate_id:
        return {"estimate_id": estimate_id}
    if order_no:
        return {"order_no": order_no}
    raise ValueError("计价规则需提供 estimate_id 或 order_no")


def charge_rule_title(car_type_name: str) -> str:
    """计价规则页标题：车型名称-計價規則。"""
    return f"{car_type_name}-計價規則"


def charge_rule_business_type(order_type: int) -> str:
    """计价规则页业务类型：即時用車 / 預約用車。"""
    return ORDER_TYPE_NAMES.get(order_type, "")


# ---------------------------------------------------------------------------
# 费项明细（预估详情 / 费用详情）
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class FeeDetail:
    """费项明细条目。

    :param title: 费项标题。
    :param value: 展示值（已格式化的字符串）。
    """
    title: str
    value: str

    def to_dict(self) -> Dict:
        return {"title": self.title, "value": self.value}


def build_fee_details(fee_map: Dict[str, object],
                      order_type: int = 5,
                      is_chartered: bool = False) -> List[Dict]:
    """组装预估详情 / 费用详情的 fee_details 出参。

    :param fee_map:     费项标题 -> 金额。
    :param order_type:  5=即时，6=预约。
    :param is_chartered: 包车价士在预约业务下费项名称调整为「總車費」。
    :return: [{"title":..., "value":...}, ...]，按标准费项顺序输出。
    """
    details: List[Dict] = []
    for title in DEFAULT_FEE_ITEMS:
        if title not in fee_map:
            continue
        display_title = title
        if is_chartered and order_type == 6 and title == FEE_ITEM_TOTAL:
            display_title = FEE_ITEM_CHARTER_TOTAL
        details.append(FeeDetail(display_title, format_amount(fee_map[title])).to_dict())
    return details


def estimate_detail_payload(order_type: int, fee_map: Dict[str, object],
                            is_chartered: bool = False) -> Dict:
    """组装 ``/passenger/estimate/detail`` 出参。"""
    return {
        "order_type": order_type,
        "order_type_name": ORDER_TYPE_NAMES.get(order_type, ""),
        "fee_details": build_fee_details(fee_map, order_type, is_chartered),
    }


def order_fee_payload(order_type: int, fee_map: Dict[str, object],
                      is_chartered: bool = False) -> Dict:
    """组装 ``/passenger/order/fee`` 出参。"""
    return {
        "order_type": order_type,
        "order_type_name": ORDER_TYPE_NAMES.get(order_type, ""),
        "fee_details": build_fee_details(fee_map, order_type, is_chartered),
    }


def fee_detail_title(car_type_name: str, is_estimate: bool) -> str:
    """费项详情页标题。

    :param is_estimate: True 为预估详情（-預估詳情），False 为费用详情（-費用詳情）。
    """
    suffix = "預估詳情" if is_estimate else "費用詳情"
    return f"{car_type_name}-{suffix}"


def payment_method_visible(is_estimate: bool) -> bool:
    """支付方式字段仅费用详情页显示。"""
    return not is_estimate


def total_is_pre_discount(fee_map: Dict[str, object]) -> bool:
    """合計为优惠前总计。"""
    return FEE_ITEM_TOTAL in fee_map


# ---------------------------------------------------------------------------
# 一口价说明文案
# ---------------------------------------------------------------------------
FIXED_PRICE_DETAIL_NOTICE = (
    "一口價訂單採取固定價收費，一口價是以預估價為基礎，根據行程公里數及起終點供需情況等因素進行一定幅度調整後的價格。\n"
    "一口價不包含行程中所產生的隧道費、行李費、動物費、停車費等附加費，需額外向司機線下支付，以實際為準。\n"
    "一口價訂單是司機根據乘客需求自願提供的出行服務，僅支持電子支付。"
)

FIXED_PRICE_PRICE_LABEL = "一口價"


def fixed_price_amount_text(amount) -> str:
    """一口价展示文案：「一口價xx HKD」。"""
    return f"{FIXED_PRICE_PRICE_LABEL}{format_amount(amount)} {CURRENCY_HKD}"


# ---------------------------------------------------------------------------
# 远途费公里段展示
# ---------------------------------------------------------------------------
def long_distance_desc(min_km: object, max_km: Optional[object] = None) -> str:
    """远途费公里段描述。

    - 有最大公里：``超过n公里-n公里``
    - 无最大公里：``超过n公里``
    """
    min_text = format_amount(min_km)
    if max_km is None or max_km == "":
        return f"超过{min_text}公里"
    return f"超过{min_text}公里-{format_amount(max_km)}公里"


def fee_item_unit_label(title: str) -> str:
    """计价规则页费项单位标签。

    - 里程費：nHKD/公里
    - 時長費：nHKD/分鍾
    - 遠途費：nHKD/公里
    - 起步價：nHKD
    """
    if title == FEE_ITEM_DISTANCE:
        return "/公里"
    if title == FEE_ITEM_DURATION:
        return "/分鍾"
    if title == FEE_ITEM_LONG_DISTANCE:
        return "/公里"
    return ""


# ---------------------------------------------------------------------------
# charge 服务接口入参
# ---------------------------------------------------------------------------
def charge_estimate_detail_request(estimate_id):
    """构造 charge 预估详情 /charge/api/v1/billing/estimate/detail 入参。"""
    return {"estimate_id": estimate_id}


def charge_order_rule_request(order_no=None, estimate_id=None):
    """构造 charge 计价规则 /charge/admin/v1/order/rule 入参。

    order_no 与 estimate_id 二选一。
    """
    if order_no:
        return {"order_no": order_no}
    if estimate_id:
        return {"estimate_id": estimate_id}
    raise ValueError("charge 计价规则需提供 order_no 或 estimate_id")


def charge_estimate_detail_response(order_type, fee_map, is_chartered=False):
    """构造 charge 预估详情出参。

    与 passenger-api 预估详情出参结构一致：
    order_type, order_type_name, fee_details[{title, value}]。
    """
    return estimate_detail_payload(order_type, fee_map, is_chartered)


def charge_order_rule_response(rule):
    """构造 charge 计价规则出参。

    与 passenger-api 计价规则出参结构一致。
    """
    return build_charge_rule_payload(rule)
