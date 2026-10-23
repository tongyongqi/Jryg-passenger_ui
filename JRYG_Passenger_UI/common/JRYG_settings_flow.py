"""设置页面自动化验证流程工具。

提供设置页面的打开、控件定位、文档加载校验、只读重试、
返回设置主页、结果落盘等通用能力，供 JRYG_test_settings 使用。
"""
import json
import logging
import re
import time
from pathlib import Path

from airtest.core.api import connect_device
from poco.drivers.android.uiautomation import AndroidUiautomationPoco

from JRYG_Passenger_UI.common.JRYG_adb_tools import JRYG_ADBTools
from JRYG_Passenger_UI.common.JRYG_config import SETTINGS, REPORT_DIR
from JRYG_Passenger_UI.common.JRYG_logger import logger


# 排除项：不点击退出登录、测试中心、注销账号
EXCLUDED_TEXT = ("退出登录", "测试中心", "注销账号")
EXCLUDED_IDS = {"tv_mydetail_exit", "ll_test", "rl_more_zhuxiao", "tv_zhuxiao"}

# 设置页面入口 resource_id → 中文名映射
SETTING_ITEMS = {
    "rl_contract": "紧急联系人",
    "rl_frequent_address": "常用地址",
    "rl_frequent_pay": "支付方式",
    "rl_notify_manage": "消息通知管理",
    "rl_more_private": "隐私中心",
    "rl_person_policy": "个人信息收集清单",
    "rl_third_policy": "第三方信息共享清单",
    "rl_more_doc": "平台协议与规则",
    "rl_more_version": "版本信息",
    "rl_more_clean": "清除缓存",
}


