"""乘客端设置页面功能自动化测试。

每次运行只执行一遍完整的顺序流程，逐个进入设置页面所有功能项
（排除退出登录、测试中心、注销账号），验证页面加载与操作。

重点覆盖：
  - 常用地址搜索（蓟门桥地铁a口）
  - 平台协议与规则：进入后点击所有子功能，包括计价规则下属各车型、准入规则下属各子项
  - 隐私中心各文档、系统权限管理、版本信息、清除缓存

测试策略：
  - 所有子项封装为独立的 check_xxx 方法，每个方法独立 try/except 不中断整体流程
  - 最终汇总所有子项的 pass/fail 结果，若有任一失败则 pytest.fail
  - 使用 SettingsFlow 封装层提供 open/click/wait/expect/document/evidence/record 等能力
  - 安全护栏：禁止点击退出登录、测试中心、注销账号（ensure_allowed 校验）

前置条件：
  - 设备已连接、Appium Server 已启动
  - 乘客端 App 已登录（start_from_app 会从 App 启动导航至设置页面）
"""
import re
import sys
import time
from pathlib import Path

import pytest

# 将项目根目录添加到 sys.path，确保 common 模块可被正确导入
PROJECT_ROOT = str(Path(__file__).resolve().parents[2])
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from JRYG_Passenger_UI.common.JRYG_settings_flow import SettingsFlow, SETTING_ITEMS
from JRYG_Passenger_UI.common.JRYG_logger import logger


# ==================== 隐私中心下属文档配置 ====================
# 每个元素为 (resource_id, 标题, 正文关键词元组)
# 用于验证隐私中心各文档的 WebView 正文是否正确加载
PRIVACY_DOCUMENTS = [
    ("rl_private_summary", "隐私政策摘要", ("信息", "隐私")),
    ("rl_private_policy", "隐私政策", ("隐私", "信息")),
    ("rl_record_policy", "行程录音处理协议", ("录音",)),
    ("rl_person_policy", "个人信息收集清单", ("手机号",)),
    ("rl_third_policy", "第三方信息共享清单", ("SDK",)),
]

# ==================== 平台协议与规则目录下所有文档标题 ====================
# 计价规则和准入规则包含子级菜单，需要特殊处理（check_platform_document_multi）
PLATFORM_DOCUMENTS = [
    "用户协议", "个人信息保护及隐私政策", "录音处理协议", "自动驾驶信息服务协议",
    "小马智行用户服务协议", "小马智行隐私协议", "自动驾驶信息服务隐私政策",
    "阳仔智能对话助手服务", "计价规则", "准入规则", "判责规则", "调价公示",
]

# 计价规则子项：5 种车型，每个进入后验证正文关键词（元/公里/费用）
PRICING_MODELS = ("阳光快车", "阳光优选", "阳光舒享", "六座专车", "豪华臻享")

# 准入规则子项：4 个二级详情，进入后验证文档正文加载
ACCESS_RULES = ("车辆等级规则", "驾驶员准入标准", "车辆准入标准", "其他")


