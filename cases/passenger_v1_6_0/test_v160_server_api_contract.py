"""香港乘客端 V1.6.0 服务端接口参数校验测试。

编写时间：2026-11-19
按需求文档给出的接口分类，逐一校验每个接口的入参构造与出参结构是否
与文档约定完全一致。

覆盖范围：
- passenger-api：计价规则、询价、预估详情、创建订单、创建支付单、
  主动收据、询价券列表、订单状态、订单详情、订单费用、取消订单、
  分享订单状态、分享订单详情
- coupon：询价匹配优惠券、询价优惠券列表
- order-service(api)：询价 car_types、下单 car_types.business_type/order_type
- order-service(mq)：支付完成发单规则、MQ 消息体字段
- passenger-service：支付完成 MQ 后续处理
- order-center：服务中订单列表/查询、取消次数查询、预约下单 order_levels、
  子订单列表、订单取消、司机接单（绑单）、绑单查询
- charge：预估详情、计价规则

每个测试用例对应接口文档中明确给出的字段名、类型与取值范围。
"""

import os
import sys
from datetime import datetime, timedelta

import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from passenger_android_core.v160.booking_contract import (  # noqa: E402
    BOOKING_DAILY_CANCEL_LIMIT,
    BOOKING_MIN_MINUTES,
    DRIVER_LOCATION_EXPOSURE_MINUTES,
    agent_cancel_params,
    bind_info_params,
    cancel_page_notice,
    child_list_params,
    coupon_assess_params,
    driver_bind_params,
    estimate_coupon_list_payload,
    estimate_request_params,
    order_cancel_params,
    order_create_params,
    order_detail_response,
    order_level_entry,
    order_pay_params,
    order_status_response,
    agent_order_create_params,
    share_order_detail_response,
    share_order_status_response,
    trip_send_dedup_key,
    trip_send_params,
)
from passenger_android_core.v160.charge_contract import (  # noqa: E402
    ChargeRule,
    ChargeRuleDay,
    ChargeRuleItem,
    build_charge_rule_payload,
    charge_estimate_detail_request,
    charge_estimate_detail_response,
    charge_order_rule_request,
    charge_order_rule_response,
    charge_rule_request,
    estimate_detail_payload,
    order_fee_payload,
)
from passenger_android_core.v160.contract import (  # noqa: E402
    BUSINESS_RIDE_HAILING,
    BUSINESS_TAXI,
    CHARGE_FIXED_PRICE,
    CHARGE_METERED,
    ORDER_TYPE_BOOKING,
    ORDER_TYPE_INSTANT,
    build_estimate_car_types,
)
from passenger_android_core.v160.fulfillment_contract import (  # noqa: E402
    ORDER_PAY_SYNC_FIELDS,
    ORDER_STATUS_ACCEPTED,
    ORDER_STATUS_CANCELLED,
    ORDER_STATUS_PAID,
    PAY_BROADCAST_CONSUMER_GROUP,
    PAY_BROADCAST_FORWARD_DELAY_SECONDS,
    PAY_BROADCAST_FORWARD_TOPIC,
    PAY_BROADCAST_TOPIC,
    PASSENGER_PAY_CONSUMER_GROUP,
    build_pay_sync_message,
    cancel_count_params,
    should_dispatch_after_payment,
    unfinished_list_params,
    unfinished_order_params,
)


NOW = datetime(2026, 11, 19, 10, 0, 0)
BOOKING_USE_TIME = NOW + timedelta(hours=1)


# ===========================================================================
# passenger-api：计价规则 /passenger/charge/rule
# ===========================================================================
class TestPassengerChargeRuleApi:
    """/passenger/charge/rule

    入参：estimate_id or order_no
    出参：car_type, car_type_name, car_type_img, order_type,
          order_type_name, rules[{day_type, day_type_name,
          items[{title, desc, value}]}]
    接口文档：http://yapi.sunlightmobility.hk/project/776/interface/api/58526
    """

    def test_request_by_estimate_id(self):
        """计价规则入参支持 estimate_id（询价后查看规则）。"""
        assert charge_rule_request(estimate_id="6afc04b3af4d480009b9efe301") == {"estimate_id": "6afc04b3af4d480009b9efe301"}

    def test_request_by_order_no(self):
        """计价规则入参支持 order_no（已有订单查看规则）。"""
        assert charge_rule_request(order_no="TH26B6PIEWECN") == {"order_no": "TH26B6PIEWECN"}

    def test_request_requires_one(self):
        """estimate_id 与 order_no 必须至少提供一个，否则拒绝。"""
        with pytest.raises(ValueError):
            charge_rule_request()

    def test_response_fields(self):
        """计价规则出参包含文档要求的 6 个字段。"""
        rule = _sample_charge_rule()
        payload = build_charge_rule_payload(rule)
        assert set(payload) == {
            "car_type", "car_type_name", "car_type_img",
            "order_type", "order_type_name", "rules",
        }

    def test_rules_day_structure(self):
        """rules 每段包含 day_type/day_type_name/items。"""
        payload = build_charge_rule_payload(_sample_charge_rule())
        for day in payload["rules"]:
            assert set(day) == {"day_type", "day_type_name", "items"}

    def test_rules_item_structure(self):
        """rules 内 items 每项包含 title/desc/value。"""
        payload = build_charge_rule_payload(_sample_charge_rule())
        for day in payload["rules"]:
            for item in day["items"]:
                assert set(item) == {"title", "desc", "value"}


