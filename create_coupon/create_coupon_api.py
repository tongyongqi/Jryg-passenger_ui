# -*- coding: utf-8 -*-
# 这个文件的功能是通过接口直接创建优惠券的代码（不经过浏览器自动化填写表单）
"""
==========================================================================
优惠券与工单自动化调度系统 - 接口创建优惠券脚本 (create_coupon_api.py)
==========================================================================
本模块通过 Playwright 极简登录流自动截获 Authorization Token 后，
使用 requests 直连 dcms-test6-tx.jryghq.com 创建优惠券接口，
无需浏览器逐项填写表单。

使用方式：
  1. 修改本文件底部默认参数（券名称、面值、发行量、有效期等）
  2. 直接运行：python -m create_coupon.create_coupon_api

依赖引入：
  - config_common: 提供公共登录配置（账号、密码、系统URL）
  - config_business: 提供优惠券业务参数
  - create_coupon_api_logger: 提供统一持久化日志落盘
"""

import asyncio
import json
import os
import sys
import requests
import urllib3
from playwright.async_api import async_playwright

# 自动追加上级目录至 Python 检索路径，保障单独运行时寻找配置文件无忧
root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(root_dir)
sys.path.append(os.path.join(root_dir, "config_common"))
sys.path.append(os.path.join(root_dir, "config_business"))

import config_common
import config_business
from logger.create_coupon_api_logger import create_coupon_api_logger as sys_logger

# 屏蔽不安全请求报警
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
os.makedirs("output", exist_ok=True)

# 接口网络服务地址（扶摇后台创建优惠券接口）
API_URL = "https://dcms-test6-tx.jryghq.com/admin/v1/coupon/add_coupon"

# ================= 默认创建参数 =================
COUPON_NAME = "1"
COUPON_TYPE = 1            # 1=满减券, 2=折扣券
DENOMINATION = 20          # 面值
USE_ROLE_MONEY = 1         # 使用门槛
COUPON_MAX_MONEY = 100     # 最高抵扣
NUMBER = 11                # 发行量
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


async def get_auth_token(headless=True):
    """
    通过 Playwright 极简登录流，绑定 Request 探测钩子自动截获 Authorization Bearer Token。

    参数：
      headless (bool): 是否使用静默模式开启浏览器截获 Token
    """
    token_holder = {}

    async def handle_request(request):
        """核心钩子：监听网页发起的所有异步请求，提纯其 Headers 中的 Authorization 头"""
        headers = request.headers
        auth = headers.get("authorization") or headers.get("Authorization")
        if auth and auth.startswith("Bearer "):
            token_holder["Authorization"] = auth

    sys_logger.info("启动浏览器以获取系统登录鉴权 Token (静默无头模式)...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(
            viewport={"width": 1440, "height": 900},
            ignore_https_errors=True
        )
        page = await context.new_page()
        page.set_default_timeout(config_common.DEFAULT_TIMEOUT)

        # 注册实时流量探测钩子监听
        page.on("request", handle_request)

        url = config_common.BASE_URL
        sys_logger.info(f"正在导航至登录页面: {url}")

        # 页面容错加载
        nav_success = False
        for retry in range(1, 4):
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=40000)
                nav_success = True
                break
            except Exception as e:
                sys_logger.warning(f"导航重试 ({retry}/3) 失败: {e}")
                if retry < 3:
                    await page.wait_for_timeout(2000)

        if not nav_success:
            sys_logger.error("无法导航至后台登录页。")
            await browser.close()
            return None

        await page.wait_for_timeout(2000)

        # 输入自动登录要素信息
        sys_logger.info("正在输入自动登录凭证...")
        await page.fill("input[placeholder='账号']", config_common.USERNAME)
        await page.fill("input[placeholder='密码']", config_common.PASSWORD)
        await page.fill("input[placeholder='图形验证码']", config_common.IMAGE_CAPTCHA)

        try:
            await page.click("text=获取验证码", timeout=5000)
        except Exception:
            pass

        await page.wait_for_timeout(1000)
        await page.fill("input[placeholder='验证码']", config_common.SMS_CAPTCHA)

        sys_logger.info("正在提交登录...")
        await page.click("button:has-text('登录')")

        sys_logger.info("正在等待后台跳转并截获 API Authorization Token...")
        for _ in range(30):
            await page.wait_for_timeout(1000)
            if "Authorization" in token_holder and "login" not in page.url:
                sys_logger.info("成功截获 Authorization Token！")
                break

        await browser.close()

    return token_holder.get("Authorization")


def create_coupon_via_api(
    auth_token,
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
    接收 Bearer Token，通过接口直接创建优惠券。

    参数：
      auth_token (str): 动态提取出的 Authorization 鉴权头
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
    if not auth_token:
        sys_logger.error("无法获取有效的 Authorization Token，创建取消！")
        return False, None

    # 读取默认配置并在传入参数时予以重写重载
    target_name = coupon_name if coupon_name else COUPON_NAME
    target_denomination = int(denomination) if denomination is not None else DENOMINATION
    target_number = int(number) if number is not None else NUMBER
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
        "Authorization": auth_token,
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
                    coupon_plan_id = data.get("CouponPlanID", data.get("coupon_plan_id", ""))
                if coupon_plan_id:
                    sys_logger.info(f"[SUCCESS] 优惠券接口创建成功！券名称: {target_name} | 批次ID: {coupon_plan_id}")
                else:
                    sys_logger.info(f"[SUCCESS] 优惠券接口创建成功！券名称: {target_name} | 返回数据: {json.dumps(data, ensure_ascii=False)}")
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


async def run_flow(
    headless=True,
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
    提供给统一控制台调用的标准动作执行流：
    1. Playwright 静默截获 Token
    2. requests POST 接口创建优惠券
    """
    auth_token = await get_auth_token(headless=headless)
    if auth_token:
        return create_coupon_via_api(
            auth_token,
            coupon_name=coupon_name,
            denomination=denomination,
            number=number,
            start_date=start_date,
            end_date=end_date,
            remark=remark,
            terminal=terminal,
            car_type_limit=car_type_limit,
            server_type_limit=server_type_limit,
            agent_id=agent_id,
            coupon_tag_id=coupon_tag_id,
            coupon_type=coupon_type,
            use_role_money=use_role_money,
            coupon_max_money=coupon_max_money,
        )
    else:
        sys_logger.error("无法进行优惠券创建，因为 Token 截获失败。")
        return False, None


if __name__ == "__main__":
    asyncio.run(run_flow(headless=True))
