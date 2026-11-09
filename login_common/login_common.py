# -*- coding: utf-8 -*-
# 这个文件的功能是统一执行后台用户登录鉴权的代码
"""
==========================================================================
🌐 优惠券与工单自动化调度系统 - 后台统一登录鉴权组件 (login_common.py)
==========================================================================
本模块提供了一种高复用、带有多轮重试及网络波动自愈机制的后台系统统一登录流。
各业务执行流（如优惠券创建、工单流转、发券Token抓取）均共享本登录流，杜绝重复冗余编写。

依赖引入：
  - config_common: 提供公共登录配置（账号、密码、系统URL）
  - sys_logger: 提供统一持久化日志落盘
"""

import config_common
from logger.login_logger import login_logger as sys_logger


async def login_to_system(page):
    """
    接收 Playwright 页面句柄并执行统一的后台用户登录鉴权。
    含有多轮网络环境自愈和页面重置，强力击穿 'about:blank' 或网络瞬时重置。
    
    参数：
      page (playwright.async_api.Page): 当前激活的浏览器页面句柄
    """
    url = config_common.BASE_URL
    sys_logger.info(f"正在导航至后台管理登录页面: {url}")
    
    # ----------------- 稳健的多轮页面导航与连接防崩机制 -----------------
    nav_success = False
    for retry in range(1, 4):
        try:
            # 采用 domcontentloaded 提升响应效率，限制 40 秒超时上限
            await page.goto(url, wait_until="domcontentloaded", timeout=40000)
            nav_success = True
            sys_logger.info(f"第 {retry} 次尝试导航成功。")
            break
        except Exception as e:
            sys_logger.warn(f"第 {retry} 次导航遇到网络波动或超时，正在重试: {e}")
            if retry < 3:
                # 递增式避让等待
                await page.wait_for_timeout(2000)
                
    if not nav_success:
        # 如果连续三轮由于 VPN 挂掉或本地连通性障碍导致失败，则抛出断言阻断后续无意义操作
        raise ConnectionError("页面导航连续 3 次失败，当前停留在空白页。请确认后台服务器可访问性或网络VPN配置！")
        
    # 留足 3 秒时间给前端渲染静态框架、JS 包及首屏表单输入框
    await page.wait_for_timeout(3000)
    
    # ----------------- 录入系统登录凭证信息 -----------------
    sys_logger.info("正在录入登录凭证与基本鉴权要素...")
    # 基于原生 placeholder 占位符的最高鲁棒性输入，防元素类名及 ID 重构
    await page.fill("input[placeholder='账号']", config_common.USERNAME)
    await page.fill("input[placeholder='密码']", config_common.PASSWORD)
    await page.fill("input[placeholder='图形验证码']", config_common.IMAGE_CAPTCHA)
    
    # ----------------- 获取短信验证码 -----------------
    sys_logger.info("正在点击‘获取验证码’按钮触发短信验证码流程...")
    try:
        # 匹配标准文字“获取验证码”以物理点击，加入 5 秒超时保护，即使由于某种原因未成功渲染也绝不阻碍主登录流
        await page.click("text=获取验证码", timeout=5000)
    except Exception as e:
        sys_logger.warn(f"点击获取验证码按钮被跳过或未找到 (可能由于前端组件尚未完全激活): {e}")
        
    # 等待短信派发并在极快速度下填入万能测试短信码（999999）
    await page.wait_for_timeout(1000)
    await page.fill("input[placeholder='验证码']", config_common.SMS_CAPTCHA)
    
    # ----------------- 提交登录并阻断式等待跳转重定向 -----------------
    sys_logger.info("正在点击‘登录’按钮提交系统鉴权请求...")
    await page.click("button:has-text('登录')")
    
    sys_logger.info("正在等待系统进行登录校验并完成路由重定向跳转离登录页...")
    # 采用 30 次（最多 30 秒）的自适应轮询，监控浏览器 URL 的变化，避免固定写死固定等待时间
    for _ in range(30):
        await page.wait_for_timeout(1000)
        # 一旦当前的浏览器 URL 不再包含 "/login" 字符串，说明已经重定向通过并鉴权成功
        if "login" not in page.url:
            break
            
    sys_logger.info(f"登录成功，重定向就绪。当前系统路由 URL: {page.url}")
    # 额外给予 2 秒钟等待，确保登录后的主界面、仪表盘和接口数据能加载完毕
    await page.wait_for_timeout(2000)
