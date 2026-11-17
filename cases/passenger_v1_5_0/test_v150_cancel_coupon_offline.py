# 编写时间：2026-11-17
# V1.5.0 取消链路+状态机兼容+优惠券降级离线契约回归
# 覆盖：主动取消/超时取消/幂等/passenger-service Handler兼容/coupon降级
"""V1.5.0 取消链路、passenger-service状态机兼容、优惠券降级离线契约回归。

覆盖处理规则文档§7.3-§7.3.3、§7.7：
- §7.3 主动取消：POST /passenger/order/cancel → OrderCancelByCappHandler
- §7.3.2 20分钟超时取消：schedulingTimeout → order_cancel_common
- §7.3.2 幂等：已取消/订单不存在/重复回调
- §7.3.3 passenger-service 4个Handler兼容 BOOKING_ORDER_TYPE
- §7.7 优惠券降级：查询失败不影响报价
"""

from datetime import timedelta

import pytest

from passenger_android_core.v150.contract import (
    BOOKING_TIMEOUT_MINUTES,
    ORDER_TYPE_BOOKING_REALTIME,
    ORDER_TYPE_REALTIME_INSTANT,
    timeout_cancel_due,
    cancellation_cleanup,
    cancellation_view,
    # 取消链路
    cancel_entry_source,
    cancel_handler,
    cancel_idempotent,
    # 状态机兼容
    order_status_consume_accepts,
    order_status_push_msg,
    order_status_coupon_consume,
    order_status_send_sms,
    # 优惠券降级
    coupon_service_type,
    coupon_degradation,
    COUPON_SERVICE_TYPE_INSTANT,
)


NOW = __import__("datetime").datetime(2026, 1, 15, 12, 0, 0)


# ==================== §7.3.1 乘客主动取消 ====================

class TestCancelEntrySource:
    """预约取消入口：乘客主动→user_cancel；超时→dispatch_timeout。"""

    def test_user_initiated_returns_user_cancel(self):
        assert cancel_entry_source(user_initiated=True) == "user_cancel"

    def test_timeout_returns_dispatch_timeout(self):
        assert cancel_entry_source(user_initiated=False) == "dispatch_timeout"


class TestCancelHandlerUserCancel:
    """OrderCancelByCappHandler 兼容 BOOKING_ORDER_TYPE。"""

    def test_booking_waiting_driver_allowed(self):
        """预约待接单状态允许乘客主动取消。"""
        allowed, handler, reason = cancel_handler(
            "user_cancel", ORDER_TYPE_BOOKING_REALTIME, "waiting_driver")
        assert allowed is True
        assert handler == "OrderCancelByCappHandler"
        assert reason == ""

    def test_instant_waiting_driver_allowed(self):
        """即时待接单状态允许取消。"""
        allowed, handler, reason = cancel_handler(
            "user_cancel", ORDER_TYPE_REALTIME_INSTANT, "waiting_driver")
        assert allowed is True

    def test_already_cancelled_idempotent(self):
        """已取消订单幂等成功返回。"""
        allowed, handler, reason = cancel_handler(
            "user_cancel", ORDER_TYPE_BOOKING_REALTIME, "cancelled")
        assert allowed is True
        assert "idempotent" in reason

    def test_invalid_status_rejected(self):
        """非待接单状态拒绝取消。"""
        allowed, handler, reason = cancel_handler(
            "user_cancel", ORDER_TYPE_BOOKING_REALTIME, "in_trip")
        assert allowed is False

    def test_unknown_order_type_rejected(self):
        """未知订单类型拒绝。"""
        allowed, handler, reason = cancel_handler("user_cancel", 99, "waiting_driver")
        assert allowed is False


class TestCancelHandlerDispatchTimeout:
    """OrderCancelByDispatchTimeoutHandler 兼容 BOOKING_ORDER_TYPE。"""

    def test_booking_waiting_driver_timeout_allowed(self):
        """预约待接单+派单超时允许取消。"""
        allowed, handler, reason = cancel_handler(
            "dispatch_timeout", ORDER_TYPE_BOOKING_REALTIME, "waiting_driver")
        assert allowed is True
        assert handler == "OrderCancelByDispatchTimeoutHandler"

    def test_instant_waiting_driver_timeout_allowed(self):
        """即时待接单+派单超时允许取消。"""
        allowed, handler, reason = cancel_handler(
            "dispatch_timeout", ORDER_TYPE_REALTIME_INSTANT, "waiting_driver")
        assert allowed is True

    def test_non_waiting_driver_rejected(self):
        """非待接单状态拒绝超时取消。"""
        allowed, handler, reason = cancel_handler(
            "dispatch_timeout", ORDER_TYPE_BOOKING_REALTIME, "in_trip")
        assert allowed is False
        assert "not_waiting" in reason

    def test_already_cancelled_rejected(self):
        """已取消订单超时回调拒绝（幂等由 cancel_idempotent 处理）。"""
        allowed, handler, reason = cancel_handler(
            "dispatch_timeout", ORDER_TYPE_BOOKING_REALTIME, "cancelled")
        assert allowed is False


