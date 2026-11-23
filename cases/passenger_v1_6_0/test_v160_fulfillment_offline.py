"""香港乘客端 V1.6.0 履约状态、分享安全与通知契约离线测试。

编写时间：2026-11-19
本期功能：预约接单后履约状态机、司机位置暴露、分享时效、安全分享时机、短信通知
需求映射：
- 需求 8：预付取消页原路退款提示
- 需求 9：新增待服务状态，司机位置暴露前 20 分钟规则，預約用車标签
- 需求 10：一口价弹框、消息栏轮播与条件展示
- 需求 11：预约安全中心、评价、短信模板、收据
- 需求 12：自动分享时机、999 报警、分享 72h/12h 时效
- 需求 13：我的行程分组与首页进行中订单卡片
- 技术方案：支付完成 MQ 派单规则、V1.6.0 版本准入

运行：pytest cases/passenger_v1_6_0/test_v160_fulfillment_offline.py -v
"""

import os
import sys
from datetime import datetime, timedelta

import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from passenger_android_core.v160.contract import (  # noqa: E402
    BOOKING_LABEL,
    FIXED_PRICE_POPUP_CONTENT,
    FIXED_PRICE_POPUP_TITLE,
    MESSAGE_FIXED_PRICE,
    MESSAGE_INVOICE,
)
from passenger_android_core.v160.booking_contract import (  # noqa: E402
    car_selector_next_state,
    CAR_SELECTOR_STATES,
    order_messages,
    show_endpoint_in_selector,
    truncate_endpoint_name,
    CAR_SELECTOR_STATE_COLLAPSED,
    CAR_SELECTOR_STATE_DEFAULT,
    CAR_SELECTOR_STATE_EXPANDED,
)
from passenger_android_core.v160.fulfillment_contract import (  # noqa: E402
    AUTO_SHARE_TRIGGER_ARRIVED,
    GROUP_BOOKING,
    GROUP_CANCELLED,
    GROUP_COMPLETED,
    GROUP_IN_SERVICE,
    GROUP_UNPAID,
    GROUP_WAITING_SERVICE,
    ORDER_STATUS_ACCEPTED,
    ORDER_STATUS_ARRIVED,
    ORDER_STATUS_BILL_PENDING,
    ORDER_STATUS_CANCELLED,
    ORDER_STATUS_IN_TRIP,
    ORDER_STATUS_PAID,
    ORDER_STATUS_PICKED_UP,
    ORDER_STATUS_UNPAID,
    ORDER_STATUS_WAITING,
    PAY_BROADCAST_FORWARD_DELAY_SECONDS,
    PAY_BROADCAST_FORWARD_TOPIC,
    PAY_BROADCAST_TOPIC,
    PASSENGER_PAY_CONSUMER_GROUP,
    SHARE_STATE_EXPIRED,
    SHARE_STATE_VALID,
    OrderPaySyncMessage,
    auto_share_trigger,
    booking_label_visible,
    business_label,
    cancel_count_params,
    cancel_refund_notice_required,
    driver_accepted_sms,
    driver_cancel_sms,
    emergency_sms_required,
    evaluation_supported,
    hit_v160,
    home_card_visible,
    legacy_compatible_order,
    pickup_main_text,
    pickup_sub_text,
    receipt_auto_send_eligible,
    receipt_fixed_entry_visible,
    receipt_manual_send_allowed,
    resolve_booking_status,
    safety_entry_visible,
    share_expire_at,
    share_state,
    share_supported,
    should_dispatch_after_payment,
    trip_ended_sms,
    trip_group_of,
    unfinished_list_params,
    unfinished_order_params,
    waiting_service_main_text,
    waiting_service_sub_text,
)


NOW = datetime(2026, 11, 13, 20, 0, 0)
USE_TIME = datetime(2026, 11, 13, 20, 25, 0)


