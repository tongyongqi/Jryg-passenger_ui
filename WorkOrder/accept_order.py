# -*- coding: utf-8 -*-
# 这个文件的功能是工单基础受理与信息录入的代码

import asyncio
import os
import sys
from playwright.async_api import async_playwright

# 1. 确保将项目根目录添加到 python path 使得模块 and 配置能被正常载入
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import config_common
import config_business
import login_common  # 导入抽离出来的公共登录模块
from logger.work_order_logger import work_order_logger as sys_logger

# 确保存放截图的 output 目录存在
os.makedirs("output", exist_ok=True)

async def run_accept_flow(headless: bool = None):
    """
    工单受理阶段专属核心执行流。
    负责：
      1. 直连进入工单列表页并点击最新待处理工单的“受理/处理”。
      2. 在受理页中仅填写投诉结果（有效）、责任方（我司承担-体验补偿）、以及乘客/司机处理结果。
      3. 截图并保留当前表单状态。
    
    参数：
      headless (bool): 是否采用静默模式运行
    """
    headless_val = headless if headless is not None else config_business.HEADLESS_DEBUG

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless_val)
        context = await browser.new_context(
            viewport={"width": 1440, "height": 900},
            ignore_https_errors=True
        )
        page = await context.new_page()
        page.set_default_timeout(config_common.DEFAULT_TIMEOUT)
        
        try:
            # STEP 1: 登录后台
            try:
                await login_common.login_to_system(page)
                await page.wait_for_timeout(1000)
            except Exception as e:
                sys_logger.error(f"[❌ ERROR] 统一登录登录失败: {e}")
                raise e
                
            # STEP 2: 进入工单列表页
            list_url = "https://dcms-test6-tx.jryghq.com/#/WorkOrderList_new"
            sys_logger.info(f"正在直接导航进入工单列表页面: {list_url}")
            
            try:
                direct_list_success = False
                for retry in range(1, 4):
                    try:
                        await page.goto(list_url, wait_until="domcontentloaded", timeout=40000)
                        direct_list_success = True
                        break
                    except Exception as e:
                        sys_logger.warn(f"直连列表页第 {retry} 次重试失败: {e}")
                        if retry < 3:
                            await page.wait_for_timeout(2000)
                
                if direct_list_success:
                    await page.wait_for_timeout(3000)
                    sys_logger.info("成功导航至工单列表页面。")
                else:
                    raise ConnectionError("直连工单列表页 3 次尝试均失败。")
            except Exception as e:
                sys_logger.error(f"导航至工单列表发生异常: {e}")
                await browser.close()
                return
            
            # STEP 3: 点击首行工单进行受理
            sys_logger.info("正在探测列表最新行并点击“受理/处理”进入受理信息录入页面...")
            has_work_order = False
            try:
                try:
                    refresh_btn = page.locator("button:visible").filter(has_text="搜索")
                    if await refresh_btn.count() == 0:
                        refresh_btn = page.locator("button:visible").filter(has_text="查询")
                    if await refresh_btn.count() > 0:
                        await refresh_btn.first.click()
                        await page.wait_for_timeout(3000)
                except Exception as rex:
                    sys_logger.warn(f"尝试点击列表刷新按钮发生异常: {rex}")
                
                rows = page.locator(".el-table__row")
                rows_count = await rows.count()
                
                if rows_count > 0:
                    row = rows.first
                    row_text = await row.inner_text()
                    sys_logger.info(f"成功捕捉到最新工单: {row_text.replace(chr(10), ' | ')}")
                    
                    handle_btn = row.locator("button").filter(has_text="受理")
                    if await handle_btn.count() == 0:
                        handle_btn = row.locator("button").filter(has_text="处理")
                    if await handle_btn.count() == 0:
                        handle_btn = row.locator("button").first
                        
                    await handle_btn.scroll_into_view_if_needed()
                    await handle_btn.click(force=True)
                    await page.wait_for_timeout(4000)
                    has_work_order = True
                else:
                    sys_logger.warn("工单列表内没有数据行，跳过受理流程。")
            except Exception as e:
                sys_logger.error(f"工单列表受理定位发生异常: {e}")
                
            # STEP 4: 仅填写工单处理基本信息
            if has_work_order:
                sys_logger.info("开始录入工单处理基本信息 (投诉结果、责任方、备注描述)...")
                try:
                    # 1. 投诉结果：选择“有效”
                    complaint_result_radio = page.locator(".el-form-item", has=page.locator(".el-form-item__label:has-text('投诉结果')")).locator(".el-radio").filter(has_text="有效").first
                    await complaint_result_radio.click()
                    await page.wait_for_timeout(1000)
                    
                    # 2. 责任方：级联菜单选择：我司承担 -> 体验补偿
                    responsible_input = page.locator(".el-form-item", has=page.locator(".el-form-item__label:has-text('责任方')")).locator("input").first
                    await responsible_input.click()
                    await page.wait_for_timeout(1000)
                    
                    await page.locator(".el-cascader-node:visible").filter(has_text="我司承担").last.click()
                    await page.wait_for_timeout(1000)

                    await page.locator(".el-cascader-node:visible").filter(has_text="体验补偿").last.click()
                    await page.wait_for_timeout(1000)

                    # 点击收起 Cascader
                    await page.locator("text=工单处理").first.click()
                    await page.wait_for_timeout(1000)

                    # 3. 乘客处理结果：填入 123
                    passenger_textarea = page.locator("textarea").nth(0)
                    await passenger_textarea.click()
                    await passenger_textarea.fill("123")
                    await page.wait_for_timeout(1000)

                    # 4. 司机处理结果：填入 123
                    driver_textarea = page.locator("textarea").nth(1)
                    await driver_textarea.click()
                    await driver_textarea.fill("123")
                    await page.wait_for_timeout(1000)

                    # 截图保存基本受理完毕状态
                    await page.screenshot(path="output/work_order_handled_form.png")
                    sys_logger.info("工单处理基本信息录入完毕，截图已保存至 output/work_order_handled_form.png。")
                    
                except Exception as e:
                    sys_logger.error(f"录入工单处理基本信息发生异常: {e}")
            
            await browser.close()
            
        except Exception as err:
            sys_logger.error(f"工单受理流程在执行中发生异常: {err}")
            await browser.close()

if __name__ == "__main__":
    asyncio.run(run_accept_flow())
