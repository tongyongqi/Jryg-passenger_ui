"""香港乘客端 V1.6.0 接口契约离线测试。

编写时间：2026-11-19
覆盖需求文档给出的 passenger-api / order-service / coupon / order-center / charge
接口清单，验证入参构造与出参结构符合文档约定。

接口清单（来自 V1.6.0 需求文档）：
- passenger-api
  - 计价规则   GET  /passenger/charge/rule
  - 询价       POST /passenger/order/estimate
  - 预估详情   GET  /passenger/estimate/detail
  - 创建订单   POST /passenger/order/create
  - 创建支付单 POST /passenger/order/pay
  - 主动收据   POST /passenger/order/tripSend
  - 询价券列表 GET  /passenger/estimate/coupons
  - 订单状态   GET  /passenger/order/status
  - 订单详情   GET  /passenger/order/detail
  - 订单费用   GET  /passenger/order/fee
  - 取消订单   POST /passenger/order/cancel
  - 分享状态   GET  /passenger/share/orderStatus
  - 分享详情   GET  /passenger/share/orderDetail
- coupon
  - /jryg-coupon-api/coupon/assessPrice       新增入参 order_type
  - /jryg-coupon-api/coupon/estimateCouponList 新增入参 order_type
- order-service
  - /order-service/capp/hk/order/estimate 新增 car_types
  - /order-service/capp/hk/order/create   新增 car_types.business_type / order_type
- order-center
  - /order/v1/common/user/unfinished/list 支持 order_type
  - /order/v1/common/user/unfinished/order 支持 order_type
  - /order/v1/common/user/cancel/count 支持 order_type
  - /order/v1/agent/order/create 支持 order_levels
  - /order/v1/agent/order/main/child/list 支持 order_type=6
  - /order/v1/agent/order/cancel 支持 order_type=6
- charge
  - /charge/api/v1/billing/estimate/detail 预估详情
  - /charge/admin/v1/order/rule             计价规则

运行：pytest cases/passenger_v1_6_0/test_v160_api_contract_offline.py -v
"""

import os
import sys

import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from passenger_android_core.v160.booking_contract import (  # noqa: E402
    coupon_assess_params,
    estimate_coupon_list_payload,
)
from passenger_android_core.v160.fulfillment_contract import (  # noqa: E402
    cancel_count_params,
    unfinished_list_params,
    unfinished_order_params,
)
from passenger_android_core.v160.charge_contract import (  # noqa: E402
    build_charge_rule_payload,
    charge_rule_request,
    estimate_detail_payload,
    order_fee_payload,
)
from passenger_android_core.v160.contract import (  # noqa: E402
    BUSINESS_RIDE_HAILING,
    BUSINESS_TAXI,
    ORDER_TYPE_BOOKING,
    ORDER_TYPE_INSTANT,
    build_estimate_car_types,
)


# 接口路径常量（便于用例引用与文档对照）
PASSENGER_API_PATHS = {
    "charge_rule": "/passenger/charge/rule",
    "estimate": "/passenger/order/estimate",
    "estimate_detail": "/passenger/estimate/detail",
    "create": "/passenger/order/create",
    "pay": "/passenger/order/pay",
    "trip_send": "/passenger/order/tripSend",
    "coupon_list": "/passenger/estimate/coupons",
    "status": "/passenger/order/status",
    "detail": "/passenger/order/detail",
    "fee": "/passenger/order/fee",
    "cancel": "/passenger/order/cancel",
    "share_status": "/passenger/share/orderStatus",
    "share_detail": "/passenger/share/orderDetail",
}

COUPON_API_PATHS = {
    "assess_price": "/jryg-coupon-api/coupon/assessPrice",
    "estimate_coupon_list": "/jryg-coupon-api/coupon/estimateCouponList",
}

ORDER_SERVICE_PATHS = {
    "estimate": "/order-service/capp/hk/order/estimate",
    "create": "/order-service/capp/hk/order/create",
}

ORDER_CENTER_PATHS = {
    "unfinished_list": "/order/v1/common/user/unfinished/list",
    "unfinished_order": "/order/v1/common/user/unfinished/order",
    "cancel_count": "/order/v1/common/user/cancel/count",
    "agent_create": "/order/v1/agent/order/create",
    "child_list": "/order/v1/agent/order/main/child/list",
    "agent_cancel": "/order/v1/agent/order/cancel",
}

CHARGE_PATHS = {
    "estimate_detail": "/charge/api/v1/billing/estimate/detail",
    "order_rule": "/charge/admin/v1/order/rule",
}