# ===========================================================================
# Section 1：预约订单状态机（需求 9）
# ===========================================================================
class TestBookingStatusFlow:
    """接单 -> 待服务 -> 接驾 -> 到达起点 -> 送驾 -> 待确认账单 -> 待支付 -> 已支付。"""

    def test_waiting_status(self):
        """未接单为待接单状态。"""
        info = resolve_booking_status(None, None, None, None, None, None)
        assert info.order_status == ORDER_STATUS_WAITING

    def test_accepted_is_waiting_service(self):
        """司机已接单为待服务状态（100）。"""
        info = resolve_booking_status(NOW, None, None, None, None, None)
        assert info.order_status == ORDER_STATUS_ACCEPTED

    def test_driver_pickup_status(self):
        """司机开始接驾后进入接驾状态。"""
        info = resolve_booking_status(
            NOW, NOW + timedelta(minutes=5), None, None, None, None)
        assert info.order_status == ORDER_STATUS_PICKED_UP

    def test_arrived_status(self):
        """司机到达上车点后进入到达起点状态。"""
        info = resolve_booking_status(
            NOW, NOW + timedelta(minutes=5), NOW + timedelta(minutes=10),
            None, None, None)
        assert info.order_status == ORDER_STATUS_ARRIVED

    def test_in_trip_status(self):
        """开始送驾后进入行程中状态。"""
        info = resolve_booking_status(
            NOW, NOW + timedelta(minutes=5), NOW + timedelta(minutes=10),
            NOW + timedelta(minutes=12), None, None)
        assert info.order_status == ORDER_STATUS_IN_TRIP

    def test_bill_pending_status(self):
        """行程结束进入待确认账单状态。"""
        info = resolve_booking_status(
            NOW, NOW + timedelta(minutes=5), NOW + timedelta(minutes=10),
            NOW + timedelta(minutes=12), NOW + timedelta(minutes=30), None)
        assert info.order_status == ORDER_STATUS_BILL_PENDING

    def test_unpaid_status(self):
        """账单确认后未支付进入待支付状态。"""
        info = resolve_booking_status(
            NOW, NOW + timedelta(minutes=5), NOW + timedelta(minutes=10),
            NOW + timedelta(minutes=12), NOW + timedelta(minutes=30),
            None, unpaid_at=NOW + timedelta(minutes=32))
        assert info.order_status == ORDER_STATUS_UNPAID

    def test_paid_status(self):
        """支付完成后进入已支付状态。"""
        info = resolve_booking_status(
            NOW, NOW + timedelta(minutes=5), NOW + timedelta(minutes=10),
            NOW + timedelta(minutes=12), NOW + timedelta(minutes=30),
            NOW + timedelta(minutes=32), NOW + timedelta(minutes=33))
        assert info.order_status == ORDER_STATUS_PAID

    def test_cancelled_status(self):
        """订单取消后进入已取消状态。"""
        info = resolve_booking_status(
            NOW, None, None, None, None, None, cancelled=True)
        assert info.order_status == ORDER_STATUS_CANCELLED

    def test_out_of_order_timestamps_raise(self):
        """状态时间戳顺序矛盾时必须报错，不得静默产出错误状态。"""
        with pytest.raises(ValueError, match="时间顺序矛盾"):
            resolve_booking_status(
                NOW + timedelta(minutes=10), NOW, None, None, None, None)


# ===========================================================================
# Section 2：司机位置暴露（需求 9）
# ===========================================================================
class TestDriverLocationExposure:
    """距出发时间大于 20 分钟时不展示司机位置。"""

    def test_not_exposed_when_far(self):
        """距出发时间超过 20 分钟不下发司机位置。"""
        info = resolve_booking_status(
            NOW, None, None, None, None, None,
            use_time=NOW + timedelta(minutes=25), now=NOW)
        assert info.driver_location_visible is False

    def test_exposed_within_20_minutes(self):
        """进入出发前 20 分钟后下发司机位置。"""
        info = resolve_booking_status(
            NOW, None, None, None, None, None,
            use_time=NOW + timedelta(minutes=19), now=NOW)
        assert info.driver_location_visible is True

    def test_exposed_after_pickup(self):
        """进入接驾后按即时规则展示司机位置。"""
        info = resolve_booking_status(
            NOW, NOW + timedelta(minutes=5), None, None, None, None,
            use_time=NOW + timedelta(minutes=25), now=NOW)
        assert info.driver_location_visible is True


