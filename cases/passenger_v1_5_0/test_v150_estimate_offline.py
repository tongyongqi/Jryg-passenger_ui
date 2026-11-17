# 编写时间：2026-11-17
# V1.5.0 询价→创建链路离线契约回归
# 覆盖：use_time→dep_time→order_type 映射、时间范围校验、报价缓存、创建事实、并发限制、免预付
"""V1.5.0 询价→创建链路离线契约回归；不连接设备、不发起真实请求。

覆盖处理规则文档§7.1-§7.2：
1. use_time 空→即时询价(type5)；非空→预约询价(type16)
2. 时间范围校验 30m<=use_time-now<=72h，失败直接返回
3. dep_time 映射：passenger-api RPC 将 use_time 映射到 dep_time
4. order_type 从 dep_time 派生，不重复时间校验
5. 报价缓存：estimate_id 为 key，存 car_type+use_time，TTL
6. order-service 缓存：capp:hk:es_id:<id> 存 order_type+use_time 作为创建事实
7. 创建请求只收 estimate_id，不收 use_time/order_type
8. passenger-api 校验 NsEstimate 缓存存在、car_type 非空
9. use_time 空→cancelFixedUnpayOrder；非空→跳过清理
10. OrderCancelLimit 只对 type5；预约不受限
11. OrderUnfinishedLimit 按类型各占1笔
12. 预约强制 skipDispatch=false、不发 OrderPayTimeout、不等待预付
13. 创建后打表缓存保留、非打表删除
"""

from datetime import datetime, timedelta

import pytest

from passenger_android_core.v150.contract import (
    BOOKING_MIN_ALLOWED,
    BOOKING_MAX_MINUTES,
    BOOKING_TIMEOUT_MINUTES,
    ORDER_TYPE_BOOKING_REALTIME,
    ORDER_TYPE_REALTIME_INSTANT,
    PASSENGER_BOOKING,
    PASSENGER_INSTANT,
    # 询价链路
    normalize_use_time,
    estimate_time_range_check,
    dep_time_from_use_time,
    order_type_from_dep_time,
    estimate_order_type,
    estimate_request,
    estimate_cache_value,
    # 报价缓存
    estimate_cache_ttl,
    order_service_cache_key,
    order_service_cache_value,
    read_order_service_cache,
    # 创建链路
    create_request,
    passenger_api_create_check,
    should_cancel_fixed_unpaid,
    order_service_transform,
    order_cancel_limit_applies,
    order_unfinished_limit_check,
    booking_dispatch_policy,
    estimate_cache_after_create,
    booking_create_policy,
    can_create,
    # 常量
    QuoteIdentity,
    quote_response_applies,
)


NOW = datetime(2026, 1, 15, 12, 0, 0)


# ==================== §7.1.1 询价链路 ====================

class TestEstimateTimeNormalization:
    """use_time 规范化为 YYYY-MM-DD HH:mm:ss。"""

    def test_empty_use_time_returns_empty(self):
        """空 use_time 规范化为空字符串（即时询价）。"""
        assert normalize_use_time("", NOW) == ""
        assert normalize_use_time(None, NOW) == ""

    def test_datetime_object_normalized(self):
        """datetime 对象规范化为字符串。"""
        result = normalize_use_time(NOW + timedelta(minutes=35), NOW)
        assert result == "2026-01-15 12:35:00"

    def test_valid_string_normalized(self):
        """合法字符串原样格式化返回。"""
        result = normalize_use_time("2026-01-15 12:35:00", NOW)
        assert result == "2026-01-15 12:35:00"

    def test_invalid_format_returns_none(self):
        """非法格式返回 None。"""
        assert normalize_use_time("invalid", NOW) is None
        assert normalize_use_time("2026/01/15 12:35", NOW) is None


