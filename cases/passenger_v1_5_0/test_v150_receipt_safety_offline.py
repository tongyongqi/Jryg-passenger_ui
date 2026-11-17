# 编写时间：2026-11-17
# V1.5.0 收据 type16 排除验证 + 安全手机号/联系人/邮箱离线契约
"""收据自动发送资格排除 type16 + 安全手机号/联系人/邮箱规则离线回归。

覆盖处理规则文档§7.5-§7.6：
- §7.6 收据自动发送资格条件固定 order_type=5，type16 不触发
- §7.6 收据事件源：charter→order_status_machine，meter→order_pay_success
- §7.4 安全手机号通过 system/config 下发
- §7.5 联系人 save/delete/share 规则
- §7.5 邮箱 save 规则
"""

import pytest

from passenger_android_core.v150.contract import (
    PASSENGER_INSTANT,
    ORDER_TYPE_REALTIME_INSTANT,
    ORDER_TYPE_BOOKING_REALTIME,
    PAYMENT_COLLECTION_ONLINE,
    BUSINESS_TAXI,
    CONTACT_LIMIT,
    CONTACT_NAME_LIMIT,
    # 收据
    receipt_auto_eligible,
    receipt_event_source,
    receipt_controls,
    receipt_request,
    receipt_success_state,
    receipt_failure_state,
    ReceiptTaskStore,
    # 安全手机号
    safety_entry_visible,
    get_safety_phone,
    call_phone_result,
    # 联系人
    Contact,
    ContactStore,
    validate_contact_input,
    mask_contact_phone,
    # 邮箱
    normalize_email,
    save_email,
    email_from_storage,
)


# ==================== §7.6 收据：type16 排除 ====================

class TestReceiptAutoEligibleType16Excluded:
    """收据自动发送资格条件固定 order_type=5，type16 不触发。"""

    _ELIGIBLE_BASE = {
        "region": "HK",
        "order_status": 13,
        "pay_status": 2,
        "payment_collection_mode": PAYMENT_COLLECTION_ONLINE,
        "belongs_to_passenger": True,
        "car_type": "meter",
        "email": "test@example.com",
    }

    def test_type5_instant_eligible(self):
        """即时 type5 满足全部条件时触发自动收据。"""
        order = {**self._ELIGIBLE_BASE, "order_type": PASSENGER_INSTANT}
        assert receipt_auto_eligible(order) is True

    def test_type16_booking_not_eligible(self):
        """预约 type16 即使满足其他条件也不触发自动收据。"""
        order = {**self._ELIGIBLE_BASE, "order_type": ORDER_TYPE_BOOKING_REALTIME}
        assert receipt_auto_eligible(order) is False

    def test_type16_excluded_regardless_of_completion(self):
        """预约 type16 完单+支付成功后仍不触发收据。"""
        order = {
            "region": "HK",
            "order_type": ORDER_TYPE_BOOKING_REALTIME,
            "order_status": 13,
            "pay_status": 2,
            "payment_collection_mode": PAYMENT_COLLECTION_ONLINE,
            "belongs_to_passenger": True,
            "car_type": "meter",
            "email": "test@example.com",
        }
        assert receipt_auto_eligible(order) is False

    def test_type5_missing_email_not_eligible(self):
        """即时 type5 无邮箱时不触发。"""
        order = {**self._ELIGIBLE_BASE, "order_type": PASSENGER_INSTANT, "email": ""}
        assert receipt_auto_eligible(order) is False

    def test_type5_offline_payment_not_eligible(self):
        """即时 type5 线下支付不触发。"""
        order = {**self._ELIGIBLE_BASE, "order_type": PASSENGER_INSTANT,
                 "payment_collection_mode": 2}
        assert receipt_auto_eligible(order) is False

    def test_type5_not_hk_not_eligible(self):
        """非 HK 不触发。"""
        order = {**self._ELIGIBLE_BASE, "order_type": PASSENGER_INSTANT, "region": "CN"}
        assert receipt_auto_eligible(order) is False


