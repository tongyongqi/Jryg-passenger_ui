# -*- coding: utf-8 -*-
# 这个文件的功能是通过扶摇登录截获 Token 后，调用接口创建社群抽奖活动
"""
==========================================================================
优惠券与工单自动化调度系统 - 社群抽奖活动接口创建脚本 (community_draw.py)
==========================================================================
本模块通过 Playwright 极简登录流自动截获 Authorization Token 后，
使用 requests 直连 jryg-admin 后台创建抽奖活动接口，
无需浏览器逐项填写表单。

使用方式：
  1. 修改本文件底部默认参数（活动标题、奖品配置、有效期等）
  2. 直接运行：python -m community_draw.community_draw

依赖引入：
  - config_common: 提供公共登录配置（账号、密码、系统URL）
  - community_draw_logger: 提供统一持久化日志落盘
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
from logger.community_draw_logger import community_draw_logger as sys_logger

# 屏蔽不安全请求报警
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==========================================
# ⚙️ 社群抽奖活动接口专属硬性配置区
# ==========================================
# 1. 接口网络服务地址（扶摇后台创建抽奖活动接口）
API_URL = "https://dcms-test6-tx.jryghq.com/admin/v1/activity/draw/add"
# 1.1 审核接口地址（update_status=6 表示审核通过）
AUDIT_API_URL = "https://dcms-test6-tx.jryghq.com/admin/v1/activity/draw/update_status"

# 2. 默认抽奖活动创建参数
TITLE = "接口创建"                           # 活动标题
SHOW_TITLE = "123"                      # 展示标题
CONTENT = "123"                         # 活动内容
START_DATE = "2026-09-08 00:00:00"      # 活动开始时间
END_DATE = "2033-10-31 00:00:00"        # 活动结束时间
START_TIME = "2026-09-08 00:00:00"      # 抽奖开始时间
CREATOR_ID = 7802                       # 创建者ID
CREATOR = "童永琦"                       # 创建者姓名

# 3. 抽奖规则配置
LIMIT_DRIVER = 1        # 限制司机参与 (1=是 0=否)
LIMIT_RECEIVE = 0       # 限制领取 (0=不限制)
DRAW_TYPE = 1           # 抽奖类型 (1=普通抽奖)
TYPE = 1                # 活动类型 (1=普通)
PRIZE_TYPE = 1          # 奖品类型 (1=优惠券)
IS_PUSH_MSG = 2         # 是否推送消息 (2=不推送)
BG_IMG_TYPE = 1         # 背景图类型 (1=默认)

# 4. 奖品配置列表 (level=0 为兜底奖, level=1 为一等奖, 依此类推)
# 4.1 大转盘奖品配置 (type=1, 4个奖品)
PRIZES = [
    {
        "terminal": 0,
        "prize": [
            {
                "level": 0,
                "title": "兜底奖",
                "number": 999,
                "img": "https://passenger-static.jryghq.com/passenger/prod/2026/09/08/YYl4KcVsTDJevVbnw5UbADqBfrEBPZDg.png",
                "coupon_package_id": 2374
            },
            {
                "level": 1,
                "title": "一等奖",
                "number": 3,
                "img": "https://passenger-static.jryghq.com/passenger/prod/2026/09/08/dA1AaXyl97iNcSoSM3eeOHw43JPdrbMX.png",
                "coupon_package_id": 2371
            },
            {
                "level": 2,
                "title": "二等奖",
                "number": 6,
                "img": "https://passenger-static.jryghq.com/passenger/prod/2026/09/08/rjH7D7TpriDnXYLEAnndDhB1FBa2K8jt.png",
                "coupon_package_id": 2372
            },
            {
                "level": 3,
                "title": "三等奖",
                "number": 10,
                "img": "https://passenger-static.jryghq.com/passenger/prod/2026/09/08/kcsQBpFS6cwz8MbX6DHsgIevkFOYhPBS.png",
                "coupon_package_id": 2373
            }
        ]
    }
]

# 4.1b 大转盘独立奖池配置 (terminal=5 乘客端 + terminal=6 司机端, 4个奖品)
PRIZES_INDEPENDENT = [
    {
        "terminal": 5,
        "prize": [
            {"level": 0, "title": "兜底奖", "number": 999, "img": "https://passenger-static.jryghq.com/passenger/prod/2026/09/08/YYl4KcVsTDJevVbnw5UbADqBfrEBPZDg.png", "coupon_package_id": 2374},
            {"level": 1, "title": "一等奖", "number": 3, "img": "https://passenger-static.jryghq.com/passenger/prod/2026/09/08/dA1AaXyl97iNcSoSM3eeOHw43JPdrbMX.png", "coupon_package_id": 2371},
            {"level": 2, "title": "二等奖", "number": 6, "img": "https://passenger-static.jryghq.com/passenger/prod/2026/09/08/rjH7D7TpriDnXYLEAnndDhB1FBa2K8jt.png", "coupon_package_id": 2372},
            {"level": 3, "title": "三等奖", "number": 10, "img": "https://passenger-static.jryghq.com/passenger/prod/2026/09/08/kcsQBpFS6cwz8MbX6DHsgIevkFOYhPBS.png", "coupon_package_id": 2373}
        ]
    },
    {
        "terminal": 6,
        "prize": [
            {"level": 0, "title": "兜底奖", "number": 999, "img": "https://passenger-static.jryghq.com/passenger/prod/2026/09/08/YYl4KcVsTDJevVbnw5UbADqBfrEBPZDg.png", "coupon_package_id": 2374},
            {"level": 1, "title": "一等奖", "number": 3, "img": "https://passenger-static.jryghq.com/passenger/prod/2026/09/08/dA1AaXyl97iNcSoSM3eeOHw43JPdrbMX.png", "coupon_package_id": 2371},
            {"level": 2, "title": "二等奖", "number": 6, "img": "https://passenger-static.jryghq.com/passenger/prod/2026/09/08/rjH7D7TpriDnXYLEAnndDhB1FBa2K8jt.png", "coupon_package_id": 2372},
            {"level": 3, "title": "三等奖", "number": 10, "img": "https://passenger-static.jryghq.com/passenger/prod/2026/09/08/kcsQBpFS6cwz8MbX6DHsgIevkFOYhPBS.png", "coupon_package_id": 2373}
        ]
    }
]

# 4.2 九宫格奖品配置 (type=2, 8个奖品 level 0-7, 各平台独立奖池)
# 乘客端 (terminal=5) 奖池
PRIZES_JIUGONGGE = [
    {
        "terminal": 5,
        "prize": [
            {
                "level": 0,
                "title": "兜底奖",
                "number": 66,
                "img": "https://passenger-static.jryghq.com/passenger/prod/2026/09/08/71urzqojTNRK7EADMl2fHwoQKtyvoYL4.png",
                "coupon_package_id": 2374
            },
            {
                "level": 1,
                "title": "一等奖",
                "number": 1,
                "img": "https://passenger-static.jryghq.com/passenger/prod/2026/09/08/UhcSwnB6Qo2OBa8yuwzPbKf1mEluOw1m.png",
                "coupon_package_id": 2371
            },
            {
                "level": 2,
                "title": "二等奖",
                "number": 2,
                "img": "https://passenger-static.jryghq.com/passenger/prod/2026/09/08/lhlQ56RQVvUEx8fhLqG6e0R2eWmcoic5.png",
                "coupon_package_id": 2372
            },
            {
                "level": 3,
                "title": "三等奖",
                "number": 3,
                "img": "https://passenger-static.jryghq.com/passenger/prod/2026/09/08/hVROub0kqRie6S0HthktfQIqoDiUoebn.png",
                "coupon_package_id": 2373
            },
            {
                "level": 4,
                "title": "四等奖",
                "number": 4,
                "img": "https://passenger-static.jryghq.com/passenger/prod/2026/09/08/H4bhRBWfklS99EJ2PTWl9JQwmB1jm7RH.png",
                "coupon_package_id": 2375
            },
            {
                "level": 5,
                "title": "五等奖",
                "number": 5,
                "img": "https://passenger-static.jryghq.com/passenger/prod/2026/09/08/TLC8Sa7aTaYfl9FdN1e3hukzWG3ItQcY.png",
                "coupon_package_id": 2376
            },
            {
                "level": 6,
                "title": "六等奖",
                "number": 6,
                "img": "https://passenger-static.jryghq.com/passenger/prod/2026/09/08/yPA9Zd6MBqTtzLqgDmEJZq3YYHhkGAuO.png",
                "coupon_package_id": 2377
            },
            {
                "level": 7,
                "title": "七等奖",
                "number": 7,
                "img": "https://passenger-static.jryghq.com/passenger/prod/2026/09/08/MjE3ZlI1O65iiKet4WexzwMd3Ca5dNxa.png",
                "coupon_package_id": 2378
            }
        ]
    },
    # 司机端 (terminal=6) 奖池
    {
        "terminal": 6,
        "prize": [
            {
                "level": 0,
                "title": "兜底奖",
                "number": 33,
                "img": "https://passenger-static.jryghq.com/passenger/prod/2026/09/08/c4gsQKi75gkRbZQyLpTRLNPUnPYCPsVw.png",
                "coupon_package_id": 2374
            },
            {
                "level": 1,
                "title": "一等奖",
                "number": 1,
                "img": "https://passenger-static.jryghq.com/passenger/prod/2026/09/08/Nk451PUOtomuQ3DsYXqUnCxb5JgJsNNT.png",
                "coupon_package_id": 2371
            },
            {
                "level": 2,
                "title": "二等奖",
                "number": 2,
                "img": "https://passenger-static.jryghq.com/passenger/prod/2026/09/08/zTX6tV1lb4NGwkXjUNCoAzka2TkS0VsO.png",
                "coupon_package_id": 2372
            },
            {
                "level": 3,
                "title": "三等奖",
                "number": 3,
                "img": "https://passenger-static.jryghq.com/passenger/prod/2026/09/08/XO8spAIP0JnmrCRs9BdFzBA2l3KBdyXr.png",
                "coupon_package_id": 2373
            },
            {
                "level": 4,
                "title": "四等奖",
                "number": 4,
                "img": "https://passenger-static.jryghq.com/passenger/prod/2026/09/08/9frCM4BEDsGcYlIfNxs6wsT9otQ3oGBD.png",
                "coupon_package_id": 2375
            },
            {
                "level": 5,
                "title": "五等奖",
                "number": 5,
                "img": "https://passenger-static.jryghq.com/passenger/prod/2026/09/08/obbtHkK0MC6TryJTPdX9HWyzvzrRIw75.png",
                "coupon_package_id": 2376
            },
            {
                "level": 6,
                "title": "六等奖",
                "number": 6,
                "img": "https://passenger-static.jryghq.com/passenger/prod/2026/09/08/P2iSnW2bR0dP50tDKelNgIgJmdxuMswS.png",
                "coupon_package_id": 2377
            },
            {
                "level": 7,
                "title": "七等奖",
                "number": 7,
                "img": "https://passenger-static.jryghq.com/passenger/prod/2026/09/08/PTDoexmwFDs2mCqo826yJM9f3Azv5CTl.png",
                "coupon_package_id": 2378
            }
        ]
    }
]

# 4.3 九宫格活动类型 (type=2 表示九宫格)
TYPE_JIUGONGGE = 2
# 4.4 九宫格奖品类型 (2=各平台独立奖池)
PRIZE_TYPE_JIUGONGGE = 2
# 4.5 九宫格共享奖池配置 (terminal=0, 8个奖品 level 0-7)
PRIZES_JIUGONGGE_SHARED = [
    {
        "terminal": 0,
        "prize": [
            {"level": 0, "title": "兜底奖", "number": 66, "img": "https://passenger-static.jryghq.com/passenger/prod/2026/09/08/71urzqojTNRK7EADMl2fHwoQKtyvoYL4.png", "coupon_package_id": 2374},
            {"level": 1, "title": "一等奖", "number": 1, "img": "https://passenger-static.jryghq.com/passenger/prod/2026/09/08/UhcSwnB6Qo2OBa8yuwzPbKf1mEluOw1m.png", "coupon_package_id": 2371},
            {"level": 2, "title": "二等奖", "number": 2, "img": "https://passenger-static.jryghq.com/passenger/prod/2026/09/08/lhlQ56RQVvUEx8fhLqG6e0R2eWmcoic5.png", "coupon_package_id": 2372},
            {"level": 3, "title": "三等奖", "number": 3, "img": "https://passenger-static.jryghq.com/passenger/prod/2026/09/08/hVROub0kqRie6S0HthktfQIqoDiUoebn.png", "coupon_package_id": 2373},
            {"level": 4, "title": "四等奖", "number": 4, "img": "https://passenger-static.jryghq.com/passenger/prod/2026/09/08/H4bhRBWfklS99EJ2PTWl9JQwmB1jm7RH.png", "coupon_package_id": 2375},
            {"level": 5, "title": "五等奖", "number": 5, "img": "https://passenger-static.jryghq.com/passenger/prod/2026/09/08/TLC8Sa7aTaYfl9FdN1e3hukzWG3ItQcY.png", "coupon_package_id": 2376},
            {"level": 6, "title": "六等奖", "number": 6, "img": "https://passenger-static.jryghq.com/passenger/prod/2026/09/08/yPA9Zd6MBqTtzLqgDmEJZq3YYHhkGAuO.png", "coupon_package_id": 2377},
            {"level": 7, "title": "七等奖", "number": 7, "img": "https://passenger-static.jryghq.com/passenger/prod/2026/09/08/MjE3ZlI1O65iiKet4WexzwMd3Ca5dNxa.png", "coupon_package_id": 2378}
        ]
    }
]

# 5. 终端与消息配置
TERMINAL = "5,6"        # 适用终端 (5=乘客端, 6=司机端)
REMARKS = [
    {"msg_type": 1, "remark": "<p>123</p>", "terminal": 5},
    {"msg_type": 1, "remark": "<p>123</p>", "terminal": 6}
]

# 6. 抽奖次数限制配置
# 6.1 大转盘抽奖次数限制
PRIZE_ATTR_LIMIT = {
    "draw_user_number": 10,     # 每用户抽奖次数
    "wins_user_number": 10      # 每用户中奖次数
}

# 6.2 九宫格抽奖次数限制 (增加 draw_user_add_number / recommender_user_add_draw / recommender_user_number 字段)
PRIZE_ATTR_LIMIT_JIUGONGGE = {
    "draw_user_number": 10,              # 每用户抽奖次数
    "wins_user_number": 10,              # 每用户中奖次数
    "draw_user_add_number": 0,           # 每用户额外抽奖次数
    "recommender_user_add_draw": 0,     # 推荐人额外抽奖次数
    "recommender_user_number": 0        # 推荐人抽奖次数
}

# 6.3 九宫格新增字段
ENABLED = 1               # 启用状态 (九宫格为1)
PRIZE_FIELD = None         # 奖品字段 (null)
PRIZE_LIMIT = []           # 奖品限制列表
USER_RECEIVED_LIMIT = 0   # 用户领取限制
WX_WORK_FOLLOW_QR = ""    # 企微关注二维码
WX_WORK_QR_URL = ""       # 企微二维码URL
# 九宫格 wx_work_follow_type 为 0
WX_WORK_FOLLOW_TYPE_JIUGONGGE = 0
# 九宫格新增 wx_work_title 和 remark 字段
WX_WORK_TITLE = ""         # 企微标题
REMARK = ""                # 备注

# 7. 企微相关配置 (默认不启用)
WX_WORK_FOLLOW_TITLE = ""
WX_WORK_FOLLOW_TYPE = None
WX_WORK_TAG_TYPE = 0
WX_WORK_DRAW_USER_TAG = []
WX_WORK_FOLLOW_USER_TAG = []
WX_WORK_FOLLOW_USER = []
IMG = []
BG_IMG = []
MSG_VALUE1 = ""
MSG_VALUE2 = ""
MSG_VALUE3 = ""


async def get_auth_token(headless=True):
    """
    通过 Playwright 极简登录流，绑定 Request 探测钩子自动截获 Authorization Bearer Token。

    参数：
      headless (bool): 是否使用静默模式开启浏览器截获 Token

    返回：
      str: Authorization Bearer Token 字符串
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