# ===========================================================================
# Section 3：状态文案与业务标签（需求 9）
# ===========================================================================
class TestStatusTextAndLabel:
    """待服务/接驾文案与「預約用車」标签。"""

    def test_waiting_service_main_text(self):
        """待服务主文案含「預約成功」及出发时间。"""
        text = waiting_service_main_text(USE_TIME)
        assert "預約成功" in text
        assert "2026-11-13 20:25" in text

    def test_waiting_service_sub_text(self):
        """待服务副文案展示距出发分钟数。"""
        assert "20分鐘" in waiting_service_sub_text()

    def test_pickup_main_text(self):
        """接驾主文案为「司機正趕來接您」。"""
        assert pickup_main_text() == "司機正趕來接您"

    def test_pickup_sub_text(self):
        """接驾副文案展示出发时间。"""
        assert "2026-11-13 20:25" in pickup_sub_text(USE_TIME)

    def test_booking_label_only_for_booking(self):
        """「預約用車」标签仅预约业务展示，即时业务不展示。"""
        assert booking_label_visible(6) is True
        assert booking_label_visible(5) is False

    def test_business_label_text(self):
        """业务标签文案：预约为「預約用車」，即时为空串。"""
        assert business_label(6) == BOOKING_LABEL
        assert business_label(5) == ""


# ===========================================================================
# Section 4：我的行程分组（需求 13）
# ===========================================================================
class TestTripGroup:
    """我的行程按业务状态分组展示预约订单。"""

    @pytest.mark.parametrize("status,group", [
        (ORDER_STATUS_WAITING, GROUP_BOOKING),
        (ORDER_STATUS_ACCEPTED, GROUP_WAITING_SERVICE),
        (ORDER_STATUS_PICKED_UP, GROUP_IN_SERVICE),
        (ORDER_STATUS_ARRIVED, GROUP_IN_SERVICE),
        (ORDER_STATUS_IN_TRIP, GROUP_IN_SERVICE),
        (ORDER_STATUS_BILL_PENDING, GROUP_IN_SERVICE),
        (ORDER_STATUS_UNPAID, GROUP_UNPAID),
        (ORDER_STATUS_PAID, GROUP_COMPLETED),
        (ORDER_STATUS_CANCELLED, GROUP_CANCELLED),
    ])
    def test_group_mapping(self, status, group):
        """预约订单按状态归入对应分组（预约中/待服务/服务中/待支付/已完成/已取消）。"""
        assert trip_group_of(status, 6) == group

    @pytest.mark.parametrize("status", [
        ORDER_STATUS_ACCEPTED, ORDER_STATUS_PICKED_UP,
        ORDER_STATUS_ARRIVED, ORDER_STATUS_IN_TRIP,
    ])
    def test_home_card_visible_for_booking(self, status):
        """首页进行中订单卡片展示预约 4 种状态。"""
        assert home_card_visible(status, 6) is True

    def test_home_card_hidden_for_paid(self):
        """已支付订单不在首页进行中卡片展示。"""
        assert home_card_visible(ORDER_STATUS_PAID, 6) is False

    def test_unfinished_list_params(self):
        """进行中订单列表按 order_type=6 查询预约订单。"""
        assert unfinished_list_params(6) == {"order_type": 6}

    def test_unfinished_order_params(self):
        """进行中订单详情按 order_type=5 查询即时订单。"""
        assert unfinished_order_params(5) == {"order_type": 5}

    def test_cancel_count_params_separate(self):
        """即时与预约取消次数分别查询。"""
        assert cancel_count_params(5) == {"order_type": 5}
        assert cancel_count_params(6) == {"order_type": 6}