# ===========================================================================
# passenger-api：询价 /passenger/order/estimate
# ===========================================================================
class TestPassengerEstimateApi:
    """/passenger/order/estimate 兼容网约车、预约一口价。"""

    def test_request_instant(self):
        """询价入参：即时订单 order_type=5，car_types 含网约车 5 车型。"""
        car_types = build_estimate_car_types(BUSINESS_RIDE_HAILING, 5,
                                             [1, 2, 3, 4, 5])
        params = estimate_request_params(
            origin={"lat": 22.2856, "lng": 114.1568},
            destination={"lat": 22.2856, "lng": 114.1569},
            order_type=5, car_types=car_types)
        assert params["order_type"] == 5
        assert params["car_types"] == car_types

    def test_request_booking(self):
        """询价入参：预约订单 order_type=6，car_types 内 order_type 同步为 6。"""
        car_types = build_estimate_car_types(BUSINESS_RIDE_HAILING, 6,
                                             [1, 2, 3, 4, 5])
        params = estimate_request_params(
            origin={"lat": 22.2856, "lng": 114.1568},
            destination={"lat": 22.2856, "lng": 114.1569},
            order_type=6, car_types=car_types)
        assert params["order_type"] == 6
        assert params["car_types"][0]["order_type"] == 6

    def test_request_taxi_and_ride_hailing(self):
        """询价同时包含出租车与网约车两组运力。"""
        taxi = build_estimate_car_types(BUSINESS_TAXI, 5, [1, 2])
        ride = build_estimate_car_types(BUSINESS_RIDE_HAILING, 5,
                                        [1, 2, 3, 4, 5])
        car_types = taxi + ride
        params = estimate_request_params(
            origin={"lat": 22.2856, "lng": 114.1568},
            destination={"lat": 22.2856, "lng": 114.1569},
            order_type=5, car_types=car_types)
        assert len(params["car_types"]) == 2
        biz_types = {c["business_type"] for c in params["car_types"]}
        assert biz_types == {BUSINESS_TAXI, BUSINESS_RIDE_HAILING}


# ===========================================================================
# passenger-api：预估详情 /passenger/estimate/detail
# ===========================================================================
class TestPassengerEstimateDetailApi:
    """/passenger/estimate/detail

    出参：order_type, order_type_name, fee_details[{title, value}]
    接口文档：http://yapi.sunlightmobility.hk/project/776/interface/api/58205
    """

    FEE_MAP = {"起步價": 23.0, "里程費": 42.6, "時長費": 8.4,
               "遠途費": 0, "合計": 74.0}

    def test_response_fields(self):
        """预估详情出参含 order_type/order_type_name/fee_details。"""
        payload = estimate_detail_payload(5, self.FEE_MAP)
        assert set(payload) == {"order_type", "order_type_name", "fee_details"}

    def test_fee_details_item_fields(self):
        """fee_details 每项含 title/value。"""
        payload = estimate_detail_payload(5, self.FEE_MAP)
        for item in payload["fee_details"]:
            assert set(item) == {"title", "value"}

    def test_instant_order_type_name(self):
        """即时订单 order_type_name=即時用車。"""
        payload = estimate_detail_payload(5, {})
        assert payload["order_type_name"] == "即時用車"

    def test_booking_order_type_name(self):
        """预约订单 order_type_name=預約用車。"""
        payload = estimate_detail_payload(6, {})
        assert payload["order_type_name"] == "預約用車"

    def test_amount_format_no_trailing_zero(self):
        """金额末尾为 0 时不显示小数位。"""
        payload = estimate_detail_payload(5, {"起步價": 23.0, "合計": 74.0})
        values = {item["title"]: item["value"] for item in payload["fee_details"]}
        assert values["起步價"] == "23"
        assert values["合計"] == "74"

    def test_amount_format_with_decimal(self):
        """金额含 1 位小数时正常显示。"""
        payload = estimate_detail_payload(5, {"起步價": 23.5})
        values = {item["title"]: item["value"] for item in payload["fee_details"]}
        assert values["起步價"] == "23.5"


# ===========================================================================
# passenger-api：创建订单 /passenger/order/create
# ===========================================================================
class TestPassengerOrderCreateApi:
    """/passenger/order/create 兼容网约车、预约一口价。"""

    def test_instant_create(self):
        """即时网约车下单入参：order_type=5、先付、携带 business_type。"""
        params = order_create_params(
            order_type=5, car_type_code="economy",
            estimate_id="6afc04b3af4d480009b9efe301", payment_collection_mode=1,
            business_type=BUSINESS_RIDE_HAILING, car_type_id=1)
        assert params["order_type"] == 5
        assert params["payment_collection_mode"] == 1
        assert params["business_type"] == BUSINESS_RIDE_HAILING

    def test_booking_create(self):
        """预约下单入参：order_type=6 并携带 use_time 出发时间。"""
        params = order_create_params(
            order_type=6, car_type_code="economy",
            estimate_id="6afc04b3af4d480009b9efe301", payment_collection_mode=1,
            business_type=BUSINESS_RIDE_HAILING, car_type_id=1,
            use_time="2026-11-19 11:00")
        assert params["order_type"] == 6
        assert params["use_time"] == "2026-11-19 11:00"

    def test_booking_no_coupon(self):
        """预约订单不携带 coupon_code。"""
        params = order_create_params(
            order_type=6, car_type_code="economy",
            estimate_id="6afc04b3af4d480009b9efe301", payment_collection_mode=1,
            coupon_code="nudHu2Dixvv2b1iv")
        assert "coupon_code" not in params

    def test_instant_with_coupon(self):
        """即时订单允许携带 coupon_code。"""
        params = order_create_params(
            order_type=5, car_type_code="taxi",
            estimate_id="6afc04b3af4d480009b9efe301", payment_collection_mode=2,
            coupon_code="nudHu2Dixvv2b1iv")
        assert params["coupon_code"] == "nudHu2Dixvv2b1iv"

    def test_service_preference_ids(self):
        """下单入参透传 service_preference_ids（儿童/宠物等偏好）。"""
        params = order_create_params(
            order_type=5, car_type_code="economy",
            estimate_id="6afc04b3af4d480009b9efe301", payment_collection_mode=1,
            service_preference_ids=[1, 2])
        assert params["service_preference_ids"] == [1, 2]


# ===========================================================================
# passenger-api：创建支付单 /passenger/order/pay
# ===========================================================================
class TestPassengerOrderPayApi:
    """/passenger/order/pay 兼容网约车、预约一口价，支付成功后进入可派单。"""

    def test_pay_params_basic(self):
        """支付入参含 order_no 与 pay_type。"""
        params = order_pay_params("TH26B6PIEWECN", pay_type=1)
        assert params["order_no"] == "TH26B6PIEWECN"
        assert params["pay_type"] == 1

    def test_pay_params_with_business_type(self):
        """网约车支付入参携带 business_type 与 order_type=5。"""
        params = order_pay_params("TH26B6PIEWECN", business_type=BUSINESS_RIDE_HAILING,
                                  order_type=5)
        assert params["business_type"] == BUSINESS_RIDE_HAILING
        assert params["order_type"] == 5

    def test_pay_params_booking(self):
        """预约支付入参 order_type=6。"""
        params = order_pay_params("TH26B6PIEWECN", business_type=BUSINESS_RIDE_HAILING,
                                  order_type=6)
        assert params["order_type"] == 6


