# -*- coding: utf-8 -*-
# 这个文件的功能是通过写死 Token 直接接口创建优惠券的代码（不启动浏览器）
"""
==========================================================================
优惠券与工单自动化调度系统 - 直连接口创建优惠券脚本 (create_coupon_direct.py)
==========================================================================
本模块使用写死的 Bearer Token，直接通过 requests 调用
dcms-test6-tx.jryghq.com 创建优惠券接口，不启动浏览器。

使用方式：
  1. 修改本文件顶部的 AUTH_TOKEN（Token 过期后需重新获取替换）
  2. 修改默认创建参数（券名称、面值、发行量等）
  3. 直接运行：python -m create_coupon.create_coupon_direct

依赖引入：
  - create_coupon_api_logger: 提供统一持久化日志落盘
"""

import json
import os
import sys
import requests
import urllib3

# 自动追加上级目录至 Python 检索路径
root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(root_dir)

from logger.create_coupon_api_logger import create_coupon_api_logger as sys_logger

# 屏蔽不安全请求报警
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==========================================
# 直连接口创建优惠券专属配置区
# ==========================================

# 1. 接口网络服务地址（扶摇后台创建优惠券接口）
API_URL = "https://dcms-test6-tx.jryghq.com/admin/v1/coupon/add_coupon"

# 2. 远端测试环境专用 Bearer JWT 静态身份认证 Token
#    注意：Token 有过期时间，过期后需重新获取并替换
AUTH_TOKEN = "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJleHAiOjE3ODg2MTI2NDksImlzcyI6ImF1dGhfbG9naW4iLCJ1aWQiOjc4MDIsImFkbWluIjp0cnVlfQ.reQbhbx9kn7_-1gsYpaH9FhE_FXVbk_a821LwoHkWlo"

# 3. 默认创建参数
COUPON_NAME = "1"
COUPON_TYPE = 1            # 1=满减券, 2=折扣券
DENOMINATION = 1000       # 面值
USE_ROLE_MONEY = 1         # 使用门槛
COUPON_MAX_MONEY = 100     # 最高抵扣
NUMBER = 1000              # 发行量
VALIDITY_TYPE = 1          # 1=固定日期区间
START_DATE = "2026-09-01"
END_DATE = "2026-10-13"
TERMINAL = "3,4,5,6,7,8"
CAR_TYPE_LIMIT = "1,9,2,3,4"
SERVER_TYPE_LIMIT = "1,11,12,21,22,4,3,15"
COUPON_TAG_ID = 21
AGENT_ID = "447,470,471,9999"
CREATE_ID = 7802
APPROVAL = 1
IS_SPECIAL = 0
IS_WECHAT_PAY_COUPON = 0
LIMIT_PER_USER = 0
NATURAL_PER_LIMIT = 0
PHONE_LIMIT = 0
CITY_LIMIT = ""
SEND_CITY_LIMIT = ""
REMARK = "<p>11</p>"
TIMES_VAL = "[]"
COUPON_NAME_DY = ""
CONSUME_DESC = ""
CONSUME_PATH = ""
RECEIVE_DESC = ""
BUSINESS_TYPE_LIMIT = []