# ===========================================================================
# Section 5：消息栏与一口价弹框（需求 10）
# ===========================================================================
class TestOrderMessages:
    """消息1 仅出租车展示，消息2 全部一口价订单展示，3 秒轮播。"""

    def test_taxi_chartered_has_both(self):
        """包車價的士同时展示消息1（纸质发票）与消息2（一口价附加费）。"""
        messages = order_messages(is_taxi=True, is_fixed_price=True)
        assert len(messages) == 2
        assert messages[0]["text"] == MESSAGE_INVOICE
        assert messages[0]["clickable"] is False
        assert messages[1]["text"] == MESSAGE_FIXED_PRICE
        assert messages[1]["clickable"] is True

    def test_taxi_metered_has_only_invoice(self):
        """打錶的士仅展示消息1（纸质发票），非一口价无消息2。"""
        messages = order_messages(is_taxi=True, is_fixed_price=False)
        assert len(messages) == 1
        assert messages[0]["text"] == MESSAGE_INVOICE

    def test_ride_hailing_has_only_fixed_price(self):
        """网约车不是出租车车型，不展示纸质发票消息。"""
        messages = order_messages(is_taxi=False, is_fixed_price=True)
        assert len(messages) == 1
        assert messages[0]["text"] == MESSAGE_FIXED_PRICE
        assert messages[0]["clickable"] is True

    def test_message2_text_adjusted(self):
        """消息2 文案为「本單為一口價...」。"""
        assert MESSAGE_FIXED_PRICE == (
            "本單為一口價，行程中產生的隧道費等額外收費，需另行自行繳付。")

    def test_fixed_price_popup_content(self):
        """R10-06：一口价说明弹框完整文案。"""
        assert FIXED_PRICE_POPUP_TITLE == "一口價說明"
        assert FIXED_PRICE_POPUP_CONTENT == (
            "一口價只計司機行車相關費用，行程期間所產生的隧道費、泊車費及其他額外收費，"
            "均須乘客另行自行繳付。\n"
            "一口價訂單只適用是次行程之起點及終點，並須按指定路線行駛，暫不支援更改目的地"
        )


# ===========================================================================
# Section 6：分享（需求 12）
# ===========================================================================
class TestShare:
    """接单后分享有效 72 小时，行程结束后 12 小时失效。"""

    def test_share_supported_for_waiting_service(self):
        """待服务状态（100）支持主动分享。"""
        assert share_supported(ORDER_STATUS_ACCEPTED) is True

    def test_share_supported_for_pickup(self):
        """接驾状态支持主动分享。"""
        assert share_supported(ORDER_STATUS_PICKED_UP) is True

    def test_share_supported_for_arrived(self):
        """到达起点状态支持主动分享。"""
        assert share_supported(ORDER_STATUS_ARRIVED) is True

    def test_share_supported_for_in_trip(self):
        """送驾/行程中状态支持主动分享。"""
        assert share_supported(ORDER_STATUS_IN_TRIP) is True

    def test_share_not_supported_for_waiting(self):
        """待接单状态不支持主动分享。"""
        assert share_supported(ORDER_STATUS_WAITING) is False

    def test_expire_at_72h_after_accept(self):
        """预约未完成时分享有效期为接单后 72 小时。"""
        expire = share_expire_at(NOW, None)
        assert expire == NOW + timedelta(hours=72)

    def test_expire_at_12h_after_trip_end(self):
        """行程结束后分享有效期为 12 小时。"""
        ended = NOW + timedelta(hours=2)
        expire = share_expire_at(NOW, ended)
        assert expire == ended + timedelta(hours=12)

    def test_earlier_deadline_wins(self):
        """行程结束 12h 早于接单 72h 时取较早者。"""
        ended = NOW + timedelta(minutes=30)
        expire = share_expire_at(NOW, ended)
        assert expire == ended + timedelta(hours=12)

    def test_state_valid_before_expire(self):
        """未超过有效期时分享状态为有效。"""
        assert share_state(NOW, None, NOW + timedelta(hours=71)) == SHARE_STATE_VALID

    def test_state_expired_after_72h(self):
        """超过接单后 72 小时分享状态为失效。"""
        assert share_state(NOW, None, NOW + timedelta(hours=73)) == SHARE_STATE_EXPIRED

    def test_state_expired_after_trip_end_12h(self):
        """超过完单后 12 小时分享状态为失效。"""
        ended = NOW + timedelta(hours=1)
        assert share_state(NOW, ended, ended + timedelta(hours=13)) == SHARE_STATE_EXPIRED