# ===========================================================================
# passenger-api：主动收据 /passenger/order/tripSend
# ===========================================================================
class TestPassengerTripSendApi:
    """/passenger/order/tripSend

    兼容网约车和预约复用归属、支付状态、邮箱及 30 秒防重规则。
    """

    def test_trip_send_params(self):
        """主动收据入参含 order_no、email 和 order_type=6。"""
        params = trip_send_params("TH26B6PIEWECN", "v160_test@sunlightmobility.hk", order_type=6)
        assert params["order_no"] == "TH26B6PIEWECN"
        assert params["email"] == "v160_test@sunlightmobility.hk"
        assert params["order_type"] == 6

    def test_trip_send_instant(self):
        """即时业务主动收据入参 order_type=5。"""
        params = trip_send_params("TH26B6PIEWECN", "v160_test@sunlightmobility.hk", order_type=5)
        assert params["order_type"] == 5

    def test_dedup_key(self):
        """相同订单号与邮箱生成相同防重键（30 秒防重依据）。"""
        key1 = trip_send_dedup_key("TH26B6PIEWECN", "passenger_v160_test@sunlightmobility.hk")
        key2 = trip_send_dedup_key("TH26B6PIEWECN", "passenger_v160_test@sunlightmobility.hk")
        assert key1 == key2

    def test_dedup_key_differs_by_order(self):
        """不同订单号生成不同防重键。"""
        key1 = trip_send_dedup_key("TH26B6PIEWECN", "passenger_v160_test@sunlightmobility.hk")
        key2 = trip_send_dedup_key("TH26B6PIEWECN2", "passenger_v160_test@sunlightmobility.hk")
        assert key1 != key2

    def test_dedup_key_differs_by_email(self):
        """不同邮箱生成不同防重键。"""
        key1 = trip_send_dedup_key("TH26B6PIEWECN", "passenger_v160_test@sunlightmobility.hk")
        key2 = trip_send_dedup_key("TH26B6PIEWECN", "alt_passenger_v160_test@sunlightmobility.hk")
        assert key1 != key2


# ===========================================================================
# passenger-api：询价券列表 /passenger/estimate/coupons
# ===========================================================================
class TestPassengerEstimateCouponsApi:
    """/passenger/estimate/coupons 兼容预约用车展示。"""

    def test_coupon_list_instant(self):
        """即时业务券列表入参携带 order_type=5。"""
        payload = estimate_coupon_list_payload(5)
        assert payload["order_type"] == 5

    def test_coupon_list_booking_empty(self):
        """预约业务返回空可用结果。"""
        payload = estimate_coupon_list_payload(6)
        assert payload["order_type"] == 6
        assert payload["coupons"] == []


# ===========================================================================
# passenger-api：订单状态 /passenger/order/status
# ===========================================================================
class TestPassengerOrderStatusApi:
    """/passenger/order/status

    兼容网约车、预约一口价。
    order_status=100（司机已接单，待服务），预约用车时间>20m 司机位置不下发。
    """

    def test_accepted_driver_location_visible_within_20min(self):
        """出发前 20 分钟内下发司机位置。"""
        use_time = NOW + timedelta(minutes=15)
        resp = order_status_response(
            ORDER_STATUS_ACCEPTED, order_type=6,
            use_time=use_time, now=NOW,
            driver_location={"lat": 22.2856, "lng": 114.1568})
        assert resp["order_status"] == 100
        assert resp["driver_location"] is not None

    def test_accepted_driver_location_hidden_beyond_20min(self):
        """出发时间>20m 司机位置不下发。"""
        use_time = NOW + timedelta(minutes=DRIVER_LOCATION_EXPOSURE_MINUTES + 1)
        resp = order_status_response(
            ORDER_STATUS_ACCEPTED, order_type=6,
            use_time=use_time, now=NOW,
            driver_location={"lat": 22.2856, "lng": 114.1568})
        assert resp["order_status"] == 100
        assert resp["driver_location"] is None

    def test_accepted_driver_location_boundary_20min(self):
        """恰好 20 分钟时下发司机位置（闭区间）。"""
        use_time = NOW + timedelta(minutes=DRIVER_LOCATION_EXPOSURE_MINUTES)
        resp = order_status_response(
            ORDER_STATUS_ACCEPTED, order_type=6,
            use_time=use_time, now=NOW,
            driver_location={"lat": 22.2856, "lng": 114.1568})
        assert resp["driver_location"] is not None

    def test_non_accepted_status_driver_location(self):
        """非待服务状态正常下发司机位置。"""
        resp = order_status_response(
            ORDER_STATUS_PAID, order_type=6,
            driver_location={"lat": 22.2856, "lng": 114.1568})
        assert resp["driver_location"] is not None


# ===========================================================================
# passenger-api：订单详情 /passenger/order/detail
# ===========================================================================
class TestPassengerOrderDetailApi:
    """/passenger/order/detail

    兼容网约车、预约一口价、预约预付取消结果增加原路退款提示。
    order_status=100 表示司机已接单。
    出参：order_cancel_reason。
    接口文档：http://yapi.sunlightmobility.hk/project/776/interface/api/52851
    """

    def test_detail_with_cancel_reason(self):
        """已取消订单返回 order_cancel_reason。"""
        resp = order_detail_response(
            ORDER_STATUS_CANCELLED, order_type=6,
            order_cancel_reason="dispatch_timeout")
        assert resp["order_cancel_reason"] == "dispatch_timeout"

    def test_detail_without_cancel_reason(self):
        """未取消订单不返回 order_cancel_reason 字段。"""
        resp = order_detail_response(
            ORDER_STATUS_ACCEPTED, order_type=6)
        assert "order_cancel_reason" not in resp

    def test_detail_instant(self):
        """即时订单详情返回 order_type=5。"""
        resp = order_detail_response(
            ORDER_STATUS_ACCEPTED, order_type=5)
        assert resp["order_type"] == 5

    def test_detail_accepts_extra_fields(self):
        """订单详情支持透传 order_no/car_type 等额外字段。"""
        resp = order_detail_response(
            ORDER_STATUS_ACCEPTED, order_type=6,
            order_no="TH26B6PIEWECN", car_type="economy")
        assert resp["order_no"] == "TH26B6PIEWECN"
        assert resp["car_type"] == "economy"


