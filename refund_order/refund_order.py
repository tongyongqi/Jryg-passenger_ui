# -*- coding: utf-8 -*-
# 这个文件的功能是通过接口执行订单退款操作的代码
"""
==========================================================================
🌐 优惠券与工单自动化调度系统 - 接口退款模块 (refund_order.py)
==========================================================================
本模块通过直接调用后端退款接口完成订单退款操作，无需浏览器自动化。
每次运行前在 config_business.py 中修改 REFUND 参数即可。

依赖引入：
  - config_business: 提供退款业务参数（订单号、退款金额等）
  - refund_order_logger: 提供统一持久化日志落盘
"""

import json
import requests

import config_business
from logger.refund_order_logger import refund_order_logger as sys_logger


def apply_refund(refund_config: dict = None):
    """
    调用退款接口，对指定订单发起退款申请。
    参数通过 refund_config 字典传入，每次运行前在 run_work_order.py 中修改即可。
    """
    if refund_config is None:
        refund_config = config_business.REFUND
    order_id = refund_config["order_id"]
    order_no = refund_config["order_no"]
    refund_amount = refund_config["refund_amount"]
    refund_reason = refund_config["refund_reason"]
    work_id = refund_config["work_id"]

    url = config_business.REFUND_API_URL

    sys_logger.info("=" * 60)
    sys_logger.info(f"开始执行接口退款，订单号: {order_id}, 订单编号: {order_no}")
    sys_logger.info(f"退款金额: {refund_amount} 分, 退款原因: {refund_reason}, 工单ID: {work_id}")
    sys_logger.info(f"请求接口: {url}")

    # 构建请求体
    payload = {
        "order_id": order_id,
        "order_no": order_no,
        "refund_amount": refund_amount,
        "refund_reason": refund_reason,
        "work_id": work_id
    }

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    try:
        sys_logger.info(f"请求参数: {json.dumps(payload, ensure_ascii=False)}")
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        sys_logger.info(f"HTTP 状态码: {response.status_code}")

        try:
            resp_json = response.json()
        except Exception:
            resp_json = response.text

        sys_logger.info(f"响应内容: {resp_json}")

        # 判断接口返回是否成功
        if isinstance(resp_json, dict):
            code = resp_json.get("code")
            if code == 10000 or code == "10000":
                sys_logger.info(f"[✅] 订单 {order_id} 退款成功！")
            else:
                sys_logger.error(f"[❌] 订单 {order_id} 退款失败，返回码: {code}, 消息: {resp_json.get('msg', resp_json.get('message', ''))}")
        else:
            sys_logger.error(f"[❌] 订单 {order_id} 退款失败，响应非 JSON: {resp_json}")

        return resp_json

    except requests.exceptions.Timeout:
        sys_logger.error(f"[❌] 请求退款接口超时！请检查网络或服务可用性。")
        return None
    except requests.exceptions.ConnectionError as e:
        sys_logger.error(f"[❌] 连接退款接口失败: {e}")
        return None
    except Exception as e:
        sys_logger.error(f"[❌] 退款接口调用异常: {e}")
        return None
    finally:
        sys_logger.info("=" * 60)


if __name__ == "__main__":
    apply_refund()
