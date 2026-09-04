# -*- coding: utf-8 -*-
# 这个文件的功能是通过接口直接发放大陆测试优惠券的代码
"""
==========================================================================
🌐 优惠券与工单自动化调度系统 - 大陆优惠券接口发放脚本 (send_coupon_api.py)
==========================================================================
本模块通过直连大陆测试环境发券接口完成优惠券发放，无需浏览器 UI 操作。
Token 通过 Playwright 极简登录流自动截获，随后用 requests 直接 POST 发券。

使用方式：
  1. 在 config_business.py 中修改 SEND_COUPON_BATCH、TARGET_PHONE、SEND_QTY 等参数
  2. 直接运行本文件，或通过 run_work_order.py 调度

依赖引入：
  - config_common: 提供公共登录配置（账号、密码、系统URL）
  - config_business: 提供发券业务参数（手机号、批次号、发放数量等）
  - send_coupon_api_logger: 提供统一持久化日志落盘
"""

import asyncio
import json
import os
import sys
import requests
import urllib3
from playwright.async_api import async_playwright

# 1. 自动追加上级目录至 Python 检索路径，保障单独运行时寻找配置文件无忧
root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(root_dir)
sys.path.append(os.path.join(root_dir, "config_common"))
sys.path.append(os.path.join(root_dir, "config_business"))

import config_common
import config_business
from logger.send_coupon_api_logger import send_coupon_api_logger as sys_logger

# 屏蔽不安全请求报警
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
os.makedirs("output", exist_ok=True)

# 大陆系统内部发券微服务网关地址
API_URL = "https://dcms-test6-tx.jryghq.com/admin/v1/coupon/send_coupon"


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
                sys_logger.warn(f"导航重试 ({retry}/3) 失败: {e}")
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


def send_coupon_via_api(auth_token, mobiles=None, send_num=None, coupon_id=None):
    """
    接收 Bearer Token，通过接口直接发放大陆测试优惠券至指定手机号。

    参数：
      auth_token (str): 动态提取出的 Authorization 鉴权头
      mobiles (str): 目标手机号 (多个号码可以用英文逗号隔开)
      send_num (int): 单次发放张数
      coupon_id (int): 优惠券批次ID
    """
    if not auth_token:
        sys_logger.error("无法获取有效的 Authorization Token，发放取消！")
        return False

    # 读取默认配置并在传入参数时予以重写重载
    target_mobiles = mobiles if mobiles else config_business.TARGET_PHONE
    target_coupon_id = int(coupon_id) if coupon_id is not None else int(config_business.SEND_COUPON_BATCH)
    send_qty = int(send_num) if send_num is not None else int(config_business.SEND_QTY)
    remark = config_business.REMARK_TEXT

    sys_logger.info("正在准备通过大陆发券接口发放优惠券...")

    # 构造携带 Bearer 校验头及 UserAgent 的发券报文头
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Authorization": auth_token,
        "Content-Type": "application/json;charset=UTF-8",
        "User-Agent": "Mozilla/5.0"
    }

    # 构建优惠券信息列表并序列化为 JSON 字符串
    coupon_info_list = [
        {"CouponID": target_coupon_id, "Num": send_qty}
    ]
    coupon_info_str = json.dumps(coupon_info_list)

    # 构建与后台大陆接口微服务契合的数据 Payload
    payload = {
        "SendType": 1,
        "CouponType": 1,
        "Remark": remark,
        "Mobiles": target_mobiles,
        "SendIndex": 1,
        "SendLimit": 5000,
        "UsersFile": "",
        "CouponInfo": coupon_info_str
    }

    sys_logger.info(f"接口: {API_URL} | 手机: {target_mobiles} | 批次: {target_coupon_id} | 数量: {send_qty}")
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
                sys_logger.info(f"[SUCCESS] 大陆优惠券接口发放指令提交成功！系统提示: {message}")
                return True
            else:
                sys_logger.warn(f"接口返回非成功状态码({code}): {message}")
                return False
        except ValueError:
            sys_logger.warn(f"响应内容 (非JSON文本): {response.text}")
            return False

    except requests.exceptions.RequestException as e:
        sys_logger.error(f"发送大陆发券请求时发生异常: {e}")
        return False


async def run_flow(headless=True, mobiles=None, send_num=None, coupon_id=None):
    """
    提供给统一控制台调用的标准动作执行流：
    1. Playwright 静默截获 Token
    2. requests POST 接口发券
    """
    auth_token = await get_auth_token(headless=headless)
    if auth_token:
        send_coupon_via_api(auth_token, mobiles=mobiles, send_num=send_num, coupon_id=coupon_id)
    else:
        sys_logger.error("无法进行优惠券发放，因为 Token 截获失败。")


if __name__ == "__main__":
    HEADLESS = True
    MOBILES = "18618251727"
    SEND_NUM = 3
    COUPON_ID = 34305
    asyncio.run(run_flow(headless=HEADLESS, mobiles=MOBILES, send_num=SEND_NUM, coupon_id=COUPON_ID))
