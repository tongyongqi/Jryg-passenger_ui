# -*- coding: utf-8 -*-
"""
发放香港优惠券脚本
接口：https://coupon.test.sunlightmobility.hk/jryg-coupon/coupon/send_coupon
"""
import json
import requests
import urllib3
from logger.logger import sys_logger

# 禁用不安全请求警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ================= 配置区域 =================
API_URL = "http://coupon.test.sunlightmobility.hk/jryg-coupon/coupon/send_coupon"
AUTH_TOKEN = "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJleHAiOjE3ODgyNTYzODMsImlzcyI6ImF1dGhfbG9naW4iLCJ1aWQiOjM1ODYsImFkbWluIjpmYWxzZX0.dxQf0YHhIHQQBHmbHXC_9eRZZL0OJ70xDAnvVQnSuIc"

COUPON_INFO_LIST = [
    {"CouponID": 28, "Num": 1}
]

SEND_TYPE = 1       # 发送类型
COUPON_TYPE = 1     # 优惠券类型
REMARK = ""         # 备注说明
SEND_INDEX = 1      # 发送索引
SEND_LIMIT = 5000   # 发送限制
USERS_FILE = ""     # 用户文件


def send_hk_coupon(mobiles, send_num=None):
    sys_logger.info("正在准备发送香港优惠券...")
    
    headers = {
        "Accept": "application/json; charset=utf-8",
        "Authorization": AUTH_TOKEN,
        "Content-Type": "application/json; charset=utf-8",
        "User-Agent": "jryg-admin",
        "Sensitive": "1"
    }
    
    coupon_id = COUPON_INFO_LIST[0]["CouponID"] if COUPON_INFO_LIST else 28
    qty = int(send_num) if send_num is not None else (COUPON_INFO_LIST[0]["Num"] if COUPON_INFO_LIST else 1)
    current_coupon_list = [{"CouponID": coupon_id, "Num": qty}]
    
    coupon_info_str = json.dumps(current_coupon_list)
    
    payload = {
        "SendType": SEND_TYPE,
        "CouponType": COUPON_TYPE,
        "Remark": REMARK,
        "Mobiles": mobiles,
        "SendIndex": SEND_INDEX,
        "SendLimit": SEND_LIMIT,
        "UsersFile": USERS_FILE,
        "CouponInfo": coupon_info_str
    }
    
    sys_logger.info(f"接口地址: {API_URL} | 目标手机: {mobiles} | 发送参数: {current_coupon_list}")
    
    try:
        response = requests.post(API_URL, headers=headers, json=payload, timeout=30)
        sys_logger.info(f"响应状态码: {response.status_code}")
        
        try:
            resp_json = response.json()
            code = resp_json.get("code")
            message = resp_json.get("message")
            if code == 10000:
                sys_logger.info(f"[🎉 SUCCESS] 香港优惠券接口发放指令提交成功！系统提示: {message}")
            else:
                sys_logger.warn(f"发放返回非成功状态码({code}): {message}")
        except ValueError:
            sys_logger.warn(f"响应内容 (非JSON文本): {response.text}")
            
    except requests.exceptions.RequestException as e:
        sys_logger.error(f"发送请求时发生异常: {e}")


if __name__ == "__main__":
    MOBILES = "11000000001"
    send_hk_coupon(MOBILES)