def create_draw_activity(
    auth_token,
    title=None,
    show_title=None,
    content=None,
    start_date=None,
    end_date=None,
    start_time=None,
    prizes=None,
    terminal=None,
    remarks=None,
    prize_attr_limit=None,
    draw_type_choice=None,
    pool_type=None,
):
    """
    接收 Bearer Token，通过接口直接创建社群抽奖活动。

    参数：
      auth_token (str): 动态提取出的 Authorization 鉴权头
      title (str): 活动标题
      show_title (str): 展示标题
      content (str): 活动内容
      start_date (str): 活动开始时间
      end_date (str): 活动结束时间
      start_time (str): 抽奖开始时间
      prizes (list): 奖品配置列表
      terminal (str): 适用终端
      remarks (list): 终端消息配置
      prize_attr_limit (dict): 抽奖次数限制
      draw_type_choice (int): 抽奖类型选择 (1=大转盘, 2=九宫格)
      pool_type (int): 奖池方式 (1=多平台共享奖池, 2=各平台独立奖池)
    """
    if not auth_token:
        sys_logger.error("无法获取有效的 Authorization Token，创建取消！")
        return False

    # 根据 draw_type_choice 动态选择大转盘或九宫格配置
    is_jiugongge = (draw_type_choice == 2)
    is_independent = (pool_type == 2)  # 1=共享奖池, 2=独立奖池
    target_type = TYPE_JIUGONGGE if is_jiugongge else TYPE

    # 根据 抽奖类型 + 奖池方式 动态选择奖品配置
    if prizes:
        target_prizes = prizes
    elif is_jiugongge and is_independent:
        target_prizes = PRIZES_JIUGONGGE
    elif is_jiugongge and not is_independent:
        target_prizes = PRIZES_JIUGONGGE_SHARED
    elif not is_jiugongge and is_independent:
        target_prizes = PRIZES_INDEPENDENT
    else:
        target_prizes = PRIZES

    target_prize_attr_limit = prize_attr_limit if prize_attr_limit else (PRIZE_ATTR_LIMIT_JIUGONGGE if is_jiugongge else PRIZE_ATTR_LIMIT)
    target_prize_type = PRIZE_TYPE_JIUGONGGE if is_jiugongge else PRIZE_TYPE
    target_wx_work_follow_type = WX_WORK_FOLLOW_TYPE_JIUGONGGE if is_jiugongge else WX_WORK_FOLLOW_TYPE

    # 读取默认配置并在传入参数时予以重写重载
    target_title = title if title else TITLE
    target_show_title = show_title if show_title else SHOW_TITLE
    target_content = content if content else CONTENT
    target_start_date = start_date if start_date else START_DATE
    target_end_date = end_date if end_date else END_DATE
    target_start_time = start_time if start_time else START_TIME
    target_terminal = terminal if terminal else TERMINAL
    target_remarks = remarks if remarks else REMARKS

    # 构建请求头
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Authorization": auth_token,
        "Content-Type": "application/json;charset=UTF-8",
        "User-Agent": "Mozilla/5.0"
    }

    # 构建创建抽奖活动的请求体
    payload = {
        "limit_driver": LIMIT_DRIVER,
        "limit_receive": LIMIT_RECEIVE,
        "draw_type": DRAW_TYPE,
        "type": target_type,
        "prize_type": target_prize_type,
        "prizes": target_prizes,
        "wx_work_follow_title": WX_WORK_FOLLOW_TITLE,
        "wx_work_follow_type": target_wx_work_follow_type,
        "img": IMG,
        "wx_work_tag_type": WX_WORK_TAG_TYPE,
        "wx_work_draw_user_tag": WX_WORK_DRAW_USER_TAG,
        "wx_work_follow_user_tag": WX_WORK_FOLLOW_USER_TAG,
        "terminal": target_terminal,
        "remarks": target_remarks,
        "is_push_msg": IS_PUSH_MSG,
        "msg_value1": MSG_VALUE1,
        "msg_value2": MSG_VALUE2,
        "msg_value3": MSG_VALUE3,
        "bg_img_type": BG_IMG_TYPE,
        "prize_attr_limit": target_prize_attr_limit,
        "wx_work_follow_user": WX_WORK_FOLLOW_USER,
        "title": target_title,
        "show_title": target_show_title,
        "content": target_content,
        "start_date": target_start_date,
        "end_date": target_end_date,
        "start_time": target_start_time,
        "bg_img": BG_IMG,
        "creator_id": CREATOR_ID,
        "creator": CREATOR
    }

    # 九宫格新增字段
    if is_jiugongge:
        payload["enabled"] = ENABLED
        payload["prize"] = PRIZE_FIELD
        payload["prize_limit"] = PRIZE_LIMIT
        payload["user_received_limit"] = USER_RECEIVED_LIMIT
        payload["wx_work_follow_qr"] = WX_WORK_FOLLOW_QR
        payload["wx_work_qr_url"] = WX_WORK_QR_URL
        payload["wx_work_title"] = WX_WORK_TITLE
        payload["remark"] = REMARK

    sys_logger.info(f"接口: {API_URL}")
    sys_logger.info(f"活动标题: {target_title} | 展示标题: {target_show_title}")
    sys_logger.info(f"活动时间: {target_start_date} ~ {target_end_date}")
    sys_logger.info(f"奖品配置: {json.dumps(target_prizes, ensure_ascii=False)}")
    sys_logger.info(f"请求参数: {json.dumps(payload, ensure_ascii=False)}")

    try:
        response = requests.post(API_URL, headers=headers, json=payload, timeout=30, verify=False)
        sys_logger.info(f"响应状态码: {response.status_code}")

        try:
            resp_json = response.json()
            code = resp_json.get("code")
            message = resp_json.get("message", "")

            if code == 10000:
                sys_logger.info(f"[SUCCESS] 社群抽奖活动创建成功！活动标题: {target_title}")
                # 打印完整返回以便调试是否包含活动ID
                sys_logger.info(f"创建接口完整返回: {json.dumps(resp_json, ensure_ascii=False)}")
                # 尝试从返回数据中提取活动ID
                activity_id = None
                if isinstance(resp_json.get("data"), dict):
                    activity_id = resp_json["data"].get("id") or resp_json["data"].get("activity_id") or resp_json["data"].get("draw_id")
                elif isinstance(resp_json.get("data"), (int, str)):
                    activity_id = resp_json.get("data")

                # 如果返回数据中不包含ID，查询数据库获取最新活动ID
                if not activity_id:
                    activity_id = get_latest_draw_id(title=target_title)
                else:
                    sys_logger.info(f"创建接口直接返回活动ID: {activity_id}")

                if activity_id:
                    sys_logger.info(f"查询到最新活动ID: {activity_id}，开始审核...")
                    audit_draw_activity(headers, activity_id)
                else:
                    sys_logger.warning("未能获取活动ID，跳过自动审核。可手动在后台审核。")
                return True
            else:
                sys_logger.warning(f"接口返回非成功状态码({code}): {message}")
                sys_logger.warning(f"完整返回: {json.dumps(resp_json, ensure_ascii=False)}")
                return False
        except ValueError:
            sys_logger.warning(f"响应内容 (非JSON文本): {response.text}")
            return False

    except requests.exceptions.RequestException as e:
        sys_logger.error(f"发送创建抽奖活动请求时发生异常: {e}")
        return False


