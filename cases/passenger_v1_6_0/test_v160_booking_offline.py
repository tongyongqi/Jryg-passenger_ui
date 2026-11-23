"""香港乘客端 V1.6.0 预约业务规则契约离线测试。

编写时间：2026-11-19
本期功能：预约业务完整链路（时间规则、并行限制、取消限制、下单分流）
需求映射：
- 需求 5：出发时间入口，出发时间变化后刷新报价，未变化不刷新
- 需求 6：预约时间 30min~72h，一笔进行中预约，取消次数独立且每日 5 次
- 需求 7：预约一口价预付 / 打表后付，预约全部车型不支持优惠券
- 需求 8：呼叫超时按出发时间前 10 分钟
- 技术方案 7.2：CappCreateBookingOrderLock 锁内校验顺序

运行：pytest cases/passenger_v1_6_0/test_v160_booking_offline.py -v
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
    BOOKING_DISPATCH_TIMEOUT_MINUTES,
    BOOKING_MAX_MINUTES,
    BOOKING_MIN_MINUTES,
    BOOKING_REASON_ACTIVE_EXISTS,
    BOOKING_REASON_CANCEL_LIMIT,
    BOOKING_REASON_COUPON,
    BOOKING_REASON_PAYMENT_MODE,
    BOOKING_REASON_TIME_INVALID,
    DepartureTimeState,
    BookingCreateContext,
    ServicePreference,
    booking_lock_key,
    booking_time_bounds,
    cancel_limit_applies,
    cancel_order_allowed,
    cancel_page_notice,
    check_booking_create,
    coupon_assess_params,
    coupon_display_scope,
    coupon_supported,
    derive_order_type,
    dispatch_timeout_at,
    driver_location_exposed,
    estimate_coupon_list_payload,
    is_booking_time,
    merge_service_preference,
    reject_coupon_for_booking,
    service_preference_to_params,
    validate_booking_time,
    validate_service_preference,
)
from passenger_android_core.v160.contract import CarTypeCatalog  # noqa: E402


NOW = datetime(2026, 11, 13, 12, 0, 0)


# ===========================================================================
# Section 1：预约时间规则（需求 6）
# ===========================================================================
class TestBookingTimeRule:
    """预约时间范围为当前时间后 30 分钟至 72 小时。"""

    def test_exactly_30_minutes_allowed(self):
        """预约时间下界：当前时间后 30 分钟允许预约。"""
        use_time = NOW + timedelta(minutes=BOOKING_MIN_MINUTES)
        ok, message = validate_booking_time(NOW, use_time)
        assert ok is True
        assert message == ""

    def test_29_minutes_rejected(self):
        """不足 30 分钟的预约时间被拒绝并提示明确文案。"""
        use_time = NOW + timedelta(minutes=29)
        ok, message = validate_booking_time(NOW, use_time)
        assert ok is False
        assert "預約時間不足30分鐘" in message

    def test_exactly_72_hours_allowed(self):
        """预约时间上界：当前时间后 72 小时允许预约。"""
        use_time = NOW + timedelta(hours=72)
        ok, _ = validate_booking_time(NOW, use_time)
        assert ok is True

    def test_over_72_hours_rejected(self):
        """超过 72 小时的预约时间被拒绝。"""
        use_time = NOW + timedelta(hours=72, minutes=1)
        ok, message = validate_booking_time(NOW, use_time)
        assert ok is False
        assert "72" in message

    def test_time_bounds(self):
        """可预约时间范围为 now+30min 至 now+72h。"""
        earliest, latest = booking_time_bounds(NOW)
        assert earliest == NOW + timedelta(minutes=BOOKING_MIN_MINUTES)
        assert latest == NOW + timedelta(minutes=BOOKING_MAX_MINUTES)

    def test_derive_order_type_instant(self):
        """5 分钟内出发派生为即时订单 order_type=5。"""
        assert derive_order_type(NOW + timedelta(minutes=5), NOW) == 5

    def test_derive_order_type_booking(self):
        """60 分钟后出发派生为预约订单 order_type=6。"""
        assert derive_order_type(NOW + timedelta(minutes=60), NOW) == 6

    def test_is_booking_time_helper(self):
        """预约时间判定辅助函数：超过下界为预约，否则为即时。"""
        assert is_booking_time(NOW + timedelta(minutes=60), NOW) is True
        assert is_booking_time(NOW + timedelta(minutes=10), NOW) is False


# ===========================================================================
# Section 2：出发时间入口与报价刷新（需求 5）
# ===========================================================================
class TestDepartureTimeEntry:
    """出发时间实际变化后刷新报价，选项未变化不刷新。"""

    def test_select_now_switches_to_instant(self):
        """选择「現在出發」切回即时业务 order_type=5。"""
        state = DepartureTimeState().select_now()
        assert state.now_selected is True
        assert state.order_type == 5

    def test_select_time_switches_to_booking(self):
        """选择预约时间切到预约业务 order_type=6。"""
        state = DepartureTimeState().select_time(NOW + timedelta(hours=1))
        assert state.now_selected is False
        assert state.order_type == 6

    def test_requote_needed_when_time_changed(self):
        """出发时间实际变化后需刷新报价。"""
        state = DepartureTimeState().select_time(NOW + timedelta(hours=1))
        assert state.needs_requote() is True

    def test_no_requote_when_time_unchanged(self):
        """出发时间未变化时不刷新报价。"""
        target = NOW + timedelta(hours=1)
        state = DepartureTimeState().select_time(target).mark_requoted(target)
        assert state.needs_requote() is False

    def test_requote_needed_after_switch_back_to_now(self):
        """从预约时间切回「現在出發」后需重新刷新报价。"""
        target = NOW + timedelta(hours=1)
        state = (DepartureTimeState().select_time(target)
                 .mark_requoted(target).select_now())
        assert state.needs_requote() is True

    def test_no_requote_when_now_unchanged(self):
        """保持「現在出發」不刷新报价。"""
        state = DepartureTimeState().select_now().mark_requoted()
        assert state.needs_requote() is False

    def test_requote_keeps_preference_state(self):
        """R5-06：切换出发时间保留 children/pet 服务偏好。

        出发时间状态切换只影响时间，服务偏好由 merge_service_preference 独立保留。
        """
        original = ServicePreference(children=True, pet=False)
        state = DepartureTimeState().select_time(NOW + timedelta(hours=1))
        assert state.now_selected is False
        # 偏好不随时间切换丢失：传入 None 表示无新偏好，保留原值
        preserved = merge_service_preference(original, None)
        assert preserved.children is True
        assert preserved.pet is False


# ===========================================================================
# Section 3：服务偏好（需求 5 / 7）
# ===========================================================================
class TestServicePreference:
    """切换预约时间后保留已选儿童、宠物服务偏好。"""

    def test_merge_keeps_children(self):
        """合并新偏好时保留原有 children 勾选。"""
        merged = merge_service_preference(ServicePreference(children=True),
                                          pet=True)
        assert merged.children is True
        assert merged.pet is True

    def test_merge_keeps_pet(self):
        """合并新偏好时保留原有 pet 勾选。"""
        merged = merge_service_preference(ServicePreference(pet=True),
                                          children=True)
        assert merged.pet is True

    def test_merge_none_keeps_original(self):
        """无新偏好时完整保留原偏好。"""
        merged = merge_service_preference(ServicePreference(children=True, pet=True))
        assert merged.children is True
        assert merged.pet is True

    def test_merge_overrides_explicit(self):
        """显式传入的新偏好覆盖原值。"""
        merged = merge_service_preference(ServicePreference(children=True),
                                          children=False)
        assert merged.children is False

    def test_empty_preference(self):
        """空偏好标记为 is_empty。"""
        assert ServicePreference().is_empty is True

    def test_validate_ok(self):
        """合法服务偏好校验通过。"""
        ok, message = validate_service_preference(ServicePreference(children=True))
        assert ok is True
        assert message == ""

    def test_to_params_order(self):
        """服务偏好入参顺序为 children=1、pet=2。"""
        params = service_preference_to_params(
            ServicePreference(children=True, pet=True))
        assert params == [1, 2]

    def test_to_params_pet_only(self):
        """仅勾选 pet 时入参为 [2]。"""
        assert service_preference_to_params(ServicePreference(pet=True)) == [2]

    def test_to_params_empty(self):
        """未勾选任何偏好时入参为空数组。"""
        assert service_preference_to_params(ServicePreference()) == []


# ===========================================================================
# Section 4：优惠券口径（需求 7）
# ===========================================================================
class TestCouponScope:
    """即时网约车与即时出租车一致；预约全部车型不支持优惠券。"""

    @pytest.mark.parametrize("code", ["chartered_taxi", "taxi", "economy",
                                      "preferred", "comfort", "business", "luxury"])
    def test_instant_supports_coupon(self, code):
        """即时业务全部 7 个车型均支持优惠券。"""
        entry = CarTypeCatalog().require_by_code(code)
        assert coupon_supported(entry, is_booking=False) is True

    @pytest.mark.parametrize("code", ["chartered_taxi", "taxi", "economy",
                                      "preferred", "comfort", "business", "luxury"])
    def test_booking_supports_no_coupon(self, code):
        """预约业务全部 7 个车型均不支持优惠券。"""
        entry = CarTypeCatalog().require_by_code(code)
        assert coupon_supported(entry, is_booking=True) is False

    def test_assess_params_include_order_type(self):
        """优惠券试算入参携带 order_type=5（即时）。"""
        assert coupon_assess_params(5) == {"order_type": 5}

    def test_coupon_list_payload_empty_for_booking(self):
        """预约业务不调用优惠券匹配，券列表返回空。"""
        payload = estimate_coupon_list_payload(6)
        assert payload["order_type"] == 6
        assert payload["coupons"] == []

    def test_reject_coupon_for_booking_raises(self):
        """预约订单携带 coupon_code 时直接拒绝。"""
        with pytest.raises(ValueError, match="不支持使用優惠券"):
            reject_coupon_for_booking(6, "nudHu2Dixvv2b1iv")

    def test_reject_coupon_booking_without_code_ok(self):
        """预约订单未携带 coupon_code 时不报错。"""
        assert reject_coupon_for_booking(6, None) is None

    def test_reject_coupon_instant_with_code_ok(self):
        """即时订单携带 coupon_code 时允许通过。"""
        assert reject_coupon_for_booking(5, "nudHu2Dixvv2b1iv") is None

    def test_display_scope_booking_none(self):
        """预约业务优惠券展示范围为 none（不展示）。"""
        assert coupon_display_scope(6, logged_in=True) == "none"

    def test_display_scope_instant_guest(self):
        """即时业务未登录时按 instant_taxi_guest 口径展示。"""
        assert coupon_display_scope(5, logged_in=False) == "instant_taxi_guest"

    def test_display_scope_instant_logged_in(self):
        """即时业务已登录时按 instant_taxi 口径展示（网约车与出租车一致）。"""
        assert coupon_display_scope(5, logged_in=True) == "instant_taxi"


# ===========================================================================
# Section 5：并行订单与取消限制（需求 6）
# ===========================================================================
class TestBookingCreateCheck:
    """锁内依次复核预约时间和进行中预约，再校验每日取消次数。"""

    def _context(self, **kwargs):
        """构造下单校验上下文基线，各用例按需覆盖个别字段。"""
        defaults = dict(
            user_id=10001,
            now=NOW,
            use_time=NOW + timedelta(hours=1),
            active_booking_count=0,
            active_instant_count=0,
            today_cancel_count=0,
            cancel_limit_enabled=True,
        )
        defaults.update(kwargs)
        return BookingCreateContext(**defaults)

    def test_valid_context_passes(self):
        """全部条件合法时下单校验通过。"""
        result = check_booking_create(self._context())
        assert result.ok is True
        assert bool(result) is True

    def test_invalid_time_rejected(self):
        """预约时间非法时下单被拒绝并返回时间非法原因。"""
        result = check_booking_create(
            self._context(use_time=NOW + timedelta(minutes=10)))
        assert result.ok is False
        assert result.reason == BOOKING_REASON_TIME_INVALID

    def test_active_booking_blocks_new(self):
        """同一乘客仅可同时存在一笔进行中预约订单。"""
        result = check_booking_create(self._context(active_booking_count=1))
        assert result.ok is False
        assert result.reason == BOOKING_REASON_ACTIVE_EXISTS

    def test_active_instant_does_not_block_booking(self):
        """即时与预约互不冲突。"""
        result = check_booking_create(self._context(active_instant_count=1))
        assert result.ok is True

    def test_daily_cancel_limit_blocks_new(self):
        """当日累计取消达 5 次后限制新建预约。"""
        result = check_booking_create(
            self._context(today_cancel_count=BOOKING_DAILY_CANCEL_LIMIT))
        assert result.ok is False
        assert result.reason == BOOKING_REASON_CANCEL_LIMIT

    def test_cancel_limit_4_times_still_allowed(self):
        """当日取消 4 次（未达上限 5 次）仍允许新建预约。"""
        result = check_booking_create(self._context(today_cancel_count=4))
        assert result.ok is True

    def test_cancel_limit_disabled_skips_stat(self):
        """开关为 false 时完全跳过该统计及限制。"""
        result = check_booking_create(self._context(
            today_cancel_count=99, cancel_limit_enabled=False))
        assert result.ok is True

    def test_coupon_rejected_before_order_center(self):
        """预约携带优惠券在下单校验阶段即被拒绝，不进入 order-center。"""
        result = check_booking_create(self._context(), coupon_code="abc")
        assert result.ok is False
        assert result.reason == BOOKING_REASON_COUPON

    def test_fixed_price_offline_payment_rejected(self):
        """一口价预约不接受非线上支付请求。"""
        result = check_booking_create(
            self._context(), requested_online=False, car_type_code="economy")
        assert result.ok is False
        assert result.reason == BOOKING_REASON_PAYMENT_MODE

    def test_metered_booking_offline_payment_allowed(self):
        """打表预约允许非线上支付（走线下后付）。"""
        result = check_booking_create(
            self._context(), requested_online=False, car_type_code="taxi")
        assert result.ok is True

    def test_time_checked_before_active_booking(self):
        """锁内顺序：先复核预约时间。"""
        result = check_booking_create(self._context(
            use_time=NOW + timedelta(minutes=5), active_booking_count=1))
        assert result.reason == BOOKING_REASON_TIME_INVALID

    def test_active_booking_checked_before_cancel_limit(self):
        """锁内顺序：再校验进行中预约，最后才是取消次数。"""
        result = check_booking_create(self._context(
            active_booking_count=1, today_cancel_count=99))
        assert result.reason == BOOKING_REASON_ACTIVE_EXISTS

    def test_lock_key_uses_user_id(self):
        """下单锁键为 capp_booking_order_lock_{下单用户ID}。"""
        assert booking_lock_key(10001) == "capp_booking_order_lock_10001"

    def test_cancel_limit_applies_switch(self):
        """取消次数统计开关直接决定限制是否生效。"""
        assert cancel_limit_applies(True) is True
        assert cancel_limit_applies(False) is False

    def test_cancel_allowed_even_at_limit(self):
        """预约达到每日上限不阻止取消。"""
        ok, message = cancel_order_allowed(True, BOOKING_DAILY_CANCEL_LIMIT)
        assert ok is True
        assert message == ""

    def test_cancel_allowed_when_switch_disabled(self):
        """取消次数开关关闭时取消始终允许。"""
        ok, _ = cancel_order_allowed(False, 99)
        assert ok is True


# ===========================================================================
# Section 6：呼叫与取消提示（需求 8）
# ===========================================================================
class TestDispatchAndCancelNotice:
    """呼叫超时按出发时间前 10 分钟；预付取消页增加退款提示。"""

    def test_dispatch_timeout_at(self):
        """呼叫超时时间为出发时间前 10 分钟。"""
        use_time = NOW + timedelta(hours=2)
        assert dispatch_timeout_at(use_time) == use_time - timedelta(
            minutes=BOOKING_DISPATCH_TIMEOUT_MINUTES)

    def test_paid_advance_cancel_has_notice(self):
        """预付订单取消页展示退款提示文案。"""
        notice = cancel_page_notice(is_paid_advance=True)
        assert "已支付款項將按原有途徑退還至您的帳戶" in notice

    def test_not_paid_cancel_no_notice(self):
        """非预付订单取消页不展示退款提示。"""
        assert cancel_page_notice(is_paid_advance=False) == ""


# ===========================================================================
# Section 7：司机位置暴露（需求 9）
# ===========================================================================
class TestDriverLocationExposure:
    """出发时间前 20 分钟内才下发司机位置。"""

    def test_more_than_20_minutes_not_exposed(self):
        """距出发时间超过 20 分钟不下发司机位置。"""
        use_time = NOW + timedelta(minutes=21)
        assert driver_location_exposed(use_time, NOW) is False

    def test_exactly_20_minutes_exposed(self):
        """距出发时间恰好 20 分钟时下发司机位置（边界含）。"""
        use_time = NOW + timedelta(minutes=20)
        assert driver_location_exposed(use_time, NOW) is True

    def test_less_than_20_minutes_exposed(self):
        """距出发时间不足 20 分钟时下发司机位置。"""
        use_time = NOW + timedelta(minutes=5)
        assert driver_location_exposed(use_time, NOW) is True
