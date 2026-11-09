# -*- coding: utf-8 -*-
# 这个文件的功能是通过扶摇登录截获 Token 后，调用接口创建领券活动
"""
==========================================================================
优惠券与工单自动化调度系统 - 领券活动接口创建脚本 (create_coupon_activity.py)
==========================================================================
本模块通过 Playwright 极简登录流自动截获 Authorization Token 后，
使用 requests 直连 jryg-admin 后台创建领券活动接口，
无需浏览器逐项填写表单。

使用方式：
  1. 修改本文件底部默认参数（活动标题、券包配置、有效期等）
  2. 直接运行：python -m create_coupon_activity.create_coupon_activity

依赖引入：
  - config_common: 提供公共登录配置（账号、密码、系统URL）
  - create_coupon_activity_logger: 提供统一持久化日志落盘
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
from logger.create_coupon_activity_logger import create_coupon_activity_logger as sys_logger

# 屏蔽不安全请求报警
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==========================================
# 领券活动接口专属硬性配置区
# ==========================================
# 1. 接口网络服务地址（扶摇后台创建领券活动接口）
API_URL = "https://dcms-test6-tx.jryghq.com/admin/v1/activity/norm_add"

# 2. 默认领券活动创建参数
TITLE = "微信模版消息活动"                        # 活动标题
SHOW_TITLE = "微信模版消息活动"                   # 展示标题
ACTIVITY_CODE = "2jr7XRaN"                        # 活动编码
ACTIVITY_URL = "pages/activityCoupon/index?id=2jr7XRaN"  # 活动前端页面路径
BG_IMG = "https://passenger-static.jryghq.com/passenger/dev/20250812ZS4HzJTQwD.png"  # 背景图
BUTTON_TITLE = "微信模版消息活动"                 # 按钮标题
REMARK = "<p>微信模版消息活动微信模版消息活动微信模版消息活动微信模版消息活动微信模版消息活动微信模版消息活动微信模版消息活动微信模版消息活动微信模版消息活动微信模版消息活动</p>"  # 活动说明

# 3. 券包配置
DRIVER_COUPON_PACKAGE_ID = 2329                   # 司机券包ID
DRIVER_COUPON_PACKAGE_TITLE = "1111"              # 司机券包标题
NEW_USER_PACKAGE_ID = 2323                        # 新用户券包ID
NEW_USER_PACKAGE_TITLE = "新人优惠卷礼包"          # 新用户券包标题
OLD_USER_PACKAGE_ID = 2323                        # 老用户券包ID
OLD_USER_PACKAGE_TITLE = "新人优惠卷礼包"          # 老用户券包标题

# 4. 活动时间配置
START_DATE = "2025-08-12"                         # 活动开始日期
END_DATE = "2039-09-30"                           # 活动结束日期

# 5. 限制与状态配置
LIMIT_DRIVER = 1                                  # 限制司机 (1=不限)
LIMIT_RECEIVE = 0                                 # 限制领取
LIMIT_CITY = 0                                    # 限制城市 (0=不限)
LIMIT_CITY_TYPE = 1                               # 限制城市类型
LIMIT_CITY_COUPON_PACKAGE_ID = 0                  # 限制城市券包ID
LIMIT_CITY_COUPON_PACKAGE_TITLE = ""              # 限制城市券包标题
LIMIT_CITY_FILE_URL = ""                          # 限制城市文件URL
LIMIT_CITY_ID_LIST = None                         # 限制城市ID列表
NEW_USER_LIMIT = "2,1"                            # 新用户限制
SHARED = 0                                        # 共享标识
ENABLED = 1                                       # 启用状态
STATUS = 1                                        # 活动状态
STOCK_ID = "LQ202508281"                          # 库存ID
TAG_ID = 0                                        # 标签ID
TERMINAL = 51                                     # 适用终端
USER_RECEIVED_LIMIT = 0                           # 用户领取限制
USER_RECEIVED_LIMIT_BY_DAY = 0                    # 每日领取限制

# 6. 展示与企微配置
SHOW_CARD_TITLE = ""                              # 卡片展示标题
SHOW_H5_TITLE = ""                                # H5展示标题
CARD_IMG = ""                                     # 卡片图片
WX_WORK_QR_URL = ""                               # 企微二维码URL
WX_WORK_TITLE = ""                                # 企微标题

# 7. 创建者信息
CREATOR_ID = 7802                                 # 创建者ID
CREATOR_NAME = "童永琦"                           # 创建者名称
CREATED_AT = "0001-01-01T00:00:00Z"               # 创建时间(后端填充)


async def get_auth_token(headless=True):
    """
    通过 Playwright 极简浏览器自动化登录扶摇后台，
    自动截获 Authorization Bearer Token 后返回。
    """
    token_holder = {}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context()
        page = await context.new_page()

        # 拦截所有请求，捕获 Authorization 头
        def on_request(request):
            auth = request.headers.get("Authorization", "")
            if auth and auth.startswith("Bearer "):
                token_holder["Authorization"] = auth

        page.on("request", on_request)

        login_url = config_common.BASE_URL
        sys_logger.info(f"正在打开扶摇后台登录页: {login_url}")

        nav_success = False
        for retry in range(5):
            try:
                await page.goto(login_url, wait_until="domcontentloaded", timeout=config_common.DEFAULT_TIMEOUT)
                nav_success = True
                break
            except Exception as e:
                sys_logger.warning(f"导航重试 {retry + 1}/5: {e}")
                if retry < 4:
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


def create_coupon_activity(auth_token, **kwargs):
    """
    接收 Bearer Token，通过接口直接创建领券活动。

    参数：
      auth_token (str): 动态提取出的 Authorization 鉴权头
      其余参数可通过 kwargs 覆盖默认配置
    """
    if not auth_token:
        sys_logger.error("无法获取有效的 Authorization Token，创建取消！")
        return False

    # 构建请求头
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Authorization": auth_token,
        "Content-Type": "application/json;charset=UTF-8",
        "User-Agent": "Mozilla/5.0"
    }

    # 构建创建领券活动的请求体
    payload = {
        "activity_code": kwargs.get("activity_code", ACTIVITY_CODE),
        "activity_url": kwargs.get("activity_url", ACTIVITY_URL),
        "bg_img": kwargs.get("bg_img", BG_IMG),
        "button_title": kwargs.get("button_title", BUTTON_TITLE),
        "card_img": kwargs.get("card_img", CARD_IMG),
        "created_at": CREATED_AT,
        "creator_id": CREATOR_ID,
        "creator_name": CREATOR_NAME,
        "driver_coupon_package_id": kwargs.get("driver_coupon_package_id", DRIVER_COUPON_PACKAGE_ID),
        "driver_coupon_package_title": kwargs.get("driver_coupon_package_title", DRIVER_COUPON_PACKAGE_TITLE),
        "enabled": ENABLED,
        "end_date": kwargs.get("end_date", END_DATE),
        "limit_city": LIMIT_CITY,
        "limit_city_coupon_package_id": LIMIT_CITY_COUPON_PACKAGE_ID,
        "limit_city_coupon_package_title": LIMIT_CITY_COUPON_PACKAGE_TITLE,
        "limit_city_file_url": LIMIT_CITY_FILE_URL,
        "limit_city_id_list": LIMIT_CITY_ID_LIST,
        "limit_city_type": LIMIT_CITY_TYPE,
        "limit_driver": LIMIT_DRIVER,
        "limit_receive": LIMIT_RECEIVE,
        "new_user_limit": NEW_USER_LIMIT,
        "new_user_package_id": kwargs.get("new_user_package_id", NEW_USER_PACKAGE_ID),
        "new_user_package_title": kwargs.get("new_user_package_title", NEW_USER_PACKAGE_TITLE),
        "old_user_package_id": kwargs.get("old_user_package_id", OLD_USER_PACKAGE_ID),
        "old_user_package_title": kwargs.get("old_user_package_title", OLD_USER_PACKAGE_TITLE),
        "remark": kwargs.get("remark", REMARK),
        "shared": SHARED,
        "show_card_title": kwargs.get("show_card_title", SHOW_CARD_TITLE),
        "show_h5_title": kwargs.get("show_h5_title", SHOW_H5_TITLE),
        "show_title": kwargs.get("show_title", SHOW_TITLE),
        "start_date": kwargs.get("start_date", START_DATE),
        "status": STATUS,
        "stock_id": kwargs.get("stock_id", STOCK_ID),
        "tag_id": TAG_ID,
        "terminal": TERMINAL,
        "title": kwargs.get("title", TITLE),
        "user_received_limit": USER_RECEIVED_LIMIT,
        "user_received_limit_by_day": USER_RECEIVED_LIMIT_BY_DAY,
        "wx_work_qr_url": WX_WORK_QR_URL,
        "wx_work_title": WX_WORK_TITLE
    }

    sys_logger.info(f"正在调用领券活动创建接口: {API_URL}")
    sys_logger.info(f"活动标题: {payload['title']} | 活动编码: {payload['activity_code']}")
    sys_logger.info(f"请求体: {json.dumps(payload, ensure_ascii=False)}")

    try:
        response = requests.post(API_URL, headers=headers, json=payload, verify=False, timeout=30)
        sys_logger.info(f"接口响应状态码: {response.status_code}")
        sys_logger.info(f"接口响应内容: {response.text}")

        if response.status_code == 200:
            resp_data = response.json()
            if resp_data.get("code") == 10000:
                sys_logger.info("领券活动创建成功！")
                return True
            else:
                sys_logger.error(f"领券活动创建失败，接口返回: {resp_data}")
                return False
        else:
            sys_logger.error(f"接口请求失败，HTTP状态码: {response.status_code}")
            return False
    except Exception as e:
        sys_logger.error(f"接口请求异常: {e}")
        return False


async def run_flow(headless=True, **kwargs):
    """
    提供给统一控制台调用的标准动作执行流：
    1. Playwright 浏览器登录截获 Token
    2. 用截获的 Token 通过 requests POST 接口创建领券活动
    """
    sys_logger.info("=" * 70)
    sys_logger.info("开始执行领券活动创建流程")
    sys_logger.info("=" * 70)

    # Step 1: 获取 Token
    sys_logger.info("[Step 1] 正在通过浏览器登录截获 Authorization Token...")
    auth_token = await get_auth_token(headless=headless)

    if not auth_token:
        sys_logger.error("未能截获 Authorization Token，流程终止！")
        return False

    sys_logger.info(f"成功获取 Token: {auth_token[:30]}...")

    # Step 2: 创建领券活动
    sys_logger.info("[Step 2] 正在通过接口创建领券活动...")
    success = create_coupon_activity(auth_token, **kwargs)

    if success:
        sys_logger.info("领券活动创建流程执行完毕，活动创建成功！")
    else:
        sys_logger.error("领券活动创建流程执行完毕，但创建失败！")

    return success


if __name__ == "__main__":
    asyncio.run(run_flow(headless=False))
