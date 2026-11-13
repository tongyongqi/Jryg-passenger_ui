"""订单中心type16改造离线契约回归；不连接设备、不发起真实请求。

覆盖需求文档§6测试要点的离线契约部分：
1. create 传 payment_collection_mode=1, business_type=1 下单 type16，
   show 返回两字段为1；不传时为0
2. create 传非法值（如3）返回参数校验错误
3. type16订单在 order/list 各状态可见；取消后从未完成列表消失
4. unfinished/list 传 order_types=16 同时返回预约后付费单，按 use_time DESC 排序
5. status/info/hk 对 type16 返回正确 order_status / pay_status
6. 订单状态 MQ 消息中 payment_collection_mode / business_type 为下单值

附加：
7. 旧接口 unfinished/order 对 type16 不支持（OrderType!=5 直接 return）
8. 下单请求参数透传：create 请求体包含两新字段
9. 熔断错误码：unfinished/list 熔断时返回特定错误码
10. 订单列表存储路径：type16 走实时库不走预约库
"""

import pytest

from jryg_hk_android.JRYG_v150_contract import (
    ORDER_TYPE_REALTIME_INSTANT,
    ORDER_TYPE_BOOKING_REALTIME,
    PAYMENT_COLLECTION_ONLINE,
    BUSINESS_TAXI,
    order_center_create,
    order_center_show,
    create_params_validate,
    order_list_visible,
    unfinished_order_legacy,
    unfinished_list,
    unfinished_list_error,
    cancellation_cleanup,
    status_info_hk,
    order_status_mq,
    order_show_fields,
    active_order_visible,
)


# ==================== 测试要点1：create 传两字段，show 返回真实值 ====================

class TestCreateAndShowFields:
    """create 传 payment_collection_mode=1, business_type=1 下单 type16，show 返回两字段为1。"""

    def test_create_type16_with_both_fields_returns_real_values(self):
        result = order_center_create(
            ORDER_TYPE_BOOKING_REALTIME,
            payment_collection_mode=PAYMENT_COLLECTION_ONLINE,
            business_type=BUSINESS_TAXI)
        assert result["order_type"] == 16
        assert result["payment_collection_mode"] == 1
        assert result["business_type"] == 1
        assert result["storage"] == "realtime"

    def test_show_returns_fields_from_create(self):
        created = order_center_create(
            ORDER_TYPE_BOOKING_REALTIME,
            payment_collection_mode=PAYMENT_COLLECTION_ONLINE,
            business_type=BUSINESS_TAXI)
        shown = order_center_show(created)
        assert shown["payment_collection_mode"] == 1
        assert shown["business_type"] == 1

    def test_create_without_fields_defaults_to_zero(self):
        result = order_center_create(ORDER_TYPE_BOOKING_REALTIME)
        assert result["payment_collection_mode"] == 0
        assert result["business_type"] == 0
        shown = order_center_show(result)
        assert shown["payment_collection_mode"] == 0
        assert shown["business_type"] == 0

    def test_create_type5_with_fields_also_works(self):
        """即时单同样支持两新字段透传。"""
        result = order_center_create(
            ORDER_TYPE_REALTIME_INSTANT,
            payment_collection_mode=2,
            business_type=2)
        assert result["payment_collection_mode"] == 2
        assert result["business_type"] == 2
        assert result["storage"] == "realtime"

    def test_show_fields_defaults_to_zero_when_missing(self):
        shown = order_show_fields({"order_type": 16})
        assert shown["payment_collection_mode"] == 0
        assert shown["business_type"] == 0


# ==================== 测试要点2：非法值参数校验 ====================

class TestCreateParamValidation:
    """create 传非法值（如3）返回参数校验错误。"""

    def test_invalid_payment_collection_mode_rejected(self):
        with pytest.raises(ValueError, match="omitempty_oneof_1_2"):
            create_params_validate(payment_collection_mode=3)

    def test_invalid_business_type_rejected(self):
        with pytest.raises(ValueError, match="omitempty_oneof_1_2"):
            create_params_validate(business_type=3)

    def test_zero_value_rejected(self):
        """validate oneof=1,2 不含 0；0 是缺省态，由 None 表示。"""
        with pytest.raises(ValueError, match="omitempty_oneof_1_2"):
            create_params_validate(payment_collection_mode=0)

    def test_negative_value_rejected(self):
        with pytest.raises(ValueError, match="omitempty_oneof_1_2"):
            create_params_validate(business_type=-1)

    def test_valid_values_pass(self):
        result = create_params_validate(
            payment_collection_mode=PAYMENT_COLLECTION_ONLINE,
            business_type=BUSINESS_TAXI)
        assert result == {"payment_collection_mode": 1, "business_type": 1}

    def test_none_defaults_to_zero(self):
        result = create_params_validate()
        assert result == {"payment_collection_mode": 0, "business_type": 0}

    def test_create_with_invalid_field_rejected(self):
        """order_center_create 内部调用 checked，非法值同样拒绝。"""
        with pytest.raises(ValueError, match="omitempty_oneof_1_2"):
            order_center_create(ORDER_TYPE_BOOKING_REALTIME, payment_collection_mode=3)