# ===========================================================================
# Section 7：安全中心与自动分享（需求 12）
# ===========================================================================
class TestSafety:
    """自动分享时机调整为到达起点；999 报警始终发送行程短信。"""

    def test_auto_share_trigger_at_arrived(self):
        """自动分享时机为到达起点。"""
        assert auto_share_trigger(ORDER_STATUS_ARRIVED) == AUTO_SHARE_TRIGGER_ARRIVED

    def test_auto_share_not_triggered_on_accept(self):
        """接单时不触发自动分享。"""
        assert auto_share_trigger(ORDER_STATUS_ACCEPTED) is None

    def test_auto_share_not_triggered_on_pickup(self):
        """接驾时不触发自动分享。"""
        assert auto_share_trigger(ORDER_STATUS_PICKED_UP) is None

    def test_emergency_sms_always_sent(self):
        """未开启自动分享时 999 报警仍发送行程短信。"""
        assert emergency_sms_required(auto_share_enabled=False) is True

    def test_emergency_sms_when_enabled(self):
        """已开启自动分享时 999 报警同样发送行程短信。"""
        assert emergency_sms_required(auto_share_enabled=True) is True

    def test_safety_entry_visible_for_both(self):
        """即时与预约业务均展示安全中心入口。"""
        assert safety_entry_visible(5) is True
        assert safety_entry_visible(6) is True


# ===========================================================================
# Section 8：短信通知与收据评价（需求 11）
# ===========================================================================
class TestNotificationAndReceipt:
    """预约短信模板、收据与评价。"""

    def test_driver_accepted_sms_template(self):
        """司机接单使用新增预约短信模板，含车牌与出发时间。"""
        sms = driver_accepted_sms("FB8793", USE_TIME)
        assert sms == "【陽光出行】司機FB8793已接單，預約出發時間為2026-11-13 20:25"

    def test_driver_cancel_sms_reused(self):
        """司机取消复用即时业务短信模板。"""
        assert driver_cancel_sms() == (
            "【陽光出行】司機已取消本次行程，您可嘗試重新下單。")

    def test_trip_ended_sms_reused(self):
        """行程结束复用即时业务短信模板。"""
        assert "行程已結束" in trip_ended_sms()

    def test_receipt_supported_for_booking(self):
        """预约业务支持收据入口。"""
        assert receipt_fixed_entry_visible(6) is True

    def test_receipt_auto_send_eligible(self):
        """已支付且有邮箱时满足自动发送收据条件。"""
        assert receipt_auto_send_eligible(6, paid=True, email="v160_receipt@sunlightmobility.hk") is True

    def test_receipt_auto_send_requires_paid(self):
        """未支付时不自动发送收据。"""
        assert receipt_auto_send_eligible(6, paid=False, email="v160_receipt@sunlightmobility.hk") is False

    def test_receipt_auto_send_requires_email(self):
        """无邮箱时不自动发送收据。"""
        assert receipt_auto_send_eligible(6, paid=True, email=None) is False

    def test_receipt_manual_send_allowed(self):
        """已支付且有邮箱时允许主动发送收据。"""
        assert receipt_manual_send_allowed(6, paid=True, email="v160_receipt@sunlightmobility.hk") is True

    def test_evaluation_supported(self):
        """即时与预约业务均支持评价。"""
        assert evaluation_supported(6) is True
        assert evaluation_supported(5) is True