class TestReceiptEventSource:
    """收据事件源：charter→order_status_machine，meter→order_pay_success。"""

    def test_charter_uses_status_machine(self):
        """包车→order_status_machine（先支付后完单）。"""
        assert receipt_event_source("charter") == "order_status_machine"

    def test_meter_uses_pay_success(self):
        """打表→order_pay_success（先完单后支付）。"""
        assert receipt_event_source("meter") == "order_pay_success"

    def test_unknown_car_type_rejected(self):
        """未知车型报错。"""
        with pytest.raises(ValueError, match="unsupported_car_type"):
            receipt_event_source("unknown")


class TestReceiptTaskStore:
    """ReceiptTaskStore：order_no 唯一任务及财务受理结果。"""

    def test_create_once_succeeds(self):
        """首次创建成功。"""
        store = ReceiptTaskStore()
        task, created = store.create_once("ORD001", "order_pay_success")
        assert created is True
        assert task["status"] == "PENDING"

    def test_create_once_idempotent(self):
        """重复创建返回已存在任务。"""
        store = ReceiptTaskStore()
        store.create_once("ORD001", "order_pay_success")
        task, created = store.create_once("ORD001", "order_status_machine")
        assert created is False
        assert task["status"] == "PENDING"

    def test_finance_accepted(self):
        """财务系统受理成功。"""
        store = ReceiptTaskStore()
        store.create_once("ORD001", "order_pay_success")
        task = store.finance_result("ORD001", {"code": 10000, "accepted": True, "request_id": "r1"})
        assert task["status"] == "ACCEPTED"
        assert task["request_id"] == "r1"

    def test_finance_retryable_failed(self):
        """财务系统临时失败可重试。"""
        store = ReceiptTaskStore()
        store.create_once("ORD001", "order_pay_success")
        task = store.finance_result("ORD001", {"temporary": True})
        assert task["status"] == "RETRYABLE_FAILED"

    def test_finance_permanent_failed(self):
        """财务系统永久失败。"""
        store = ReceiptTaskStore()
        store.create_once("ORD001", "order_pay_success")
        task = store.finance_result("ORD001", {"code": 500})
        assert task["status"] == "PERMANENT_FAILED"

    def test_finance_transport_error(self):
        """传输错误→UNKNOWN。"""
        store = ReceiptTaskStore()
        store.create_once("ORD001", "order_pay_success")
        task = store.finance_result("ORD001", transport_error=True)
        assert task["status"] == "UNKNOWN"


# ==================== §7.4 安全手机号 ====================

class TestSafetyPhone:
    """安全手机号通过 system/config 下发。"""

    def test_safety_phone_from_config(self):
        """从配置中读取安全手机号。"""
        config = {"safety_phone": "+85299999999"}
        assert get_safety_phone(config) == "+85299999999"

    def test_safety_phone_missing_returns_empty(self):
        """配置缺失返回空字符串。"""
        assert get_safety_phone({}) == ""

    def test_safety_phone_null_returns_empty(self):
        """配置为 None 返回空字符串。"""
        assert get_safety_phone({"safety_phone": None}) == ""

    def test_call_phone_can_open(self):
        """能打开拨号盘返回 YES。"""
        assert call_phone_result(True) == "YES"

    def test_call_phone_cannot_open(self):
        """不能打开拨号盘返回 NO。"""
        assert call_phone_result(False) == "NO"

    def test_safety_entry_visible_on_home(self):
        """安全中心入口在首页可见。"""
        assert safety_entry_visible("home") is True

    def test_safety_entry_visible_on_calling(self):
        """安全中心入口在呼叫中可见。"""
        assert safety_entry_visible("instant_calling") is True

    def test_safety_entry_not_visible_on_unknown_page(self):
        """未知页面不可见。"""
        assert safety_entry_visible("unknown_page") is False


# ==================== §7.5 紧急联系人 ====================