def get_latest_draw_id(title=None):
    """
    通过数据库查询最新创建的抽奖活动ID。
    查询 jryg_passenger.passenger_activity_draw 表，按 id DESC 取最新记录。
    如果传入 title，则按标题精准匹配。

    参数：
      title (str): 可选，按标题精准匹配刚创建的活动
    """
    sys_logger.info("正在通过数据库查询最新活动ID...")

    try:
        import pymysql
        from config_business.config_business import DB_CONFIG
        
        conn = pymysql.connect(**DB_CONFIG)
        cursor = conn.cursor()
        
        if title:
            sql = "SELECT id, title FROM jryg_passenger.passenger_activity_draw WHERE title = %s ORDER BY id DESC LIMIT 1;"
            cursor.execute(sql, (title,))
        else:
            sql = "SELECT id, title FROM jryg_passenger.passenger_activity_draw ORDER BY id DESC LIMIT 1;"
            cursor.execute(sql)
        
        row = cursor.fetchone()
        conn.close()
        
        if row:
            activity_id = row[0]
            activity_title = row[1]
            sys_logger.info(f"数据库查询到活动: ID={activity_id}, 标题={activity_title}")
            return activity_id
        else:
            sys_logger.warning(f"数据库中未找到匹配的活动记录。")
            return None

    except Exception as e:
        sys_logger.error(f"数据库查询活动ID时发生异常: {e}")
        return None