# ==================== §7.3.2 幂等语义 ====================

class TestCancelIdempotent:
    """已取消/订单不存在/重复回调按即时链路幂等语义处理。"""

    def test_already_cancelled_idempotent(self):
        """已取消订单幂等成功返回。"""
        result = cancel_idempotent("cancelled")
        assert result["handled"] is True
        assert "idempotent" in result["result"]

    def test_order_not_found_idempotent(self):
        """订单不存在幂等成功返回。"""
        result = cancel_idempotent(None, order_exists=False)
        assert result["handled"] is True
        assert "not_found" in result["result"]

    def test_active_order_proceeds(self):
        """活跃订单正常处理。"""
        result = cancel_idempotent("waiting_driver")
        assert result["handled"] is False
        assert result["result"] == "proceed"


# ==================== §7.3.2 20分钟派单超时 ====================

class TestTimeoutCancelDue:
    """后端仅在仍为待接单且已满20分钟时取消。"""

    def test_waiting_driver_at_20_min_triggers_cancel(self):
        """待接单满20分钟触发超时取消。"""
        assert timeout_cancel_due(timedelta(minutes=BOOKING_TIMEOUT_MINUTES), "waiting_driver") is True

    def test_waiting_driver_below_20_min_no_cancel(self):
        """待接单不足20分钟不取消。"""
        assert timeout_cancel_due(timedelta(minutes=19), "waiting_driver") is False

    def test_non_waiting_driver_no_cancel(self):
        """非待接单状态不取消。"""
        assert timeout_cancel_due(timedelta(minutes=30), "in_trip") is False
        assert timeout_cancel_due(timedelta(minutes=30), "cancelled") is False

    def test_exactly_20_minutes_triggers(self):
        """刚好20分钟触发。"""
        assert timeout_cancel_due(timedelta(minutes=20), "waiting_driver") is True


class TestCancellationView:
    """取消页面展示：超时取消和用户主动取消文案不同。"""

    def test_timeout_cancel_message(self):
        """超时取消显示"抱歉，暫無司機接單"。"""
        view = cancellation_view(True, "ORD001", "meter", "12:35", "北角", "港大")
        assert "抱歉" in view["message"]

    def test_user_cancel_message(self):
        """用户主动取消显示"你的訂單已取消"。"""
        view = cancellation_view(False, "ORD001", "meter", "12:35", "北角", "港大")
        assert "你的訂單" in view["message"]


# ==================== §7.3 取消清理 ====================

class TestCancellationCleanup:
    """取消后从未完成列表和订单列表进行中清理。"""

    def test_type16_cleaned_from_all(self):
        """type16 取消后从 unfinished/list 和 order/list 进行中移除。"""
        result = cancellation_cleanup(ORDER_TYPE_BOOKING_REALTIME)
        assert result["removed_from_unfinished_list"] is True
        assert result["removed_from_order_list_in_progress"] is True

    def test_type5_cleaned_from_all(self):
        """type5 取消后同样清理。"""
        result = cancellation_cleanup(ORDER_TYPE_REALTIME_INSTANT)
        assert result["removed_from_unfinished_list"] is True

    def test_unknown_type_rejected(self):
        """未知类型拒绝。"""
        with pytest.raises(ValueError):
            cancellation_cleanup(99)


# ==================== §7.3.3 passenger-service 状态机兼容 ====================

class TestOrderStatusConsume:
    """OrderStatusConsume 接受预约订单从待接单进入取消状态。"""

    def test_booking_waiting_to_cancelled_accepted(self):
        """预约待接单→取消被接受。"""
        assert order_status_consume_accepts(16, "waiting_driver", "cancelled") is True

    def test_booking_other_transition_rejected(self):
        """预约其他状态转换不被接受。"""
        assert order_status_consume_accepts(16, "waiting_driver", "in_trip") is False
        assert order_status_consume_accepts(16, "in_trip", "cancelled") is False

    def test_instant_all_accepted(self):
        """即时订单按当前逻辑全接受。"""
        assert order_status_consume_accepts(5, "waiting_driver", "cancelled") is True
        assert order_status_consume_accepts(5, "in_trip", "completed") is True

    def test_unknown_type_rejected(self):
        """未知类型拒绝。"""
        assert order_status_consume_accepts(99, "waiting_driver", "cancelled") is False


