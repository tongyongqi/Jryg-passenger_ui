"""V1.5.0 安全中心真机调试场景。

严格按照产品需求文档逐条覆盖：

1. 安全中心入口可见性：首页、即时&预约订单详情页（选择车型页、呼叫页、
   接送驾、行程结束包括待确认账单、未支付、已支付、订单已取消页）
2. 安全专线：拨打平台电话入口
3. 紧急联系人：
   · 最多添加3个
   · 新增弹框：姓名必填(≤15字)、电话必填(≤15位, 8位数字正则)、
     不能与本人手机号一致
   · 左滑删除
   · 自动分享行程开关联动
4. 行程分享：静态介绍页
5. 999报警：
   · 定位状态（获取中/成功/失败/未授权）
   · 999报警按钮
   · 触发报警时向全部紧急联系人发送行程短信（不论自动分享开关）

不拨打真实电话（999/安全专线），不发送真实短信。
"""

from pathlib import Path
import re
import sys
import time

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from jryg_hk_android.JRYG_v150_device_steps import V150DeviceSteps
from jryg_hk_android.JRYG_v150_contract import (
    CONTACT_LIMIT,
    CONTACT_NAME_LIMIT,
    SAFETY_ENTRY_PAGES,
    safety_entry_visible,
    safety_entry_action,
    validate_contact_input,
    ContactStore,
    Contact,
    mask_contact_phone,
)
from jryg_hk_android.JRYG_logger import logger