# ===========================================================================
# Section 9：预付取消退款提示（需求 8）
# ===========================================================================
class TestCancelRefundNotice:
    """预付订单取消页增加原路退款提示。"""

    def test_paid_advance_has_notice(self):
        """预付订单取消页需要展示原路退款提示。"""
        assert cancel_refund_notice_required(True) is True

    def test_not_paid_no_notice(self):
        """非预付订单取消页不展示退款提示。"""
        assert cancel_refund_notice_required(False) is False


# ===========================================================================
# Section 10：车型选择栏三段式高度（需求 4）
# ===========================================================================
class TestCarSelectorState:
    """默认/展开/收起三种高度状态。"""

    def test_three_states(self):
        """车型栏存在 default/expanded/collapsed 三种高度状态。"""
        assert set(CAR_SELECTOR_STATES) == {
            CAR_SELECTOR_STATE_DEFAULT,
            CAR_SELECTOR_STATE_EXPANDED,
            CAR_SELECTOR_STATE_COLLAPSED,
        }

    def test_slide_up_expands(self):
        """默认状态下上滑进入展开状态。"""
        assert car_selector_next_state(
            CAR_SELECTOR_STATE_DEFAULT, "up") == CAR_SELECTOR_STATE_EXPANDED

    def test_slide_down_collapses(self):
        """默认状态下下滑进入收起状态。"""
        assert car_selector_next_state(
            CAR_SELECTOR_STATE_DEFAULT, "down") == CAR_SELECTOR_STATE_COLLAPSED

    def test_slide_up_at_top_stays(self):
        """展开状态继续上滑保持不变（已到顶）。"""
        assert car_selector_next_state(
            CAR_SELECTOR_STATE_EXPANDED, "up") == CAR_SELECTOR_STATE_EXPANDED

    def test_slide_down_at_bottom_stays(self):
        """收起状态继续下滑保持不变（已到底）。"""
        assert car_selector_next_state(
            CAR_SELECTOR_STATE_COLLAPSED, "down") == CAR_SELECTOR_STATE_COLLAPSED

    def test_invalid_state_raises(self):
        """未知车型栏状态必须报错。"""
        with pytest.raises(ValueError, match="未知车型栏状态"):
            car_selector_next_state("bad", "up")

    def test_invalid_direction_raises(self):
        """未知滑动方向必须报错。"""
        with pytest.raises(ValueError, match="未知滑动方向"):
            car_selector_next_state(CAR_SELECTOR_STATE_DEFAULT, "left")

    def test_endpoint_shown_only_when_expanded(self):
        """起终点仅在展开状态展示。"""
        assert show_endpoint_in_selector(CAR_SELECTOR_STATE_EXPANDED) is True
        assert show_endpoint_in_selector(CAR_SELECTOR_STATE_DEFAULT) is False

    def test_truncate_within_limit(self):
        """10 字以内不截断。"""
        assert truncate_endpoint_name("北角地铁站") == "北角地铁站"

    def test_truncate_over_limit(self):
        """超过 10 字截断为前 10 字加省略号。"""
        assert truncate_endpoint_name("香港大学 station 很长很长") == \
            "香港大学 stati..."

    def test_truncate_exactly_10(self):
        """恰好 10 字不截断。"""
        assert truncate_endpoint_name("1234567890") == "1234567890"

    def test_truncate_11_chars(self):
        """11 字截断为前 10 字加省略号。"""
        assert truncate_endpoint_name("12345678901") == "1234567890..."


