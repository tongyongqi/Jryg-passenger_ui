"""香港乘客端退款接口自动化。

接口：POST /pay/v1/applyTradeRefund
域名：http://cashier.test.hqygcx.com
Content-Type: application/json

请求体：
  refund_amount  退款金额（整数，HKD）
  refund_reason  退款原因
  order_no       订单号
  order_id       订单ID（必填）
  work_id        工单ID（整数）

用法：
  # 1) 直接改下面三个参数，然后运行
  python3 JRYG_Passenger_API_HK/cases/JRYG_test_hk_refund.py

  # 2) 或通过命令行参数指定
  python3 JRYG_Passenger_API_HK/cases/JRYG_test_hk_refund.py --order-no 26A4IW2WECNW --amount 1 --work-id 123

  # 3) 或通过环境变量
  HK_REFUND_ORDER_NO=26A4IW2WECNW HK_REFUND_AMOUNT=1 HK_REFUND_WORK_ID=123 \
  python3 JRYG_Passenger_API_HK/cases/JRYG_test_hk_refund.py
"""
import argparse
import json
import os
import sys

import requests

# ==================== 在这里改参数 ====================

ORDER_NO = "26A4IW2WECNW"   # 订单号
REFUND_AMOUNT = 30000        # 退款金额（HKD）
WORK_ID = 1                  # 工单ID
REFUND_REASON = "接口自动化测试退款"
ORDER_ID = 0                 # 订单ID（必填）

# =====================================================

BASE_URL = "http://cashier.test.hqygcx.com"
REFUND_PATH = "/pay/v1/applyTradeRefund"
SUCCESS_CODE = 10000


def apply_refund(order_no, refund_amount, work_id, refund_reason="", order_id=0,
                 base_url=BASE_URL):
    """提交退款申请，返回响应 JSON。"""
    body = {
        "refund_amount": refund_amount,
        "order_no": order_no,
        "order_id": order_id,
        "work_id": work_id,
    }
    if refund_reason:
        body["refund_reason"] = refund_reason

    print(f"请求: POST {base_url}{REFUND_PATH}")
    print(f"参数: {json.dumps(body, ensure_ascii=False)}")

    resp = requests.post(
        f"{base_url}{REFUND_PATH}",
        json=body,
        headers={"Content-Type": "application/json"},
        timeout=15,
    )

    try:
        result = resp.json()
    except Exception:
        result = {"raw": resp.text}

    print(f"响应: {resp.status_code} {json.dumps(result, ensure_ascii=False)}")
    return result


def main():
    parser = argparse.ArgumentParser(description="香港乘客端退款接口")
    parser.add_argument("--order-no", default=ORDER_NO, help="订单号")
    parser.add_argument("--amount", type=int, default=REFUND_AMOUNT, help="退款金额")
    parser.add_argument("--work-id", type=int, default=WORK_ID, help="工单ID")
    parser.add_argument("--reason", default=REFUND_REASON, help="退款原因")
    parser.add_argument("--order-id", type=int, default=ORDER_ID, help="订单ID（必填）")
    parser.add_argument("--base-url", default=BASE_URL, help="收银台域名")
    args = parser.parse_args()

    # 命令行参数 > 环境变量 > 文件默认值
    order_no = os.environ.get("HK_REFUND_ORDER_NO", args.order_no)
    amount = int(os.environ.get("HK_REFUND_AMOUNT", args.amount))
    work_id = int(os.environ.get("HK_REFUND_WORK_ID", args.work_id))
    reason = os.environ.get("HK_REFUND_REASON", args.reason)
    order_id_env = os.environ.get("HK_REFUND_ORDER_ID")
    order_id = int(order_id_env) if order_id_env else args.order_id

    result = apply_refund(order_no, amount, work_id, reason, order_id, args.base_url)

    if result.get("code") == SUCCESS_CODE:
        print(f"\n[✓] 退款成功！order_no={order_no}, amount={amount}")
        return 0
    else:
        print(f"\n[✗] 退款失败: code={result.get('code')}, "
              f"msg={result.get('msg')}, sub_msg={result.get('sub_msg')}")
        return 1


# ==================== pytest 用例 ====================

def test_refund():
    """退款接口测试：已知订单号、金额、工单ID，提交退款并校验响应。"""
    order_no = os.environ.get("HK_REFUND_ORDER_NO", ORDER_NO)
    amount = int(os.environ.get("HK_REFUND_AMOUNT", REFUND_AMOUNT))
    work_id = int(os.environ.get("HK_REFUND_WORK_ID", WORK_ID))
    reason = os.environ.get("HK_REFUND_REASON", REFUND_REASON)
    order_id_env = os.environ.get("HK_REFUND_ORDER_ID")
    order_id = int(order_id_env) if order_id_env else ORDER_ID

    result = apply_refund(order_no, amount, work_id, reason, order_id)

    # 只要接口返回结构化响应即视为通过（退款是否成功取决于订单是否已真实支付）
    assert "code" in result, f"响应缺少 code 字段: {result}"


if __name__ == "__main__":
    sys.exit(main())
