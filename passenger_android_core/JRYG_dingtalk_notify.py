"""钉钉群通知模块：读取批量运行结果，发送 Markdown 消息到钉钉群。

使用钉钉自定义机器人 Webhook（Outgoing），支持 @ 指定手机号。
Webhook URL 和密钥从环境变量或配置文件读取，不硬编码。
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
import hashlib
import hmac
import base64
import time
import urllib.parse
import urllib.request

LOG = logging.getLogger("JRYG_HK_android")

# 钉钉机器人 Webhook（从环境变量读取，不硬编码）
DINGTALK_WEBHOOK_ENV = "DINGTALK_WEBHOOK"
DINGTALK_SECRET_ENV = "DINGTALK_SECRET"
DINGTALK_AT_MOBILES_ENV = "DINGTALK_AT_MOBILES"


def _get_webhook_url() -> str:
    """从环境变量获取钉钉 Webhook URL。"""
    url = os.environ.get(DINGTALK_WEBHOOK_ENV, "").strip()
    if not url:
        LOG.warning("[钉钉通知] 未设置 %s 环境变量，跳钉钉通知", DINGTALK_WEBHOOK_ENV)
        return ""
    return url


def _get_secret() -> str:
    """从环境变量获取钉钉加签密钥。"""
    return os.environ.get(DINGTALK_SECRET_ENV, "").strip()


def _get_at_mobiles() -> List[str]:
    """从环境变量获取需要 @ 的手机号列表。"""
    raw = os.environ.get(DINGTALK_AT_MOBILES_ENV, "").strip()
    if not raw:
        return []
    return [m.strip() for m in raw.split(",") if m.strip()]


def _sign_url(webhook: str, secret: str) -> str:
    """钉钉加签：计算 timestamp + secret 的 HMAC-SHA256 签名，拼接到 Webhook URL。"""
    timestamp = str(round(time.time() * 1000))
    string_to_sign = f"{timestamp}\n{secret}"
    hmac_code = hmac.new(
        secret.encode("utf-8"),
        string_to_sign.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()
    sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
    separator = "&" if "?" in webhook else "?"
    return f"{webhook}{separator}timestamp={timestamp}&sign={sign}"


def _send_message(webhook: str, payload: Dict) -> bool:
    """发送 HTTP POST 请求到钉钉 Webhook。"""
    url = webhook
    secret = _get_secret()
    if secret:
        url = _sign_url(webhook, secret)
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json; charset=utf-8"}
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode("utf-8")
            result = json.loads(body)
            errcode = result.get("errcode", -1)
            if errcode == 0:
                LOG.info("[钉钉通知] 发送成功")
                return True
            LOG.error("[钉钉通知] 发送失败：errcode=%s, errmsg=%s", errcode, result.get("errmsg"))
            return False
    except Exception as exc:
        LOG.error("[钉钉通知] 发送异常：%s", exc)
        return False


def _format_markdown(batch_result: Dict) -> str:
    """将 batch_result.json 转换为钉钉 Markdown 消息内容。"""
    exit_code = batch_result.get("exit_code", -1)
    cases: List[Dict] = batch_result.get("cases", [])
    total = len(cases)
    passed = sum(1 for c in cases if c.get("status") == "passed")
    failed = sum(1 for c in cases if c.get("status") in ("failed", "interrupted"))
    not_run = total - passed - failed

    status_emoji = "全部通过" if exit_code == 0 else "存在失败"
    overall = f"{'pass' if exit_code == 0 else 'FAIL'}"

    lines = [
        f"### 香港乘客端Android六场景自动化 {status_emoji}",
        "",
        f"> **总览**：{overall} | 通过 {passed}/{total} | 失败 {failed} | 未运行 {not_run}",
        "",
        "| # | 场景 | 状态 | 订单号 | 开始 | 完成 |",
        "|:---:|:---|:---:|:---:|:---:|:---:|",
    ]

    case_display = {
        "JRYG_test_android_charter_alipay_order.py::TestCharterAlipayAndroid::test_order_flow": "charter_alipay",
        "JRYG_test_android_charter_bankcard_order.py::TestCharterBankcardAndroid::test_order_flow": "charter_bankcard",
        "JRYG_test_android_meter_cash_order.py::TestMeterCashAndroid::test_order_flow": "meter_cash",
        "JRYG_test_android_meter_epayment_bankcard_order.py::TestMeterEpaymentBankcardAndroid::test_order_flow": "meter_epayment_bankcard",
        "JRYG_test_android_meter_epayment_alipay_order.py::TestMeterEpaymentAlipayAndroid::test_order_flow": "meter_epayment_alipay",
        "JRYG_test_android_meter_alipay_order.py::TestMeterAlipayAndroid::test_order_flow": "meter_alipay",
    }

    for case in cases:
        seq = case.get("sequence", "")
        case_file = case.get("case", "")
        name = case_display.get(case_file, Path(case_file).stem)
        status = case.get("status", "unknown")
        order_no = case.get("order_no", "-")
        started = case.get("started_at", "-")
        finished = case.get("finished_at", "-")
        status_icon = {"passed": "PASS", "failed": "FAIL", "interrupted": "STOP", "not_run": "--"}.get(status, status)
        lines.append(f"| {seq} | {name} | {status_icon} | {order_no} | {started} | {finished} |")

    lines.append("")
    lines.append(f"> 时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    at_mobiles = _get_at_mobiles()
    if at_mobiles and exit_code != 0:
        lines.append("")
        at_text = " ".join(f"@{m}" for m in at_mobiles)
        lines.append(f"> {at_text}")

    return "\n".join(lines)


def send_batch_result(batch_result_path: str) -> bool:
    """读取批量结果 JSON 文件并发送钉钉通知。

    :param batch_result_path: batch_result.json 的路径
    :return: True 表示发送成功，False 表示发送失败或跳过
    """
    webhook = _get_webhook_url()
    if not webhook:
        LOG.info("[钉钉通知] 未配置 Webhook，跳过钉钉通知")
        return False

    result_file = Path(batch_result_path)
    if not result_file.is_file():
        LOG.warning("[钉钉通知] 批量结果文件不存在：%s", result_file)
        return False

    try:
        batch_result = json.loads(result_file.read_text(encoding="utf-8"))
    except Exception as exc:
        LOG.error("[钉钉通知] 解析批量结果失败：%s", exc)
        return False

    markdown_text = _format_markdown(batch_result)

    at_mobiles = _get_at_mobiles()
    payload = {
        "msgtype": "markdown",
        "markdown": {"title": "香港Android六场景自动化结果", "text": markdown_text},
        "at": {
            "atMobiles": at_mobiles,
            "isAtAll": False,
        },
    }

    return _send_message(webhook, payload)


def send_text(text: str, *, at_all: bool = False, at_mobiles: Optional[List[str]] = None) -> bool:
    """发送纯文本消息到钉钉群。

    :param text: 文本内容
    :param at_all: 是否 @ 所有人
    :param at_mobiles: 指定 @ 的手机号列表
    :return: True 表示发送成功
    """
    webhook = _get_webhook_url()
    if not webhook:
        LOG.info("[钉钉通知] 未配置 Webhook，跳过钉钉通知")
        return False

    mobiles = at_mobiles if at_mobiles is not None else _get_at_mobiles()
    payload = {
        "msgtype": "text",
        "text": {"content": text},
        "at": {
            "atMobiles": mobiles,
            "isAtAll": at_all,
        },
    }
    return _send_message(webhook, payload)