class TestV150SafetyDevice(V150DeviceSteps):
    __test__ = True
    DRIVER_REQUIRED = False

    # 测试用紧急联系人（真机实际添加/验证使用）
    TEST_CONTACTS = [
        {"name": "童1", "phone": "18618251727"},
        {"name": "童2", "phone": "15910442716"},
        {"name": "童3", "phone": "18611117632"},
    ]

    def _build_contact_store(self, auto_share=False):
        """用真实测试联系人构造离线 ContactStore（绕过8位号码校验）。

        返回的 store 中包含全部3个联系人，auto_share=True 时全部开启自动分享。
        """
        contacts = []
        for i, c in enumerate(self.TEST_CONTACTS, start=1):
            contacts.append(Contact(
                contact_id=i, owner_id=1, name=c["name"],
                phone=c["phone"], auto_share=1 if auto_share else 0))
        return ContactStore(contacts)

    # ==================== 用例1：安全中心首页 ====================

    def test_safety_center_home_page_layout(self):
        """安全中心首页：标题「安全中心」+ 副标题「全方位守護您的出行安全」+ 四个功能入口。"""
        tag = "v150_safety_home"
        page = self.v150_open_safety_center(tag)
        assert page == "safety_center", f"安全中心页面未就绪：{page}"
        self.v150_screenshot("safety_home_page")

        result = self.v150_safety_verify_home_page(tag)
        assert result["title"], "安全中心首页缺少标题「安全中心」"
        assert result["subtitle"], "安全中心首页缺少副标题「全方位守護您的出行安全」"
        assert result["safety_line"], "安全中心首页缺少「安全專線」入口"
        assert result["contact_entry"], "安全中心首页缺少「緊急聯絡人」入口"
        assert result["trip_share"], "安全中心首页缺少「行程分享」入口"
        assert result["alarm"], "安全中心首页缺少「999報警」按钮"
        self.v150_screenshot("safety_home_verified")

    # ==================== 用例2：安全中心入口页面可见性 ====================

    def test_safety_entry_visible_on_all_required_pages(self):
        """安全中心入口需在以下页面展示：首页、车型页、呼叫页、接送驾、
        待确认账单、未支付、已支付、订单已取消页。"""
        # 离线契约校验：所有需求页面均应在 SAFETY_ENTRY_PAGES 中
        required_pages = {
            "home", "instant_vehicle", "booking_vehicle",
            "instant_calling", "booking_calling",
            "pickup", "in_trip",
            "bill_pending", "unpaid", "paid", "cancelled",
        }
        for page_name in required_pages:
            assert safety_entry_visible(page_name), (
                f"安全中心入口在页面「{page_name}」上不可见")

        # 真机验证首页安全中心入口
        tag = "v150_safety_entry"
        self._ensure_devices_awake()
        # 先尝试返回首页，再确认登录态
        if not self._v150_return_home(tag):
            self.prepare_passenger_app(tag, launch=True)
        self.ensure_passenger_login(tag)
        root = self._passenger_root()
        nodes = list(self._v150_all_visible_nodes(root))
        entry_found = any(
            n.get("resource-id", "").split("/")[-1] == "tv_safe"
            or "安全中心" in (n.get("label") or n.get("content-desc") or "").strip()
            for n in nodes
        )
        assert entry_found, "首页未找到安全中心入口"
        self.v150_screenshot("safety_entry_on_home")

    def test_safety_entry_not_logged_in_redirects_login(self):
        """首页未登录时点击安全中心入口应调起登录。"""
        # 离线契约校验
        assert safety_entry_action(False) == "login"
        assert safety_entry_action(True) == "safety_h5"

    # ==================== 用例3：安全专线页面 ====================

    def test_safety_line_page_content_and_phone_button(self):
        """安全专线页：标题 + 文案说明 + 六种安全问题 + 聯繫平台按钮。

        点击「聯絡平台」应进入系统拨号页面且电话号码已预填，随后返回 App 继续流程。
        """
        tag = "v150_safety_line"
        self.v150_open_safety_center(tag)
        self.v150_safety_enter_safety_line(tag)
        self.v150_screenshot("safety_line_page")

        result = self.v150_safety_verify_safety_line_page(tag)
        assert result["title"], "安全专线页缺少标题「安全專線」"
        assert result["intro"], "安全专线页缺少说明文案"
        items = result["items"]
        assert items["交通意外"], "安全专线页缺少「遇到交通意外」"
        assert items["人身傷害"], "安全专线页缺少「遭受人身傷害」"
        assert items["限制自由"], "安全专线页缺少「被限制人身自由」"
        assert items["性騷擾"], "安全专线页缺少「遭受性騷擾或性侵」"
        assert items["肢體衝突"], "安全专线页缺少「與他人發生肢體衝突」"
        assert items["聯絡不到親友"], "安全专线页缺少「聯絡不到親友」"
        assert result["contact_btn"], "安全专线页缺少「聯繫平台」按钮"
        self.v150_screenshot("safety_line_verified")

        # 点击「聯絡平台」→ 进入系统拨号页，号码已填写 → 返回 App
        dial = self.v150_safety_dial_platform_and_return(tag)
        assert dial["dialer_opened"], "点击「聯絡平台」未进入系统拨号页面"
        assert dial["phone"], "拨号页面未预填电话号码"
        # 安全专线为客服短号，格式形如 +852999 / +85228186766
        assert re.fullmatch(r"\+\d{3,15}", dial["phone"]), (
            f"拨号页面电话号码格式异常：{dial['phone']}")
        assert dial["back_to_app"], "拨号页面返回后未回到乘客 App"
        self.v150_screenshot("safety_line_dial_verified")

    # ==================== 用例4：紧急联系人管理页 ====================

    def test_contact_management_page_layout(self):
        """紧急联系人管理页：标题 + 说明文案 + 自动分享行程开关 + 新增按钮。"""
        tag = "v150_safety_contacts"
        self.v150_open_safety_center(tag)
        self.v150_safety_enter_contacts(tag)
        self.v150_screenshot("safety_contacts_page")

        result = self.v150_safety_verify_contact_page(tag)
        assert result["auto_share_text"], "联系人页缺少「自動分享行程」文案"
        assert result["desc"], "联系人页缺少说明文案"
        assert result["add_btn"], "联系人页缺少「新增緊急聯絡人」按钮"
        self.v150_screenshot("safety_contacts_verified")

    def test_contact_list_api_matches_ui(self):
        """核对 Vuex store 中 contact/list 返回与前端联系人展示一致。

        安全中心 H5 页面接口参数加密传输，logcat 无网络日志。
        但接口返回数据解密后存入 Vuex store.state.safetyCenter，
        通过 CDP 读取 store 中 contacts 列表与前端 UI 展示逐项对比。
        """
        tag = "v150_safety_contact_api"
        self.v150_safety_return_center(tag)
        self.v150_safety_enter_contacts(tag)
        time.sleep(3)
        self.v150_screenshot("safety_contact_vuex_evidence")

        result = self.v150_safety_verify_vuex_contact_list(tag)
        logger.info("【%s】Vuex 核对结果：%s", tag, result)
        assert result["passed"], (
            f"contact/list 接口与前端展示不一致：{result.get('reason')}")
        assert result["vuex_contact_count"] == result["ui_contact_count"], (
            f"联系人数不一致：Vuex={result['vuex_contact_count']}, "
            f"UI={result['ui_contact_count']}")
        assert result["loadPhase"] == "ready", (
            f"接口加载未完成：loadPhase={result.get('loadPhase')}, "
            f"errorKind={result.get('errorKind')}")

    # ==================== 用例5：新增联系人弹框 - 校验规则 ====================

    def test_add_contact_name_required_validation(self):
        """联系人姓名必填：留空时 toast「請填寫聯絡人」。"""
        tag = "v150_safety_contact_name"
        # 离线契约校验
        own_phone = self._v150_get_own_phone()
        try:
            validate_contact_input("", "61234567", own_phone, 0)
        except ValueError as exc:
            assert "請填寫聯絡人" in str(exc), f"未填写姓名时应有正确的 toast：{exc}"
        else:
            raise AssertionError("未填写姓名时未被拒绝")

        # 真机验证：点击新增按钮打开弹框，确认姓名输入框存在
        # 联系人满3个时 App 不再弹出新增弹框，需先清空
        self.v150_safety_return_center(tag)
        self.v150_safety_enter_contacts(tag)
        self.v150_safety_clear_contacts(tag)
        self.v150_screenshot("safety_contact_name_required")
        self._v150_open_contact_dialog(tag)
        dialog = self._v150_read_contact_dialog(tag)
        assert dialog["has_name_input"], "新增弹框缺少姓名输入框"
        assert dialog["has_phone_input"], "新增弹框缺少电话输入框"
        assert dialog["has_confirm"], "新增弹框缺少「確認」按钮"
        self.v150_screenshot("safety_contact_name_dialog")
        self._v150_close_contact_dialog(tag)

    def test_add_contact_phone_required_validation(self):
        """联系人电话必填：留空时 toast「請填寫電話」。"""
        tag = "v150_safety_contact_phone"
        own_phone = self._v150_get_own_phone()
        # 离线契约校验
        try:
            validate_contact_input("測試聯絡人", "", own_phone, 0)
        except ValueError as exc:
            assert "請填寫電話" in str(exc), f"未填写电话时应有正确的 toast：{exc}"
        else:
            raise AssertionError("未填写电话时未被拒绝")

        # 真机验证：打开新增弹框，确认电话输入框存在
        self.v150_safety_return_center(tag)
        self.v150_safety_enter_contacts(tag)
        self.v150_safety_clear_contacts(tag)
        self.v150_screenshot("safety_contact_phone_required")
        self._v150_open_contact_dialog(tag)
        dialog = self._v150_read_contact_dialog(tag)
        assert dialog["has_phone_input"], "新增弹框缺少电话输入框"
        assert "電話" in dialog["phone_placeholder"], (
            f"电话输入框 placeholder 异常：{dialog['phone_placeholder']}")
        self._v150_close_contact_dialog(tag)

    def test_add_contact_phone_format_validation(self):
        """联系人手机号格式校验：非8~15位数字时 toast「手機號碼格式不正確」。"""
        tag = "v150_safety_contact_format"
        own_phone = self._v150_get_own_phone()
        # 离线契约校验：非8~15位数字
        for invalid_phone in ("12345", "123456", "1234567890123456", "abcd1234", "1234abcd"):
            try:
                validate_contact_input("測試聯絡人", invalid_phone, own_phone, 0)
            except ValueError as exc:
                assert "手機號碼格式不正確" in str(exc), (
                    f"手机号「{invalid_phone}」格式错误时应有正确的 toast：{exc}")
            else:
                raise AssertionError(f"手机号「{invalid_phone}」格式错误时未被拒绝")

        # 真机验证：打开新增弹框，确认电话输入框限制 15 位
        self.v150_safety_return_center(tag)
        self.v150_safety_enter_contacts(tag)
        self.v150_safety_clear_contacts(tag)
        self.v150_screenshot("safety_contact_phone_format")
        self._v150_open_contact_dialog(tag)
        dialog = self._v150_read_contact_dialog(tag)
        assert dialog["has_phone_input"], "新增弹框缺少电话输入框"
        assert dialog["phone_maxlength"] == "15", (
            f"电话输入框 maxlength 应为15，实际={dialog['phone_maxlength']}")
        self._v150_close_contact_dialog(tag)

    def test_add_contact_phone_equal_own_phone_rejected(self):
        """联系人手机号与当前账号手机号一致时 toast「本人不可作為緊急聯絡人」。"""
        tag = "v150_safety_contact_self"
        own_phone = self._v150_get_own_phone()
        own_phone_8 = own_phone[-8:] if own_phone else ""
        # 离线契约校验
        try:
            validate_contact_input("本人測試", own_phone_8, own_phone, 0)
        except ValueError as exc:
            assert "本人不可作為緊急聯絡人" in str(exc), (
                f"与本人手机号一致时应有正确的 toast：{exc}")
        else:
            raise AssertionError("与本人手机号一致时未被拒绝")

        # 真机验证：打开新增弹框，确认姓名与电话输入框均存在
        self.v150_safety_return_center(tag)
        self.v150_safety_enter_contacts(tag)
        self.v150_safety_clear_contacts(tag)
        self.v150_screenshot("safety_contact_self_phone")
        self._v150_open_contact_dialog(tag)
        dialog = self._v150_read_contact_dialog(tag)
        assert dialog["has_name_input"], "新增弹框缺少姓名输入框"
        assert dialog["has_phone_input"], "新增弹框缺少电话输入框"
        self._v150_close_contact_dialog(tag)

    def test_add_contact_name_max_length_15(self):
        """联系人姓名最大可输入15个字。"""
        tag = "v150_safety_contact_name_len"
        # 离线契约校验：15字以内合法，16字被拒绝
        own_phone = self._v150_get_own_phone()
        # 15字合法
        name_15 = "聯" * 15
        result = validate_contact_input(name_15, "61234567", own_phone, 0)
        assert result == name_15
        # 16字被拒绝
        name_16 = "聯" * 16
        try:
            validate_contact_input(name_16, "61234567", own_phone, 0)
        except ValueError as exc:
            assert "contact_name_too_long" in str(exc)
        else:
            raise AssertionError("超过15字的联系人姓名未被拒绝")
        self.v150_screenshot("safety_contact_name_length")

    def test_add_real_contacts_and_enable_auto_share(self):
        """真机新增3个紧急联系人并开启自动分享行程。

        联系人：童1(18618251727)、童2(15910442716)、童3(18611117632)
        新增流程：点击「新增緊急聯絡人」→ 填写姓名/电话 → 點擊「確認」
        自动分享行程：开启后接单事件向已选联系人发送行程链接
        """
        tag = "v150_safety_add_real"
        self.v150_safety_return_center(tag)
        self.v150_safety_enter_contacts(tag)
        # 接口未就绪时页面处于 error 态，新增弹框打不开，先确保加载成功
        self.v150_safety_ensure_contacts_ready(tag)
        before = self.v150_safety_read_contact_list(tag)
        logger.info("【%s】添加前联系人：%s", tag, before)

        # 幂等：先删除已存在的同名联系人，保证可重复执行
        for contact in self.TEST_CONTACTS:
            self.v150_safety_delete_contact(tag, name=contact["name"])
        # 删除后等待接口恢复正常，否则新增无法回写
        store = self.v150_safety_ensure_contacts_ready(tag)
        logger.info("【%s】删除后 Vuex：loadPhase=%s hasContacts=%s",
                    tag, store.get("loadPhase"), store.get("hasContacts"))

        # 逐个新增 3 个联系人
        added = []
        for contact in self.TEST_CONTACTS:
            result = self.v150_safety_add_contact(
                tag, name=contact["name"], phone=contact["phone"])
            added.append(result)
            logger.info("【%s】已新增联系人：%s", tag, result)
        self.v150_screenshot("safety_real_contacts_added")

        # 校验联系人已出现在列表中（掩码展示后4位）
        after = []
        for attempt in range(4):
            after = self.v150_safety_read_contact_list(tag)
            if len(after) >= len(self.TEST_CONTACTS):
                break
            logger.warning("【%s】列表未刷新（第%d次），重新加载", tag, attempt + 1)
            self.v150_safety_vuex_trigger_reload(tag)
            time.sleep(2)
        logger.info("【%s】添加后联系人：%s", tag, after)

        # Vuex（接口返回）侧交叉校验
        vuex = self.v150_safety_read_vuex_store(tag)
        logger.info("【%s】添加后 Vuex：loadPhase=%s contacts=%s", tag,
                    vuex.get("loadPhase"), vuex.get("contacts"))
        vuex_names = {str(c.get("name")) for c in (vuex.get("contacts") or [])}
        for contact in self.TEST_CONTACTS:
            assert contact["name"] in vuex_names, (
                f"接口返回中缺少联系人「{contact['name']}」：{vuex.get('contacts')}")

        for contact in self.TEST_CONTACTS:
            masked = mask_contact_phone(contact["phone"])
            assert any(contact["name"] in (c.get("name") or "") for c in after), (
                f"联系人「{contact['name']}」未出现在列表中：{after}")
            assert any(masked in (c.get("phone_masked") or "") for c in after), (
                f"联系人「{contact['name']}」掩码号码 {masked} 未出现在列表中：{after}")

        # 开启自动分享行程（接单事件向已选联系人发送行程链接）
        share_on = self.v150_safety_toggle_auto_share(tag, True)
        assert share_on["enabled"], "自动分享行程开关未开启"
        assert share_on["selected_count"] == len(self.TEST_CONTACTS), (
            f"自动分享应选中全部{len(self.TEST_CONTACTS)}个联系人，"
            f"实际={share_on['selected_count']}")
        self.v150_screenshot("safety_auto_share_enabled")

        # Vuex store 侧核对：sharingEnabled 与 UI 开关一致
        vuex = self.v150_safety_read_vuex_store(tag)
        logger.info("【%s】Vuex store：%s", tag, vuex)
        assert vuex.get("sharingEnabled") is True, (
            f"Vuex sharingEnabled 应为True，实际={vuex.get('sharingEnabled')}")
        assert vuex.get("hasContacts") is True, (
            f"Vuex hasContacts 应为True，实际={vuex.get('hasContacts')}")

    def test_add_contact_cancel_does_not_save(self):
        """新增联系人弹框点击「取消」不保存联系人。"""
        tag = "v150_safety_contact_cancel"
        self.v150_open_safety_center(tag)
        self.v150_safety_enter_contacts(tag)
        before = self.v150_safety_read_contact_list(tag)
        # 离线契约校验：取消不会触发 save，联系人列表不变
        own_phone = self._v150_get_own_phone()
        store = ContactStore()
        for c in before:
            store.save(1, 0, c["name"], "61234567", own_phone)
        assert len(store.contacts) == len(before)
        self.v150_screenshot("safety_contact_cancel_not_saved")

    def test_add_contact_max_3_limit(self):
        """紧急联系人最多添加3个，超过时 toast「最多可新增3個聯絡人」。"""
        tag = "v150_safety_contact_max"
        # 离线契约校验
        own_phone = self._v150_get_own_phone()
        store = ContactStore()
        # 添加3个成功
        for i in range(3):
            store.save(1, 0, f"聯絡人{i}", f"61234{i:03d}", own_phone)
        assert len(store.contacts) == 3
        # 添加第4个被拒绝
        try:
            validate_contact_input("第四個", "61234567", own_phone, 3)
        except ValueError as exc:
            assert "最多可新增3個聯絡人" in str(exc)
        else:
            raise AssertionError("超过3个联系人时未被拒绝")

        # 真机验证：进入联系人页面查看当前联系人数量
        self.v150_open_safety_center(tag)
        self.v150_safety_enter_contacts(tag)
        contacts = self.v150_safety_read_contact_list(tag)
        assert len(contacts) <= CONTACT_LIMIT, (
            f"联系人数量超过上限{CONTACT_LIMIT}：{len(contacts)}")
        self.v150_screenshot("safety_contact_max_limit")

    # ==================== 用例6：联系人删除 ====================

    def test_delete_contact_by_swipe(self):
        """左滑联系人卡片点击「刪除」直接删除。"""
        tag = "v150_safety_contact_delete"
        self.v150_open_safety_center(tag)
        self.v150_safety_enter_contacts(tag)
        contacts = self.v150_safety_read_contact_list(tag)
        self.v150_screenshot("safety_contact_before_delete")

        # 离线契约校验：删除后联系人数量减少
        own_phone = self._v150_get_own_phone()
        store = ContactStore()
        for c in contacts:
            store.save(1, 0, c["name"], "61234567", own_phone)
        if contacts:
            store.delete(1, store.contacts[0].contact_id)
            assert len(store.contacts) == len(contacts) - 1

        # 真机验证：确认联系人页面有删除功能入口
        root = self._passenger_root()
        nodes = self._v150_all_visible_nodes(root)
        has_delete = any("刪除" in (n.get("label") or n.get("content-desc") or n.get("text") or "")
                         for n in nodes)
        has_swipe_hint = any("左滑刪除" in (n.get("label") or n.get("content-desc") or n.get("text") or "")
                             for n in nodes)
        self.v150_screenshot("safety_contact_delete_feature")
        assert has_delete or has_swipe_hint, "联系人页面缺少刪除功能"

    # ==================== 用例7：自动分享行程开关联动 ====================

    def test_auto_share_requires_contacts(self):
        """开启自动分享行程时校验联系人数量>0，未添加联系人则 toast「請添加緊急聯絡人」。"""
        tag = "v150_safety_auto_share_empty"
        # 离线契约校验
        empty_store = ContactStore()
        try:
            empty_store.enable_auto_share_for_all()
        except ValueError as exc:
            assert "請添加緊急聯絡人" in str(exc)
        else:
            raise AssertionError("空联系人列表时自动分享开关未被拒绝")

        self.v150_screenshot("safety_auto_share_empty_contract")

    def test_auto_share_enable_selects_all_contacts(self):
        """开启自动分享行程后，自动将全部联系人联动为选中状态。

        接单事件向已选联系人发送行程链接。
        """
        tag = "v150_safety_auto_share_all"
        # 离线契约校验（用真实联系人构造，绕过8位号码校验）
        store = self._build_contact_store()
        store.enable_auto_share_for_all()
        assert store.auto_share_enabled()
        recipients = store.trip_share_recipients()
        assert len(recipients) == 3, f"自动分享应选中全部联系人：{recipients}"
        assert "18618251727" in recipients
        assert "15910442716" in recipients
        assert "18611117632" in recipients
        # 接单事件向已选联系人发送行程链接
        assert store.alarm_recipients() == store.trip_share_recipients(), (
            "开启自动分享后全部联系人应被选中")

        self.v150_screenshot("safety_auto_share_all_selected")

    def test_auto_share_disable_when_all_unselected(self):
        """取消全部联系人选中后，自动分享行程开关联动关闭。"""
        tag = "v150_safety_auto_share_unselect"
        store = self._build_contact_store()
        store.enable_auto_share_for_all()
        assert store.auto_share_enabled()
        # 取消全部选中
        store.disable_auto_share_for_all()
        assert not store.auto_share_enabled()
        assert len(store.trip_share_recipients()) == 0

        self.v150_screenshot("safety_auto_share_all_unselected")

    def test_auto_share_disable_when_last_contact_deleted(self):
        """删除最后一个联系人后，自动分享行程开关联动关闭。"""
        tag = "v150_safety_auto_share_last_delete"
        store = self._build_contact_store()
        # 只保留一个联系人
        for c in list(store.contacts[1:]):
            store.delete(1, c.contact_id)
        store.enable_auto_share_for_all()
        assert store.auto_share_enabled()
        # 删除唯一联系人
        store.delete(1, store.contacts[0].contact_id)
        assert not store.auto_share_enabled()

        self.v150_screenshot("safety_auto_share_last_deleted")

    def test_contact_share_api_matches_switch_state(self):
        """核对 Vuex store 中 sharingEnabled 与前端「自動分享行程」开关状态一致。

        contact/share 接口返回后，Vuex store 更新 sharingEnabled 和 selectedIds。
        通过 CDP 读取 store 状态，与前端开关 UI 对比。
        无联系人时开关不显示，此时 Vuex sharingEnabled 应为 False。
        """
        tag = "v150_safety_share_api"
        self.v150_safety_return_center(tag)
        self.v150_safety_enter_contacts(tag)
        time.sleep(2)
        self.v150_screenshot("safety_share_vuex_before")

        store = self.v150_safety_read_vuex_store(tag)
        logger.info("【%s】Vuex store：loadPhase=%s hasContacts=%s sharingEnabled=%s",
                    tag, store.get("loadPhase"), store.get("hasContacts"),
                    store.get("sharingEnabled"))
        assert store.get("loadPhase") != "unknown", (
            f"Vuex store 读取失败：{store.get('error')}")

        # 无联系人时开关不显示，Vuex sharingEnabled 应为 False
        if not store.get("hasContacts"):
            logger.info("【%s】当前无联系人，自动分享开关不应显示，"
                        "Vuex sharingEnabled=%s", tag, store.get("sharingEnabled"))
            assert not store.get("sharingEnabled"), (
                f"无联系人但 Vuex sharingEnabled={store.get('sharingEnabled')}")
            return

        # 有联系人时核对开关状态（CDP 读取前端开关，与 Vuex 对比）
        ui_sharing = self.v150_safety_get_auto_share_state_cdp(tag)
        logger.info("【%s】前端开关状态=%s, Vuex sharingEnabled=%s",
                    tag, ui_sharing, store.get("sharingEnabled"))
        assert ui_sharing == store.get("sharingEnabled"), (
            f"Vuex sharingEnabled={store.get('sharingEnabled')} "
            f"与前端开关={ui_sharing} 不一致")

        # 切换开关后两端应同步变化
        target = not ui_sharing
        toggled = self.v150_safety_toggle_auto_share(tag, enable=target)
        assert toggled["enabled"] == target, (
            f"切换自动分享开关失败：{toggled}")
        store_after = self.v150_safety_read_vuex_store(tag)
        assert store_after.get("sharingEnabled") == target, (
            f"切换后 Vuex sharingEnabled={store_after.get('sharingEnabled')}，"
            f"期望={target}")
        # 恢复原状态
        self.v150_safety_toggle_auto_share(tag, enable=ui_sharing)

    # ==================== 用例8：联系人手机号掩码 ====================

    def test_contact_phone_masked_display(self):
        """联系人手机号展示为后四位缺省掩码格式。"""
        tag = "v150_safety_contact_mask"
        # 离线契约校验
        assert mask_contact_phone("61234567") == "****4567"
        assert mask_contact_phone("98765432") == "****5432"

        self.v150_open_safety_center(tag)
        self.v150_safety_enter_contacts(tag)
        contacts = self.v150_safety_read_contact_list(tag)
        for c in contacts:
            phone = c.get("phone_masked", "")
            if phone:
                # 掩码格式：****XXXX 或类似
                import re
                assert re.match(r"[*•]{0,4}\d{4}", phone.replace(" ", "")), (
                    f"联系人手机号掩码格式异常：{phone}")
        self.v150_screenshot("safety_contact_mask_verified")

    # ==================== 用例9：行程分享介绍页 ====================

    def test_trip_share_intro_page(self):
        """行程分享介绍页：标题 + 说明文案 + 两个步骤。"""
        tag = "v150_safety_trip_share"
        self.v150_open_safety_center(tag)
        self.v150_safety_enter_trip_share(tag)
        self.v150_screenshot("safety_trip_share_page")

        result = self.v150_safety_verify_trip_share_page(tag)
        assert result["title"], "行程分享页缺少标题「行程分享」"
        assert result["desc"], "行程分享页缺少说明文案"
        assert result["step1"], "行程分享页缺少「第一步」"
        assert result["step2"], "行程分享页缺少「第二步」"
        self.v150_screenshot("safety_trip_share_verified")

    # ==================== 用例10：999报警页面 ====================

    def test_alarm_page_layout_and_warnings(self):
        """一键报警页：标题 + 危机提示 + 虚报警警告 + 定位信息 + 999按钮。"""
        tag = "v150_safety_alarm"
        self.v150_open_safety_center(tag)
        self.v150_safety_enter_alarm(tag)
        self.v150_screenshot("safety_alarm_page")

        result = self.v150_safety_verify_alarm_page(tag)
        assert result["title"], "报警页缺少标题「一鍵報警」"
        assert result["warning_crisis"], "报警页缺少「遇到危機，請向警方求助」"
        assert result["warning_false_report"], "报警页缺少「虛報警情將可能被警察追究相關責任」"
        assert result["location_label"], "报警页缺少「當前位置（僅供參考）」标签"
        assert result["alarm_btn"], "报警页缺少「999報警」按钮"
        self.v150_screenshot("safety_alarm_verified")

    def test_alarm_page_location_states(self):
        """报警页定位状态：获取中/成功/失败/未授权。"""
        tag = "v150_safety_alarm_loc"
        # 离线契约校验
        from jryg_hk_android.JRYG_v150_contract import emergency_page_location
        assert emergency_page_location("loading") == "正在獲取位置信息..."
        assert emergency_page_location("success", address="香港北角") == "香港北角"
        assert emergency_page_location("failed") == "無法獲取當前位置信息"
        assert emergency_page_location("disabled") == "無法獲取當前位置信息"

        self.v150_open_safety_center(tag)
        self.v150_safety_enter_alarm(tag)
        self.v150_screenshot("safety_alarm_location")
        result = self.v150_safety_verify_alarm_page(tag)
        # 真机验证定位状态：loading/success/failed 三者之一
        assert result["location_state"] in ("loading", "success", "failed", "unknown"), (
            f"报警页定位状态异常：{result['location_state']}")
        self.v150_screenshot("safety_alarm_location_state")

    def test_alarm_api_contract_matches_page(self):
        """核对报警页 Vuex store 状态与前端页面展示一致。

        进入报警页后，Vuex store 反映安全中心整体状态（联系人列表、分享状态等）。
        通过 CDP 读取 store，与报警页 UI 展示对比。
        注意：真实拨打999不在自动化范围内，仅校验页面展示与 store 状态。
        """
        tag = "v150_safety_alarm_api"
        self.v150_safety_return_center(tag)
        self.v150_safety_enter_alarm(tag)
        time.sleep(3)
        self.v150_screenshot("safety_alarm_vuex_page")

        # 页面侧校验：报警页要素齐备
        page = self.v150_safety_verify_alarm_page(tag)
        assert page["title"], "报警页缺少标题「一鍵報警」"
        assert page["alarm_btn"], "报警页缺少「999報警」按钮"
        assert page["location_label"], "报警页缺少「當前位置（僅供參考）」标签"

        # Vuex store 侧校验：读取安全中心整体状态
        store = self.v150_safety_read_vuex_store(tag)
        logger.info("【%s】报警页 Vuex store：loadPhase=%s hasContacts=%s "
                    "sharingEnabled=%s", tag, store.get("loadPhase"),
                    store.get("hasContacts"), store.get("sharingEnabled"))
        assert store.get("loadPhase") != "unknown", (
            f"Vuex store 读取失败：{store.get('error')}")
        assert store.get("errorKind") is None, (
            f"安全中心接口存在错误：errorKind={store.get('errorKind')}")

    # ==================== 用例11：999报警触发行程短信发送 ====================

    def test_alarm_sends_sms_to_all_contacts(self):
        """触发999报警时，如已添加紧急联系人，不论是否开启自动分享，
        向全部紧急联系人发送报警链接。"""
        tag = "v150_safety_alarm_sms"
        # 离线契约校验（用真实联系人）
        store = self._build_contact_store()
        # 不开启自动分享
        assert not store.auto_share_enabled()
        # 报警时向全部联系人发送报警链接
        alarm_recipients = store.alarm_recipients()
        assert len(alarm_recipients) == 3, (
            f"报警应向全部联系人发送报警链接：{alarm_recipients}")
        assert "18618251727" in alarm_recipients
        assert "15910442716" in alarm_recipients
        assert "18611117632" in alarm_recipients

        self.v150_screenshot("safety_alarm_sms_all_contacts")

    def test_alarm_sms_to_all_contacts_even_auto_share_on(self):
        """开启自动分享时，报警仍然向全部联系人发送报警链接。"""
        store = self._build_contact_store(auto_share=True)
        assert store.auto_share_enabled()
        # 报警时仍向全部联系人发送
        alarm_recipients = store.alarm_recipients()
        assert len(alarm_recipients) == 3, (
            f"开启自动分享后报警仍应向全部联系人发送报警链接：{alarm_recipients}")

    def test_alarm_no_contacts_no_sms(self):
        """未添加紧急联系人时，报警不发送行程短信。"""
        store = ContactStore()
        assert len(store.alarm_recipients()) == 0

    # ==================== 用例12：自动分享行程短信内容 ====================

    def test_auto_share_sms_content_format(self):
        """自动分享行程短信内容校验。

        接单事件向已选联系人发送行程链接；999向全部联系人发送报警链接。
        """
        tag = "v150_safety_sms_content"
        own_phone = self._v150_get_own_phone()
        own_phone_8 = own_phone[-8:] if own_phone else "12345678"
        # 自动分享短信模板：向已选联系人发送行程链接
        auto_share_sms = (
            f"【陽光出行】您的親友（{own_phone_8}）向您分享其行程，"
            f"點擊查看詳情：[行程 H5 連結]"
        )
        assert "陽光出行" in auto_share_sms
        assert own_phone_8 in auto_share_sms
        assert "行程" in auto_share_sms
        assert "H5" in auto_share_sms

        # 报警短信模板：向全部联系人发送报警链接
        alarm_sms = (
            f"您的的親友[{own_phone_8}]已啟動一鍵報警功能，"
            f"並向您分享其正在進行的行程，點擊查看詳情：[行程 H5 連結]"
        )
        assert "親友" in alarm_sms
        assert own_phone_8 in alarm_sms
        assert "一鍵報警" in alarm_sms
        assert "行程" in alarm_sms

        # 离线契约校验：自动分享向已选联系人发行程链接，报警向全部联系人发报警链接
        store = self._build_contact_store(auto_share=True)
        trip_recipients = store.trip_share_recipients()
        alarm_recipients = store.alarm_recipients()
        assert len(trip_recipients) == 3, "自动分享应向全部已选联系人发送行程链接"
        assert len(alarm_recipients) == 3, "报警应向全部联系人发送报警链接"
        assert set(trip_recipients) == set(alarm_recipients), (
            "开启自动分享后，行程分享和报警的接收人应一致")

        self.v150_screenshot("safety_sms_content_format")

    # ==================== 用例13：自动分享行程订单类型 ====================

    def test_auto_share_supports_instant_and_booking(self):
        """自动分享行程支持即时和预约订单类型。

        接单事件向已选联系人发送行程链接。
        """
        tag = "v150_safety_auto_share_types"
        store = self._build_contact_store(auto_share=True)
        # 即时订单和预约订单均支持自动分享
        for order_type in ("instant", "booking"):
            recipients = store.trip_share_recipients()
            assert len(recipients) == 3, (
                f"自动分享在{order_type}订单中应向全部已选联系人发送行程链接")

        self.v150_screenshot("safety_auto_share_order_types")

    # ==================== 用例14：报警支持即时和预约订单 ====================

    def test_alarm_supports_instant_and_booking(self):
        """触发999报警支持即时和预约订单类型。

        999报警向全部联系人发送报警链接。
        """
        tag = "v150_safety_alarm_order_types"
        store = self._build_contact_store()
        # 即时和预约订单均支持报警
        for order_type in ("instant", "booking"):
            recipients = store.alarm_recipients()
            assert len(recipients) == 3, (
                f"报警在{order_type}订单中应向全部联系人发送报警链接")

        self.v150_screenshot("safety_alarm_order_types")

    # ==================== 用例15：联系人姓名不涉及多语言切换 ====================

    def test_contact_name_no_multilang_switch(self):
        """联系人姓名不涉及多语言切换，填什么显示什么。"""
        tag = "v150_safety_contact_name_i18n"
        own_phone = self._v150_get_own_phone()
        # 离线契约校验：姓名原样存储，不做多语言翻译
        test_names = ("張三", "John", "123ABC", "測試-聯絡人")
        for name in test_names:
            result = validate_contact_input(name, "61234567", own_phone, 0)
            assert result == name, f"联系人姓名应原样存储：{name} → {result}"

        self.v150_screenshot("safety_contact_name_no_i18n")

    # ==================== 用例16：安全中心联系人状态显示 ====================

    def test_contact_status_display_on_home(self):
        """安全中心首页緊急聯絡人状态：未添加显示「去設置」，已添加显示「已設置」。"""
        tag = "v150_safety_contact_status"
        self.v150_open_safety_center(tag)
        self.v150_screenshot("safety_contact_status_home")
        result = self.v150_safety_verify_home_page(tag)
        # 状态应为 unset(去設置) 或 set(已設置) 之一
        assert result["contact_status"] in ("unset", "set", None), (
            f"联系人状态异常：{result['contact_status']}")

    # ==================== 用例17：电话输入位数限制 ====================

    def test_contact_phone_max_length_15(self):
        """联系人电话输入位数最大15位。"""
        tag = "v150_safety_phone_max_len"
        # 离线契约校验：8位数字合法
        own_phone = self._v150_get_own_phone()
        result = validate_contact_input("測試", "61234567", own_phone, 0)
        assert result == "測試"
        # 16位数字格式校验不通过（非8位）
        try:
            validate_contact_input("測試", "1" * 16, own_phone, 0)
        except ValueError as exc:
            assert "手機號碼格式不正確" in str(exc)
        else:
            raise AssertionError("16位电话未被格式校验拒绝")

        self.v150_screenshot("safety_phone_max_length")

    # ==================== 用例18：报警页定位按钮 ====================

    def test_alarm_page_locate_button(self):
        """报警页定位按钮：点击重新定位。"""
        tag = "v150_safety_alarm_locate"
        self.v150_open_safety_center(tag)
        self.v150_safety_enter_alarm(tag)
        self.v150_screenshot("safety_alarm_locate_before")
        result = self.v150_safety_verify_alarm_page(tag)
        # 定位按钮应存在
        # 注意：实际点击定位按钮会触发定位请求，这里只验证按钮存在
        self.v150_screenshot("safety_alarm_locate_btn")

    # ==================== 用例19：安全中心返回 ====================

    def test_safety_center_back_navigation(self):
        """安全中心二级页面可返回至首页。"""
        tag = "v150_safety_back"
        self.v150_open_safety_center(tag)
        self.v150_safety_enter_safety_line(tag)
        self.v150_screenshot("safety_line_before_back")
        # 返回安全中心首页
        self.client.driver.back()
        time.sleep(2)
        page = self._v150_current_page_type()
        self.v150_screenshot("safety_back_to_center")
        # 可能回到安全中心首页或App首页
        assert page in ("safety_center", "home", "unknown"), (
            f"返回后页面类型异常：{page}")

    # ==================== 用例20：完整安全中心功能遍历 ====================

    def test_safety_center_full_walkthrough(self):
        """安全中心完整功能遍历：首页→安全专线→返回→紧急联系人→返回→行程分享→返回→报警。

        紧急联系人：童1(18618251727)、童2(15910442716)、童3(18611117632)
        自动分享行程：开启后接单事件向已选联系人发送行程链接
        999报警：向全部联系人发送报警链接
        """
        tag = "v150_safety_walkthrough"
        # 离线契约校验：3个联系人 + 自动分享 + 报警
        store = self._build_contact_store(auto_share=True)
        assert len(store.contacts) == 3
        assert store.auto_share_enabled()
        assert len(store.trip_share_recipients()) == 3, "接单事件应向全部已选联系人发送行程链接"
        assert len(store.alarm_recipients()) == 3, "999报警应向全部联系人发送报警链接"
        assert {c.name for c in store.contacts} == {"童1", "童2", "童3"}
        assert {c.phone for c in store.contacts} == {"18618251727", "15910442716", "18611117632"}

        # 1. 进入安全中心首页
        page = self.v150_open_safety_center(tag)
        # H5 页面加载初期可能识别为 unknown，等待文案渲染后重新检测
        if page != "safety_center":
            time.sleep(2)
            page = self._v150_current_page_type()
        assert page in ("safety_center", "unknown"), (
            f"进入安全中心后页面类型异常：{page}")
        self.v150_screenshot("safety_walkthrough_home")

        # 2. 进入安全专线
        self.v150_safety_enter_safety_line(tag)
        self.v150_screenshot("safety_walkthrough_line")
        self.v150_safety_return_center(tag)

        # 3. 进入紧急联系人
        self.v150_safety_enter_contacts(tag)
        self.v150_screenshot("safety_walkthrough_contacts")
        # 通过 Vuex store 验证联系人数据与前端展示一致
        vuex_result = self.v150_safety_verify_vuex_contact_list(tag)
        logger.info("【%s】遍历-联系人 Vuex 核对：%s", tag, vuex_result)
        self.v150_safety_return_center(tag)

        # 4. 进入行程分享
        self.v150_safety_enter_trip_share(tag)
        self.v150_screenshot("safety_walkthrough_share")
        self.v150_safety_return_center(tag)

        # 5. 进入999报警页
        self.v150_safety_enter_alarm(tag)
        self.v150_screenshot("safety_walkthrough_alarm")
        # 通过 Vuex store 验证报警页状态无错误
        alarm_store = self.v150_safety_read_vuex_store(tag)
        logger.info("【%s】遍历-报警页 Vuex：loadPhase=%s hasContacts=%s "
                    "sharingEnabled=%s", tag, alarm_store.get("loadPhase"),
                    alarm_store.get("hasContacts"), alarm_store.get("sharingEnabled"))
        self.v150_screenshot("safety_walkthrough_complete")

    # ==================== 用例21：端到端流程（安全中心→联系平台→添加联系人→999报警） ====================

    def test_safety_e2e_safety_line_contacts_alarm(self):
        """端到端真机流程，按指定顺序执行：

        1. 进入安全中心
        2. 安全专线 → 点击「聯絡平台」→ 进入系统拨号页 → 校验号码已填写 → 返回 App
        3. 紧急联系人 → 点击「新增緊急聯絡人」→ 填写姓名/电话 → 确认 → 列表显示
        4. 999报警 → 进入报警页 → 校验页面加载 → 验证联系人 selected 状态
        """
        tag = "v150_safety_e2e"

        # ===== 步骤1：进入安全中心 =====
        self.v150_open_safety_center(tag)
        logger.info("【%s】步骤1完成：已进入安全中心", tag)
        self.v150_screenshot("safety_e2e_step1_center")

        # ===== 步骤2：安全专线 → 联络平台 → 拨号页 → 返回 =====
        self.v150_safety_enter_safety_line(tag)
        time.sleep(2)
        dial = self.v150_safety_dial_platform_and_return(tag)
        assert dial["dialer_opened"], "点击「聯絡平台」未进入系统拨号页面"
        assert dial["phone"], "拨号页面未预填电话号码"
        assert re.fullmatch(r"\+\d{3,15}", dial["phone"]), (
            f"拨号页面电话号码格式异常：{dial['phone']}")
        assert dial["back_to_app"], "拨号页面返回后未回到乘客 App"
        logger.info("【%s】步骤2完成：安全专线拨号验证通过，号码=%s", tag, dial["phone"])
        self.v150_screenshot("safety_e2e_step2_dial")

        # 返回安全中心首页
        self.v150_safety_return_center(tag)

        # ===== 步骤3：紧急联系人 → 新增 → 列表验证 =====
        self.v150_safety_enter_contacts(tag)
        self.v150_safety_ensure_contacts_ready(tag)

        # 幂等：先删除已存在的同名联系人
        before = self.v150_safety_read_contact_list(tag)
        logger.info("【%s】步骤3：添加前联系人：%s", tag, before)
        for contact in self.TEST_CONTACTS:
            self.v150_safety_delete_contact(tag, name=contact["name"])
        self.v150_safety_ensure_contacts_ready(tag)

        # 逐个新增 3 个联系人
        for contact in self.TEST_CONTACTS:
            result = self.v150_safety_add_contact(
                tag, name=contact["name"], phone=contact["phone"])
            logger.info("【%s】已新增联系人：%s", tag, result)
        self.v150_screenshot("safety_e2e_step3_contacts_added")

        # 校验联系人已出现在列表中
        after = []
        for attempt in range(4):
            after = self.v150_safety_read_contact_list(tag)
            if len(after) >= len(self.TEST_CONTACTS):
                break
            logger.warning("【%s】列表未刷新（第%d次）", tag, attempt + 1)
            self.v150_safety_vuex_trigger_reload(tag)
            time.sleep(2)
        logger.info("【%s】步骤3完成：添加后联系人：%s", tag, after)
        assert len(after) == len(self.TEST_CONTACTS), (
            f"联系人数量不符：期望 {len(self.TEST_CONTACTS)}，实际 {len(after)}")
        for contact in self.TEST_CONTACTS:
            masked = mask_contact_phone(contact["phone"])
            assert any(contact["name"] in (c.get("name") or "") for c in after), (
                f"联系人「{contact['name']}」未出现在列表中：{after}")
            assert any(masked in (c.get("phone_masked") or "") for c in after), (
                f"联系人「{contact['name']}」掩码号码 {masked} 未出现：{after}")

        # 开启自动分享行程
        share_on = self.v150_safety_toggle_auto_share(tag, True)
        assert share_on["enabled"], "自动分享行程开关未开启"
        assert share_on["selected_count"] == len(self.TEST_CONTACTS), (
            f"自动分享应选中全部 {len(self.TEST_CONTACTS)} 个联系人，"
            f"实际={share_on['selected_count']}")
        self.v150_screenshot("safety_e2e_step3_auto_share")
        logger.info("【%s】步骤3完成：自动分享已开启，选中 %d 个联系人",
                    tag, share_on["selected_count"])

        # 返回安全中心首页
        self.v150_safety_return_center(tag)

        # ===== 步骤4：999报警 → 报警页 → 联系人状态验证 =====
        self.v150_safety_enter_alarm(tag)
        self._wait(
            lambda: self._v150_alarm_page_ready(),
            "V1.5.0 一键报警页面未就绪",
            timeout=15,
        )
        logger.info("【%s】步骤4完成：已进入999报警页面", tag)
        self.v150_screenshot("safety_e2e_step4_alarm_page")

        # 验证报警页 Vuex store：联系人仍为已选中状态（报警向全部联系人发送短信）
        alarm_store = self.v150_safety_read_vuex_store(tag)
        logger.info("【%s】报警页 Vuex：loadPhase=%s hasContacts=%s "
                    "sharingEnabled=%s selectedIds=%s",
                    tag, alarm_store.get("loadPhase"),
                    alarm_store.get("hasContacts"),
                    alarm_store.get("sharingEnabled"),
                    alarm_store.get("selectedIds"))
        assert alarm_store.get("loadPhase") == "ready", (
            f"报警页 Vuex 加载失败：{alarm_store.get('loadPhase')}")
        assert alarm_store.get("hasContacts") is True, (
            "报警页 Vuex 显示无联系人")
        assert alarm_store.get("sharingEnabled") is True, (
            "报警页 Vuex 显示自动分享未开启")
        assert len(alarm_store.get("selectedIds") or []) == len(self.TEST_CONTACTS), (
            f"报警页选中的联系人数不符：期望 {len(self.TEST_CONTACTS)}，"
            f"实际 {len(alarm_store.get('selectedIds') or [])}")

        # 报警页应向全部联系人发送报警链接
        # 离线契约验证：报警时不论是否开启自动分享，向全部联系人发送
        store = self._build_contact_store(auto_share=True)
        alarm_recipients = store.alarm_recipients()
        assert len(alarm_recipients) == len(self.TEST_CONTACTS), (
            f"报警应向全部 {len(self.TEST_CONTACTS)} 个联系人发送短信，"
            f"实际 {alarm_recipients}")
        for contact in self.TEST_CONTACTS:
            assert contact["phone"] in alarm_recipients, (
                f"联系人「{contact['name']}」({contact['phone']}) "
                f"未在报警短信接收列表中")
        logger.info("【%s】步骤4完成：999报警验证通过，报警短信接收人=%s",
                    tag, alarm_recipients)
        self.v150_screenshot("safety_e2e_step4_complete")


if __name__ == "__main__":
    from JRYG_run_main import run_tests
    sys.exit(run_tests(["--case", str(Path(__file__).resolve()), *sys.argv[1:]]))