def audit_draw_activity(headers, activity_id, update_status=6):
    """
    调用审核接口对指定活动进行审核操作。

    参数：
      headers (dict): 包含 Authorization 的请求头
      activity_id (int): 抽奖活动ID（由创建后动态查询获取）
      update_status (int): 审核状态码（6=审核通过）
    """
    if not activity_id:
        sys_logger.error("活动ID为空，审核取消！")
        return False

    payload = {
        "id": int(activity_id),
        "update_status": int(update_status)
    }

    sys_logger.info(f"正在审核活动: ID={activity_id}, update_status={update_status}")

    try:
        response = requests.post(AUDIT_API_URL, headers=headers, json=payload, timeout=30, verify=False)
        sys_logger.info(f"审核响应状态码: {response.status_code}")

        try:
            resp_json = response.json()
            code = resp_json.get("code")
            message = resp_json.get("message", "")

            if code == 10000:
                sys_logger.info(f"[SUCCESS] 社群抽奖活动审核成功！活动ID: {activity_id}")
                return True
            else:
                sys_logger.warning(f"审核接口返回非成功状态码({code}): {message}")
                return False
        except ValueError:
            sys_logger.warning(f"审核响应内容 (非JSON文本): {response.text}")
            return False

    except requests.exceptions.RequestException as e:
        sys_logger.error(f"发送审核请求时发生异常: {e}")
        return False


