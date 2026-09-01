# -*- coding: utf-8 -*-
"""
==========================================================================
🌐 优惠券与工单自动化调度系统 - 香港优惠券发放接口对接脚本 (send_hk_coupon.py)
==========================================================================
本模块提供直连香港测试环境发券接口 (http://coupon.test.sunlightmobility.hk) 的发放功能。
直接通过 Requests 构建 JSON Payload 提交给发券 API，规避 UI 复杂的选择及人机校检拦截，发券更极速。
"""

import json
import requests
import urllib3
from logger.logger import sys_logger

# 禁用因忽略 SSL 请求或降级到 HTTP 产生的安全不信任警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==========================================
# ⚙️ 香港优惠券系统专属硬性配置区
# ==========================================
# 1. 接口网络服务地址 (HTTP 直连协议规避远端繁琐的 SSL/TLS 握手限制)
API_URL = "http://coupon.test.sunlightmobility.hk/jryg-coupon/coupon/send_coupon"

# 2. 远端测试环境专用 Bearer JWT 静态身份认证 Token
AUTH_TOKEN = "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJleHAiOjE3ODgyNTYzODMsImlzcyI6ImF1dGhfbG9naW4iLCJ1aWQiOjM1ODYsImFkbWluIjpmYWxzZX0.dxQf0YHhIHQQBHmbHXC_9eRZZL0OJ70xDAnvVQnSuIc"

# 3. 默认发券参数配置列表
COUPON_INFO_LIST = [
    {"CouponID": 28, "Num": 1}
]

SEND_TYPE = 1       # 默认发送类型 (1 代表按手机号主动精准发放)
COUPON_TYPE = 1     # 默认优惠券类型 (1 代表普通体验券)
REMARK = ""         # 备注信息
SEND_INDEX = 1      # 单批次发送索引号
SEND_LIMIT = 5000   # 最大限制发送手机数 (防暴力请求)
USERS_FILE = ""     # 可空的用户大盘导入文件


def send_hk_coupon(mobiles, send_num=None):
    """
    通过接口直接给香港的目标手机号派发测试优惠券。
    
    参数：
      mobiles (str): 目标派发客户手机号 (多个号码支持用英文逗号 ',' 拼接隔开)
      send_num (int): 可选，派发张数配置。若未传入则默认使用 COUPON_INFO_LIST 里的全局配置数
    """
    sys_logger.info("正在准备发送香港优惠券...")
    
    # 构建契合香港测试环境网关与反爬检测要求的专属请求头
    headers = {
        "Accept": "application/json; charset=utf-8",
        "Authorization": AUTH_TOKEN,
        "Content-Type": "application/json; charset=utf-8",
        "User-Agent": "jryg-admin",
        "Sensitive": "1"
    }
    
    # 重载：允许从外部控制脚本中传入具体的单次发放张数，动态改写 Num 字段
    coupon_id = COUPON_INFO_LIST[0]["CouponID"] if COUPON_INFO_LIST else 28
    qty = int(send_num) if send_num is not None else (COUPON_INFO_LIST[0]["Num"] if COUPON_INFO_LIST else 1)
    current_coupon_list = [{"CouponID": coupon_id, "Num": qty}]
    
    # 优惠券配置信息列表强制转化为标准 JSON 字符串
    coupon_info_str = json.dumps(current_coupon_list)
    
    # 构建与香港发券微服务服务端对接的标准 Body Payload 结构
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
    
    sys_logger.info(f"接口: {API_URL} | 手机: {mobiles} | 券列表配置: {current_coupon_list}")
    
    try:
        # 发送标准 POST 网络请求
        response = requests.post(API_URL, headers=headers, json=payload, timeout=30)
        sys_logger.info(f"响应状态码: {response.status_code}")
        
        try:
            # 自动提纯并解析返回的 JSON 结构数据
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
