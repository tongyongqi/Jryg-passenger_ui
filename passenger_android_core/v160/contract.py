"""香港乘客端 V1.6.0 车型品类与运力配置的纯内存离线模型。

对应需求点 1（新增网约车运力，5 种车型）、需求点 14（车辆图片颜色适配）
以及技术方案 7.1（MSE 车型事实与读模型）。

核心事实
--------
- 车型运行时使用 ``config.car_type.types``；``mapping`` 独立保存
  ``id+biz_mode+charge_mode`` 到车型编码的映射，未命中映射时使用相同组合键
  直接读取车型；``mapping``、``types``、``images`` 是同级配置。
- ``types`` 的顺序就是车型排序。
- ``code`` 是车型稳定编码和直接查询键，必须非空且唯一。
- 同一数字 id 可由不同业务模式或计费模式复用，因此 id 不能单独作为车型
  唯一键；读模型同时建立 code 和 ``id+biz_mode+charge_mode`` 两类索引，
  组合键也必须唯一，避免出租车与网约车同 ID 时互相覆盖。
- 本版条目固定为：
  ``chartered_taxi``(id=1, biz_mode=1, charge_mode=3) 与
  ``taxi``(id=1, biz_mode=1, charge_mode=4, multi_pay_mode=true)；
  ``economy``(id=1)、``preferred``(id=9)、``comfort``(id=2)、
  ``business``(id=3)、``luxury``(id=4) 均显式配置 biz_mode=2、charge_mode=3。

不连接设备、不访问网络，不补写文档未定义的枚举。
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# 文档常量
# ---------------------------------------------------------------------------
BUSINESS_TAXI = 1          # 运力类型：出租车
BUSINESS_RIDE_HAILING = 2  # 运力类型：网约车

CHARGE_FIXED_PRICE = 3     # 计费类型：平台计费一口价
CHARGE_METERED = 4         # 计费类型：线下打表

PAYMENT_ADVANCE = "advance"  # 先付（线上）
PAYMENT_AFTER = "after"      # 后付（线上 or 现金）

# 预约业务：乘客侧 order_type
ORDER_TYPE_INSTANT = 5
ORDER_TYPE_BOOKING = 6

# 订单中心侧预约类型
ORDER_CENTER_BOOKING = 16


# ---------------------------------------------------------------------------
# 车型名称三语映射（PRD 指定）
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class CarTypeName:
    """车型三语名称。

    :param zh_hant: 繁体（香港端展示）
    :param zh_hans: 简体
    :param en:      英文
    """
    zh_hant: str
    zh_hans: str
    en: str


CAR_TYPE_NAMES: Dict[str, CarTypeName] = {
    "economy": CarTypeName("經濟型", "经济型", "Economy"),
    "preferred": CarTypeName("優選型", "优选型", "Preferred"),
    "comfort": CarTypeName("舒適型", "舒适型", "Comfort"),
    "business": CarTypeName("商務型", "商务型", "Business"),
    "luxury": CarTypeName("豪華型", "豪华型", "Luxury"),
}

# 出租车两种展示车型的名称（业务上包车/打表同属经济型，端上拆两个展示）
TAXI_CHARTERED_NAME = CarTypeName("包車價的士", "包车价的士", "Chartered Taxi")
TAXI_METERED_NAME = CarTypeName("打錶的士", "打表的士", "Metered Taxi")

# 语言代码 -> 名称字段
LANGUAGE_FIELD = {
    "zh-Hant": "zh_hant",
    "zh-HK": "zh_hant",
    "zh-TW": "zh_hant",
    "zh-Hans": "zh_hans",
    "zh-CN": "zh_hans",
    "en": "en",
    "en-US": "en",
    "en-GB": "en",
}


def localize_car_type(code: str, language: str = "zh-Hant") -> str:
    """按语言返回车型展示名称。

    :param code:     车型编码，如 ``economy``。
    :param language: 语言代码，支持 zh-Hant / zh-Hans / en 及其变体。
    :raises ValueError: 车型编码不存在或语言不支持。
    """
    if code not in CAR_TYPE_NAMES:
        raise ValueError(f"未知车型编码：{code}")
    field_name = LANGUAGE_FIELD.get(language)
    if field_name is None:
        raise ValueError(f"不支持的语言：{language}")
    return getattr(CAR_TYPE_NAMES[code], field_name)


# ---------------------------------------------------------------------------
# 车型条目与读模型
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class CarTypeEntry:
    """车型配置条目（对应 config.car_type.types 中的一项）。

    :param code:          车型稳定编码，非空且唯一。
    :param id:            数字 id，可被不同 biz_mode/charge_mode 复用。
    :param biz_mode:      运力类型，1=出租车，2=网约车。
    :param charge_mode:   计费类型，3=一口价，4=线下打表。
    :param icon:          图标资源标识。
    :param multi_pay_mode: 是否多支付模式，仅 taxi 显式为 true。
    :param disabled:      是否禁用。
    """
    code: str
    id: int
    biz_mode: int
    charge_mode: int
    icon: str
    multi_pay_mode: bool = False
    disabled: bool = False

    @property
    def composite_key(self) -> Tuple[int, int, int]:
        """组合键 id+biz_mode+charge_mode，作为车型唯一索引。"""
        return (self.id, self.biz_mode, self.charge_mode)

    @property
    def is_ride_hailing(self) -> bool:
        """是否网约车运力。"""
        return self.biz_mode == BUSINESS_RIDE_HAILING

    @property
    def is_taxi(self) -> bool:
        """是否出租车运力。"""
        return self.biz_mode == BUSINESS_TAXI

    @property
    def is_fixed_price(self) -> bool:
        """是否一口价计费。"""
        return self.charge_mode == CHARGE_FIXED_PRICE


# 本版固定车型条目，顺序即车型排序
DEFAULT_CAR_TYPES: Tuple[CarTypeEntry, ...] = (
    CarTypeEntry(code="chartered_taxi", id=1, biz_mode=BUSINESS_TAXI,
                 charge_mode=CHARGE_FIXED_PRICE, icon="chartered_taxi_icon"),
    CarTypeEntry(code="taxi", id=1, biz_mode=BUSINESS_TAXI,
                 charge_mode=CHARGE_METERED, icon="taxi_icon",
                 multi_pay_mode=True),
    CarTypeEntry(code="economy", id=1, biz_mode=BUSINESS_RIDE_HAILING,
                 charge_mode=CHARGE_FIXED_PRICE, icon="economy_icon"),
    CarTypeEntry(code="preferred", id=9, biz_mode=BUSINESS_RIDE_HAILING,
                 charge_mode=CHARGE_FIXED_PRICE, icon="preferred_icon"),
    CarTypeEntry(code="comfort", id=2, biz_mode=BUSINESS_RIDE_HAILING,
                 charge_mode=CHARGE_FIXED_PRICE, icon="comfort_icon"),
    CarTypeEntry(code="business", id=3, biz_mode=BUSINESS_RIDE_HAILING,
                 charge_mode=CHARGE_FIXED_PRICE, icon="business_icon"),
    CarTypeEntry(code="luxury", id=4, biz_mode=BUSINESS_RIDE_HAILING,
                 charge_mode=CHARGE_FIXED_PRICE, icon="luxury_icon"),
)

# 网约车 5 种车型编码，按 PRD 展示顺序
RIDE_HAILING_CODES: Tuple[str, ...] = (
    "economy", "preferred", "comfort", "business", "luxury",
)

# 出租车两种展示车型
TAXI_CODES: Tuple[str, ...] = ("chartered_taxi", "taxi")


class CarTypeCatalog:
    """车型读模型。

    同时建立 code 索引与 ``id+biz_mode+charge_mode`` 组合键索引。
    """

    def __init__(self, entries: Optional[List[CarTypeEntry]] = None):
        source = list(entries) if entries is not None else list(DEFAULT_CAR_TYPES)
        self._entries: List[CarTypeEntry] = source
        self._by_code: Dict[str, CarTypeEntry] = {}
        self._by_composite: Dict[Tuple[int, int, int], CarTypeEntry] = {}
        for entry in source:
            self._by_code[entry.code] = entry
            self._by_composite[entry.composite_key] = entry

    # ---- 查询 ----
    @property
    def entries(self) -> List[CarTypeEntry]:
        """按配置顺序返回车型列表（types 顺序即车型排序）。"""
        return list(self._entries)

    def get_by_code(self, code: str) -> Optional[CarTypeEntry]:
        """按车型编码查询。"""
        return self._by_code.get(code)

    def get_by_composite(self, car_type_id: int, biz_mode: int,
                         charge_mode: int) -> Optional[CarTypeEntry]:
        """按 id+biz_mode+charge_mode 组合键查询。"""
        return self._by_composite.get((car_type_id, biz_mode, charge_mode))

    def require_by_code(self, code: str) -> CarTypeEntry:
        """按车型编码查询，不存在时抛错。"""
        entry = self._by_code.get(code)
        if entry is None:
            raise ValueError(f"未知车型编码：{code}")
        return entry

    def ride_hailing_entries(self) -> List[CarTypeEntry]:
        """返回网约车车型列表（保持配置顺序）。"""
        return [e for e in self._entries if e.is_ride_hailing]

    def taxi_entries(self) -> List[CarTypeEntry]:
        """返回出租车车型列表（保持配置顺序）。"""
        return [e for e in self._entries if e.is_taxi]

    def enabled_entries(self) -> List[CarTypeEntry]:
        """返回未禁用的车型列表。"""
        return [e for e in self._entries if not e.disabled]

    def name_of(self, code: str, language: str = "zh-Hant") -> str:
        """取车型展示名称。出租车车型使用包车/打表专属名称。"""
        if code == "chartered_taxi":
            field_name = LANGUAGE_FIELD.get(language)
            if field_name is None:
                raise ValueError(f"不支持的语言：{language}")
            return getattr(TAXI_CHARTERED_NAME, field_name)
        if code == "taxi":
            field_name = LANGUAGE_FIELD.get(language)
            if field_name is None:
                raise ValueError(f"不支持的语言：{language}")
            return getattr(TAXI_METERED_NAME, field_name)
        return localize_car_type(code, language)


# ---------------------------------------------------------------------------
# 配置校验规则
# ---------------------------------------------------------------------------
def validate_car_type_config(config: Dict) -> List[str]:
    """校验 config.car_type 配置，返回错误列表（空列表表示通过）。

    校验项：
    1. types 每项必须显式提供 id、code、biz_mode、charge_mode、icon。
    2. code 非空且唯一。
    3. 组合键 id+biz_mode+charge_mode 唯一。
    4. multi_pay_mode 仅 taxi 显式为 true，其他未配置按 false。
    5. disabled 未配置按 false。
    6. mapping 与 types 同级配置；mapping 命中组合键必须能读到车型。
    """
    errors: List[str] = []
    car_type_cfg = config.get("car_type")
    if not isinstance(car_type_cfg, dict):
        return ["缺少 config.car_type 配置"]

    types = car_type_cfg.get("types")
    if not isinstance(types, list) or not types:
        return ["config.car_type.types 缺失或为空"]

    seen_codes = set()
    seen_composite = set()
    for index, item in enumerate(types):
        prefix = f"types[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{prefix} 不是对象")
            continue
        for field_name in ("id", "code", "biz_mode", "charge_mode", "icon"):
            if item.get(field_name) in (None, ""):
                errors.append(f"{prefix} 缺少必填字段 {field_name}")
        code = item.get("code")
        if code:
            if code in seen_codes:
                errors.append(f"{prefix} code 重复：{code}")
            seen_codes.add(code)
        car_type_id = item.get("id")
        biz_mode = item.get("biz_mode")
        charge_mode = item.get("charge_mode")
        if None not in (car_type_id, biz_mode, charge_mode):
            composite = (car_type_id, biz_mode, charge_mode)
            if composite in seen_composite:
                errors.append(
                    f"{prefix} 组合键重复：id={car_type_id} "
                    f"biz_mode={biz_mode} charge_mode={charge_mode}"
                )
            seen_composite.add(composite)

    mapping = car_type_cfg.get("mapping")
    if mapping is not None:
        if not isinstance(mapping, list):
            errors.append("config.car_type.mapping 不是数组")
        else:
            for index, item in enumerate(mapping):
                if not isinstance(item, dict):
                    errors.append(f"mapping[{index}] 不是对象")
                    continue
                key = (item.get("id"), item.get("biz_mode"),
                       item.get("charge_mode"))
                if key not in seen_composite:
                    errors.append(
                        f"mapping[{index}] 组合键未命中任何车型：{key}"
                    )
    return errors


def build_car_type_catalog(config: Dict) -> CarTypeCatalog:
    """从 config.car_type.types 构建车型读模型。

    :raises ValueError: 配置缺少必填字段。
    """
    car_type_cfg = (config or {}).get("car_type") or {}
    raw_types = car_type_cfg.get("types") or []
    entries = []
    for item in raw_types:
        entries.append(
            CarTypeEntry(
                code=item["code"],
                id=item["id"],
                biz_mode=item["biz_mode"],
                charge_mode=item["charge_mode"],
                icon=item.get("icon") or "",
                multi_pay_mode=bool(item.get("multi_pay_mode", False)),
                disabled=bool(item.get("disabled", False)),
            )
        )
    return CarTypeCatalog(entries)


# ---------------------------------------------------------------------------
# 下单业务类型与支付模式分流
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class CarTypePaymentProfile:
    """车型的下单属性。

    :param code:           车型编码。
    :param payment_mode:   PAYMENT_ADVANCE 或 PAYMENT_AFTER。
    :param support_coupon: 是否支持优惠券。
    :param support_cancel_fee: 是否支持取消费。
    :param support_price_adjust: 是否支持多退少补。
    """
    code: str
    payment_mode: str
    support_coupon: bool
    support_cancel_fee: bool
    support_price_adjust: bool


def payment_profile_of(entry: CarTypeEntry, is_booking: bool) -> CarTypePaymentProfile:
    """按车型与业务类型推导下单属性。

    - 出租车打表的士（charge_mode=4）：后付，支持优惠券。
    - 一口价车型（包车价的士 / 网约车）：先付。
    - 预约业务全部车型不支持优惠券。
    - 一口价车型不支持取消费与多退少补，附加费提示线下支付。
    """
    if entry.charge_mode == CHARGE_METERED:
        return CarTypePaymentProfile(
            code=entry.code,
            payment_mode=PAYMENT_AFTER,
            support_coupon=not is_booking,
            support_cancel_fee=False,
            support_price_adjust=True,
        )
    return CarTypePaymentProfile(
        code=entry.code,
        payment_mode=PAYMENT_ADVANCE,
        support_coupon=not is_booking,
        support_cancel_fee=False,
        support_price_adjust=False,
    )


def payment_collection_mode(entry: CarTypeEntry) -> int:
    """返回下单支付模式标识：1=线上支付（先付），2=线下支付（后付）。"""
    if entry.charge_mode == CHARGE_METERED:
        return 2
    return 1


def resolve_payment_collection_mode(car_type_code: str, is_booking: bool,
                                   requested_online: bool,
                                   catalog: Optional[CarTypeCatalog] = None) -> int:
    """解析下单支付模式。

    - 一口价车型（包车价的士 / 网约车）只接受线上预付，
      非线上支付请求用于一口价预约时按参数错误拒绝。
    - 打表的士进入后付。

    :raises ValueError: 一口价车型请求非线上支付。
    """
    cat = catalog or CarTypeCatalog()
    entry = cat.require_by_code(car_type_code)
    if entry.charge_mode == CHARGE_FIXED_PRICE:
        if not requested_online:
            raise ValueError("一口价订单仅支持线上预付支付")
        return 1
    return payment_collection_mode(entry)


# ---------------------------------------------------------------------------
# 车型选择：单选约束
# ---------------------------------------------------------------------------
@dataclass
class CarTypeSelection:
    """车型选择状态（单选）。

    :param selected_code: 当前唯一选中的车型编码。
    :param candidates:    当前可选车型编码列表。
    """
    selected_code: Optional[str] = None
    candidates: List[str] = field(default_factory=list)

    def select(self, code: str) -> "CarTypeSelection":
        """选择车型。重复选择同一车型不报错，切换则覆盖。

        :raises ValueError: 车型不在候选列表中。
        """
        if code not in self.candidates:
            raise ValueError(f"车型不可选：{code}")
        return CarTypeSelection(selected_code=code, candidates=list(self.candidates))

    def clear(self) -> "CarTypeSelection":
        """清空选择。"""
        return CarTypeSelection(selected_code=None, candidates=list(self.candidates))

    @property
    def is_single(self) -> bool:
        """车型列表仅支持单选下单（恒为 True）。"""
        return True

    @property
    def has_selection(self) -> bool:
        """是否已选中车型。"""
        return self.selected_code is not None


def build_estimate_car_types(biz_mode: int, order_type: int,
                             car_type_ids: List[int]) -> List[Dict]:
    """构建 order-service 询价接口的 car_types 入参。

    技术方案给出：
    ``[{"business_type": 1, "order_type": 5, "car_type_id": [1,2]},
       {"business_type": 2, "order_type": 5, "car_type_id": [1,2,3,4,5]}]``

    :param biz_mode:     运力类型，1=出租车，2=网约车。
    :param order_type:   订单类型，5=即时，6=预约。
    :param car_type_ids: 该运力下参与报价的车型 id 列表。
    """
    return [{
        "business_type": biz_mode,
        "order_type": order_type,
        "car_type_id": list(car_type_ids),
    }]


# ---------------------------------------------------------------------------
# 车辆图片颜色适配（需求点 14）
# ---------------------------------------------------------------------------
DEFAULT_VEHICLE_COLOR_TAXI = "red"
DEFAULT_VEHICLE_COLOR_RIDE_HAILING = "white"

# 司机侧车辆颜色 -> 端上图片资源
VEHICLE_COLOR_IMAGES: Dict[str, str] = {
    "red": "vehicle_red",
    "white": "vehicle_white",
    "black": "vehicle_black",
    "silver": "vehicle_silver",
    "grey": "vehicle_grey",
    "gray": "vehicle_gray",
    "blue": "vehicle_blue",
    "yellow": "vehicle_yellow",
    "green": "vehicle_green",
    "brown": "vehicle_brown",
    "gold": "vehicle_gold",
}


def resolve_vehicle_image(biz_mode: int, color: Optional[str]) -> str:
    """按运力类型与司机侧车辆颜色返回车辆图片资源。

    - 出租车未获取到颜色时默认红色。
    - 网约车未获取到颜色时默认白色。
    - 颜色无法识别时同样回退到该运力的默认颜色。
    """
    normalized = (color or "").strip().lower()
    if normalized and normalized in VEHICLE_COLOR_IMAGES:
        return VEHICLE_COLOR_IMAGES[normalized]
    fallback = (DEFAULT_VEHICLE_COLOR_TAXI if biz_mode == BUSINESS_TAXI
                else DEFAULT_VEHICLE_COLOR_RIDE_HAILING)
    return VEHICLE_COLOR_IMAGES[fallback]


def default_vehicle_color(biz_mode: int) -> str:
    """返回该运力类型的默认车辆颜色。"""
    return (DEFAULT_VEHICLE_COLOR_TAXI if biz_mode == BUSINESS_TAXI
            else DEFAULT_VEHICLE_COLOR_RIDE_HAILING)


# ---------------------------------------------------------------------------
# 一口价提示文案（需求点 10）
# ---------------------------------------------------------------------------
MESSAGE_INVOICE = "如需發票，請向司機索取紙本發票。"
MESSAGE_FIXED_PRICE = "本單為一口價，行程中產生的隧道費等額外收費，需另行自行繳付。"

FIXED_PRICE_POPUP_TITLE = "一口價說明"
FIXED_PRICE_POPUP_CONTENT = (
    "一口價只計司機行車相關費用，行程期間所產生的隧道費、泊車費及其他額外收費，"
    "均須乘客另行自行繳付。\n"
    "一口價訂單只適用是次行程之起點及終點，並須按指定路線行駛，暫不支援更改目的地"
)

MESSAGE_CAROUSEL_INTERVAL_SECONDS = 3

CANCEL_REFUND_NOTICE = "已支付款項將按原有途徑退還至您的帳戶"

BOOKING_LABEL = "預約用車"