class TestContactValidation:
    """联系人输入校验。"""

    def test_valid_contact_passes(self):
        """合法联系人通过校验。"""
        name = validate_contact_input("張三", "12345678", "98765432", 0)
        assert name == "張三"

    def test_empty_name_rejected(self):
        """空姓名被拒绝。"""
        with pytest.raises(ValueError, match="請填寫聯絡人"):
            validate_contact_input("", "12345678", "98765432", 0)

    def test_name_too_long_rejected(self):
        """姓名超15字符被拒绝。"""
        long_name = "x" * (CONTACT_NAME_LIMIT + 1)
        with pytest.raises(ValueError, match="contact_name_too_long"):
            validate_contact_input(long_name, "12345678", "98765432", 0)

    def test_empty_phone_rejected(self):
        """空电话被拒绝。"""
        with pytest.raises(ValueError, match="請填寫電話"):
            validate_contact_input("張三", "", "98765432", 0)

    def test_short_phone_rejected(self):
        """短于8位电话被拒绝。"""
        with pytest.raises(ValueError, match="手機號碼格式不正確"):
            validate_contact_input("張三", "1234567", "98765432", 0)

    def test_own_phone_rejected(self):
        """本人手机号不能作为紧急联系人。"""
        with pytest.raises(ValueError, match="本人不可作為緊急聯絡人"):
            validate_contact_input("張三", "98765432", "98765432", 0)

    def test_invalid_auto_share_rejected(self):
        """auto_share 非0/1被拒绝。"""
        with pytest.raises(ValueError, match="auto_share_must_be_0_or_1"):
            validate_contact_input("張三", "12345678", "98765432", 0, auto_share=3)

    def test_limit_3_contacts(self):
        """达到3人时拒绝创建。"""
        with pytest.raises(ValueError, match="最多可新增3個聯絡人"):
            validate_contact_input("張三", "12345678", "98765432", CONTACT_LIMIT)


class TestContactStore:
    """联系人存储：增删改查+自动分享。"""

    def _store_with_contacts(self):
        """构造含2个联系人的存储。"""
        store = ContactStore()
        store.save(1, 0, "張三", "12345678", "99999999", auto_share=0)
        store.save(1, 0, "李四", "87654321", "99999999", auto_share=1)
        return store

    def test_save_new_contact(self):
        """保存新联系人。"""
        store = ContactStore()
        contact = store.save(1, 0, "張三", "12345678", "99999999")
        assert contact.contact_id == 1
        assert contact.name == "張三"
        assert len(store.contacts) == 1

    def test_update_existing_contact(self):
        """更新已有联系人不占新增名额。"""
        store = self._store_with_contacts()
        store.save(1, 1, "張三改", "12345678", "99999999")
        assert len(store.contacts) == 2  # 数量不变
        assert store.contacts[0].name == "張三改"

    def test_delete_contact(self):
        """删除联系人同时删除自动分享状态。"""
        store = self._store_with_contacts()
        store.delete(1, 1)
        assert len(store.contacts) == 1
        assert store.contacts[0].name == "李四"

    def test_share_contact(self):
        """设置自动分享开关。"""
        store = self._store_with_contacts()
        store.share(1, 1, auto_share=1)
        assert store.contacts[0].auto_share == 1

    def test_enable_auto_share_for_all(self):
        """开启全部联系人自动分享。"""
        store = self._store_with_contacts()
        store.enable_auto_share_for_all()
        assert all(c.auto_share == 1 for c in store.contacts)

    def test_disable_auto_share_for_all(self):
        """关闭全部联系人自动分享。"""
        store = self._store_with_contacts()
        store.disable_auto_share_for_all()
        assert all(c.auto_share == 0 for c in store.contacts)

    def test_auto_share_enabled_check(self):
        """存在任一 auto_share=1 即表示开启。"""
        store = self._store_with_contacts()
        assert store.auto_share_enabled() is True
        store.disable_auto_share_for_all()
        assert store.auto_share_enabled() is False

    def test_alarm_recipients_all_contacts(self):
        """报警接收人包含全部联系人。"""
        store = self._store_with_contacts()
        recipients = store.alarm_recipients()
        assert len(recipients) == 2

    def test_trip_share_only_auto_share(self):
        """行程分享接收人仅含 auto_share=1 的联系人。"""
        store = self._store_with_contacts()
        recipients = store.trip_share_recipients()
        assert len(recipients) == 1
        assert recipients[0] == "87654321"

    def test_delete_not_found_raises(self):
        """删除不存在的联系人报错。"""
        store = ContactStore()
        with pytest.raises(ValueError, match="contact_not_found"):
            store.delete(1, 99)

    def test_delete_other_user_contact_raises(self):
        """删除不属于自己的联系人报错。"""
        store = self._store_with_contacts()
        with pytest.raises(ValueError, match="contact_not_found"):
            store.delete(2, 1)  # user_id=2 不是 owner

    def test_enable_auto_share_empty_raises(self):
        """无联系人时开启自动分享报错。"""
        store = ContactStore()
        with pytest.raises(ValueError, match="請添加緊急聯絡人"):
            store.enable_auto_share_for_all()