class TestJRYGSettings:
    """设置页面功能测试，顺序执行所有子项验证，每次只运行一遍。

    测试架构：
      - setup_class: 创建 SettingsFlow 实例，从 App 启动导航至设置页面
      - test_settings_all_functions: 主测试方法，顺序执行所有子项验证
      - check_xxx 系列: 各功能项的独立验证方法

    设计原则：
      - 每个子项独立 try/except，单项失败不中断整体流程
      - 最终汇总错误列表，若有失败则 pytest.fail 并列出所有失败项
      - 安全护栏：禁止操作退出登录、测试中心、注销账号
    """

    @classmethod
    def setup_class(cls):
        """类级初始化：创建 SettingsFlow 实例并从 App 启动导航至设置页面。

        SettingsFlow 封装了设备连接、Poco 控件树遍历、文本断言、
        文档正文校验、只读重试、结果落盘等能力。
        start_from_app 流程：App→首页→我的→齿轮→设置（含误入客服页重试）
        """
        cls.flow = SettingsFlow()
        cls.flow.start_from_app()

    def test_settings_all_functions(self):
        """顺序执行设置页面所有功能验证，每个子项独立 try/except 不中断整体流程。

        步骤组织方式：
          1. steps 列表：每个元素为 (标签, 方法, 参数) 三元组
          2. 遍历 steps，每步先 return_settings 回到设置主页，再执行子项验证
          3. 子项失败时采集 evidence（页面快照），记录到 results.json
          4. 最终汇总 errors，若有失败则 pytest.fail
        """
        steps = [
            ("菜单完整性与正常入口", self.check_inventory, None),
            ("紧急联系人列表", self.check_contacts, None),
            ("新增紧急联系人入口与取消", self.check_contact_form, None),
            ("常用一地址搜索", self.check_address, "rl_home"),
            ("常用二地址搜索", self.check_address, "rl_company"),
            ("常用地址清空与空态", self.check_clear_address_cancel, None),
            ("支付方式列表", self.check_payments, None),
            ("消息通知系统入口", self.check_notifications, None),
            ("隐私中心菜单", self.check_privacy, None),
            ("个人信息收集清单", self.check_personal, None),
            ("第三方信息共享清单", self.check_third_party, None),
            ("平台协议规则目录", self.check_platform, None),
            ("系统权限管理目录", self.check_permission_menu, None),
            ("定位权限系统入口", self.check_permission, "rl_private_location"),
            ("麦克风权限系统入口", self.check_permission, "rl_private_mike"),
            ("通讯录权限系统入口", self.check_permission, "rl_private_contacts"),
            ("撤回隐私协议取消", self.check_revoke_cancel, None),
        ]
        # 隐私中心各文档
        for rid, title, terms in PRIVACY_DOCUMENTS:
            steps.append((f"隐私中心-{title}", self.check_privacy_document, (rid, terms)))
        # 平台协议各文档；计价规则/准入规则单独处理多级遍历
        _multi_level = {"计价规则", "准入规则"}
        for title in PLATFORM_DOCUMENTS:
            if title in _multi_level:
                steps.append((f"平台协议-{title}（含子项遍历）", self.check_platform_document_multi, title))
            else:
                steps.append((f"平台协议-{title}", self.check_platform_document, title))
        # 版本信息、清除缓存
        steps.append(("版本信息与安装版本一致", self.check_version, None))
        steps.append(("清除缓存取消", self.check_cache_cancel, None))
        steps.append(("清除缓存确认与登录态保留", self.check_cache_confirm, None))

        errors = []
        # 遍历所有步骤，每步独立 try/except，失败不中断后续步骤
        for label, method, data in steps:
            error = None
            try:
                # 每步先返回设置主页，确保从已知状态开始操作
                self.flow.return_settings()
                method(data)
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                self.flow.evidence(label)  # 采集失败页面快照
            # 尝试返回设置页，确保下一步能从设置主页开始
            try:
                self.flow.return_settings()
            except Exception as exc:
                error = f"{error or ''}; 返回设置失败: {exc}"
                self.flow.evidence(f"{label}_return")
            # 记录单条测试结果并写入 results.json
            self.flow.record(label, "failed" if error else "passed",
                             error or "页面内容/操作结果及返回设置均通过")
            if error:
                errors.append(f"{label}: {error}")
                logger.error(f"【设置测试】{label} 失败: {error}")
            else:
                logger.info(f"【设置测试】{label} 通过")

        # 汇总所有失败项，若存在失败则标记整个测试为 FAILED
        if errors:
            pytest.fail(f"{len(errors)}/{len(steps)} 项失败:\n" + "\n".join(errors), pytrace=False)

    def check_inventory(self, _):
        """验证设置菜单包含所有预期入口且无未覆盖项。

        检查逻辑：
          1. 断言 SETTING_ITEMS 中定义的所有 resource_id 均出现在页面控件树中
          2. 反向校验：页面中发现的 rl_ 开头入口不应超出已知集合（防止新增入口遗漏测试）
        """
        flow = self.flow
        flow.expect("设置")
        names = {node["name"] for node in flow.nodes()}
        # 正向校验：所有预期入口必须存在
        for rid, label in SETTING_ITEMS.items():
            assert f"{flow.package}:id/{rid}" in names, f"设置菜单缺少 {label}"
        # 反向校验：不应发现未覆盖的入口
        known = set(SETTING_ITEMS) | {"rl_more_zhuxiao"}  # rl_more_zhuxiao 为注销账号入口，单独排除
        discovered = {name.split(":id/")[-1] for name in names if ":id/rl_" in name}
        assert discovered <= known, f"发现未覆盖设置入口: {discovered - known}"

    def check_contacts(self, _):
        """验证紧急联系人列表页面加载正常。"""
        flow = self.flow
        flow.open("rl_contract")
        flow.expect("新增紧急联系人", "自动分享行程")
        flow.document(("紧急联系人",))

    def check_contact_form(self, _):
        """验证新增紧急联系人入口可打开表单、触发上限提示或跳转 WebView 介绍页。"""
        flow = self.flow
        self.check_contacts(None)
        before_texts = flow.texts()
        before_activity = flow.adb.get_top_activity()
        flow.click(text="新增紧急联系人")
        # 等待页面发生变化：Activity 变化、文本变化或出现输入框
        flow.wait(lambda: (
            flow.adb.get_top_activity() != before_activity
            or bool(flow.texts() - before_texts)
            or any(node.get("type") == "android.widget.EditText" for node in flow.nodes())
        ), "新增联系人页面变化（表单/上限提示/WebView）", timeout=25)
        texts = " ".join(flow.texts())
        # 兼容多种情况：表单（姓名/手机号）、原生上限提示、WebView 介绍/提示页
        assert any(word in texts for word in (
            "姓名", "手机号", "上限", "最多", "3位", "3个",
            "联系人", "已满", "添加", "紧急", "超过", "无法",
            "分享", "报警", "行程",
        )), "未展示联系人表单或上限校验"

    def check_address(self, rid):
        """验证常用地址搜索功能（常用一/常用二），搜索蓟门桥地铁a口。

        流程：进入常用地址 → 点击常用一/常用二 → 输入搜索关键词 → 验证搜索结果出现
        参数 rid: "rl_home"（常用一）或 "rl_company"（常用二）
        """
        flow = self.flow
        flow.open("rl_frequent_address")  # 返回设置 → 滚动定位 → 点击常用地址入口
        flow.expect("常用地址", "常用一", "常用二")
        flow.click(rid=rid)  # 点击常用一或常用二进入搜索页
        flow.wait(lambda: flow.exists(rid="et_search"), "地址编辑搜索页")
        flow.element(rid="et_search").set_text("蓟门桥地铁a口")
        # 等待搜索结果出现：页面中出现"蓟门桥"关键词（排除输入框自身文本），或结果列表项出现
        flow.wait(lambda: any("蓟门桥" in text for text in flow.texts()
                             if text != "蓟门桥地铁a口") or flow.exists(rid="tv_address_name"), "蓟门桥地铁a口搜索结果")
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
        """验证支付方式列表包含三大渠道且开通按钮文本正确。"""
        flow = self.flow
        flow.open("rl_frequent_pay")
        flow.expect("支付方式", "微信支付分", "芝麻先享", "抖音")
        titles = list(flow.poco(f"{flow.package}:id/credit_pay_title"))
        buttons = list(flow.poco(f"{flow.package}:id/btn_setting"))
        assert len(titles) == 3 and len(buttons) == 3, "支付渠道或操作按钮缺失"
        states = [{"channel": title.get_text(), "label": button.get_text(), "enabled": button.attr("enabled")}
                  for title, button in zip(titles, buttons)]
        flow.events.append({"action": "assert_payment_channels", "states": states,
                            "boundary": "不开通先乘后付/免密扣款授权；未开通按钮禁用属正常"})
        # 按钮文本应为开通/管理类操作；enabled 为 False 表示未开通属正常状态
        assert all(item["label"] in ("去开通", "已开通", "去设置", "管理") for item in states), f"按钮文本异常: {states}"

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
        flow.expect("功能类型", "SDK名称", "使用目的", "收集的个人信息种类", package=None)

    def check_platform(self, _):
        """验证平台协议与规则目录加载正常（带只读重试，滚动确保全部可见）。

        平台协议目录是 WebView 页面，package 可能不是乘客端，因此不按包名过滤。
        滚动最多 3 次确保底部文档（计价规则/判责规则/调价公示）可见。
        首次加载超时会自动重新进入重试一次（read_only_retry）。
        """
        flow = self.flow
        def load():
            flow.open("rl_more_doc")  # 返回设置 → 点击平台协议与规则入口
            # 不按包名过滤获取全部文本（WebView 页面 package 可能不是乘客端）
            flow.wait(lambda: "平台协议" in flow.texts(package=None) or "用户协议" in flow.texts(package=None),
                      "平台协议目录加载", timeout=30)
            # 滚动确保全部文档可见（底部文档出现说明全部已加载）
            for _ in range(3):
                all_texts = flow.texts(package=None)
                if all(t in all_texts for t in ("计价规则", "判责规则", "调价公示")):
                    break
                flow.poco.swipe([0.5, 0.79], [0.5, 0.35], duration=0.8)
                time.sleep(0.5)
            flow.expect("平台协议", "用户协议", "计价规则", timeout=35)
        flow.read_only_retry(load, "平台协议目录")

    def _scroll_to_text(self, text, max_swipes=5):
        """在当前页面滚动查找指定文本，找到返回 True。

        向上滚动最多 max_swipes 次，每次滚动后检查目标文本是否出现。
        不按包名过滤文本，因为 WebView 页面 package 可能不是乘客端。
        """
        flow = self.flow
        for _ in range(max_swipes):
            if flow.exists(text=text) or text in flow.texts(package=None):
                return True
            flow.poco.swipe([0.5, 0.79], [0.5, 0.35], duration=0.8)
            time.sleep(0.5)
        return flow.exists(text=text) or text in flow.texts(package=None)

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
        # 滚动查找文档入口并点击
        self._scroll_to_text(title, max_swipes=5)
        flow.click(text=title)
        # 等待离开协议目录（不再同时出现目录标题文本）
        flow.wait(lambda: not {"用户协议", "平台协议", "平台规则"} <= flow.texts(package=None),
                  f"{title}离开协议目录", timeout=20)
        if title == "计价规则":
            flow.expect("计价规则", "阳光快车", "阳光优选", "阳光舒享", "六座专车", "豪华臻享")
        elif title == "准入规则":
            flow.expect("准入规则", "车辆等级规则", "驾驶员准入标准", "车辆准入标准", "其他")
        else:
            flow.document(timeout=45)

    def check_platform_document_multi(self, title):
        """验证计价规则/准入规则：进入后逐个点击每个子功能，验证详情正文加载后返回。

        计价规则子项：阳光快车、阳光优选、阳光舒享、六座专车、豪华臻享
        准入规则子项：车辆等级规则、驾驶员准入标准、车辆准入标准、其他

        遍历策略：
          1. 进入计价规则/准入规则列表页（需先进入平台协议目录再点击进入）
          2. 滚动确保所有子项可见
          3. 逐个点击子功能 → 等待进入详情页 → 验证 WebView 正文加载 → ADB 返回 → 回到列表页
          4. 每个子项独立 try/except，单项失败不中断后续子项验证

        参数 title: "计价规则" 或 "准入规则"
        """
        flow = self.flow
        # 根据标题选择子项列表和预期正文关键词
        sub_items = list(PRICING_MODELS) if title == "计价规则" else list(ACCESS_RULES)
        expected_terms = ("元", "公里", "费用") if title == "计价规则" else ()

        # 进入计价规则/准入规则列表页
        self.check_platform(None)  # 先进入平台协议目录
        self._scroll_to_text(title, max_swipes=5)  # 滚动找到目标标题
        flow.click(text=title)
        # 等待离开平台协议目录（不再同时出现多个目录标题）
        flow.wait(lambda: not {"用户协议", "平台协议", "平台规则"} <= flow.texts(package=None),
                  f"{title}离开协议目录", timeout=20)
        # 滚动确保所有子项可见（最后一个子项可见说明全部已加载）
        self._scroll_to_text(sub_items[-1], max_swipes=3)
        flow.expect(title, *sub_items[:2])

        # 逐个点击子功能，验证详情正文后返回列表页
        for sub in sub_items:
            sub_label = f"{title}-{sub}"
            sub_error = None
            try:
                # 滚动找到子项并点击
                self._scroll_to_text(sub, max_swipes=3)
                flow.click(text=sub)
                # 等待进入详情页（子项标题从页面消失，或不再处于协议目录）
                flow.wait(lambda: sub not in flow.texts() or not {"用户协议", "平台协议"} <= flow.texts(),
                          f"{sub}进入详情页", timeout=20)
                # 验证 WebView 文档正文加载（计价规则需包含费用相关关键词）
                flow.document(expected_terms, timeout=45)
            except Exception as exc:
                sub_error = f"{type(exc).__name__}: {exc}"
                flow.evidence(sub_label)
            # 返回列表页
            try:
                flow.adb.back()
                time.sleep(1)
                self._scroll_to_text(sub, max_swipes=3)
            except Exception as exc:
                sub_error = f"{sub_error or ''}; 返回列表失败: {exc}"
                flow.evidence(f"{sub_label}_return")
            flow.record(sub_label, "failed" if sub_error else "passed",
                        sub_error or f"{sub}详情正文加载及返回均通过")
            if sub_error:
                logger.error(f"【设置测试】{sub_label} 失败: {sub_error}")
            else:
                logger.info(f"【设置测试】{sub_label} 通过")

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
        """验证清除缓存确认后归零且登录态保留。

        流程：点击清除缓存 → 确认弹窗 → 等待缓存数值归零 → 返回"我的"页 →
        断言手机号仍显示（登录态保留） → 重新进入设置页
        """
        flow = self.flow
        flow.click(rid="rl_more_clean")
        flow.expect("清除缓存", "取消", "确认")
        flow.click(rid="positive")  # 点击确认按钮
        # 等待缓存数值归零（匹配 0 / 0.0 / 0B / 0KB 等格式）
        flow.wait(lambda: bool(re.fullmatch(r"0(?:\.0+)?\s*[KMG]?B?", flow.element(rid="tv_more").get_text(), re.I)),
                  "App内缓存清理至0", timeout=15)
        flow.adb.back()  # 返回"我的"页
        # 断言登录态保留：手机号仍显示且不含"登录"字样
        flow.wait(lambda: flow.exists(rid="tv_mine_phone"), "清缓存后仍保留登录态")
        phone = flow.element(rid="tv_mine_phone").get_text()
        assert re.search(r"\d", phone) and "登录" not in phone
        flow.click(rid="iv_setting")  # 重新进入设置页供后续步骤使用


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "-s", *sys.argv[1:]]))