def create_coupon_direct(
    coupon_name=None,
    denomination=None,
    number=None,
    start_date=None,
    end_date=None,
    remark=None,
    terminal=None,
    car_type_limit=None,
    server_type_limit=None,
    agent_id=None,
    coupon_tag_id=None,
    coupon_type=None,
    use_role_money=None,
    coupon_max_money=None,
):
    """
    使用写死的 Token，通过接口直接创建优惠券。
    不启动浏览器，纯接口调用。

    参数：
      coupon_name (str): 优惠券名称
      denomination (int): 面值
      number (int): 发行量
      start_date (str): 有效期开始日期 (YYYY-MM-DD)
      end_date (str): 有效期结束日期 (YYYY-MM-DD)
      remark (str): 使用说明（富文本HTML）
      terminal (str): 适用终端
      car_type_limit (str): 适用车型
      server_type_limit (str): 适用服务类型
      agent_id (str): 商家ID
      coupon_tag_id (int): 优惠券标签ID
      coupon_type (int): 1=满减券 2=折扣券
      use_role_money (int): 使用门槛
      coupon_max_money (int): 最高抵扣金额
    """
    sys_logger.info("正在准备通过直连接口创建优惠券（不启动浏览器）...")

    # 读取默认配置并在传入参数时予以重写重载
    target_denomination = int(denomination) if denomination is not None else DENOMINATION
    target_number = int(number) if number is not None else NUMBER
    # 优惠券名称根据面值自动生成，不需要手动配置
    target_name = coupon_name if coupon_name else f"{target_denomination}元优惠券"
    target_start = start_date if start_date else START_DATE
    target_end = end_date if end_date else END_DATE
    target_remark = remark if remark else REMARK
    target_terminal = terminal if terminal else TERMINAL
    target_car = car_type_limit if car_type_limit else CAR_TYPE_LIMIT
    target_server = server_type_limit if server_type_limit else SERVER_TYPE_LIMIT
    target_agent = agent_id if agent_id else AGENT_ID
    target_tag_id = int(coupon_tag_id) if coupon_tag_id is not None else COUPON_TAG_ID
    target_coupon_type = int(coupon_type) if coupon_type is not None else COUPON_TYPE
    target_use_rule = int(use_role_money) if use_role_money is not None else USE_ROLE_MONEY
    target_max_money = int(coupon_max_money) if coupon_max_money is not None else COUPON_MAX_MONEY

    # 构建请求头
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Authorization": AUTH_TOKEN,
        "Content-Type": "application/json;charset=UTF-8",
        "User-Agent": "Mozilla/5.0"
    }

    # 构建创建优惠券的请求体
    payload = {
        "Terminal": target_terminal,
        "TimesVal": TIMES_VAL,
        "AgentId": target_agent,
        "ValidityType": VALIDITY_TYPE,
        "Approval": APPROVAL,
        "BusinessTypeLimit": BUSINESS_TYPE_LIMIT,
        "CarTypeLimit": target_car,
        "CityLimit": CITY_LIMIT,
        "ConsumeDesc": CONSUME_DESC,
        "ConsumePath": CONSUME_PATH,
        "CouponEndDate": "",
        "CouponMaxMoney": target_max_money,
        "CouponName": target_name,
        "CouponNameDy": COUPON_NAME_DY,
        "CouponStartDate": "",
        "CouponTagID": target_tag_id,
        "CouponType": target_coupon_type,
        "CreateID": CREATE_ID,
        "Denomination": target_denomination,
        "EndDate": target_end,
        "IsSpecial": IS_SPECIAL,
        "IsWechatPayCoupon": IS_WECHAT_PAY_COUPON,
        "LimitPerUser": LIMIT_PER_USER,
        "NaturalPerLimit": NATURAL_PER_LIMIT,
        "Number": target_number,
        "PhoneLimit": PHONE_LIMIT,
        "ReceiveDesc": RECEIVE_DESC,
        "Remark": target_remark,
        "SendCityLimit": SEND_CITY_LIMIT,
        "ServerTypeLimit": target_server,
        "StartDate": target_start,
        "UseRoleMoney": target_use_rule,
    }

    sys_logger.info(f"接口: {API_URL}")
    sys_logger.info(f"券名称: {target_name} | 类型: {target_coupon_type} | 面值: {target_denomination} | 发行量: {target_number}")
    sys_logger.info(f"有效期: {target_start} ~ {target_end}")
    sys_logger.info(f"请求参数: {json.dumps(payload, ensure_ascii=False)}")

    try:
        response = requests.post(API_URL, headers=headers, json=payload, timeout=30, verify=False)
        sys_logger.info(f"响应状态码: {response.status_code}")

        try:
            resp_json = response.json()
            code = resp_json.get("code")
            message = resp_json.get("message", "")
            data = resp_json.get("data", {})

            if code == 10000:
                coupon_plan_id = ""
                if isinstance(data, dict):
                    coupon_plan_id = data.get("CouponPlanID", data.get("coupon_plan_id", data.get("id", "")))
                if coupon_plan_id:
                    sys_logger.info(f"[SUCCESS] 优惠券直连接口创建成功！券名称: {target_name} | ID: {coupon_plan_id}")
                else:
                    sys_logger.info(f"[SUCCESS] 优惠券直连接口创建成功！券名称: {target_name} | 返回数据: {json.dumps(data, ensure_ascii=False)}")
                return True, coupon_plan_id
            else:
                sys_logger.warning(f"接口返回非成功状态码({code}): {message}")
                sys_logger.warning(f"完整返回: {json.dumps(resp_json, ensure_ascii=False)}")
                return False, None
        except ValueError:
            sys_logger.warning(f"响应内容 (非JSON文本): {response.text}")
            return False, None

    except requests.exceptions.RequestException as e:
        sys_logger.error(f"发送创建优惠券请求时发生异常: {e}")
        return False, None


if __name__ == "__main__":
    # 执行时配置：优惠券金额和张数，名称自动生成
    print("=" * 50)
    print("  直连接口创建优惠券")
    print("=" * 50)
    input_denomination = input("请输入优惠券面值（元，默认1000）: ").strip()
    input_number = input("请输入发行张数（默认1000）: ").strip()
    denomination = int(input_denomination) if input_denomination else 1000
    number = int(input_number) if input_number else 1000
    auto_name = f"{denomination}元优惠券"
    print(f"自动生成券名称: {auto_name}")
    print("=" * 50)
    create_coupon_direct(coupon_name=auto_name, denomination=denomination, number=number)