class TestMaskContactPhone:
    """联系人手机号掩码。"""

    def test_mask_shows_last_4(self):
        """掩码显示后4位。"""
        assert mask_contact_phone("12345678") == "****5678"

    def test_mask_long_phone(self):
        assert mask_contact_phone("13800138000") == "****8000"


# ==================== §7.5 邮箱 ====================

class TestEmailNormalization:
    """邮箱格式校验与归一化。"""

    def test_valid_email_passes(self):
        """合法邮箱通过。"""
        assert normalize_email("test@example.com") == "test@example.com"

    def test_empty_email_returns_empty(self):
        """空字符串返回空（表示删除）。"""
        assert normalize_email("") == ""
        assert normalize_email(None) == ""

    def test_no_at_rejected(self):
        """缺少@被拒绝。"""
        with pytest.raises(ValueError, match="郵箱格式不正確"):
            normalize_email("testexample.com")

    def test_multiple_at_rejected(self):
        """多个@被拒绝。"""
        with pytest.raises(ValueError, match="郵箱格式不正確"):
            normalize_email("test@@example.com")

    def test_no_dot_in_domain_rejected(self):
        """域名无点被拒绝。"""
        with pytest.raises(ValueError, match="郵箱格式不正確"):
            normalize_email("test@example")

    def test_whitespace_trimmed(self):
        """首尾空白被去除。"""
        assert normalize_email("  test@example.com  ") == "test@example.com"

    def test_domain_leading_dot_rejected(self):
        """域名以点开头被拒绝。"""
        with pytest.raises(ValueError, match="郵箱格式不正確"):
            normalize_email("test@.example.com")

    def test_consecutive_dots_rejected(self):
        """域名连续点被拒绝。"""
        with pytest.raises(ValueError, match="郵箱格式不正確"):
            normalize_email("test@example..com")


class TestSaveEmail:
    """邮箱保存：缺失不修改、空白删除、非空保存。"""

    def test_missing_field_unchanged(self):
        """字段缺失不修改邮箱。"""
        current, action = save_email("old@example.com")
        assert current == "old@example.com"
        assert action == "unchanged"

    def test_null_field_unchanged(self):
        """JSON null 不修改邮箱。"""
        current, action = save_email("old@example.com", None)
        assert action == "unchanged"

    def test_empty_string_deletes(self):
        """空字符串删除邮箱。"""
        current, action = save_email("old@example.com", "")
        assert current == ""
        assert action == "deleted"

    def test_valid_email_saved(self):
        """合法邮箱保存。"""
        current, action = save_email("old@example.com", "new@example.com")
        assert current == "new@example.com"
        assert action == "saved"

    def test_whitespace_only_deletes(self):
        """纯空白删除邮箱。"""
        current, action = save_email("old@example.com", "   ")
        assert action == "deleted"


class TestEmailFromStorage:
    """从存储值解析邮箱。"""

    def test_null_returns_empty(self):
        """数据库 NULL 映射为空字符串。"""
        assert email_from_storage(None) == ""

    def test_value_returned(self):
        """有值时原样返回。"""
        assert email_from_storage("test@example.com") == "test@example.com"