# ==================== 测试要点3：订单列表可见性与取消清理 ====================

class TestOrderListVisibility:
    """type16订单在 order/list 进行中可见；取消后从未完成列表消失。"""

    @pytest.mark.parametrize("status,expected_source", [
        ("in_progress", "realtime_zset"),
        ("unpaid", "need_pay_map"),
        ("completed", "ots_terms"),
    ])
    def test_type16_visible_in_all_statuses(self, status, expected_source):
        result = order_list_visible(ORDER_TYPE_BOOKING_REALTIME, status=status)
        assert result == expected_source

    @pytest.mark.parametrize("status,expected_source", [
        ("in_progress", "realtime_zset"),
        ("unpaid", "need_pay_map"),
        ("completed", "ots_terms"),
    ])
    def test_type5_also_visible(self, status, expected_source):
        result = order_list_visible(ORDER_TYPE_REALTIME_INSTANT, status=status)
        assert result == expected_source

    def test_unknown_order_type_rejected(self):
        with pytest.raises(ValueError):
            order_list_visible(6)

    def test_invalid_status_rejected(self):
        with pytest.raises(ValueError):
            order_list_visible(ORDER_TYPE_BOOKING_REALTIME, status="unknown")

    def test_cancellation_removes_from_unfinished_list(self):
        result = cancellation_cleanup(ORDER_TYPE_BOOKING_REALTIME)
        assert result["removed_from_unfinished_list"] is True
        assert result["removed_from_order_list_in_progress"] is True

    def test_cancellation_cleanup_type5_consistent(self):
        """即时单取消后清理路径一致。"""
        result = cancellation_cleanup(ORDER_TYPE_REALTIME_INSTANT)
        assert result["removed_from_unfinished_list"] is True

    def test_cancellation_unknown_type_rejected(self):
        with pytest.raises(ValueError):
            cancellation_cleanup(99)


# ==================== 测试要点4：unfinished/list 多类型过滤与排序 ====================

class TestUnfinishedList:
    """unfinished/list 传 order_types=16 同时返回预约后付费单，按 use_time DESC 排序。"""

    def _sample_orders(self):
        return [
            {"order_type": 5, "use_time": "2026-01-01 10:00:00", "order_no": "A"},
            {"order_type": 16, "use_time": "2026-01-01 12:00:00", "order_no": "B"},
            {"order_type": 16, "use_time": "2026-01-01 11:00:00", "order_no": "C"},
            {"order_type": 5, "use_time": "2026-01-01 09:00:00", "order_no": "D"},
        ]

    def test_filter_type16_returns_only_booking_realtime(self):
        result = unfinished_list(self._sample_orders(), order_types=[16])
        assert len(result) == 2
        assert all(item["order_type"] == 16 for item in result)

    def test_sorted_by_use_time_desc(self):
        result = unfinished_list(self._sample_orders(), order_types=[16])
        assert result[0]["order_no"] == "B"  # 12:00
        assert result[1]["order_no"] == "C"  # 11:00

    def test_filter_both_types(self):
        result = unfinished_list(self._sample_orders(), order_types=[5, 16])
        assert len(result) == 4
        # 全部按 use_time DESC
        assert result[0]["order_no"] == "B"  # 12:00
        assert result[1]["order_no"] == "C"  # 11:00
        assert result[2]["order_no"] == "A"  # 10:00
        assert result[3]["order_no"] == "D"  # 09:00

    def test_no_filter_returns_all(self):
        """不传 order_types 默认返回全类型（≤5条）。"""
        result = unfinished_list(self._sample_orders())
        assert len(result) == 4

    def test_max_five_items(self):
        orders = [
            {"order_type": 16, "use_time": f"2026-01-01 {10+i:02d}:00:00", "order_no": f"O{i}"}
            for i in range(7)
        ]
        result = unfinished_list(orders, order_types=[16])
        assert len(result) == 5
        # 取最新的5条（use_time DESC）
        assert result[0]["order_no"] == "O6"
        assert result[4]["order_no"] == "O2"

    def test_empty_orders(self):
        result = unfinished_list([], order_types=[16])
        assert result == []


# ==================== 测试要点5：status/info/hk ====================

