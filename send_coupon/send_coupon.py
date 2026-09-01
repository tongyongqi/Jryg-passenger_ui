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

# 1. 支持单独运行时引入其他自定义配置模块
root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(root_dir)
sys.path.append(os.path.join(root_dir, "config_common"))
sys.path.append(os.path.join(root_dir, "config_business"))

# 导入业务配置和通用配置
import config_common
import config_business

# 禁用不安全请求的警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 创建 output 目录
os.makedirs("output", exist_ok=True)

# 接口地址
API_URL = "https://dcms-test6-tx.jryghq.com/admin/v1/coupon/send_coupon"

async def get_auth_token(headless=True):
    """
    通过运行极简的 Playwright 登录流程，从页面请求流量中自动拦截并提取 Authorization Token。
    """
    token_holder = {}

    async def handle_request(request):
        headers = request.headers
        auth = headers.get("authorization") or headers.get("Authorization")
        if auth and auth.startswith("Bearer "):
            token_holder["Authorization"] = auth

    print("[*] 启动浏览器以获取系统登录鉴权 Token (静默无头模式)...")
    async with async_playwright() as p:
        # 强制支持传入的静默/有头参数
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(
            viewport={"width": 1440, "height": 900},
            ignore_https_errors=True
        )
        page = await context.new_page()
        page.set_default_timeout(config_common.DEFAULT_TIMEOUT)

        # 注册网络请求拦截监听器
        page.on("request", handle_request)

        url = config_common.BASE_URL
        print(f"[*] 正在导航至登录页面: {url}")
        
        # 稳健的网络自愈和重试导航
        nav_success = False
        for retry in range(1, 4):
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=40000)
                nav_success = True
                break
            except Exception as e:
                print(f"[!] 导航重试 ({retry}/3) 失败: {e}")
                if retry < 3:
                    await page.wait_for_timeout(2000)

        if not nav_success:
            print("[❌] 无法导航至后台登录页。")
            await browser.close()
            return None

        await page.wait_for_timeout(2000)

        # 输入账户信息登录
        print("[*] 正在输入自动登录凭证...")
        await page.fill("input[placeholder='账号']", config_common.USERNAME)
        await page.fill("input[placeholder='密码']", config_common.PASSWORD)
        await page.fill("input[placeholder='图形验证码']", config_common.IMAGE_CAPTCHA)
        
        try:
            await page.click("text=获取验证码", timeout=5000)
        except Exception as e:
            print(f"[!] 获取短信验证码跳过: {e}")

        await page.wait_for_timeout(1000)
        await page.fill("input[placeholder='验证码']", config_common.SMS_CAPTCHA)
        
        print("[*] 正在提交登录...")
        await page.click("button:has-text('登录')")

        # 等待重定向及 Token 拦截
        print("[*] 正在等待后台跳转并截获 API Authorization Token...")
        for _ in range(30):
            await page.wait_for_timeout(1000)
            # 一旦截获到了 Token 且已成功跳转离开 login 页，就可以提前结束
            if "Authorization" in token_holder and "login" not in page.url:
                print("[🎉] 成功截获 Authorization Token！")
                break
        
        await browser.close()
        
    return token_holder.get("Authorization")


def send_mainland_coupon(auth_token, mobiles=None, send_num=None):
    """
    使用抓取的 Authorization Token 直接通过 requests 发送大陆优惠券。
    """
    if not auth_token:
        print("[❌ ERROR] 无法获取有效的 Authorization Token，发放取消！")
        return False

    # 读取业务配置，并支持参数重载
    target_mobiles = mobiles if mobiles else config_business.TARGET_PHONE
    coupon_id = int(config_business.SEND_COUPON_BATCH)
    send_qty = int(send_num) if send_num is not None else int(config_business.SEND_QTY)
    remark = config_business.REMARK_TEXT

    print("\n[*] 正在准备通过大陆发券接口发放优惠券...")
    
    # 构造接口请求头
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Authorization": auth_token,
        "Content-Type": "application/json;charset=UTF-8",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    # 优惠券配置信息 (首字母大写的 CouponID 和 Num)
    coupon_info_list = [
        {"CouponID": coupon_id, "Num": send_qty}
    ]
    coupon_info_str = json.dumps(coupon_info_list)

    # 构造 Payload
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

    print(f"[*] 接口地址: {API_URL}")
    print(f"[*] 目标手机号: {target_mobiles}")
    print(f"[*] 发放批次(CouponID): {coupon_id}")
    print(f"[*] 数量(Num): {send_qty}")
    print(f"[*] 发送参数 Payload: {json.dumps(payload, ensure_ascii=False, indent=2)}")

    try:
        # 发送接口请求
        response = requests.post(API_URL, headers=headers, json=payload, timeout=30, verify=False)
        print("\n" + "=" * 50)
        print(f"[*] 响应状态码: {response.status_code}")

        try:
            resp_json = response.json()
            print("[*] 响应内容 (JSON):")
            print(json.dumps(resp_json, ensure_ascii=False, indent=2))
            
            code = resp_json.get("code")
            message = resp_json.get("message")
            if code == 10000:
                print("\n[🎉 SUCCESS] 优惠券接口发放指令提交成功！")
                print(f"[💬] 系统提示: {message}")
                return True
            else:
                print(f"\n[⚠️ WARNING] 接口返回非成功状态码({code}): {message}")
                return False
        except ValueError:
            print("[*] 响应内容 (非JSON文本):")
            print(response.text)
            return False

        print("=" * 50)

    except requests.exceptions.RequestException as e:
        print(f"\n[❌ ERROR] 发送大陆发券请求时发生异常: {e}")
        return False


async def run_flow(headless=True, mobiles=None, send_num=None):
    # 1. 自动登录截获 Token (支持传入静默配置)
    auth_token = await get_auth_token(headless=headless)
    
    # 2. 调用大陆发券接口发送优惠券
    if auth_token:
        send_mainland_coupon(auth_token, mobiles=mobiles, send_num=send_num)
    else:
        print("[❌] 无法进行优惠券发放，因为 Token 截获失败。")


if __name__ == "__main__":
    # 鉴权登录配置：True 代表开启静默模式，False 代表真实弹出浏览器
    HEADLESS = True
    
    # 发放的目标手机号，多手机号可以用英文逗号隔开，或者单手机号
    MOBILES = "11000000001"
    
    # 发放个数（每次给客户发放的优惠券张数）
    SEND_NUM = 10
    
    asyncio.run(run_flow(headless=HEADLESS, mobiles=MOBILES, send_num=SEND_NUM))