# ===========================================================================
# passenger-api：订单费用详情 /passenger/order/fee
# ===========================================================================
class TestPassengerOrderFeeApi:
    """/passenger/order/fee

    出参：order_type, order_type_name, fee_details[{title, value}]
    接口文档：http://yapi.sunlightmobility.hk/project/776/interface/api/58217
    """

    FEE_MAP = {"起步價": 23.0, "里程費": 42.6, "時長費": 8.4,
               "遠途費": 0, "合計": 74.0}

    def test_response_fields(self):
        """订单费用详情出参含 order_type/order_type_name/fee_details。"""
        payload = order_fee_payload(5, self.FEE_MAP)
        assert set(payload) == {"order_type", "order_type_name", "fee_details"}

    def test_fee_details_item_fields(self):
        """费用详情每项含 title/value。"""
        payload = order_fee_payload(5, self.FEE_MAP)
        for item in payload["fee_details"]:
            assert set(item) == {"title", "value"}

    def test_booking_order_type_name(self):
        """预约订单费用详情 order_type_name=預約用車。"""
        payload = order_fee_payload(6, {})
        assert payload["order_type_name"] == "預約用車"


# ===========================================================================
# passenger-api：取消订单 /passenger/order/cancel
# ===========================================================================
class TestPassengerOrderCancelApi:
    """/passenger/order/cancel 兼容预约达到每日上限不阻止取消。"""

    def test_cancel_params_basic(self):
        """取消入参含 order_no 与 order_type=6。"""
        params = order_cancel_params("TH26B6PIEWECN", order_type=6)
        assert params["order_no"] == "TH26B6PIEWECN"
        assert params["order_type"] == 6

    def test_cancel_with_reason(self):
        """取消入参支持携带 cancel_reason。"""
        params = order_cancel_params("TH26B6PIEWECN", order_type=6,
                                     cancel_reason="passenger_cancel")
        assert params["cancel_reason"] == "passenger_cancel"

    def test_cancel_instant(self):
        """即时订单取消入参 order_type=5。"""
        params = order_cancel_params("TH26B6PIEWECN", order_type=5)
        assert params["order_type"] == 5


# ===========================================================================
# passenger-api：分享订单状态 /passenger/share/orderStatus
# ===========================================================================
class TestPassengerShareOrderStatusApi:
    """/passenger/share/orderStatus

    同订单状态，预约未完成订单分享有效期 72h。
    """

    def test_share_status_valid_within_72h(self):
        """接单后 72 小时内分享状态为有效。"""
        accepted_at = NOW
        resp = share_order_status_response(
            ORDER_STATUS_ACCEPTED, order_type=6,
            accepted_at=accepted_at, trip_ended_at=None,
            now=NOW + timedelta(hours=71))
        assert resp["share_state"] == "valid"

    def test_share_status_expired_after_72h(self):
        """超过接单后 72 小时分享状态为失效。"""
        accepted_at = NOW
        resp = share_order_status_response(
            ORDER_STATUS_ACCEPTED, order_type=6,
            accepted_at=accepted_at, trip_ended_at=None,
            now=NOW + timedelta(hours=73))
        assert resp["share_state"] == "expired"


# ===========================================================================
# passenger-api：分享订单详情 /passenger/share/orderDetail
# ===========================================================================
class TestPassengerShareOrderDetailApi:
    """/passenger/share/orderDetail

    同订单详情，预约未完成订单分享有效期 72h。
    出参：order_cancel_reason。
    接口文档：http://yapi.sunlightmobility.hk/project/776/interface/api/58442
    """

    def test_share_detail_with_cancel_reason(self):
        """分享详情在已取消订单时返回 order_cancel_reason。"""
        resp = share_order_detail_response(
            ORDER_STATUS_CANCELLED, order_type=6,
            order_cancel_reason="dispatch_timeout")
        assert resp["order_cancel_reason"] == "dispatch_timeout"

    def test_share_detail_valid_within_72h(self):
        """接单后 72 小时内分享详情状态为有效。"""
        resp = share_order_detail_response(
            ORDER_STATUS_ACCEPTED, order_type=6,
            accepted_at=NOW, trip_ended_at=None,
            now=NOW + timedelta(hours=71))
        assert resp["share_state"] == "valid"

    def test_share_detail_expired_after_72h(self):
        """超过接单后 72 小时分享详情状态为失效。"""
        resp = share_order_detail_response(
            ORDER_STATUS_ACCEPTED, order_type=6,
            accepted_at=NOW, trip_ended_at=None,
            now=NOW + timedelta(hours=73))
        assert resp["share_state"] == "expired"

    def test_share_detail_no_share_state_for_instant(self):
        """即时业务不携带 share_state。"""
        resp = share_order_detail_response(
            ORDER_STATUS_ACCEPTED, order_type=5)
        assert "share_state" not in resp


# ===========================================================================
# coupon：询价匹配优惠券 /jryg-coupon-api/coupon/assessPrice
# ===========================================================================
class TestCouponAssessPriceApi:
    """/jryg-coupon-api/coupon/assessPrice 新增入参 order_type。"""

    def test_assess_price_instant(self):
        """优惠券试算入参 order_type=5（即时）。"""
        assert coupon_assess_params(5) == {"order_type": 5}

    def test_assess_price_booking(self):
        """优惠券试算入参 order_type=6（预约）。"""
        assert coupon_assess_params(6) == {"order_type": 6}


# ===========================================================================
# coupon：询价优惠券列表 /jryg-coupon-api/coupon/estimateCouponList
# ===========================================================================
class TestCouponEstimateCouponListApi:
    """/jryg-coupon-api/coupon/estimateCouponList 新增入参 order_type。"""

    def test_coupon_list_instant(self):
        """优惠券列表入参 order_type=5（即时）。"""
        payload = estimate_coupon_list_payload(5)
        assert payload["order_type"] == 5

    def test_coupon_list_booking_empty(self):
        """优惠券列表入参 order_type=6（预约），且不返回可用券。"""
        payload = estimate_coupon_list_payload(6)
        assert payload["order_type"] == 6
        assert payload["coupons"] == []