class TestEstimateTimeRangeCheck:
    """30m <= use_time-now <= 72h 时间范围校验。"""

    def test_empty_use_time_passes(self):
        """即时询价（空 use_time）不校验时间范围。"""
        passed, reason = estimate_time_range_check("", NOW)
        assert passed is True

    def test_exact_29_minutes_passes(self):
        """29分钟（含）刚好通过。"""
        use_time = (NOW + timedelta(minutes=BOOKING_MIN_ALLOWED)).strftime("%Y-%m-%d %H:%M:%S")
        passed, reason = estimate_time_range_check(use_time, NOW)
        assert passed is True

    def test_below_29_minutes_rejected(self):
        """不足29分钟被拒绝。"""
        use_time = (NOW + timedelta(minutes=28)).strftime("%Y-%m-%d %H:%M:%S")
        passed, reason = estimate_time_range_check(use_time, NOW)
        assert passed is False
        assert "不足" in reason

    def test_exactly_72_hours_passes(self):
        """72小时（含）刚好通过。"""
        use_time = (NOW + timedelta(minutes=BOOKING_MAX_MINUTES)).strftime("%Y-%m-%d %H:%M:%S")
        passed, reason = estimate_time_range_check(use_time, NOW)
        assert passed is True

    def test_exceeds_72_hours_rejected(self):
        """超过72小时被拒绝。"""
        use_time = (NOW + timedelta(minutes=BOOKING_MAX_MINUTES + 1)).strftime("%Y-%m-%d %H:%M:%S")
        passed, reason = estimate_time_range_check(use_time, NOW)
        assert passed is False
        assert "72" in reason

    def test_past_time_rejected(self):
        """过去时间被拒绝。"""
        use_time = (NOW - timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
        passed, reason = estimate_time_range_check(use_time, NOW)
        assert passed is False


class TestDepTimeMapping:
    """passenger-api RPC 将 use_time 映射到内部 dep_time。"""

    def test_empty_use_time_maps_to_empty_dep_time(self):
        """空 use_time 映射为空 dep_time（即时）。"""
        assert dep_time_from_use_time("") == ""

    def test_non_empty_use_time_maps_to_dep_time(self):
        """非空 use_time 原样映射为 dep_time（预约）。"""
        assert dep_time_from_use_time("2026-01-15 12:35:00") == "2026-01-15 12:35:00"

    def test_dep_time_consistent_with_use_time(self):
        """dep_time 与 use_time 值一致（不修改格式）。"""
        for val in ("", "2026-01-15 12:35:00"):
            assert dep_time_from_use_time(val) == val


class TestOrderTypeFromDepTime:
    """order-service 根据 dep_time 派生 order_type，不重复时间校验。"""

    def test_empty_dep_time_derives_instant(self):
        """空 dep_time→即时 type5。"""
        assert order_type_from_dep_time("") == ORDER_TYPE_REALTIME_INSTANT

    def test_non_empty_dep_time_derives_booking(self):
        """非空 dep_time→预约 type16。"""
        assert order_type_from_dep_time("2026-01-15 12:35:00") == ORDER_TYPE_BOOKING_REALTIME


class TestEstimateRequestPayload:
    """询价请求体：预约附加 use_time，即时不带。"""

    def test_instant_request_has_no_use_time(self):
        """即时询价请求不含 use_time。"""
        payload = estimate_request("北角地铁站", "香港大学")
        assert "use_time" not in payload
        assert payload["start"] == "北角地铁站"

    def test_booking_request_has_use_time(self):
        """预约询价请求含 use_time。"""
        payload = estimate_request("北角地铁站", "香港大学", "2026-01-15 12:35:00")
        assert payload["use_time"] == "2026-01-15 12:35:00"


# ==================== §7.1.2 报价缓存与有效期 ====================

class TestEstimateCache:
    """estimate_id 为 key 的缓存：car_type+use_time，TTL。"""

    def test_cache_value_contains_car_type_and_use_time(self):
        """缓存 value 包含 car_type 和 use_time。"""
        val = estimate_cache_value("meter", "2026-01-15 12:35:00")
        assert val == {"car_type": "meter", "use_time": "2026-01-15 12:35:00"}

    def test_instant_cache_has_empty_use_time(self):
        """即时询价缓存 use_time 为空字符串。"""
        val = estimate_cache_value("charter")
        assert val["use_time"] == ""

    def test_ttl_positive(self):
        """TTL 为 timeout*秒，必须为正。"""
        assert estimate_cache_ttl(300) == 300

    def test_ttl_zero_rejected(self):
        """TTL 为 0 报错。"""
        with pytest.raises(ValueError, match="timeout_must_be_positive"):
            estimate_cache_ttl(0)

    def test_ttl_negative_rejected(self):
        """TTL 为负报错。"""
        with pytest.raises(ValueError, match="timeout_must_be_positive"):
            estimate_cache_ttl(-1)


class TestOrderServiceCache:
    """order-service 侧缓存：capp:hk:es_id:<id> 存 order_type/use_time。"""

    def test_cache_key_format(self):
        """缓存 key 格式为 capp:hk:es_id:<estimate_id>。"""
        assert order_service_cache_key("abc123") == "capp:hk:es_id:abc123"

    def test_cache_value_contains_order_type_and_use_time(self):
        """缓存 value 包含 order_type 和 use_time。"""
        val = order_service_cache_value(16, "2026-01-15 12:35:00")
        assert val == {"order_type": 16, "use_time": "2026-01-15 12:35:00"}

    def test_cache_value_instant_has_empty_use_time(self):
        """即时缓存 use_time 为空。"""
        val = order_service_cache_value(5, "")
        assert val["use_time"] == ""

    def test_read_valid_cache(self):
        """从缓存读取 order_type/use_time。"""
        parsed = read_order_service_cache({"order_type": 16, "use_time": "2026-01-15 12:35:00"})
        assert parsed["order_type"] == 16
        assert parsed["use_time"] == "2026-01-15 12:35:00"

    def test_read_none_cache_returns_none(self):
        """缓存不存在返回 None。"""
        assert read_order_service_cache(None) is None

    def test_read_invalid_json_returns_none(self):
        """非法 JSON 返回 None。"""
        assert read_order_service_cache("not_a_dict") is None


# ==================== §7.2 创建链路 ====================

class TestCreateRequestPayload:
    """创建请求只收 estimate_id，不收 use_time/order_type。"""

    def test_request_contains_only_estimate_id(self):
        """请求体只有 estimate_list[0].estimate_id。"""
        req = create_request(["es_001"])
        assert req == {"estimate_list": [{"estimate_id": "es_001"}]}
        assert "use_time" not in req
        assert "order_type" not in req

    def test_request_rejects_multiple_ids(self):
        """外部创建当前只允许 1 个 estimate_list 元素。"""
        with pytest.raises(ValueError, match="estimate_list_must_contain_one"):
            create_request(["es_001", "es_002"])

    def test_request_rejects_empty_list(self):
        """空列表报错。"""
        with pytest.raises(ValueError, match="estimate_list_must_contain_one"):
            create_request([])


class TestPassengerApiCreateCheck:
    """passenger-api 校验 NsEstimate 缓存存在、car_type 非空。"""

    def test_valid_cache_passes(self):
        """缓存存在且 car_type 非空时通过。"""
        cache = {"car_type": "meter", "use_time": "2026-01-15 12:35:00"}
        passed, car_type, use_time, reason = passenger_api_create_check(cache, "meter")
        assert passed is True
        assert car_type == "meter"
        assert use_time == "2026-01-15 12:35:00"

    def test_missing_cache_rejected(self):
        """缓存不存在拒绝创建。"""
        passed, _, _, reason = passenger_api_create_check(None, "meter")
        assert passed is False
        assert "not_found" in reason

    def test_invalid_json_rejected(self):
        """JSON 非法拒绝创建。"""
        passed, _, _, reason = passenger_api_create_check("not_a_dict", "meter")
        assert passed is False
        assert "invalid" in reason

    def test_empty_car_type_rejected(self):
        """car_type 为空拒绝创建。"""
        passed, _, _, reason = passenger_api_create_check({"car_type": ""}, None)
        assert passed is False
        assert "empty" in reason

    def test_car_type_mismatch_rejected(self):
        """car_type 不匹配拒绝创建。"""
        cache = {"car_type": "charter", "use_time": ""}
        passed, _, _, reason = passenger_api_create_check(cache, "meter")
        assert passed is False
        assert "mismatch" in reason


class TestCancelFixedUnpaid:
    """use_time 空→执行 cancelFixedUnpayOrder；非空→跳过。"""

    def test_instant_executes_cleanup(self):
        """即时询价 use_time 为空，执行清理。"""
        assert should_cancel_fixed_unpaid("") is True
        assert should_cancel_fixed_unpaid(None) is True

    def test_booking_skips_cleanup(self):
        """预约询价 use_time 非空，跳过清理。"""
        assert should_cancel_fixed_unpaid("2026-01-15 12:35:00") is False


class TestOrderServiceTransform:
    """order-service transform：读缓存→校验→写 OrderCreateParam。"""

    def test_valid_cache_writes_order_type_and_use_time(self):
        """缓存存在且有效时写入 order_type/use_time。"""
        def lookup(eid):
            return {"order_type": 16, "use_time": "2026-01-15 12:35:00", "user_id": 100}
        order_type, use_time, errors = order_service_transform(["es_001"], lookup, 100)
        assert order_type == 16
        assert use_time == "2026-01-15 12:35:00"
        assert errors == []

    def test_missing_cache_returns_error(self):
        """缓存不存在返回错误。"""
        order_type, use_time, errors = order_service_transform(["es_001"], lambda _: None, 100)
        assert order_type is None
        assert any("not_found" in e for e in errors)

    def test_user_mismatch_returns_error(self):
        """用户不一致返回错误。"""
        def lookup(eid):
            return {"order_type": 16, "use_time": "", "user_id": 200}
        order_type, use_time, errors = order_service_transform(["es_001"], lookup, 100)
        assert order_type is None
        assert any("mismatch" in e for e in errors)

    def test_multiple_ids_rejected(self):
        """多个 estimate_id 报错。"""
        order_type, use_time, errors = order_service_transform(["es_001", "es_002"], lambda _: {}, 100)
        assert order_type is None
        assert any("must_contain_one" in e for e in errors)

    def test_empty_ids_rejected(self):
        """空列表报错。"""
        order_type, use_time, errors = order_service_transform([], lambda _: {}, 100)
        assert order_type is None
        assert any("no_estimate" in e for e in errors)


class TestOrderCancelLimit:
    """OrderCancelLimit 只对即时(type5)执行。"""

    def test_instant_has_cancel_limit(self):
        """即时单受取消次数限制。"""
        assert order_cancel_limit_applies(ORDER_TYPE_REALTIME_INSTANT) is True

    def test_booking_no_cancel_limit(self):
        """预约单不受即时取消次数限制。"""
        assert order_cancel_limit_applies(ORDER_TYPE_BOOKING_REALTIME) is False


class TestOrderUnfinishedLimit:
    """OrderUnfinishedLimit 按类型各占1笔。"""

    def test_instant_occupies_instant_slot(self):
        """即时单只占即时额度。"""
        assert order_unfinished_limit_check(5, 0, 1) is True
        assert order_unfinished_limit_check(5, 1, 1) is False

    def test_booking_occupies_booking_slot(self):
        """预约单只占预约额度。"""
        assert order_unfinished_limit_check(16, 1, 0) is True
        assert order_unfinished_limit_check(16, 1, 1) is False

    def test_both_types_can_coexist(self):
        """两类订单可各存在1笔：即时已有1笔时仍可创建预约，反之亦然。"""
        # 即时已有1笔(active_instant=1)，预约0笔 → 可创建预约
        assert order_unfinished_limit_check(16, 1, 0) is True
        # 预约已有1笔(active_booking=1)，即时0笔 → 可创建即时
        assert order_unfinished_limit_check(5, 0, 1) is True
        # 两类各已有1笔 → 都不能创建
        assert order_unfinished_limit_check(5, 1, 1) is False
        assert order_unfinished_limit_check(16, 1, 1) is False

    def test_unknown_type_rejected(self):
        """未知类型报错。"""
        with pytest.raises(ValueError):
            order_unfinished_limit_check(99, 0, 0)


class TestBookingDispatchPolicy:
    """预约创建强制 skipDispatch=false、不发 OrderPayTimeout、不等待预付。"""

    def test_booking_forces_dispatch(self):
        """预约强制 skipDispatch=false、立即派单。"""
        policy = booking_dispatch_policy(ORDER_TYPE_BOOKING_REALTIME)
        assert policy["skip_dispatch"] is False
        assert policy["send_pay_timeout"] is False
        assert policy["wait_prepayment"] is False
        assert policy["dispatch_immediately"] is True

    def test_instant_uses_default_logic(self):
        """即时订单按当前逻辑（None=不强制覆盖）。"""
        policy = booking_dispatch_policy(ORDER_TYPE_REALTIME_INSTANT)
        assert policy["skip_dispatch"] is None
        assert policy["dispatch_immediately"] is False


class TestEstimateCacheAfterCreate:
    """创建后打表缓存保留、非打表删除。"""

    def test_meter_cache_kept(self):
        """打表缓存保留。"""
        result = estimate_cache_after_create("meter")
        assert result["action"] == "keep"

    def test_charter_cache_deleted(self):
        """包车缓存删除。"""
        result = estimate_cache_after_create("charter")
        assert result["action"] == "delete"


class TestBookingCreatePolicy:
    """booking_create_policy 预约/即时策略。"""

    def test_booking_meter_no_prepayment(self):
        """预约打表无预付。"""
        policy = booking_create_policy("meter", "2026-01-15 12:35:00")
        assert policy["prepayment"] is False
        assert policy["dispatch_immediately"] is True
        assert policy["skip_fixed_unpaid_cleanup"] is True

    def test_instant_charter_has_prepayment(self):
        """即时包车有预付。"""
        policy = booking_create_policy("charter", "")
        assert policy["prepayment"] is True
        assert policy["dispatch_immediately"] is False

    def test_unknown_car_type_rejected(self):
        """未知车型报错。"""
        with pytest.raises(ValueError, match="unknown_car_type"):
            booking_create_policy("unknown", "2026-01-15 12:35:00")


class TestCanCreate:
    """can_create：对应类型无活跃订单时允许创建。"""

    def test_instant_allowed_when_none_active(self):
        assert can_create(0, 0, "instant") is True

    def test_instant_blocked_when_active(self):
        assert can_create(1, 0, "instant") is False

    def test_booking_allowed_when_none_active(self):
        assert can_create(0, 0, "booking") is True

    def test_booking_blocked_when_active(self):
        assert can_create(0, 1, "booking") is False

    def test_unknown_type_rejected(self):
        with pytest.raises(ValueError):
            can_create(0, 0, "unknown")


class TestQuoteIdentity:
    """报价请求标识：地址/时间/代次/业务类型变化淘汰旧响应。"""

    def test_same_identity_accepts_response(self):
        """地址/时间/代次一致时接受报价响应。"""
        current = QuoteIdentity("A", "B", "12:35", 1, True)
        assert quote_response_applies(current, current) is True

    def test_different_identity_rejects_response(self):
        """任一字段变化拒绝旧报价。"""
        base = QuoteIdentity("A", "B", "12:35", 1, True)
        changed = QuoteIdentity("A", "C", "12:35", 1, True)  # 终点变了
        assert quote_response_applies(base, changed) is False
