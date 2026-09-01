# -*- coding: utf-8 -*-
# 这个文件的功能是后台登录凭证录入与鉴权重定向的代码

import config_common

async def login_to_system(page):
    """
    负责执行统一的后台用户登录全过程，包括凭证录入、验证码获取、以及重定向安全等待。
    """
    url = config_common.BASE_URL
    print(f"[*] 正在导航至优惠券管理页面: {url}")
    
    # 稳健的网络连接自愈与重试机制 (严防 about:blank)
    nav_success = False
    for retry in range(1, 4):
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=40000)
            nav_success = True
            print(f"[*] 第 {retry} 次尝试导航成功。")
            break
        except Exception as e:
            print(f"[!] 第 {retry} 次导航失败 (可能由于网络重置或波动): {e}")
            if retry < 3:
                print("[*] 正在等待 2 秒后尝试重新连接...")
                await page.wait_for_timeout(2000)
                
    if not nav_success:
        raise ConnectionError("页面导航连续 3 次失败，当前停留在空白页。请检查您的网络连接、科学上网代理或服务器是否开启！")
        
    await page.wait_for_timeout(3000)
    
    # 1. 登录流程
    print("[*] 正在输入登录凭证...")
    await page.fill("input[placeholder='账号']", config_common.USERNAME)
    await page.fill("input[placeholder='密码']", config_common.PASSWORD)
    await page.fill("input[placeholder='图形验证码']", config_common.IMAGE_CAPTCHA)
    
    print("[*] 正在点击获取验证码...")
    try:
        await page.click("text=获取验证码", timeout=5000)
    except Exception as e:
        print(f"[!] 点击获取验证码失败或被跳过: {e}")
        
    await page.wait_for_timeout(1000)
    await page.fill("input[placeholder='验证码']", config_common.SMS_CAPTCHA)
    
    print("[*] 正在点击登录...")
    await page.click("button:has-text('登录')")
    
    # 稳健等待登录重定向跳离登录页
    print("[*] 正在等待登录跳转重定向...")
    for _ in range(30):
        await page.wait_for_timeout(1000)
        if "login" not in page.url:
            break
    print(f"[*] 登录成功，当前页面 URL: {page.url}")