# ===========================================================================
# order-service(api)：询价 /order-service/capp/hk/order/estimate
# ===========================================================================
class TestOrderServiceEstimateApi:
    """/order-service/capp/hk/order/estimate

    新增字段 car_types:
    [{"business_type": 1, "order_type": 5, "car_type_id": [1,2]},
     {"business_type": 2, "order_type": 5, "car_type_id": [1,2,3,4,5]}]
    """

    def test_car_types_taxi(self):
        """order-service 询价 car_types：出租车 business_type=1。"""
        payload = build_estimate_car_types(BUSINESS_TAXI, 5, [1, 2])
        assert payload == [{"business_type": 1, "order_type": 5,
                            "car_type_id": [1, 2]}]

    def test_car_types_ride_hailing(self):
        """order-service 询价 car_types：网约车 business_type=2 且含 5 个车型 id。"""
        payload = build_estimate_car_types(BUSINESS_RIDE_HAILING, 5,
                                           [1, 2, 3, 4, 5])
        assert payload == [{"business_type": 2, "order_type": 5,
                            "car_type_id": [1, 2, 3, 4, 5]}]

    def test_car_types_booking_order_type(self):
        """order-service 询价 car_types：预约业务 order_type=6。"""
        payload = build_estimate_car_types(BUSINESS_RIDE_HAILING, 6,
                                           [1, 2, 3, 4, 5])
        assert payload[0]["order_type"] == 6

    def test_car_type_id_is_list(self):
        """order-service 询价 car_types：car_type_id 必须为数组。"""
        payload = build_estimate_car_types(BUSINESS_TAXI, 5, [1, 2])
        assert isinstance(payload[0]["car_type_id"], list)

    def test_full_car_types_both_businesses(self):
        """文档示例：出租车 + 网约车两组。"""
        taxi = build_estimate_car_types(BUSINESS_TAXI, 5, [1, 2])
        ride = build_estimate_car_types(BUSINESS_RIDE_HAILING, 5,
                                        [1, 2, 3, 4, 5])
        car_types = taxi + ride
        assert len(car_types) == 2
        assert car_types[0]["business_type"] == 1
        assert car_types[1]["business_type"] == 2
        assert car_types[0]["car_type_id"] == [1, 2]
        assert car_types[1]["car_type_id"] == [1, 2, 3, 4, 5]


# ===========================================================================
# order-service(api)：下单 /order-service/capp/hk/order/create
# ===========================================================================
class TestOrderServiceCreateApi:
    """/order-service/capp/hk/order/create

    新增字段：car_types.business_type, order_type
    订单支持一单多车型。
    """

    def test_create_params_instant(self):
        """order-service 下单：即时请求携带顶层 business_type 与 car_type_id。"""
        params = order_create_params(
            order_type=5, car_type_code="economy",
            estimate_id="6afc04b3af4d480009b9efe301", payment_collection_mode=1,
            business_type=BUSINESS_RIDE_HAILING, car_type_id=1)
        assert params["business_type"] == BUSINESS_RIDE_HAILING
        assert params["car_type_id"] == 1

    def test_create_params_booking(self):
        """order-service 下单：预约请求携带 order_type=6 与 use_time。"""
        params = order_create_params(
            order_type=6, car_type_code="economy",
            estimate_id="6afc04b3af4d480009b9efe301", payment_collection_mode=1,
            business_type=BUSINESS_RIDE_HAILING, car_type_id=1,
            use_time="2026-11-19 11:00")
        assert params["order_type"] == 6
        assert params["use_time"] == "2026-11-19 11:00"

    def test_create_params_with_car_types(self):
        """一单多车型：car_types 嵌套数组包含 business_type 和 order_type。"""
        car_types = build_estimate_car_types(
            BUSINESS_RIDE_HAILING, 5, [1, 2, 3, 4, 5])
        params = order_create_params(
            order_type=5, car_type_code="economy",
            estimate_id="6afc04b3af4d480009b9efe301", payment_collection_mode=1,
            business_type=BUSINESS_RIDE_HAILING, car_type_id=1,
            car_types=car_types)
        assert "car_types" in params
        assert isinstance(params["car_types"], list)
        assert params["car_types"][0]["business_type"] == BUSINESS_RIDE_HAILING
        assert params["car_types"][0]["order_type"] == 5
        assert isinstance(params["car_types"][0]["car_type_id"], list)

    def test_create_params_multi_business_car_types(self):
        """一单多车型：car_types 同时包含出租车和网约车两组。"""
        taxi_types = build_estimate_car_types(BUSINESS_TAXI, 5, [1, 2])
        ride_types = build_estimate_car_types(
            BUSINESS_RIDE_HAILING, 5, [1, 2, 3, 4, 5])
        car_types = taxi_types + ride_types
        params = order_create_params(
            order_type=5, car_type_code="economy",
            estimate_id="6afc04b3af4d480009b9efe301", payment_collection_mode=1,
            business_type=BUSINESS_RIDE_HAILING, car_type_id=1,
            car_types=car_types)
        assert len(params["car_types"]) == 2
        assert params["car_types"][0]["business_type"] == BUSINESS_TAXI
        assert params["car_types"][1]["business_type"] == BUSINESS_RIDE_HAILING


# ===========================================================================
# order-service(mq)：支付完成发单规则
# ===========================================================================
class TestOrderServiceMqDispatch:
    """支付完成发单规则。

    即时支付完成发单，预约不发单。
    business_type=2（网约车），order_type=5（即时）发单，order_type=6（预约）不发单。
    """

    @pytest.mark.parametrize("business_type,order_type,expected", [
        (BUSINESS_RIDE_HAILING, ORDER_TYPE_INSTANT, True),    # 网约车即时 → 发单
        (BUSINESS_RIDE_HAILING, ORDER_TYPE_BOOKING, False),   # 网约车预约 → 不发单
        (BUSINESS_TAXI, ORDER_TYPE_INSTANT, True),            # 出租车即时 → 发单
        (BUSINESS_TAXI, ORDER_TYPE_BOOKING, False),           # 出租车预约 → 不发单
    ])
    def test_should_dispatch(self, business_type, order_type, expected):
        """发单规则：即时(order_type=5)发单，预约(order_type=6)不发单。"""
        assert should_dispatch_after_payment(business_type, order_type) is expected