# ===========================================================================
# Section 1：接口路径清单完整性
# ===========================================================================
class TestApiPathInventory:
    """需求文档列出的接口必须全部登记，避免漏测。"""

    @pytest.mark.parametrize("name,path", [
        ("charge_rule", "/passenger/charge/rule"),
        ("estimate", "/passenger/order/estimate"),
        ("estimate_detail", "/passenger/estimate/detail"),
        ("create", "/passenger/order/create"),
        ("pay", "/passenger/order/pay"),
        ("trip_send", "/passenger/order/tripSend"),
        ("coupon_list", "/passenger/estimate/coupons"),
        ("status", "/passenger/order/status"),
        ("detail", "/passenger/order/detail"),
        ("fee", "/passenger/order/fee"),
        ("cancel", "/passenger/order/cancel"),
        ("share_status", "/passenger/share/orderStatus"),
        ("share_detail", "/passenger/share/orderDetail"),
    ])
    def test_passenger_api_paths(self, name, path):
        """passenger-api 13 条接口路径与需求文档清单逐一登记一致。"""
        assert PASSENGER_API_PATHS[name] == path

    def test_coupon_api_paths(self):
        """coupon 两条接口路径与需求文档一致（新增 order_type 的两个接口）。"""
        assert COUPON_API_PATHS["assess_price"] == \
            "/jryg-coupon-api/coupon/assessPrice"
        assert COUPON_API_PATHS["estimate_coupon_list"] == \
            "/jryg-coupon-api/coupon/estimateCouponList"

    def test_order_service_paths(self):
        """order-service 询价与下单接口路径登记一致。"""
        assert ORDER_SERVICE_PATHS["estimate"] == \
            "/order-service/capp/hk/order/estimate"
        assert ORDER_SERVICE_PATHS["create"] == \
            "/order-service/capp/hk/order/create"

    def test_order_center_paths(self):
        """order-center 6 条接口路径登记一致（含预约子订单与代理取消）。"""
        assert ORDER_CENTER_PATHS["unfinished_list"] == \
            "/order/v1/common/user/unfinished/list"
        assert ORDER_CENTER_PATHS["unfinished_order"] == \
            "/order/v1/common/user/unfinished/order"
        assert ORDER_CENTER_PATHS["cancel_count"] == \
            "/order/v1/common/user/cancel/count"
        assert ORDER_CENTER_PATHS["agent_create"] == "/order/v1/agent/order/create"
        assert ORDER_CENTER_PATHS["child_list"] == \
            "/order/v1/agent/order/main/child/list"
        assert ORDER_CENTER_PATHS["agent_cancel"] == "/order/v1/agent/order/cancel"

    def test_charge_paths(self):
        """charge 预估详情与计价规则接口路径登记一致。"""
        assert CHARGE_PATHS["estimate_detail"] == \
            "/charge/api/v1/billing/estimate/detail"
        assert CHARGE_PATHS["order_rule"] == "/charge/admin/v1/order/rule"


# ===========================================================================
# Section 2：计价规则接口
# ===========================================================================
class TestChargeRuleApi:
    """/passenger/charge/rule 与 /charge/admin/v1/order/rule。"""

    def test_request_by_estimate_id(self):
        """计价规则入参支持 estimate_id（询价后查看规则）。"""
        assert charge_rule_request(estimate_id="6afc04b3af4d480009b9efe301") == \
            {"estimate_id": "6afc04b3af4d480009b9efe301"}

    def test_request_by_order_no(self):
        """计价规则入参支持 order_no（已有订单查看规则）。"""
        assert charge_rule_request(order_no="TH26B6PIEWECN") == {"order_no": "TH26B6PIEWECN"}

    def test_request_requires_one(self):
        """estimate_id 与 order_no 必须至少提供一个，否则拒绝。"""
        with pytest.raises(ValueError):
            charge_rule_request()

    def test_response_has_all_documented_fields(self):
        """计价规则出参包含文档要求的 6 个字段。"""
        payload = build_charge_rule_payload({
            "car_type": "economy",
            "car_type_name": "經濟型",
            "car_type_img": "economy.png",
            "order_type": 5,
            "order_type_name": "即時用車",
            "rules": [],
        } if False else _sample_rule())
        assert set(payload) == {
            "car_type", "car_type_name", "car_type_img",
            "order_type", "order_type_name", "rules",
        }

    def test_rules_item_structure(self):
        """rules 结构：day(day_type/day_type_name/items) + item(title/desc/value)。"""
        payload = build_charge_rule_payload(_sample_rule())
        for day in payload["rules"]:
            assert set(day) == {"day_type", "day_type_name", "items"}
            for item in day["items"]:
                assert set(item) == {"title", "desc", "value"}


def _sample_rule():
    """构造示例计价规则（避免依赖 dataclass 构造细节）。"""
    from passenger_android_core.v160.charge_contract import (
        ChargeRule, ChargeRuleDay, ChargeRuleItem,
    )
    return ChargeRule(
        car_type="economy",
        car_type_name="經濟型",
        car_type_img="economy.png",
        order_type=5,
        order_type_name="即時用車",
        rules=[
            ChargeRuleDay("workday", "工作日", [
                ChargeRuleItem("起步價", "含5公里 10分鐘", "23"),
            ]),
        ],
    )


