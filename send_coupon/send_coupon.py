# -*- coding: utf-8 -*-
"""
发放大陆优惠券脚本（通过接口发放）
接口：https://dcms-test6-tx.jryghq.com/admin/v1/coupon/send_coupon
"""
import asyncio
import json
import os
import sys
import requests
import urllib3
from playwright.async_api import async_playwright

root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(root_dir)
sys.path.append(os.path.join(root_dir, "config_common"))
sys.path.append(os.path.join(root_dir, "config_business"))

import config_common
import config_business
from logger.logger import sys_logger

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
os.makedirs("output", exist_ok=True)

API_URL = "https://dcms-test6-tx.jryghq.com/admin/v1/coupon/send_coupon"

async def get_auth_token(headless=True):
    token_holder = {}

    async def handle_request(request):
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

        page.on("request", handle_request)

        url = config_common.BASE_URL
        sys_logger.info(f"正在导航至登录页面: {url}")
        
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

        sys_logger.info("正在输入自动登录凭证...")
        await page.fill("input[placeholder='账号']", config_common.USERNAME)
        await page.fill("input[placeholder='密码']", config_common.PASSWORD)
        await page.fill("input[placeholder='图形验证码']", config_common.IMAGE_CAPTCHA)
        
        try:
            await page.click("text=获取验证码", timeout=5000)
        except Exception as e:
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


def send_mainland_coupon(auth_token, mobiles=None, send_num=None):
    if not auth_token:
        sys_logger.error("无法获取有效的 Authorization Token，发放取消！")
        return False

    target_mobiles = mobiles if mobiles else config_business.TARGET_PHONE
    coupon_id = int(config_business.SEND_COUPON_BATCH)
    send_qty = int(send_num) if send_num is not None else int(config_business.SEND_QTY)
    remark = config_business.REMARK_TEXT

    sys_logger.info("正在准备通过大陆发券接口发放优惠券...")
    
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Authorization": auth_token,
        "Content-Type": "application/json;charset=UTF-8",
        "User-Agent": "Mozilla/5.0"
    }

    coupon_info_list = [
        {"CouponID": coupon_id, "Num": send_qty}
    ]
    coupon_info_str = json.dumps(coupon_info_list)

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

    sys_logger.info(f"接口: {API_URL} | 手机: {target_mobiles} | 批次: {coupon_id} | 数量: {send_qty}")

    try:
        response = requests.post(API_URL, headers=headers, json=payload, timeout=30, verify=False)
        sys_logger.info(f"响应状态码: {response.status_code}")

        try:
            resp_json = response.json()
            code = resp_json.get("code")
            message = resp_json.get("message")
            if code == 10000:
                sys_logger.info(f"[🎉 SUCCESS] 大陆优惠券接口发放指令提交成功！系统提示: {message}")
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


async def run_flow(headless=True, mobiles=None, send_num=None):
    auth_token = await get_auth_token(headless=headless)
    if auth_token:
        send_mainland_coupon(auth_token, mobiles=mobiles, send_num=send_num)
    else:
        sys_logger.error("无法进行优惠券发放，因为 Token 截获失败。")


if __name__ == "__main__":
    HEADLESS = True
    MOBILES = "11000000001"
    SEND_NUM = 10
    asyncio.run(run_flow(headless=HEADLESS, mobiles=MOBILES, send_num=SEND_NUM))
