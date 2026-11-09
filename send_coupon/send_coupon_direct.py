# -*- coding: utf-8 -*-
# 这个文件的功能是直连大陆发券接口发放大陆测试优惠券的代码（不通过扶摇）
"""
==========================================================================
🌐 优惠券与工单自动化调度系统 - 大陆直连接口发券脚本 (send_coupon_direct.py)
==========================================================================
本模块直连大陆测试环境发券微服务接口 (coupon.tx-test6.jryghq.cn)，
通过 requests 直接 POST 发放优惠券，不经过扶摇后台，不启动浏览器。

使用方式：
  1. 修改本文件底部的 AUTH_TOKEN（Bearer Token）和默认参数
  2. 直接运行：python -m send_coupon.send_coupon_direct

依赖引入：
  - config_business: 提供发券业务参数（手机号、批次号、发放数量等）
  - send_coupon_direct_logger: 提供统一持久化日志落盘
"""

import json
import os
import sys
import requests
import urllib3

# 自动追加上级目录至 Python 检索路径，保障单独运行时寻找配置文件无忧
root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(root_dir)
sys.path.append(os.path.join(root_dir, "config_business"))

import config_business
from logger.send_coupon_direct_logger import send_coupon_direct_logger as sys_logger

# 禁用因忽略 SSL 请求产生的安全不信任警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==========================================
# ⚙️ 大陆直连发券接口专属硬性配置区
# ==========================================

# 1. 接口网络服务地址（直连发券微服务，不经过扶摇）
#    使用 HTTP 协议（内网服务不支持 HTTPS SSL 握手）
API_URL = "http://coupon.tx-test6.jryghq.cn/jryg-coupon/coupon/send_coupon"

# 2. 远端测试环境专用 Bearer JWT 静态身份认证 Token
#    注意：Token 有过期时间，过期后需重新获取并替换
AUTH_TOKEN = "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJleHAiOjE3ODgyNTYzODMsImlzcyI6ImF1dGhfbG9naW4iLCJ1aWQiOjM1ODYsImFkbWluIjpmYWxzZX0.dxQf0YHhIHQQBHmbHXC_9eRZZL0OJ70xDAnvVQnSuIc"

# 3. 默认发券参数配置
COUPON_INFO_LIST = [
    {"CouponID": 34305, "Num": 3}
]

SEND_TYPE = 1       # 发送类型 (1 代表按手机号主动精准发放)
COUPON_TYPE = 1     # 优惠券类型 (1 代表普通体验券)
REMARK = ""         # 备注信息
SEND_INDEX = 1      # 单批次发送索引号
SEND_LIMIT = 5000   # 最大限制发送手机数 (防暴力请求)
USERS_FILE = ""     # 可空的用户大盘导入文件


def send_coupon_direct(mobiles=None, send_num=None, coupon_id=None):
    """
    直连大陆发券接口，通过接口直接发放大陆测试优惠券至指定手机号。
    不经过扶摇系统，不启动浏览器，纯接口调用。

    参数：
      mobiles (str): 目标手机号 (多个号码用英文逗号 ',' 隔开)
      send_num (int): 派发张数。若未传入则使用 COUPON_INFO_LIST 里的默认配置
      coupon_id (int): 优惠券批次ID。若未传入则使用 COUPON_INFO_LIST 里的默认配置
    """
    sys_logger.info("正在准备直连大陆发券接口发放优惠券（不经过扶摇）...")

    # 读取默认配置并在传入参数时予以重写重载
    target_mobiles = mobiles if mobiles else config_business.TARGET_PHONE
    default_coupon_id = COUPON_INFO_LIST[0]["CouponID"] if COUPON_INFO_LIST else int(config_business.SEND_COUPON_BATCH)
    default_num = COUPON_INFO_LIST[0]["Num"] if COUPON_INFO_LIST else int(config_business.SEND_QTY)
    target_coupon_id = int(coupon_id) if coupon_id is not None else default_coupon_id
    target_qty = int(send_num) if send_num is not None else default_num

    # 构建契合大陆发券微服务网关的专属请求头
    headers = {
        "Accept": "application/json; charset=utf-8",
        "Authorization": AUTH_TOKEN,
        "Content-Type": "application/json; charset=utf-8",
        "User-Agent": "jryg-admin",
        "Sensitive": "1"
    }

    # 构建优惠券信息列表并序列化为 JSON 字符串
    current_coupon_list = [{"CouponID": target_coupon_id, "Num": target_qty}]
    coupon_info_str = json.dumps(current_coupon_list)

    # 构建与大陆发券微服务对接的标准 Body Payload 结构
    payload = {
        "SendType": SEND_TYPE,
        "CouponType": COUPON_TYPE,
        "Remark": REMARK,
        "Mobiles": target_mobiles,
        "SendIndex": SEND_INDEX,
        "SendLimit": SEND_LIMIT,
        "UsersFile": USERS_FILE,
        "CouponInfo": coupon_info_str
    }

    sys_logger.info(f"接口: {API_URL}")
    sys_logger.info(f"手机: {target_mobiles} | 券ID: {target_coupon_id} | 数量: {target_qty}")
    sys_logger.info(f"请求参数: {json.dumps(payload, ensure_ascii=False)}")

    try:
        # 发起 HTTP POST 请求派发优惠券
        response = requests.post(API_URL, headers=headers, json=payload, timeout=30, verify=False)
        sys_logger.info(f"响应状态码: {response.status_code}")

        try:
            resp_json = response.json()
            code = resp_json.get("code")
            message = resp_json.get("message")
            if code == 10000:
                sys_logger.info(f"[SUCCESS] 大陆优惠券直连接口发放成功！系统提示: {message}")
                return True
            else:
                sys_logger.warn(f"接口返回非成功状态码({code}): {message}")
                return False
        except ValueError:
            sys_logger.warn(f"响应内容 (非JSON文本): {response.text}")
            return False

    except requests.exceptions.RequestException as e:
        sys_logger.error(f"发送请求时发生异常: {e}")
        return False


if __name__ == "__main__":
    MOBILES = "18618251727"
    SEND_NUM = 3
    COUPON_ID = 34305
    send_coupon_direct(mobiles=MOBILES, send_num=SEND_NUM, coupon_id=COUPON_ID)