# ===========================================================================
# order-service(mq)：支付完成转发 MQ 消息体
# ===========================================================================
class TestOrderServiceMqMessage:
    """支付完成转发 MQ。

    Topic: topic_cashier_trade_order_pay_broadcast
    Consumer: consumer_group_order_service_trade_order_pay_broadcast
    转发 Topic: topic_order_service_order_pay_broadcast (延时 1s)
    """

    def test_topics(self):
        """MQ Topic、Consumer 组与转发延时常量与需求文档一致。"""
        assert PAY_BROADCAST_TOPIC == "topic_cashier_trade_order_pay_broadcast"
        assert PAY_BROADCAST_CONSUMER_GROUP == \
            "consumer_group_order_service_trade_order_pay_broadcast"
        assert PAY_BROADCAST_FORWARD_TOPIC == \
            "topic_order_service_order_pay_broadcast"
        assert PAY_BROADCAST_FORWARD_DELAY_SECONDS == 1

    def test_passenger_consumer_group(self):
        """passenger-service 消费 topic_order_service_order_pay_broadcast。"""
        assert PASSENGER_PAY_CONSUMER_GROUP == \
            "consumer_group_passenger_service_trade_order_pay_broadcast"

    def test_message_fields_complete(self):
        """消息体字段与文档 OrderPaySyncMessage struct 完全一致。

        文档定义 18 个 JSON 字段（不含 EventID）：
        order_id, order_no, trade_no, order_type, city_id, agent_id,
        is_paid_advance, pay_channel_name, pay_amount, total_discount_amount,
        discount_amount, agent_discount_amount, premium_amount, voucher_amount,
        voucher_id, pay_type, company_trade_no, company_pay_agent
        """
        # 文档定义的独立字段清单，不从实现常量 ORDER_PAY_SYNC_FIELDS 引用
        DOCUMENTED_MQ_FIELDS = {
            "order_id", "order_no", "trade_no", "order_type", "city_id",
            "agent_id", "is_paid_advance", "pay_channel_name", "pay_amount",
            "total_discount_amount", "discount_amount", "agent_discount_amount",
            "premium_amount", "voucher_amount", "voucher_id", "pay_type",
            "company_trade_no", "company_pay_agent",
        }
        msg = build_pay_sync_message(
            order_id=100001, order_no="TH26B6PIEWECN", trade_no="TR20261119001",
            order_type=5, city_id=514, agent_id=1,
            is_paid_advance=True, pay_channel_name="epayment",
            pay_amount=7400, total_discount_amount=1010,
            discount_amount=1010, agent_discount_amount=0,
            premium_amount=0, voucher_amount=0, voucher_id="",
            pay_type=1, company_trade_no="", company_pay_agent=0,
            business_type=BUSINESS_RIDE_HAILING)
        payload = msg.to_dict()
        assert set(payload) == DOCUMENTED_MQ_FIELDS

    # 文档定义的 18 字段，用于参数化逐一验证
    _MQ_FIELDS = [
        "order_id", "order_no", "trade_no", "order_type", "city_id",
        "agent_id", "is_paid_advance", "pay_channel_name", "pay_amount",
        "total_discount_amount", "discount_amount", "agent_discount_amount",
        "premium_amount", "voucher_amount", "voucher_id", "pay_type",
        "company_trade_no", "company_pay_agent",
    ]

    @pytest.mark.parametrize("field", _MQ_FIELDS)
    def test_message_field_present(self, field):
        """文档定义的 18 个字段逐一存在于消息体中。"""
        msg = build_pay_sync_message(order_id=100001, order_no="TH26B6PIEWECN", trade_no="TR20261119001")
        payload = msg.to_dict()
        assert field in payload

    def test_message_should_dispatch_instant(self):
        """即时消息判定为发单。"""
        msg = build_pay_sync_message(order_id=100001, order_no="TH26B6PIEWECN", trade_no="TR20261119001",
                                     order_type=5,
                                     business_type=BUSINESS_RIDE_HAILING)
        assert msg.should_dispatch() is True

    def test_message_should_not_dispatch_booking(self):
        """预约消息判定为不发单。"""
        msg = build_pay_sync_message(order_id=100001, order_no="TH26B6PIEWECN", trade_no="TR20261119001",
                                     order_type=6,
                                     business_type=BUSINESS_RIDE_HAILING)
        assert msg.should_dispatch() is False

    def test_message_field_types(self):
        """文档标注的字段类型校验。"""
        msg = build_pay_sync_message(
            order_id=100001, order_no="TH26B6PIEWECN", trade_no="TR20261119001",
            order_type=5, city_id=514, agent_id=1,
            is_paid_advance=True, pay_channel_name="epayment",
            pay_amount=7400, total_discount_amount=1010,
            discount_amount=1010, agent_discount_amount=0,
            premium_amount=0, voucher_amount=0, voucher_id="V1",
            pay_type=1, company_trade_no="CT1", company_pay_agent=1,
            business_type=BUSINESS_RIDE_HAILING)
        payload = msg.to_dict()
        assert isinstance(payload["order_id"], int)
        assert isinstance(payload["order_no"], str)
        assert isinstance(payload["trade_no"], str)
        assert isinstance(payload["order_type"], int)
        assert isinstance(payload["city_id"], int)
        assert isinstance(payload["agent_id"], int)
        assert isinstance(payload["is_paid_advance"], bool)
        assert isinstance(payload["pay_channel_name"], str)
        assert isinstance(payload["pay_amount"], int)
        assert isinstance(payload["total_discount_amount"], int)
        assert isinstance(payload["discount_amount"], int)
        assert isinstance(payload["agent_discount_amount"], int)
        assert isinstance(payload["premium_amount"], int)
        assert isinstance(payload["voucher_amount"], int)
        assert isinstance(payload["voucher_id"], str)
        assert isinstance(payload["pay_type"], int)
        assert isinstance(payload["company_trade_no"], str)
        assert isinstance(payload["company_pay_agent"], int)
        # business_type 不在文档定义的 18 字段中，不写入 MQ JSON

    def test_amount_in_cents(self):
        """文档标注金额单位为分。"""
        msg = build_pay_sync_message(order_id=100001, order_no="TH26B6PIEWECN", trade_no="TR20261119001",
                                     pay_amount=7400,
                                     total_discount_amount=1010,
                                     discount_amount=1010)
        payload = msg.to_dict()
        assert payload["pay_amount"] == 7400
        assert payload["total_discount_amount"] == 1010
        assert payload["discount_amount"] == 1010


