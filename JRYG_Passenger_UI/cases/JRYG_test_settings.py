"""大陆乘客端设置页面功能自动化测试。

覆盖设置页面所有功能项（排除退出登录、测试中心、注销账号），
包括：菜单完整性、紧急联系人、常用地址、支付方式、消息通知、
隐私中心各文档、平台协议与规则、系统权限管理、版本信息、清除缓存。
使用 SettingsFlow 提供的通用能力进行页面导航与断言。
"""
import re
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = str(Path(__file__).resolve().parents[2])
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from JRYG_Passenger_UI.common.JRYG_settings_flow import SettingsFlow, SETTING_ITEMS


# 隐私中心下属文档列表：每个元素为 (resource_id, 标题, 正文关键词元组)，
# resource_id 用于点击进入详情，正文关键词用于验证页面内容是否正确加载。
PRIVACY_DOCUMENTS = [
    ("rl_private_summary", "隐私政策摘要", ("信息", "隐私")),
    ("rl_private_policy", "隐私政策", ("隐私", "信息")),
    ("rl_record_policy", "行程录音处理协议", ("录音",)),
    ("rl_person_policy", "个人信息收集清单", ("手机号",)),
    ("rl_third_policy", "第三方信息共享清单", ("SDK",)),
]

# 平台协议与规则目录下所有文档标题，来源于设置-平台协议页面展开后的完整列表。
PLATFORM_DOCUMENTS = [
    "用户协议", "个人信息保护及隐私政策", "录音处理协议", "自动驾驶信息服务协议",
    "小马智行用户服务协议", "小马智行隐私协议", "自动驾驶信息服务隐私政策",
    "阳仔智能对话助手服务", "计价规则", "准入规则", "判责规则", "调价公示",
]

# 计价规则子项：5种车型，对应计价规则详情页中展示的不同服务类型。
PRICING_MODELS = ("阳光快车", "阳光优选", "阳光舒享", "六座专车", "豪华臻享")

# 准入规则子项：4个二级详情，涵盖车辆/驾驶员准入标准等维度。
ACCESS_RULES = ("车辆等级规则", "驾驶员准入标准", "车辆准入标准", "其他")

# 全部测试用例：(标签, action 方法名, 附加数据)
CASES = [
    ("菜单完整性与正常入口", "inventory", None),
    ("紧急联系人列表", "contacts", None),
    ("新增紧急联系人入口与取消", "contact_form", None),
    ("常用一地址搜索", "address", "rl_home"),
    ("常用二地址搜索", "address", "rl_company"),
    ("常用地址清空与空态", "clear_address_cancel", None),
    ("支付方式列表", "payments", None),
    ("消息通知系统入口", "notifications", None),
    ("隐私中心菜单", "privacy", None),
    ("个人信息收集清单", "personal", None),
    ("第三方信息共享清单", "third_party", None),
    ("平台协议规则目录", "platform", None),
    ("系统权限管理目录", "permission_menu", None),
    ("定位权限系统入口", "permission", "rl_private_location"),
    ("麦克风权限系统入口", "permission", "rl_private_mike"),
    ("通讯录权限系统入口", "permission", "rl_private_contacts"),
    ("撤回隐私协议取消", "revoke_cancel", None),
] + [(f"隐私中心-{title}", "privacy_document", (rid, terms)) for rid, title, terms in PRIVACY_DOCUMENTS] + [
    (f"平台协议-{title}", "platform_document", title) for title in PLATFORM_DOCUMENTS
] + [
    (f"计价规则-{title}", "rule_detail", ("计价规则", title))
    for title in PRICING_MODELS
] + [
    (f"准入规则-{title}", "rule_detail", ("准入规则", title))
    for title in ACCESS_RULES
] + [
    ("版本信息与安装版本一致", "version", None),
    ("清除缓存取消", "cache_cancel", None),
    ("清除缓存确认与登录态保留", "cache_confirm", None),
]


