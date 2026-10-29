"""有界读取 iOS 页面，识别登录状态并保存卡点现场。

两层结构：
  - IOSPage        ：对一次页面树快照的封装，负责文本提取与状态识别。
  - IOSPageMonitor ：负责实际请求 WDA、保存页面树/截图、提供等待与点击能力。

设计约束：
  - 读取必须有超时上限，不能因页面卡死而无限等待。
  - 状态识别只依据页面可见文本，任何未知情况都返回 "unknown" 而非猜测。
"""

import base64
import logging
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlparse

import requests

logger = logging.getLogger("JRYG_HK_ios")


class IOSPage:
    """单次页面树快照，封装可见节点、文本与状态判定。"""

    def __init__(self, source):
        """解析页面树 XML，提取可见节点、去重文本并建立状态判定基础。"""
        # 原始 XML 字符串，卡点保存时原样落盘
        self.source = source
        # 解析后的根节点
        self.root = ET.fromstring(source)
        # 只保留 visible != false 的节点，避免点到隐藏控件
        self.nodes = [node for node in self.root.iter()
                      if node.get("visible", "true") != "false"]
        # 去重后的可见文本，保留出现顺序
        self.texts = tuple(dict.fromkeys(
            value.strip() for node in self.nodes
            for key in ("label", "name", "value")
            for value in [node.get(key, "")] if value.strip()
        ))
        # 拼接文本，便于做子串匹配
        self.text = " ".join(self.texts)

    def has(self, *texts):
        """判断页面是否包含任一给定文本（简体/繁体混用时可同时传入）。"""
        return any(text in self.text for text in texts)

    def has_type(self, name):
        """判断是否存在指定类型的控件，如 TextField、Alert、Button。"""
        return any(node.tag.endswith(name) or node.get("type", "").endswith(name)
                   for node in self.nodes)

    @property
    def accounts(self):
        """提取页面上的脱敏账号文本，如 ******1727 或 8 位数字。"""
        return [text for text in self.texts if re.fullmatch(r"\d*\*{2,}\d{2,4}|\d{8}", text)]

    def matches_account(self, phone):
        """判断脱敏账号与目标手机号是否一致（星号位置视为通配）。

        用于确认当前登录的是测试账号，避免误操作他人订单。
        """
        return any(len(account) == len(phone) and all(
            shown == "*" or shown == digit for shown, digit in zip(account, phone)
        ) for account in self.accounts)

    @property
    def state(self):
        """识别当前页面状态。

        判断顺序有讲究：登录页特征优先于活动弹窗，
        订单进行中/已取消/已完成等状态也必须在首页特征之前判断。
        无法确定时返回 "unknown"，由调用方决定下一步。
        """
        # 系统级弹窗优先
        if self.has_type("Alert"):
            return "permission_dialog"
        # 登录页元素优先（登录页也可能含有 icon hd gb，不能误判为活动弹窗）
        if self.has("取得驗證碼", "获取验证码", "獲取驗證碼", "請輸入手機號", "请输入手机号"):
            return "login_phone_input"
        if self.has("請輸入驗證碼", "请输入验证码", "重新獲取", "重新获取", "重新發送", "重新发送"):
            return "login_code_input"
        if self.has("登錄/註冊", "登录/注册", "登入/註冊"):
            return "mine_unlogged"
        if self.has("歡迎登錄", "欢迎登录"):
            return "login_phone_input"
        if "icon hd gb" in self.texts:
            # icon hd gb 在个人中心和活动弹窗中都存在，
            # 只有没有其他主要页面特征时才判为活动弹窗
            if not (self.has("我的行程", "想去哪", "想去邊", "確認呼叫", "确认呼叫",
                             "取得驗證碼", "請輸入驗證碼", "訂單進行中")):
                return "activity_popup"
        if self.has("不同意", "拒絕", "拒绝") and "同意" in self.texts:
            return "privacy_agreement"
        if self.accounts and self.has("我的行程", "slm icon mine setting"):
            return "mine_logged"
        if self.has("去授權", "去授权"):
            return "permission_dialog"
        if self.has("司機正在趕來", "正在為您優先調度", "訂單進行中", "進行中的訂單", "筆訂單進行中"):
            return "order_active"
        if self.has("未能查閱到付款記錄", "付款失敗"):
            return "payment_failed"
        if self.has("訂單已取消", "订单已取消", "已取消", "重新下單", "重新下单"):
            return "order_cancelled"
        if self.has("行程結束", "行程结束") or (
                "已完成" in self.texts and self.has("訂單編號", "订单编号", "服務完成時間")):
            return "order_complete"
        if self.has("確認呼叫", "确认呼叫", "立即呼叫"):
            return "route_selected"
        if self.has_type("TextField") and self.has("取消", "搜尋", "搜索"):
            return "address_search"
        if self.has("想去哪", "想去邊", "要去邊", "輸入目的地", "输入目的地"):
            # 首页：已登录和未登录都显示"想去哪裡"，通过是否有底部"我的"tab 判断
            # 个人中心已登录时 accounts 非空，但首页也可能缓存了账号信息
            # 简化处理：首页统一返回 home_unlogged，登录态由个人中心确认
            return "home_unlogged"
        return "unknown"