# ===========================================================================
# order-center：服务中订单列表 /order/v1/common/user/unfinished/list
# ===========================================================================
class TestOrderCenterUnfinishedListApi:
    """/order/v1/common/user/unfinished/list 支持 order_type 查询。"""

    def test_instant(self):
        """进行中订单列表按 order_type=5 查询即时订单。"""
        assert unfinished_list_params(ORDER_TYPE_INSTANT) == {"order_type": 5}

    def test_booking(self):
        """进行中订单列表按 order_type=6 查询预约订单。"""
        assert unfinished_list_params(ORDER_TYPE_BOOKING) == {"order_type": 6}


# ===========================================================================
# order-center：服务中订单查询 /order/v1/common/user/unfinished/order
# ===========================================================================
class TestOrderCenterUnfinishedOrderApi:
    """/order/v1/common/user/unfinished/order 支持 order_type 查询。"""

    def test_instant(self):
        """服务中订单查询按 order_type=5 查询即时订单。"""
        assert unfinished_order_params(ORDER_TYPE_INSTANT) == {"order_type": 5}

    def test_booking(self):
        """服务中订单查询按 order_type=6 查询预约订单。"""
        assert unfinished_order_params(ORDER_TYPE_BOOKING) == {"order_type": 6}


# ===========================================================================
# order-center：取消订单次数查询 /order/v1/common/user/cancel/count
# ===========================================================================
class TestOrderCenterCancelCountApi:
    """/order/v1/common/user/cancel/count 支持 order_type 查询。"""

    def test_instant(self):
        """取消次数按 order_type=5 统计即时订单。"""
        assert cancel_count_params(ORDER_TYPE_INSTANT) == {"order_type": 5}

    def test_booking(self):
        """取消次数按 order_type=6 统计预约订单。"""
        assert cancel_count_params(ORDER_TYPE_BOOKING) == {"order_type": 6}

    def test_queries_independent(self):
        """即时与预约取消次数分别查询。"""
        assert cancel_count_params(5) != cancel_count_params(6)


# ===========================================================================
# order-center：预约下单 /order/v1/agent/order/create
# ===========================================================================
class TestOrderCenterAgentCreateApi:
    """/order/v1/agent/order/create

    支持入参 order_levels，一单多车型数据存储，接单回写主订单信息。
    """

    def test_order_levels_entry_fields(self):
        """order_levels 单条条目字段与文档完全一致。"""
        entry = order_level_entry(
            order_level_id=1, order_level_name="經濟",
            estimate_id="6afc04b3af4d480009b9efe301",
            estimate_amount=1720, estimate_distance=6100,
            estimate_duration=1200, coupon_code="nudHu2Dixvv2b1iv",
            coupon_amount=1010, is_agent_coupon=0,
            coupon_remark="", business_type=BUSINESS_TAXI)
        assert set(entry) == {
            "order_level_id", "order_level_name", "estimate_id",
            "estimate_amount", "estimate_distance", "estimate_duration",
            "coupon_code", "coupon_amount", "is_agent_coupon",
            "coupon_remark", "business_type",
        }

    def test_order_levels_entry_values(self):
        """order_levels 单条条目的字段值与文档示例一致。"""
        entry = order_level_entry(
            order_level_id=1, order_level_name="經濟",
            estimate_id="6afc04b3af4d480009b9efe301",
            estimate_amount=1720, estimate_distance=6100,
            estimate_duration=1200, coupon_code="nudHu2Dixvv2b1iv",
            coupon_amount=1010, is_agent_coupon=0,
            coupon_remark="", business_type=BUSINESS_TAXI)
        assert entry["order_level_id"] == 1
        assert entry["order_level_name"] == "經濟"
        assert entry["estimate_id"] == "6afc04b3af4d480009b9efe301"
        assert entry["estimate_amount"] == 1720
        assert entry["estimate_distance"] == 6100
        assert entry["estimate_duration"] == 1200
        assert entry["coupon_code"] == "nudHu2Dixvv2b1iv"
        assert entry["coupon_amount"] == 1010
        assert entry["is_agent_coupon"] == 0
        assert entry["coupon_remark"] == ""
        assert entry["business_type"] == BUSINESS_TAXI

    def test_agent_create_params(self):
        """预约下单入参含 order_type/order_levels/city_id/agent_id/user_id。"""
        levels = [order_level_entry(
            order_level_id=1, order_level_name="經濟",
            estimate_id="6afc04b3af4d480009b9efe301", estimate_amount=1720,
            estimate_distance=6100, estimate_duration=1200,
            business_type=BUSINESS_TAXI)]
        params = agent_order_create_params(
            order_levels=levels, order_type=6, city_id=514,
            agent_id=1, user_id=100)
        assert params["order_type"] == 6
        assert params["order_levels"] == levels
        assert params["city_id"] == 514
        assert params["agent_id"] == 1
        assert params["user_id"] == 100

    def test_agent_create_multi_car_types(self):
        """一单多车型：order_levels 包含多个车型条目。"""
        level1 = order_level_entry(
            order_level_id=1, order_level_name="經濟",
            estimate_id="6afc04b3af4d480009b9efe301", estimate_amount=1720,
            estimate_distance=6100, estimate_duration=1200,
            business_type=BUSINESS_TAXI)
        level2 = order_level_entry(
            order_level_id=2, order_level_name="舒適",
            estimate_id="6afc04b3af4d480009b9efe302", estimate_amount=2200,
            estimate_distance=6100, estimate_duration=1200,
            business_type=BUSINESS_RIDE_HAILING)
        params = agent_order_create_params(
            order_levels=[level1, level2], order_type=6)
        assert len(params["order_levels"]) == 2


# ===========================================================================
# order-center：获取子订单编号 /order/v1/agent/order/main/child/list
# ===========================================================================
class TestOrderCenterChildListApi:
    """/order/v1/agent/order/main/child/list 支持 order_type=6。"""

    def test_child_list_booking(self):
        """子订单查询入参含主订单号与 order_type=6。"""
        params = child_list_params("MAIN_TH26B6PIEWECN", order_type=6)
        assert params["main_order_no"] == "MAIN_TH26B6PIEWECN"
        assert params["order_type"] == 6


