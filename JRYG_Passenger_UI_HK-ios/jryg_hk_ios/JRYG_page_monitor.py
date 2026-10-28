"""有界读取 iOS 页面，识别登录状态并保存卡点现场。"""

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
    def __init__(self, source):
        self.source = source
        self.root = ET.fromstring(source)
        self.nodes = [node for node in self.root.iter()
                      if node.get("visible", "true") != "false"]
        self.texts = tuple(dict.fromkeys(
            value.strip() for node in self.nodes
            for key in ("label", "name", "value")
            for value in [node.get(key, "")] if value.strip()
        ))
        self.text = " ".join(self.texts)

    def has(self, *texts):
        return any(text in self.text for text in texts)

    def has_type(self, name):
        return any(node.tag.endswith(name) or node.get("type", "").endswith(name)
                   for node in self.nodes)

    @property
    def accounts(self):
        return [text for text in self.texts if re.fullmatch(r"\d*\*{2,}\d{2,4}|\d{8}", text)]

    def matches_account(self, phone):
        return any(len(account) == len(phone) and all(
            shown == "*" or shown == digit for shown, digit in zip(account, phone)
        ) for account in self.accounts)

    @property
    def state(self):
        if self.has_type("Alert"):
            return "permission_dialog"
        if "icon hd gb" in self.texts:
            return "activity_popup"
        if self.has("不同意", "拒絕", "拒绝") and "同意" in self.texts:
            return "privacy_agreement"
        if self.has("取得驗證碼", "获取验证码", "獲取驗證碼", "請輸入手機號", "请输入手机号"):
            return "login_phone_input"
        if self.has("請輸入驗證碼", "请输入验证码", "重新獲取", "重新获取", "重新發送", "重新发送"):
            return "login_code_input"
        if self.has("登錄/註冊", "登录/注册", "登入/註冊"):
            return "mine_unlogged"
        if self.accounts and self.has("我的行程", "slm icon mine setting"):
            return "mine_logged"
        if self.has("去授權", "去授权"):
            return "permission_dialog"
        if self.has("確認呼叫", "确认呼叫", "立即呼叫"):
            return "route_selected"
        if self.has_type("TextField") and self.has("取消", "搜尋", "搜索"):
            return "address_search"
        if self.has("想去哪", "想去邊", "要去邊", "輸入目的地", "输入目的地"):
            return "home_unlogged"
        return "unknown"


class IOSPageMonitor:
    def __init__(self, wda_url, output_dir, request_timeout=12):
        self.url = wda_url.rstrip("/")
        self.output_dir = Path(output_dir)
        self.request_timeout = request_timeout
        self.http = requests.Session()
        if urlparse(self.url).hostname in ("localhost", "127.0.0.1", "::1"):
            self.http.trust_env = False
        self.last_page = None

    def close(self):
        self.http.close()

    def _get(self, path, timeout=None):
        response = self.http.get(self.url + path, timeout=(3, timeout or self.request_timeout))
        response.raise_for_status()
        data = response.json()
        value = data.get("value")
        if data.get("status", 0) != 0 or isinstance(value, dict) and value.get("error"):
            raise RuntimeError(f"WDA 页面请求失败: {value}")
        return value

    def inspect(self, timeout=None):
        self.last_page = IOSPage(self._get("/source?format=xml", timeout))
        logger.info("[页面检测] state=%s", self.last_page.state)
        return self.last_page

    def capture(self, reason):
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
            if not image.startswith(b"\x89PNG\r\n\x1a\n"):
                raise ValueError("WDA 未返回 PNG 截图")
            target.with_suffix(".png").write_bytes(image)
        except Exception as exc:
            logger.warning("卡点截图失败，不覆盖原始错误: %s", exc)
        logger.error("[卡点现场] %s", target)
        return target

    def click_text(self, client, *texts):
        page = self.inspect()
        for node in page.nodes:
            if node.get("enabled", "true") == "false":
                continue
            if not any(node.get(key) in texts for key in ("label", "name", "value")):
                continue
            width, height = float(node.get("width", 0)), float(node.get("height", 0))
            if width <= 0 or height <= 0:
                continue
            client.click(int(float(node.get("x", 0)) + width / 2),
                         int(float(node.get("y", 0)) + height / 2))
            logger.info("[页面操作] 点击可见控件 %s", texts)
            return True
        return False

    def dismiss_activity_popup(self, client):
        page = self.inspect()
        if page.state == "activity_popup":
            logger.info("[自动恢复] 关闭活动弹窗 icon hd gb")
            assert self.click_text(client, "icon hd gb"), "活动弹窗关闭按钮不可见"
            self.wait_for("关闭活动弹窗", lambda current: current.state != "activity_popup", timeout=15)

    def wait_for(self, description, predicate, timeout=30, interval=1, recover=None):
        deadline = time.monotonic() + timeout
        last_error = None
        while time.monotonic() < deadline:
            try:
                page = self.inspect(timeout=min(self.request_timeout, max(0.1, deadline - time.monotonic())))
                if predicate(page):
                    return page
                if recover is not None:
                    recover(page)
            except (requests.RequestException, ET.ParseError, ValueError, RuntimeError) as exc:
                last_error = exc
                logger.warning("[页面检测] %s: %s", description, exc)
            time.sleep(min(interval, max(0, deadline - time.monotonic())))
        state = self.last_page.state if self.last_page else "unavailable"
        evidence = self.capture(description)
        raise AssertionError(f"{description} 超时({timeout}s)，当前页面={state}，最后错误={last_error}，现场={evidence}")