# ===========================================================================
# Section 11：支付完成 MQ 与派单（技术方案）
# ===========================================================================
class TestPayBroadcast:
    """支付完成转发 MQ 延时 1s；预约不发单。"""

    def test_topics(self):
        """MQ Topic/Consumer/延时常量与需求文档一致。"""
        assert PAY_BROADCAST_TOPIC == "topic_cashier_trade_order_pay_broadcast"
        assert PAY_BROADCAST_FORWARD_TOPIC == "topic_order_service_order_pay_broadcast"
        assert PAY_BROADCAST_FORWARD_DELAY_SECONDS == 1
        assert PASSENGER_PAY_CONSUMER_GROUP == \
            "consumer_group_passenger_service_trade_order_pay_broadcast"

    def test_instant_ride_hailing_dispatches(self):
        """business_type=2 且 order_type=5 发单。"""
        assert should_dispatch_after_payment(2, 5) is True

    def test_booking_ride_hailing_no_dispatch(self):
        """order_type=6 不发单。"""
        assert should_dispatch_after_payment(2, 6) is False

    def test_instant_taxi_dispatches(self):
        """business_type=1 且 order_type=5 发单。"""
        assert should_dispatch_after_payment(1, 5) is True

    def test_booking_taxi_no_dispatch(self):
        """business_type=1 且 order_type=6 不发单。"""
        assert should_dispatch_after_payment(1, 6) is False

    def test_message_should_dispatch(self):
        """消息对象自身的派单判定与函数一致。"""
        message = OrderPaySyncMessage(business_type=2, order_type=5)
        assert message.should_dispatch() is True

    def test_booking_message_no_dispatch(self):
        """预约消息对象判定为不发单。"""
        message = OrderPaySyncMessage(business_type=2, order_type=6)
        assert message.should_dispatch() is False

    def test_message_payload_keys(self):
        """MQ 消息体包含文档定义的核心字段，且不含 event_id。"""
        message = OrderPaySyncMessage(
            order_id=100001, order_no="TH26B6PIEWECN", trade_no="TR20261119001",
            order_type=6,
            business_type=2, pay_amount=1720, total_discount_amount=1010)
        payload = message.to_dict()
        assert payload["order_id"] == 100001
        assert payload["order_no"] == "TH26B6PIEWECN"
        assert payload["pay_amount"] == 1720
        assert payload["total_discount_amount"] == 1010
        assert "event_id" not in payload


# ===========================================================================
# Section 12：V1.6.0 版本准入（技术方案 7.2）
# ===========================================================================
class TestVersionAdmission:
    """总开关 + 灰度命中才创建 V1.6.0 订单。"""

    def test_hit_when_switch_on_and_gray_matched(self):
        """总开关开启且 agent 在灰度范围内时命中 V1.6.0。"""
        assert hit_v160(True, 1001, "1.6.0", [1001]) is True

    def test_not_hit_when_switch_off(self):
        """总开关关闭时不命中，不创建 V1.6.0 订单。"""
        assert hit_v160(False, 1001, "1.6.0", [1001]) is False

    def test_not_hit_when_agent_not_in_scope(self):
        """agent 不在灰度范围内时不命中。"""
        assert hit_v160(True, 2002, "1.6.0", [1001]) is False

    def test_not_hit_when_client_version_too_low(self):
        """客户端版本低于最低要求时不命中。"""
        assert hit_v160(True, 1001, "1.5.9", [1001], "1.6.0") is False

    def test_hit_when_client_version_ok(self):
        """客户端版本达到最低要求时命中。"""
        assert hit_v160(True, 1001, "1.6.0", [1001], "1.6.0") is True

    def test_empty_scope_means_all_agents(self):
        """灰度范围为空表示对全部 agent 生效。"""
        assert hit_v160(True, 9999, "1.6.0", []) is True

    def test_legacy_taxi_instant_always_allowed(self):
        """既有出租车即时下单不受影响。"""
        assert legacy_compatible_order(5, False, False) is True

    def test_legacy_taxi_booking_always_allowed(self):
        """既有出租车预约下单不受影响。"""
        assert legacy_compatible_order(6, False, False) is True

    def test_legacy_client_cannot_create_ride_hailing(self):
        """老版本不得创建新增网约车订单。"""
        assert legacy_compatible_order(5, True, False) is False

    def test_new_client_can_create_ride_hailing(self):
        """新版本允许创建网约车订单。"""
        assert legacy_compatible_order(5, True, True) is True