# ===========================================================================
# order-center：订单取消 /order/v1/agent/order/cancel
# ===========================================================================
class TestOrderCenterAgentCancelApi:
    """/order/v1/agent/order/cancel 支持 order_type=6。"""

    def test_agent_cancel_booking(self):
        """代理取消入参含 order_no 与 order_type=6。"""
        params = agent_cancel_params("TH26B6PIEWECN", order_type=6)
        assert params["order_no"] == "TH26B6PIEWECN"
        assert params["order_type"] == 6

    def test_agent_cancel_with_reason(self):
        """代理取消入参支持携带 cancel_reason。"""
        params = agent_cancel_params("TH26B6PIEWECN", order_type=6,
                                     cancel_reason="passenger_cancel")
        assert params["cancel_reason"] == "passenger_cancel"


# ===========================================================================
# order-center：司机接单（绑单）/order/v1/agent/driver/main/create
# ===========================================================================
class TestOrderCenterDriverBindApi:
    """/order/v1/agent/driver/main/create 司机接单（绑单）。"""

    def test_bind_params(self):
        """司机接单（绑单）入参含 order_no/driver_id/business_type/order_type。

        当前需求仅明确该接口路径，参数项由现有实现补充，待获取接口原文后校正。
        """
        params = driver_bind_params("TH26B6PIEWECN", driver_id=31,
                                    business_type=BUSINESS_RIDE_HAILING,
                                    order_type=6)
        assert params["order_no"] == "TH26B6PIEWECN"
        assert params["driver_id"] == 31
        assert params["business_type"] == BUSINESS_RIDE_HAILING
        assert params["order_type"] == 6


# ===========================================================================
# order-center：绑单查询 /order/v1/agent/order/main/bind/info
# ===========================================================================
class TestOrderCenterBindInfoApi:
    """/order/v1/agent/order/main/bind/info 绑单查询。"""

    def test_bind_info_params(self):
        """绑单查询入参含 order_no。

        当前需求仅明确该接口路径，参数项由现有实现补充，待获取接口原文后校正。
        """
        params = bind_info_params("TH26B6PIEWECN")
        assert params == {"order_no": "TH26B6PIEWECN"}


# ===========================================================================
# charge：预估详情 /charge/api/v1/billing/estimate/detail
# ===========================================================================
class TestChargeEstimateDetailApi:
    """/charge/api/v1/billing/estimate/detail

    接口文档：http://yapi.sunlightmobility.hk/project/812/interface/api/58181
    """

    def test_request_params(self):
        """charge 预估详情入参携带 estimate_id。"""
        assert charge_estimate_detail_request("6afc04b3af4d480009b9efe301") == {"estimate_id": "6afc04b3af4d480009b9efe301"}

    def test_response_fields(self):
        """charge 预估详情出参含 order_type/order_type_name/fee_details。"""
        fee_map = {"起步價": 23.0, "合計": 74.0}
        payload = charge_estimate_detail_response(5, fee_map)
        assert set(payload) == {"order_type", "order_type_name", "fee_details"}

    def test_response_consistent_with_passenger_api(self):
        """charge 预估详情与 passenger-api 预估详情出参结构关系待确认。

        当前需求只给出 charge 接口路径，未提供 charge 服务独立接口文档。
        charge_estimate_detail_response 与 estimate_detail_payload 使用同一构造函数，
        因此此处仅验证结构字段集，不假定 charge 服务实际出参与 passenger-api 完全相同。
        """
        fee_map = {"起步價": 23.0, "合計": 74.0}
        charge_resp = charge_estimate_detail_response(5, fee_map)
        passenger_resp = estimate_detail_payload(5, fee_map)
        # 两者来自同一构造函数，字段集必然相同；这不证明 charge 服务实际返回相同结构。
        assert set(charge_resp) == set(passenger_resp)


# ===========================================================================
# charge：计价规则 /charge/admin/v1/order/rule
# ===========================================================================
class TestChargeOrderRuleApi:
    """/charge/admin/v1/order/rule

    接口文档：http://yapi.sunlightmobility.hk/project/812/interface/api/58235
    """

    def test_request_by_order_no(self):
        """charge 计价规则入参支持 order_no。"""
        assert charge_order_rule_request(order_no="TH26B6PIEWECN") == {"order_no": "TH26B6PIEWECN"}

    def test_request_by_estimate_id(self):
        """charge 计价规则入参支持 estimate_id。"""
        assert charge_order_rule_request(estimate_id="6afc04b3af4d480009b9efe301") == {"estimate_id": "6afc04b3af4d480009b9efe301"}

    def test_request_requires_one(self):
        """estimate_id 与 order_no 必须至少提供一个。"""
        with pytest.raises(ValueError):
            charge_order_rule_request()

    def test_response_consistent_with_passenger_api(self):
        """charge 计价规则与 passenger-api 计价规则出参结构关系待确认。

        当前需求只给出 charge 接口路径，未提供 charge 服务独立接口文档。
        charge_order_rule_response 与 build_charge_rule_payload 使用同一构造函数，
        因此此处仅验证结构字段集，不假定 charge 服务实际出参与 passenger-api 完全相同。
        """
        rule = _sample_charge_rule()
        charge_resp = charge_order_rule_response(rule)
        passenger_resp = build_charge_rule_payload(rule)
        # 两者来自同一构造函数，字段集必然相同；这不证明 charge 服务实际返回相同结构。
        assert set(charge_resp) == set(passenger_resp)


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------
def _sample_charge_rule():
    """构造示例计价规则。"""
    return ChargeRule(
        car_type="economy",
        car_type_name="經濟型",
        car_type_img="economy.png",
        order_type=5,
        order_type_name="即時用車",
        rules=[
            ChargeRuleDay("workday", "工作日", [
                ChargeRuleItem("起步價", "含5公里 10分鐘", "23"),
                ChargeRuleItem("里程費", "超過5公里", "2.4"),
            ]),
            ChargeRuleDay("restday", "休息日", [
                ChargeRuleItem("起步價", "含5公里 10分鐘", "28"),
            ]),
        ],
    )