class IOSPageMonitor:
    """页面监控器：读取页面树、保存卡点现场、等待状态、点击文本。"""

    def __init__(self, wda_url, output_dir, request_timeout=12):
        """初始化 WDA 地址、卡点输出目录与请求超时，并准备 HTTP 会话。"""
        # WDA 基地址，去掉结尾斜杠便于拼接路径
        self.url = wda_url.rstrip("/")
        # 卡点文件输出目录
        self.output_dir = Path(output_dir)
        # 单次请求读超时上限
        self.request_timeout = request_timeout
        # 复用连接减少握手开销
        self.http = requests.Session()
        if urlparse(self.url).hostname in ("localhost", "127.0.0.1", "::1"):
            # 本地 WDA 不走系统代理，避免代理导致连接失败
            self.http.trust_env = False
        # 最近一次读取的页面，便于卡点时保存原始 XML
        self.last_page = None

    def close(self):
        """关闭底层 HTTP 连接。"""
        self.http.close()

    def _get(self, path, timeout=None):
        """向 WDA 发起 GET 请求并返回 data 中的 value 字段。

        连接超时固定 3 秒，读超时可按需收紧，避免长时间挂起。
        """
        response = self.http.get(self.url + path, timeout=(3, timeout or self.request_timeout))
        response.raise_for_status()
        data = response.json()
        value = data.get("value")
        # WDA 用 status!=0 或 value.error 表示失败，必须显式检查
        if data.get("status", 0) != 0 or isinstance(value, dict) and value.get("error"):
            raise RuntimeError(f"WDA 页面请求失败: {value}")
        return value

    def inspect(self, timeout=None):
        """读取当前页面树并包装成 IOSPage。"""
        self.last_page = IOSPage(self._get("/source?format=xml", timeout))
        logger.info("[页面检测] state=%s", self.last_page.state)
        return self.last_page

    def capture(self, reason):
        """保存卡点现场（页面树 XML + 截图 PNG）。

        任一环节失败只记录警告，不覆盖原始异常。
        """
        # 名称清洗并截断，避免文件名过长或含非法字符
        name = re.sub(r"[^\w.-]+", "_", reason)[:70]
        target = self.output_dir / f"{time.time_ns()}_{name}"
        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            if self.last_page is not None:
                target.with_suffix(".xml").write_text(self.last_page.source, encoding="utf-8")
        except OSError as exc:
            logger.warning("页面树保存失败，不覆盖原始错误: %s", exc)
        try:
            image = base64.b64decode(self._get("/screenshot", timeout=5), validate=True)
            # 校验 PNG magic bytes，防止把错误页当图片保存
            if not image.startswith(b"\x89PNG\r\n\x1a\n"):
                raise ValueError("WDA 未返回 PNG 截图")
            target.with_suffix(".png").write_bytes(image)
        except Exception as exc:
            logger.warning("卡点截图失败，不覆盖原始错误: %s", exc)
        logger.error("[卡点现场] %s", target)
        return target

    def click_text(self, client, *texts):
        """按文本点击页面上第一个可见、可用的控件。

        只点击尺寸大于 0 的控件，避免点到不可见占位元素。
        找到并点击返回 True，否则返回 False。
        """
        page = self.inspect()
        for node in page.nodes:
            # 跳过被禁用的控件
            if node.get("enabled", "true") == "false":
                continue
            # 文本需精确匹配 label/name/value
            if not any(node.get(key) in texts for key in ("label", "name", "value")):
                continue
            width, height = float(node.get("width", 0)), float(node.get("height", 0))
            # 尺寸为 0 表示不可见/不可点
            if width <= 0 or height <= 0:
                continue
            # 点击控件中心点
            client.click(int(float(node.get("x", 0)) + width / 2),
                         int(float(node.get("y", 0)) + height / 2))
            logger.info("[页面操作] 点击可见控件 %s", texts)
            return True
        return False

    def dismiss_activity_popup(self, client):
        """关闭活动弹窗/全屏广告。广告可能有多页，需多次点击关闭按钮。"""
        # 最多尝试 4 次，覆盖多页广告
        for attempt in range(4):
            page = self.inspect()
            if page.state != "activity_popup":
                return
            logger.info("[自动恢复] 关闭活动弹窗 icon hd gb (尝试 %d)", attempt + 1)
            if not self.click_text(client, "icon hd gb"):
                # 兜底：直接坐标点击（广告关闭按钮常见位置）
                client.click(196, 653)
            time.sleep(1.5)
        # 最终检查
        page = self.inspect()
        if page.state != "activity_popup":
            logger.info("[自动恢复] 活动弹窗已关闭")
            return
        logger.warning("[自动恢复] 活动弹窗多次点击仍未关闭")

    def wait_for(self, description, predicate, timeout=30, interval=1, recover=None):
        """轮询等待页面满足条件，超时抛出带现场证据的断言错误。

        recover 用于等待期间自动处理遮挡弹窗；
        单次读取失败只记录警告并继续轮询，不立即中断。
        """
        deadline = time.monotonic() + timeout
        last_error = None
        while time.monotonic() < deadline:
            try:
                # 剩余时间过短时仍保留最小读超时，避免 WDA 请求被压缩到 0.1s 而白白浪费轮次
                remaining = deadline - time.monotonic()
                read_timeout = min(self.request_timeout, max(3.0, remaining))
                page = self.inspect(timeout=read_timeout)
                if predicate(page):
                    return page
                if recover is not None:
                    recover(page)
            except (requests.RequestException, ET.ParseError, ValueError, RuntimeError) as exc:
                # 记录最后一次错误，作为超时信息的一部分
                last_error = exc
                logger.warning("[页面检测] %s: %s", description, exc)
            time.sleep(min(interval, max(0, deadline - time.monotonic())))
        # 超时：记录当前状态并保存现场，再抛断言错误
        state = self.last_page.state if self.last_page else "unavailable"
        evidence = self.capture(description)
        raise AssertionError(f"{description} 超时({timeout}s)，当前页面={state}，最后错误={last_error}，现场={evidence}")