class SettingsFlow:
    """设置页面验证流程控制器。

    封装 Poco 控件树遍历、文本断言、文档正文校验、只读页面重试、
    系统页面包名适配、脱敏日志、结果落盘等能力。
    """

    def __init__(self):
        """初始化设备连接、Poco 实例、结果与输出目录。"""
        self.package = SETTINGS["packages"]["passenger"]
        self.adb = JRYG_ADBTools()
        logging.getLogger("airtest").setLevel(logging.WARNING)
        connect_device(f"android://127.0.0.1:5037/{SETTINGS['device']['udid']}")
        self.poco = AndroidUiautomationPoco(use_airtest_input=True, screenshot_each_action=False)
        self.results = []
        self.events = []
        self.output = Path(REPORT_DIR) / "settings"
        self.output.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def flatten(root, package=None):
        """递归展平 Poco 控件树，返回可见节点列表，可选按包名过滤。"""
        result = []
        pending = [(root, [])]
        while pending:
            node, parents = pending.pop()
            payload = dict(node.get("payload", {}))
            payload["name"] = payload.get("name") or node.get("name", "")
            if payload.get("visible") is not False and (package is None or payload.get("package") == package):
                payload["parents"] = parents
                result.append(payload)
            pending.extend((child, parents + [payload["name"]]) for child in reversed(node.get("children", [])))
        return result

    def nodes(self, package=None):
        """获取当前页面所有可见节点（默认按乘客端包名过滤）。"""
        return self.flatten(self.poco.agent.hierarchy.dump(), package or self.package)

    def texts(self, package=None):
        """提取当前页面所有文本（text + desc 字段），返回去重集合。"""
        return {value.strip() for node in self.nodes(package)
                for value in (node.get("text"), node.get("desc"))
                if isinstance(value, str) and value.strip()}

    def wait(self, predicate, description, timeout=20):
        """轮询等待条件成立，超时抛出带页面快照的断言。"""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.5)
        raise AssertionError(f"{description}超时；页面={self.adb.get_top_activity()}；文本={self.redact(' | '.join(sorted(self.texts())))}")

    def expect(self, *labels, timeout=20, package=None):
        """断言页面包含指定文本，超时则失败。"""
        self.wait(lambda: set(labels) <= self.texts(package), f"等待文本 {labels}", timeout)

    def exists(self, rid=None, text=None, package=None):
        """判断指定控件是否存在。"""
        return self.element(rid, text, package).exists()

    def element(self, rid=None, text=None, package=None):
        """构建 Poco 控件选择器，自动补全包名前缀。"""
        options = {"package": package or self.package}
        if rid:
            options["name"] = rid if ":id/" in rid else f"{self.package}:id/{rid}"
        if text is not None:
            options["text"] = text
        return self.poco(**options)

    @staticmethod
    def ensure_allowed(rid, text):
        """安全护栏：检查目标不在排除项（退出登录/测试中心/注销账号）内。"""
        if (rid or "").split(":id/")[-1] in EXCLUDED_IDS or any(word in (text or "") for word in EXCLUDED_TEXT):
            raise AssertionError(f"禁止操作排除项: {rid or text}")

    def click(self, rid=None, text=None, package=None):
        """等待控件出现后点击，附带排除项校验和事件记录。"""
        self.ensure_allowed(rid, text)
        self.wait(lambda: self.exists(rid, text, package), f"定位 {rid or text}", 12)
        node = self.element(rid, text, package)
        self.ensure_allowed(node.attr("name"), node.get_text())
        assert node.attr("enabled") is not False, f"控件不可用: {rid or text}"
        self.events.append({"action": "click", "target": rid or text, "package": package or self.package})
        logger.info("【设置验证】点击 %s", rid or text)
        node.click()
        time.sleep(0.6)

    def is_settings(self):
        """判断当前是否在设置主页面（YGUMoreActivity 且隐私中心入口可见）。"""
        return "YGUMoreActivity" in self.adb.get_top_activity() and self.exists(rid="rl_more_private")

    def return_settings(self):
        """通过导航返回设置主页，最多尝试8次，禁止点击排除项。"""
        for _ in range(8):
            if self.is_settings() and not self.exists(rid="dialog_container"):
                return
            if self.exists(rid="iv_setting"):
                self.click(rid="iv_setting")
            elif self.exists(text="我的") and "YGAHomeActivity" in self.adb.get_top_activity():
                self.click(text="我的")
            else:
                self.adb.back()
                time.sleep(0.6)
        raise AssertionError("返回设置失败，停止当前项并保留现场，不点击退出/注销/测试中心")

    def start_from_app(self):
        """从启动 App 开始导航至设置页面（App→首页→我的→齿轮→设置）。

        点击齿轮后有时会误入智能客服页面（YGFFlutterActivity），
        需检测到非设置页面后返回重试，最多尝试 3 次。
        """
        self.adb.start_app(self.package, SETTINGS["packages"]["passenger_activity"])
        navigated = False
        for _ in range(15):
            activity = self.adb.get_top_activity().lower()
            if "blockcanary" in activity or "displayactivity" in activity:
                self.adb.back()
            elif self.exists(rid="iv_cancel"):
                self.click(rid="iv_cancel")
            elif self.exists(text="首页") and self.exists(text="我的") and not navigated:
                self.click(text="我的")
                navigated = True
            elif navigated and self.exists(rid="iv_setting"):
                self.click(rid="iv_setting")
                time.sleep(1.5)
                act = self.adb.get_top_activity()
                if "YGUMoreActivity" in act and self.exists(rid="rl_more_private"):
                    return
                # 误入客服页面（YGFFlutterActivity），返回后重试
                logger.warning("点击齿轮后未进入设置页（当前=%s），返回重试", act)
                self.adb.back()
                time.sleep(1)
            elif "login" in activity:
                raise AssertionError("当前账号未登录，设置验证不自动切换账号")
            elif self.package in activity and not navigated:
                self.adb.back()
            time.sleep(1)
        raise AssertionError("未能完成打开App→我的→齿轮→设置")

    def open(self, rid):
        """返回设置主页后滚动定位并点击指定设置入口。"""
        assert rid in SETTING_ITEMS, f"设置入口不在测试允许清单: {rid}"
        self.return_settings()
        for _ in range(3):
            if self.exists(rid=rid):
                break
            self.poco.swipe([0.5, 0.79], [0.5, 0.35], duration=0.8)
            time.sleep(0.5)
        self.click(rid=rid)

    def open_privacy(self, rid=None):
        """打开隐私中心页面，可选点击子入口。"""
        self.open("rl_more_private")
        self.expect("隐私中心", "系统权限管理")
        if rid:
            self.click(rid=rid)

    def read_only_retry(self, operation, description):
        """只读页面加载超时后重新进入重试一次，避免首次加载失败误报。"""
        try:
            return operation()
        except AssertionError as exc:
            if "超时" not in str(exc):
                raise
            self.events.append({"action": "retry_read_only_page", "target": description,
                                "reason": self.redact(str(exc))})
            logger.warning("只读页面首次加载超时，重新进入一次: %s", description)
            self.return_settings()
            return operation()

    def system_page_package(self):
        """检测当前是否在系统设置页，返回匹配的包名（兼容 Vivo 等厂商适配）。"""
        activity = self.adb.get_top_activity()
        for package in ("com.android.settings", "com.vivo.systemuiplugin", "com.vivo.permissionmanager"):
            if f"{package}/" in activity:
                return package
        return None

    def document(self, expected_terms=(), timeout=45):
        """校验 WebView 文档正文已加载（非仅标题），可选断言关键词存在。

        判定标准：WebView 内文本长度 ≥ 30 字符（非空文档），
        若指定 expected_terms 则要求至少命中一个关键词。
        不按包名过滤节点，因为 WebView 页面 package 可能不是乘客端。
        """
        errors = ("网页无法打开", "ERR_", "404 Not Found", "502 Bad Gateway", "网络异常", "加载失败")
        def loaded():
            nodes = self.nodes(package=None)
            texts = [node.get("text") or node.get("desc") or "" for node in nodes
                     if "android.webkit.WebView" in node.get("parents", [])
                     and node.get("type") != "android.webkit.WebView"]
            body = "\n".join(dict.fromkeys(texts))
            if any(error in body for error in errors):
                raise AssertionError(f"文档加载错误: {self.redact(body[:250])}")
            return len(body) >= 30 and (not expected_terms or any(term in body for term in expected_terms))
        self.wait(loaded, "文档正文加载（不是仅有标题）", timeout)
        self.events.append({"action": "assert_document_body", "terms": list(expected_terms)})

    @staticmethod
    def redact(text):
        """脱敏处理：将手机号和邮箱替换为占位符，避免敏感信息落盘。"""
        text = re.sub(r"(?<!\d)\d{11}(?!\d)", "[手机号已脱敏]", text)
        return re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[邮箱已脱敏]", text)

    def record(self, name, status, detail=""):
        """记录单条测试结果并写入 results.json 文件。"""
        self.results.append({"case": name, "status": status, "detail": self.redact(detail),
                             "events": list(self.events)})
        self.events.clear()
        report = {"excluded": list(EXCLUDED_TEXT), "results": self.results,
                  "scope": "未新增/删除真实联系人、未开通扣款授权、未撤回隐私协议；对应功能验证入口和取消返回"}
        (self.output / "results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    def evidence(self, name):
        """采集失败页面证据（Activity、文本、事件）并脱敏写入 JSON 文件。"""
        try:
            detail = {"activity": self.adb.get_top_activity(), "texts": sorted(self.texts()), "events": self.events}
            safe = self.redact(json.dumps(detail, ensure_ascii=False, indent=2))
            filename = re.sub(r"[^\w.-]", "_", name)
            (self.output / f"{filename}.json").write_text(safe, encoding="utf-8")
        except Exception:
            logger.exception("设置失败页面证据采集失败")