async def run_flow(
    headless=True,
    title=None,
    show_title=None,
    content=None,
    start_date=None,
    end_date=None,
    start_time=None,
    prizes=None,
    terminal=None,
    remarks=None,
    prize_attr_limit=None,
    draw_type_choice=None,
    pool_type=None,
):
    """
    提供给统一控制台调用的标准动作执行流：
    1. Playwright 浏览器登录截获 Token
    2. 用截获的 Token 通过 requests POST 接口创建抽奖活动
    3. 创建成功后，通过数据库查询获取最新活动 ID
    4. 用截获的 ID 通过 requests POST 接口审核活动

    参数：
      draw_type_choice (int): 抽奖类型选择 (1=大转盘, 2=九宫格)
      pool_type (int): 奖池方式 (1=多平台共享奖池, 2=各平台独立奖池)
    """
    # 根据 draw_type_choice + pool_type 动态选择配置
    is_jiugongge = (draw_type_choice == 2)
    is_independent = (pool_type == 2)  # 1=共享奖池, 2=独立奖池
    target_type = TYPE_JIUGONGGE if is_jiugongge else TYPE

    # 根据 抽奖类型 + 奖池方式 动态选择奖品配置
    if prizes:
        target_prizes = prizes
    elif is_jiugongge and is_independent:
        target_prizes = PRIZES_JIUGONGGE
    elif is_jiugongge and not is_independent:
        target_prizes = PRIZES_JIUGONGGE_SHARED
    elif not is_jiugongge and is_independent:
        target_prizes = PRIZES_INDEPENDENT
    else:
        target_prizes = PRIZES

    target_prize_attr_limit = prize_attr_limit if prize_attr_limit else (PRIZE_ATTR_LIMIT_JIUGONGGE if is_jiugongge else PRIZE_ATTR_LIMIT)
    target_prize_type = PRIZE_TYPE_JIUGONGGE if is_jiugongge else PRIZE_TYPE
    target_wx_work_follow_type = WX_WORK_FOLLOW_TYPE_JIUGONGGE if is_jiugongge else WX_WORK_FOLLOW_TYPE

    # 读取默认配置并在传入参数时予以重写重载
    target_title = title if title else TITLE
    target_show_title = show_title if show_title else SHOW_TITLE
    target_content = content if content else CONTENT
    target_start_date = start_date if start_date else START_DATE
    target_end_date = end_date if end_date else END_DATE
    target_start_time = start_time if start_time else START_TIME
    target_terminal = terminal if terminal else TERMINAL
    target_remarks = remarks if remarks else REMARKS

    token_holder = {}

    async def handle_request(request):
        """核心钩子：监听网页发起的所有异步请求，提纯其 Headers 中的 Authorization 头"""
        headers = request.headers
        auth = headers.get("authorization") or headers.get("Authorization")
        if auth and auth.startswith("Bearer "):
            token_holder["Authorization"] = auth

    sys_logger.info("启动浏览器执行社群抽奖创建+审核全流程...")
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
            return False

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

        auth_token = token_holder.get("Authorization")
        if not auth_token:
            sys_logger.error("Token 截获失败，流程终止。")
            await browser.close()
            return False

        # ------------------ 步骤2: 用截获的 Token 创建活动 ------------------
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Authorization": auth_token,
            "Content-Type": "application/json;charset=UTF-8",
            "User-Agent": "Mozilla/5.0"
        }

        payload = {
            "limit_driver": LIMIT_DRIVER,
            "limit_receive": LIMIT_RECEIVE,
            "draw_type": DRAW_TYPE,
            "type": target_type,
            "prize_type": target_prize_type,
            "prizes": target_prizes,
            "wx_work_follow_title": WX_WORK_FOLLOW_TITLE,
            "wx_work_follow_type": target_wx_work_follow_type,
            "img": IMG,
            "wx_work_tag_type": WX_WORK_TAG_TYPE,
            "wx_work_draw_user_tag": WX_WORK_DRAW_USER_TAG,
            "wx_work_follow_user_tag": WX_WORK_FOLLOW_USER_TAG,
            "terminal": target_terminal,
            "remarks": target_remarks,
            "is_push_msg": IS_PUSH_MSG,
            "msg_value1": MSG_VALUE1,
            "msg_value2": MSG_VALUE2,
            "msg_value3": MSG_VALUE3,
            "bg_img_type": BG_IMG_TYPE,
            "prize_attr_limit": target_prize_attr_limit,
            "wx_work_follow_user": WX_WORK_FOLLOW_USER,
            "title": target_title,
            "show_title": target_show_title,
            "content": target_content,
            "start_date": target_start_date,
            "end_date": target_end_date,
            "start_time": target_start_time,
            "bg_img": BG_IMG,
            "creator_id": CREATOR_ID,
            "creator": CREATOR
        }

        # 九宫格新增字段
        if is_jiugongge:
            payload["enabled"] = ENABLED
            payload["prize"] = PRIZE_FIELD
            payload["prize_limit"] = PRIZE_LIMIT
            payload["user_received_limit"] = USER_RECEIVED_LIMIT
            payload["wx_work_follow_qr"] = WX_WORK_FOLLOW_QR
            payload["wx_work_qr_url"] = WX_WORK_QR_URL
            payload["wx_work_title"] = WX_WORK_TITLE
            payload["remark"] = REMARK

        sys_logger.info(f"接口: {API_URL}")
        sys_logger.info(f"活动标题: {target_title} | 展示标题: {target_show_title}")
        sys_logger.info(f"活动时间: {target_start_date} ~ {target_end_date}")
        sys_logger.info(f"奖品配置: {json.dumps(target_prizes, ensure_ascii=False)}")

        try:
            response = requests.post(API_URL, headers=headers, json=payload, timeout=30, verify=False)
            sys_logger.info(f"创建响应状态码: {response.status_code}")
            resp_json = response.json()
            code = resp_json.get("code")

            if code != 10000:
                sys_logger.warning(f"创建失败！状态码({code}): {resp_json.get('message', '')}")
                await browser.close()
                return False

            sys_logger.info(f"[SUCCESS] 社群抽奖活动创建成功！活动标题: {target_title}")
        except requests.exceptions.RequestException as e:
            sys_logger.error(f"创建活动请求异常: {e}")
            await browser.close()
            return False

        # ------------------ 步骤3: 通过数据库查询获取最新活动ID ------------------
        activity_id = get_latest_draw_id(title=target_title)

        # ------------------ 步骤4: 审核活动 ------------------
        if activity_id:
            sys_logger.info(f"查询到活动ID: {activity_id}，开始审核...")
            audit_draw_activity(headers, activity_id)
        else:
            sys_logger.warning("未能获取活动ID，跳过自动审核。可手动在后台审核。")

        await browser.close()
        return True


if __name__ == "__main__":
    asyncio.run(run_flow(headless=True))