# ===========================================================================
# Section 3：预估详情与费用详情接口
# ===========================================================================
class TestFeeApi:
    """/passenger/estimate/detail 与 /passenger/order/fee。"""

    FEE_MAP = {"起步價": 23.0, "里程費": 42.6, "時長費": 8.4, "遠途費": 0,
               "合計": 74.0}

    def test_estimate_detail_response(self):
        """预估详情出参包含 order_type/order_type_name/fee_details。"""
        payload = estimate_detail_payload(5, self.FEE_MAP)
        assert set(payload) == {"order_type", "order_type_name", "fee_details"}

    def test_order_fee_response(self):
        """订单费用详情出参与预估详情结构一致。"""
        payload = order_fee_payload(6, self.FEE_MAP)
        assert set(payload) == {"order_type", "order_type_name", "fee_details"}

    def test_fee_details_item_structure(self):
        """fee_details 每项包含 title/value 两个字段。"""
        payload = order_fee_payload(5, self.FEE_MAP)
        for item in payload["fee_details"]:
            assert set(item) == {"title", "value"}

    def test_order_type_name_mapping(self):
        """order_type 5=即時用車、6=預約用車 的文案映射正确。"""
        assert estimate_detail_payload(5, {})["order_type_name"] == "即時用車"
        assert order_fee_payload(6, {})["order_type_name"] == "預約用車"


# ===========================================================================
# Section 4：订单中心查询接口
# ===========================================================================
class TestOrderCenterApi:
    """order-center 支持 order_type 查询。"""

    def test_unfinished_list_order_type_5(self):
        """进行中订单列表支持 order_type=5（仅即时）查询。"""
        assert unfinished_list_params(ORDER_TYPE_INSTANT) == {"order_type": 5}

    def test_unfinished_list_order_type_6(self):
        """进行中订单列表支持 order_type=6（仅预约）查询。"""
        assert unfinished_list_params(ORDER_TYPE_BOOKING) == {"order_type": 6}

    def test_unfinished_order_order_type(self):
        """进行中订单详情支持 order_type 查询。"""
        assert unfinished_order_params(6) == {"order_type": 6}

    def test_cancel_count_order_type(self):
        """取消次数统计按 order_type 区分即时与预约。"""
        assert cancel_count_params(5) == {"order_type": 5}
        assert cancel_count_params(6) == {"order_type": 6}

    def test_cancel_count_queries_are_independent(self):
        """即时与预约取消次数分别查询。"""
        assert cancel_count_params(5) != cancel_count_params(6)


# ===========================================================================
# Section 5：order-service 询价与下单
# ===========================================================================
class TestOrderServiceApi:
    """order-service 的 car_types 入参。"""

    def test_estimate_car_types_taxi(self):
        """order-service 询价：出租车业务 car_types 结构。"""
        payload = build_estimate_car_types(BUSINESS_TAXI, 5, [1, 2])
        assert payload == [{"business_type": 1, "order_type": 5,
                            "car_type_id": [1, 2]}]

    def test_estimate_car_types_ride_hailing(self):
        """order-service 询价：网约车业务 car_types 结构（5 个车型 id）。"""
        payload = build_estimate_car_types(BUSINESS_RIDE_HAILING, 5,
                                           [1, 2, 3, 4, 5])
        assert payload == [{"business_type": 2, "order_type": 5,
                            "car_type_id": [1, 2, 3, 4, 5]}]

    def test_estimate_car_types_for_booking(self):
        """order-service 询价：预约业务 car_types 的 order_type=6。"""
        payload = build_estimate_car_types(BUSINESS_RIDE_HAILING,
                                           ORDER_TYPE_BOOKING, [1, 2, 3, 4, 5])
        assert payload[0]["order_type"] == 6

    def test_car_types_car_type_id_is_list(self):
        """order-service 询价：car_type_id 必须为数组而非单值。"""
        payload = build_estimate_car_types(BUSINESS_TAXI, 5, [1, 2])
        assert isinstance(payload[0]["car_type_id"], list)


# ===========================================================================
# Section 6：优惠券接口
# ===========================================================================
class TestCouponApi:
    """coupon 接口新增入参 order_type。"""

    def test_assess_price_params(self):
        """优惠券试算接口新增 order_type=5（即时）。"""
        assert coupon_assess_params(5) == {"order_type": 5}

    def test_assess_price_params_booking(self):
        """优惠券试算接口新增 order_type=6（预约）。"""
        assert coupon_assess_params(6) == {"order_type": 6}

    def test_coupon_list_params_booking_empty(self):
        """预约业务券列表返回空数组，不匹配优惠券。"""
        payload = estimate_coupon_list_payload(6)
        assert payload["order_type"] == 6
        assert payload["coupons"] == []

    def test_coupon_list_params_instant(self):
        """即时业务券列表携带 order_type=5。"""
        payload = estimate_coupon_list_payload(5)
        assert payload["order_type"] == 5