class TestJRYGSettings:
    """设置页面功能测试套件，参数化驱动所有设置子项验证。"""

    @classmethod
    def setup_class(cls):
        """类级初始化：创建 SettingsFlow 实例并从 App 启动导航至设置页面。"""
        cls.flow = SettingsFlow()
        cls.flow.start_from_app()

    @pytest.mark.parametrize("label,action,data", CASES, ids=[case[0] for case in CASES])
    def test_settings_function(self, label, action, data):
        """参数化测试入口：每个用例执行对应 check_ 方法，采集证据并记录结果。"""
        flow = self.flow
        error = None
        try:
            flow.return_settings()
            getattr(self, f"check_{action}")(data)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            flow.evidence(label)
        try:
            flow.return_settings()
        except Exception as exc:
            error = f"{error or ''}; 返回设置失败: {exc}"
            flow.evidence(f"{label}_return")
        flow.record(label, "failed" if error else "passed", error or "页面内容/操作结果及返回设置均通过")
        if error:
            pytest.fail(error, pytrace=False)

    def check_inventory(self, _):
        """验证设置菜单包含所有预期入口且无未覆盖项。"""
        flow = self.flow
        flow.expect("设置")
        names = {node["name"] for node in flow.nodes()}
        for rid, label in SETTING_ITEMS.items():
            assert f"{flow.package}:id/{rid}" in names, f"设置菜单缺少 {label}"
        known = set(SETTING_ITEMS) | {"rl_more_zhuxiao"}
        discovered = {name.split(":id/")[-1] for name in names if ":id/rl_" in name}
        assert discovered <= known, f"发现未覆盖设置入口: {discovered - known}"

    def check_contacts(self, _):
        """验证紧急联系人列表页面加载正常。"""
        flow = self.flow
        flow.open("rl_contract")
        flow.expect("新增紧急联系人", "自动分享行程")
        flow.document(("紧急联系人",))

    def check_contact_form(self, _):
        """验证新增紧急联系人入口可打开表单或触发上限提示。"""
        flow = self.flow
        self.check_contacts(None)
        before = flow.texts()
        flow.click(text="新增紧急联系人")
        flow.wait(lambda: bool(flow.texts() - before) or any(
            node.get("type") == "android.widget.EditText" for node in flow.nodes()
        ), "新增联系人表单或数量上限提示")
        texts = " ".join(flow.texts())
        assert any(word in texts for word in ("姓名", "手机号", "上限", "最多", "3位", "3个")), "未展示联系人表单或上限校验"

    def check_address(self, rid):
        """验证常用地址搜索功能（常用一/常用二）。"""
        flow = self.flow
        flow.open("rl_frequent_address")
        flow.expect("常用地址", "常用一", "常用二")
        flow.click(rid=rid)
        flow.wait(lambda: flow.exists(rid="et_search"), "地址编辑搜索页")
        flow.element(rid="et_search").set_text("时代之光名苑")
        flow.wait(lambda: any("时代之光名苑" in text for text in flow.texts()
                             if text != "时代之光名苑") or flow.exists(rid="tv_address_name"), "常用地址搜索结果")
        assert "AddressSearch" in flow.adb.get_top_activity(), "搜索页未正常打开"

    def check_clear_address_cancel(self, _):
        """验证空地址状态下清空按钮取消操作不产生异常。"""
        flow = self.flow
        flow.open("rl_frequent_address")
        flow.expect("常用一", "常用二")
        data_texts = flow.texts() - {"常用地址", "常用一", "常用二", "清空", "设置常用的地址"}
        assert not data_texts, "已有用户常用地址，禁止为测试直接清空；需要专用可恢复测试数据"
        flow.click(rid="tv_clear")
        if flow.exists(text="取消"):
            flow.click(text="取消")
        flow.expect("常用地址", "常用一", "常用二", "设置常用的地址")
        assert not flow.texts() - {"常用地址", "常用一", "常用二", "清空", "设置常用的地址"}, "空地址清理后出现意外数据"

    def check_payments(self, _):
        """验证支付方式列表包含三大渠道且开通按钮可用。"""
        flow = self.flow
        flow.open("rl_frequent_pay")
        flow.expect("支付方式", "微信支付分", "芝麻先享", "抖音")
        titles = list(flow.poco(f"{flow.package}:id/credit_pay_title"))
        buttons = list(flow.poco(f"{flow.package}:id/btn_setting"))
        assert len(titles) == 3 and len(buttons) == 3, "支付渠道或操作按钮缺失"
        states = [{"channel": title.get_text(), "label": button.get_text(), "enabled": button.attr("enabled")}
                  for title, button in zip(titles, buttons)]
        flow.events.append({"action": "assert_payment_channels", "states": states,
                            "boundary": "不开通先乘后付/免密扣款授权"})
        assert all(item["enabled"] is not False for item in states), f"支付开通按钮禁用: {states}"
        assert all(item["label"] in ("去开通", "已开通", "去设置", "管理") for item in states)

    def check_notifications(self, _):
        """验证消息通知管理可跳转系统通知设置页（兼容 Vivo 厂商适配）。"""
        flow = self.flow
        flow.open("rl_notify_manage")
        flow.expect("消息通知管理", "接收消息通知")
        flow.click(rid="notify_status")
        flow.wait(lambda: flow.system_page_package(), "跳转系统通知设置")
        package = flow.system_page_package()
        flow.expect("阳光出行", package=package)
        assert any("通知" in text for text in flow.texts(package)), "不是通知设置页"

    def check_privacy(self, _):
        """验证隐私中心菜单包含所有预期子项。"""
        flow = self.flow
        flow.open_privacy()
        flow.expect("隐私政策摘要", "隐私政策", "行程录音处理协议", "个人信息收集清单",
                    "第三方信息共享清单", "系统权限管理", "撤回隐私政策协议")

    def check_personal(self, _):
        """验证个人信息收集清单页面内容加载正常。"""
        flow = self.flow
        flow.open("rl_person_policy")
        flow.expect("个人信息清单", "昵称", "手机号", "紧急联系人", "下载")
        flow.document(("手机号",))

    def check_third_party(self, _):
        """验证第三方信息共享清单页面包含表格字段。"""
        flow = self.flow
        flow.open("rl_third_policy")
        flow.document(("SDK",))
        flow.expect("功能类型", "SDK名称", "使用目的", "收集的个人信息种类")

    def check_platform(self, _):
        """验证平台协议与规则目录加载正常（带只读重试）。"""
        flow = self.flow
        def load():
            flow.open("rl_more_doc")
            flow.expect("平台协议", "平台规则", "用户协议", "计价规则", timeout=35)
        flow.read_only_retry(load, "平台协议目录")

    def check_privacy_document(self, data):
        """验证隐私中心下属各文档正文加载（带只读重试）。"""
        rid, terms = data
        def load():
            self.flow.open_privacy(rid)
            self.flow.document(terms, timeout=35)
        self.flow.read_only_retry(load, rid)

    def check_platform_document(self, title):
        """验证平台协议目录下各文档加载（区分目录列表与正文详情）。"""
        flow = self.flow
        self.check_platform(None)
        flow.click(text=title)
        # 等待离开协议目录（不再同时出现目录标题文本）
        flow.wait(lambda: not {"用户协议", "平台协议", "平台规则"} <= flow.texts(),
                  f"{title}离开协议目录", timeout=20)
        if title == "计价规则":
            flow.expect("计价规则", "阳光快车", "阳光优选", "阳光舒享", "六座专车", "豪华臻享")
        elif title == "准入规则":
            flow.expect("准入规则", "车辆等级规则", "驾驶员准入标准", "车辆准入标准", "其他")
        else:
            flow.document(timeout=35)

    def check_rule_detail(self, data):
        """验证计价规则/准入规则的二级详情文档正文。"""
        menu, title = data
        flow = self.flow
        self.check_platform_document(menu)
        flow.click(text=title)
        flow.document(("元", "公里", "费用") if menu == "计价规则" else (), timeout=35)

    def check_permission_menu(self, _):
        """验证系统权限管理目录包含三项权限状态。"""
        flow = self.flow
        flow.open_privacy("rl_private_setting")
        flow.expect("系统权限设置")
        for rid in ("tv_status_location", "tv_status_mike", "tv_status_contacts"):
            assert flow.exists(rid=rid), f"缺少权限状态: {rid}"
            assert flow.element(rid=rid).get_text() in ("已开启", "去设置", "未开启", "已关闭")

    def check_permission(self, rid):
        """验证单项权限入口可跳转系统设置页。"""
        flow = self.flow
        self.check_permission_menu(None)
        flow.click(rid=rid)
        flow.wait(lambda: "com.android.settings/" in flow.adb.get_top_activity(), "权限入口跳转系统设置")
        flow.expect("阳光出行", package="com.android.settings")

    def check_revoke_cancel(self, _):
        """验证撤回隐私协议弹窗可取消并返回隐私中心。"""
        flow = self.flow
        flow.open_privacy()
        flow.click(rid="rl_revoke_setting")
        flow.expect("确定要撤回协议吗？", "我再想想", "确认撤回")
        flow.click(text="我再想想")
        flow.expect("隐私中心", "系统权限管理")

    def check_version(self, _):
        """验证版本信息格式与已安装版本一致。"""
        flow = self.flow
        shown = flow.element(rid="tv_version").get_text()
        assert re.fullmatch(r"v?\d+(?:\.\d+){1,3}(?:[-.\w]*)?", shown), f"版本号格式错误: {shown}"
        installed = flow.adb.run_cmd(["dumpsys", "package", flow.package])
        match = re.search(r"versionName=([^\s]+)", installed)
        assert match and shown.lstrip("v") == match.group(1), "显示版本与已安装版本不一致"
        flow.click(rid="rl_more_version")
        flow.wait(flow.is_settings, "版本检查后仍在设置页")

    def check_cache_cancel(self, _):
        """验证清除缓存弹窗取消后缓存数值不变。"""
        flow = self.flow
        before = flow.element(rid="tv_more").get_text()
        flow.click(rid="rl_more_clean")
        flow.expect("清除缓存", "取消", "确认")
        assert "缓存" in flow.element(rid="message").get_text()
        flow.click(rid="negative")
        assert flow.element(rid="tv_more").get_text() == before, "取消后缓存数值异常改变"

    def check_cache_confirm(self, _):
        """验证清除缓存确认后归零且登录态保留。"""
        flow = self.flow
        flow.click(rid="rl_more_clean")
        flow.expect("清除缓存", "取消", "确认")
        flow.click(rid="positive")
        flow.wait(lambda: bool(re.fullmatch(r"0(?:\.0+)?\s*[KMG]?B?", flow.element(rid="tv_more").get_text(), re.I)),
                  "App内缓存清理至0", timeout=15)
        flow.adb.back()
        flow.wait(lambda: flow.exists(rid="tv_mine_phone"), "清缓存后仍保留登录态")
        phone = flow.element(rid="tv_mine_phone").get_text()
        assert re.search(r"\d", phone) and "登录" not in phone
        flow.click(rid="iv_setting")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "-s", *sys.argv[1:]]))