class TestStatusInfoHK:
    """status/info/hk 对 type16 返回正确 order_status / pay_status。"""

    def test_type16_returns_correct_status(self):
        order = {"order_status": 4, "pay_status": 2}
        result = status_info_hk(order)
        assert result == {"order_status": 4, "pay_status": 2}

    def test_type5_returns_correct_status(self):
        order = {"order_status": 13, "pay_status": 0}
        result = status_info_hk(order)
        assert result["order_status"] == 13

    def test_status_info_independent_of_type(self):
        """status/info/hk 按 order_id 查询，type16 命中实时库分支。"""
        for order_type in (5, 16):
            order = {"order_type": order_type, "order_status": 4, "pay_status": 2}
            result = status_info_hk(order)
            assert result["order_status"] == 4


# ==================== 测试要点6：订单状态 MQ 消息 ====================

class TestOrderStatusMQ:
    """MQ 消息中 payment_collection_mode / business_type 为下单值。"""

    def test_mq_carries_create_values(self):
        order = order_center_create(
            ORDER_TYPE_BOOKING_REALTIME,
            payment_collection_mode=PAYMENT_COLLECTION_ONLINE,
            business_type=BUSINESS_TAXI)
        mq = order_status_mq(order)
        assert mq["payment_collection_mode"] == 1
        assert mq["business_type"] == 1

    def test_mq_carries_zero_when_not_set(self):
        order = order_center_create(ORDER_TYPE_BOOKING_REALTIME)
        mq = order_status_mq(order)
        assert mq["payment_collection_mode"] == 0
        assert mq["business_type"] == 0

    def test_mq_consistent_with_show(self):
        """MQ 字段与 show 接口返回一致。"""
        created = order_center_create(
            ORDER_TYPE_BOOKING_REALTIME,
            payment_collection_mode=2,
            business_type=1)
        assert order_status_mq(created) == {
            "payment_collection_mode": 2,
            "business_type": 1}
        assert order_center_show(created) == {
            "order_type": 16,
            "payment_collection_mode": 2,
            "business_type": 1}


# ==================== 测试要点7：旧接口 unfinished/order 不支持 type16 ====================

class TestUnfinishedOrderLegacy:
    """旧接口 /user/unfinished/order 不支持 type16（OrderType!=5 直接 return）。"""

    def test_type5_supported(self):
        result = unfinished_order_legacy(ORDER_TYPE_REALTIME_INSTANT)
        assert result["supported"] is True

    def test_type16_not_supported(self):
        result = unfinished_order_legacy(ORDER_TYPE_BOOKING_REALTIME)
        assert result["supported"] is False
        assert "not_5" in result["reason"]

    def test_legacy_should_be_replaced_by_list(self):
        """旧接口不支持 type16，需切换到 unfinished/list。"""
        legacy = unfinished_order_legacy(ORDER_TYPE_BOOKING_REALTIME)
        assert not legacy["supported"], "旧接口不支持 type16，应切换到 unfinished/list"
        list_result = unfinished_list(
            [{"order_type": 16, "use_time": "2026-01-01 10:00:00"}],
            order_types=[16])
        assert len(list_result) == 1


# ==================== 测试要点8：熔断错误码 ====================

class TestUnfinishedListCircuitBreaker:
    """unfinished/list 熔断时返回 ErrQueryOrderPassengerServingPolardbBreak。"""

    def test_circuit_open_returns_error(self):
        err = unfinished_list_error(circuit_open=True)
        assert err == "ErrQueryOrderPassengerServingPolardbBreak"

    def test_circuit_closed_returns_none(self):
        err = unfinished_list_error(circuit_open=False)
        assert err is None


# ==================== 测试要点9：存储路径验证 ====================

class TestStoragePath:
    """type16 走实时库，不走预约库。"""

    def test_type16_storage_is_realtime(self):
        result = order_center_create(ORDER_TYPE_BOOKING_REALTIME)
        assert result["storage"] == "realtime"

    def test_type5_storage_is_realtime(self):
        result = order_center_create(ORDER_TYPE_REALTIME_INSTANT)
        assert result["storage"] == "realtime"

    def test_type6_storage_is_booking(self):
        """预约前付费 type6 走预约库（对比验证）。"""
        result = order_center_create(6)
        assert result["storage"] == "booking"


# ==================== 测试要点10：active_order_visible 取消后消失 ====================

class TestActiveOrderVisible:
    """active_order_visible 判断订单是否在列表中可见。"""

    def test_active_order_visible(self):
        order = {"cancelled": False, "completed": False}
        assert active_order_visible(order) is True

    def test_cancelled_order_not_visible(self):
        order = {"cancelled": True}
        assert active_order_visible(order) is False

    def test_completed_paid_order_not_visible(self):
        order = {"completed": True, "paid": True}
        assert active_order_visible(order) is False

    def test_completed_unpaid_order_still_visible(self):
        """已完成但未支付的订单仍需展示（待支付列表）。"""
        order = {"completed": True, "paid": False}
        assert active_order_visible(order) is True
