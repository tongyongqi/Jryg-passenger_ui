# -*- coding: utf-8 -*-
"""
发放香港优惠券脚本
接口：https://coupon.test.sunlightmobility.hk/jryg-coupon/coupon/send_coupon
"""
import json
import requests
import urllib3

# 禁用不安全请求警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ================= 配置区域 =================
# 接口地址 (由于本地环境与远端 SSL 握手存在兼容性限制，推荐使用 HTTP 协议，更加稳健高效)
API_URL = "http://coupon.test.sunlightmobility.hk/jryg-coupon/coupon/send_coupon"

# 鉴权 Token (Bearer Token)
AUTH_TOKEN = "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJleHAiOjE3ODgyNTYzODMsImlzcyI6ImF1dGhfbG9naW4iLCJ1aWQiOjM1ODYsImFkbWluIjpmYWxzZX0.dxQf0YHhIHQQBHmbHXC_9eRZZL0OJ70xDAnvVQnSuIc"

# 优惠券配置：[{"CouponID": 28, "Num": 1}]
COUPON_INFO_LIST = [
    {"CouponID": 28, "Num": 1}
]

# 其他发送参数
SEND_TYPE = 1       # 发送类型
COUPON_TYPE = 1     # 优惠券类型
REMARK = ""         # 备注说明
SEND_INDEX = 1      # 发送索引
SEND_LIMIT = 5000   # 发送限制
USERS_FILE = ""     # 用户文件


def send_hk_coupon(mobiles, send_num=None):
    print("[*] 正在准备发送香港优惠券...")
    
    # 构建请求头
    headers = {
        "Accept": "application/json; charset=utf-8",
        "Authorization": AUTH_TOKEN,
        "Content-Type": "application/json; charset=utf-8",
        "User-Agent": "jryg-admin",
        "Sensitive": "1"
    }
    
    # 支持外部参数传入重写发送张数
    coupon_id = COUPON_INFO_LIST[0]["CouponID"] if COUPON_INFO_LIST else 28
    qty = int(send_num) if send_num is not None else (COUPON_INFO_LIST[0]["Num"] if COUPON_INFO_LIST else 1)
    current_coupon_list = [{"CouponID": coupon_id, "Num": qty}]
    
    # 优惠券信息转为 JSON 字符串
    coupon_info_str = json.dumps(current_coupon_list)
    
    # 构建请求体
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
    
    print(f"[*] 接口地址: {API_URL}")
    print(f"[*] 目标手机号: {mobiles}")
    print(f"[*] 优惠券信息: {current_coupon_list}")
    print(f"[*] 发送参数 Payload: {json.dumps(payload, ensure_ascii=False, indent=2)}")
    
    try:
        # 发送 POST 请求
        response = requests.post(API_URL, headers=headers, json=payload, timeout=30)
        
        print("\n" + "=" * 50)
        print(f"[*] 响应状态码: {response.status_code}")
        
        # 尝试解析响应
        try:
            resp_json = response.json()
            print("[*] 响应内容 (JSON):")
            print(json.dumps(resp_json, ensure_ascii=False, indent=2))
            
            code = resp_json.get("code")
            message = resp_json.get("message")
            if code == 10000:
                print("\n[🎉 SUCCESS] 优惠券发放指令提交成功！")
                print(f"[💬] 系统提示: {message}")
            else:
                print(f"\n[⚠️ WARNING] 发放返回非成功状态码({code}): {message}")
        except ValueError:
            print("[*] 响应内容 (非JSON文本):")
            print(response.text)
            
        print("=" * 50)
        
    except requests.exceptions.RequestException as e:
        print(f"\n[❌ ERROR] 发送请求时发生异常: {e}")


if __name__ == "__main__":
    # 接收优惠券的目标手机号，多手机号可以用英文逗号隔开，或者单手机号
    MOBILES = "11000000001"
    send_hk_coupon(MOBILES)