class TestOrderStatusPushMsg:
    """OrderStatusPushMsgConsume 文案映射。"""

    def test_booking_system_timeout_message(self):
        """预约+系统取消+派单超时→预约呼叫超时文案。"""
        assert order_status_push_msg(16, "system", True) == "booking_dispatch_timeout"

    def test_booking_user_cancel_message(self):
        """预约+用户取消→乘客取消文案。"""
        assert order_status_push_msg(16, "user", False) == "passenger_cancel"

    def test_booking_system_no_timeout_message(self):
        """预约+系统取消但非派单超时→系统取消文案。"""
        assert order_status_push_msg(16, "system", False) == "system_cancel"

    def test_instant_user_cancel_message(self):
        """即时+用户取消→乘客取消文案。"""
        assert order_status_push_msg(5, "user", False) == "passenger_cancel"

    def test_instant_system_timeout_message(self):
        """即时+系统取消+派单超时→乘客取消文案（即时无预约超时文案）。"""
        assert order_status_push_msg(5, "system", True) == "passenger_cancel"


class TestOrderStatusCouponConsume:
    """OrderStatusCouponConsume 使用当前优惠券返还和解锁。"""

    def test_booking_cancel_refund_and_unlock(self):
        """预约取消→优惠券返还+解锁。"""
        result = order_status_coupon_consume(16, "user")
        assert result["handled"] is True
        assert result["action"] == "refund_and_unlock"

    def test_instant_cancel_refund_and_unlock(self):
        """即时取消→优惠券返还+解锁。"""
        result = order_status_coupon_consume(5, "system")
        assert result["handled"] is True

    def test_unknown_type_not_handled(self):
        """未知类型不处理。"""
        result = order_status_coupon_consume(99, "user")
        assert result["handled"] is False


class TestOrderStatusSendSms:
    """OrderStatusSendSmsConsume 按取消短信规则处理。"""

    def test_booking_dispatch_timeout_sms(self):
        """预约+派单超时→预约超时短信。"""
        result = order_status_send_sms(16, "system", True)
        assert result["send"] is True
        assert result["template"] == "booking_dispatch_timeout_sms"

    def test_booking_user_cancel_sms(self):
        """预约+用户取消→用户取消短信。"""
        result = order_status_send_sms(16, "user", False)
        assert result["send"] is True
        assert result["template"] == "user_cancel_sms"

    def test_instant_system_cancel_sms(self):
        """即时+系统取消→系统取消短信。"""
        result = order_status_send_sms(5, "system", False)
        assert result["send"] is True
        assert result["template"] == "system_cancel_sms"

    def test_unknown_type_no_sms(self):
        """未知类型不发短信。"""
        result = order_status_send_sms(99, "user", False)
        assert result["send"] is False


# ==================== §7.7 优惠券降级依赖 ====================

class TestCouponServiceType:
    """预约使用即时券 service_type=5。"""

    def test_booking_uses_instant_coupon(self):
        """预约 type16 使用即时券 service_type=5。"""
        assert coupon_service_type(16) == COUPON_SERVICE_TYPE_INSTANT

    def test_instant_uses_instant_coupon(self):
        """即时 type5 使用即时券 service_type=5。"""
        assert coupon_service_type(5) == COUPON_SERVICE_TYPE_INSTANT

    def test_unknown_type_rejected(self):
        """未知类型报错。"""
        with pytest.raises(ValueError):
            coupon_service_type(99)


class TestCouponDegradation:
    """优惠券为降级依赖：查询失败不影响基础报价返回。"""

    def test_coupon_success_applies_discount(self):
        """优惠券查询成功时应用优惠。"""
        base_quote = {"fare": 50, "surcharge": 0}
        result = coupon_degradation(True, base_quote)
        assert result["coupon_applied"] is True
        assert result["base_quote"] == base_quote
        assert result["error"] is None

    def test_coupon_failure_does_not_affect_quote(self):
        """优惠券查询失败不影响基础报价返回。"""
        base_quote = {"fare": 50, "surcharge": 0}
        result = coupon_degradation(False, base_quote)
        assert result["coupon_applied"] is False
        assert result["base_quote"] == base_quote  # 报价不受影响
        assert result["error"] == "coupon_query_failed"

    def test_coupon_failure_logs_error(self):
        """优惠券查询失败必须记录错误指标和日志。"""
        result = coupon_degradation(False, {"fare": 50})
        assert result["error_logged"] is True
        assert result["metric_recorded"] is True

    def test_coupon_failure_not_displayed(self):
        """优惠券查询失败时响应不展示优惠结果。"""
        result = coupon_degradation(False, {"fare": 50})
        assert result["coupon_displayed"] is False
