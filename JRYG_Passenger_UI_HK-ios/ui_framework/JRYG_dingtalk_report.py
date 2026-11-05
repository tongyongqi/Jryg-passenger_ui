"""香港iOS批次结束后的脱敏钉钉摘要；通知失败不改变订单测试结果。"""

import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib.parse import parse_qs, urlparse

import requests


KEYCHAIN_SERVICE = "jryg-hk-ios:dingtalk"
CASE_LABELS = {
    "JRYG_test_ios_charter_alipay_order.py": "包车＋Alipay HK",
    "JRYG_test_ios_charter_bankcard_order.py": "包车＋银行卡",
    "JRYG_test_ios_meter_cash_order.py": "打表＋现金",
    "JRYG_test_ios_meter_epayment_bankcard_order.py": "打表＋电子支付后付银行卡",
    "JRYG_test_ios_meter_epayment_alipay_order.py": "打表＋电子支付后付Alipay HK",
    "JRYG_test_ios_meter_alipay_order.py": "打表＋直接Alipay HK",
}
STATUS_LABELS = {"passed": "通过", "failed": "失败", "interrupted": "中断", "not_run": "未运行"}


def robot_credentials():
    webhook = os.environ.get("HK_IOS_DINGTALK_WEBHOOK")
    secret = os.environ.get("HK_IOS_DINGTALK_SECRET")
    if webhook or secret:
        if not webhook or not secret:
            raise ValueError("钉钉环境变量必须同时配置Webhook和Secret")
    elif sys.platform == "darwin":
        result = subprocess.run(
            ["/usr/bin/security", "find-generic-password", "-a", "robot",
             "-s", KEYCHAIN_SERVICE, "-w"],
            capture_output=True, text=True, timeout=15, check=False,
        )
        if result.returncode != 0:
            raise RuntimeError("钉钉钥匙串凭据缺失或未获访问授权")
        value = json.loads(result.stdout)
        webhook, secret = value.get("webhook"), value.get("secret")
    else:
        raise RuntimeError("请配置钉钉Webhook和Secret环境变量")
    if not isinstance(webhook, str) or not isinstance(secret, str) or not secret.startswith("SEC"):
        raise ValueError("钉钉加签机器人配置无效")
    url = urlparse(webhook)
    if (url.scheme != "https" or url.netloc != "oapi.dingtalk.com"
            or url.path != "/robot/send" or url.fragment
            or not parse_qs(url.query).get("access_token")):
        raise ValueError("钉钉Webhook地址无效")
    return webhook, secret


def report_payload(summary_file):
    path = Path(summary_file)
    summary = json.loads(path.read_text(encoding="utf-8"))
    rows = summary["cases"]
    counts = {status: sum(row.get("status") == status for row in rows) for status in STATUS_LABELS}
    if any(row.get("status") not in STATUS_LABELS for row in rows):
        raise ValueError("批次包含未结束状态，不能发送最终报告")
    title = "香港iOS UI自动化报告：%s通过、%s失败、%s未运行、%s中断" % (
        counts["passed"], counts["failed"], counts["not_run"], counts["interrupted"],
    )
    exit_code = int(summary["exit_code"])
    overall = "已中断" if exit_code >= 128 else "全部通过" if exit_code == 0 else "失败或未完成"
    batch_name = path.parent.name
    batch_label = batch_name if re.fullmatch(r"[0-9]{8}_[0-9]{6}_[0-9]{6}", batch_name) else "本次执行"
    lines = ["### 香港iOS UI自动化报告", "", "- 批次：" + batch_label,
             "- 批次结果：" + overall,
             "- 总计：%s个场景" % len(rows),
             "- 通过：%s｜失败：%s｜未运行：%s｜中断：%s" % (
                 counts["passed"], counts["failed"], counts["not_run"], counts["interrupted"]),
             "", "#### 场景结果"]
    for index, row in enumerate(rows, 1):
        label = CASE_LABELS.get(row.get("case"), "场景%s" % index)
        lines.append("- %s：%s" % (label, STATUS_LABELS[row["status"]]))
    if exit_code != 0 or counts["failed"] or counts["interrupted"]:
        lines.extend(["", "测试失败或中断后已停止后续场景；支付状态请核对原报告和当前交易，勿直接重付。"])
    lines.extend(["", "消息为本次执行的报告摘要，完整HTML保存在运行电脑的report/batches目录。",
                  "本地文件尚未托管，未附加HTML/ZIP；账号、卡号、验证码及原始异常不发送到群内。"])
    return {"msgtype": "markdown", "markdown": {"title": title, "text": "\n".join(lines)},
            "at": {"isAtAll": False}}


def send_report(summary_file):
    webhook, secret = robot_credentials()
    payload = report_payload(summary_file)
    timestamp = str(int(time.time() * 1000))
    signature = base64.b64encode(hmac.new(
        secret.encode("utf-8"), (timestamp + "\n" + secret).encode("utf-8"), hashlib.sha256,
    ).digest()).decode("ascii")
    with requests.Session() as session:
        session.mount("https://", requests.adapters.HTTPAdapter(max_retries=0))
        response = session.post(webhook, params={"timestamp": timestamp, "sign": signature},
                                json=payload, timeout=(5, 15), allow_redirects=False)
        if response.status_code != 200:
            return {"status": "unconfirmed", "http_status": int(response.status_code)}
        code = response.json().get("errcode")
        if not isinstance(code, int):
            return {"status": "unconfirmed"}
        return {"status": "sent" if code == 0 else "rejected", "errcode": code}


def notify_batch(summary_file):
    if os.environ.get("HK_IOS_DINGTALK_ENABLED", "1").lower() in ("0", "false", "no"):
        result = {"status": "disabled"}
    else:
        try:
            result = send_report(summary_file)
        except KeyboardInterrupt:
            result = {"status": "unconfirmed", "error_type": "KeyboardInterrupt"}
        except Exception as exc:
            result = {"status": "unconfirmed", "error_type": type(exc).__name__}
    if result["status"] == "sent":
        print("[钉钉报告] 已发送本次批次摘要。", flush=True)
    elif result["status"] == "disabled":
        print("[钉钉报告] 已关闭本次通知。", flush=True)
    else:
        print("[钉钉报告] 发送未确认成功；不自动重发，不影响测试退出码。", flush=True)
    try:
        Path(summary_file).with_name("dingtalk_result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8",
        )
    except OSError:
        print("[钉钉报告] 通知状态文件保存失败，不影响测试报告。", flush=True)
    return result
