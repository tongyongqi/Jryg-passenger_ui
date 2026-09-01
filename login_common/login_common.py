# -*- coding: utf-8 -*-
"""
统一的后台登录公共模块，供各个脚本共享调用，避免重复编写登录流程。
"""
import config_common
from logger.logger import sys_logger

async def login_to_system(page):
    """
    负责执行统一的后台用户登录全过程，包括凭证录入、验证码获取、以及重定向安全等待。
    """
    url = config_common.BASE_URL
    sys_logger.info(f"正在导航至后台管理页面: {url}")
    
    nav_success = False
    for retry in range(1, 4):
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=40000)
            nav_success = True
            sys_logger.info(f"第 {retry} 次尝试导航成功。")
            break
        except Exception as e:
            sys_logger.warn(f"第 {retry} 次导航失败: {e}")
            if retry < 3:
                await page.wait_for_timeout(2000)
                
    if not nav_success:
        raise ConnectionError("页面导航连续 3 次失败。")
        
    await page.wait_for_timeout(3000)
    
    sys_logger.info("正在输入登录凭证...")
    await page.fill("input[placeholder='账号']", config_common.USERNAME)
    await page.fill("input[placeholder='密码']", config_common.PASSWORD)
    await page.fill("input[placeholder='图形验证码']", config_common.IMAGE_CAPTCHA)
    
    try:
        await page.click("text=获取验证码", timeout=5000)
    except Exception as e:
        sys_logger.warn(f"点击获取验证码被跳过或失败: {e}")
        
    await page.wait_for_timeout(1000)
    await page.fill("input[placeholder='验证码']", config_common.SMS_CAPTCHA)
    
    sys_logger.info("正在点击登录...")
    await page.click("button:has-text('登录')")
    
    sys_logger.info("正在等待登录跳转重定向...")
    for _ in range(30):
        await page.wait_for_timeout(1000)
        if "login" not in page.url:
            break
    sys_logger.info(f"登录成功，当前 URL: {page.url}")
    await page.wait_for_timeout(2000)
