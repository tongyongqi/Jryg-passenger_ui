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
      2. 在受理页中仅填写投诉结果（有效）、责任方（我司承担-取消订单）、以及乘客/司机处理结果。
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
            
            # STEP 3: 精准匹配包含目标订单号的工单行进行受理
            sys_logger.info(f"正在工单列表中寻找并精准匹配包含目标订单号 {config_business.TARGET_ORDER_ID} 的工单行进行受理...")
            await page.wait_for_timeout(3000) # 给列表充足的时间进行首屏渲染
            has_work_order = False
            try:
                # 1. 自动切换到“全部”或“全部工单”页签，彻底穿透默认的“我的/处理中”筛选限制
                try:
                    tab_success = await page.evaluate("""() => {
                        const items = Array.from(document.querySelectorAll('.el-radio-button__inner, .el-tabs__item, .el-radio__label, span, button, a'));
                        const allTab = items.find(t => t.innerText && (t.innerText.trim() === '全部' || t.innerText.trim() === '全部工单'));
                        if (allTab) {
                            allTab.click();
                            return true;
                        }
                        return false;
                    }""")
                    if tab_success:
                        sys_logger.info("[*] 已成功切换至列表“全部/全部工单”页签。")
                        await page.wait_for_timeout(2000)
                except Exception as t_err:
                    sys_logger.warn(f"切换全部页签要素时跳过: {t_err}")

                # 2. 采用万能 JS 穿透，自动匹配各种“订单号/单号/业务ID/号”输入框并填入数据
                try:
                    fill_success = await page.evaluate("""(orderNo) => {
                        const inputs = document.querySelectorAll('input');
                        for (let input of inputs) {
                            const ph = (input.placeholder || '').trim();
                            if (ph.includes('订单') || ph.includes('单号') || ph.includes('业务') || ph.includes('ID') || ph.includes('号')) {
                                input.value = '';
                                input.dispatchEvent(new Event('input', { bubbles: true }));
                                input.value = orderNo;
                                input.dispatchEvent(new Event('input', { bubbles: true }));
                                return true;
                            }
                        }
                        return false;
                    }""", config_business.TARGET_ORDER_ID)
                    if fill_success:
                        sys_logger.info(f"已精准在过滤搜索框中输入目标订单号: {config_business.TARGET_ORDER_ID}")
                except Exception as o_err:
                    sys_logger.warn(f"填充过滤订单号检索要素时跳过: {o_err}")

                # 3. 点击搜索/查询按钮刷新列表
                try:
                    refresh_btn = page.locator("button:visible").filter(has_text="搜索")
                    if await refresh_btn.count() == 0:
                        refresh_btn = page.locator("button:visible").filter(has_text="查询")
                    if await refresh_btn.count() > 0:
                        await refresh_btn.first.click()
                        sys_logger.info("[*] 已点击搜索按钮刷新列表。")
                        await page.wait_for_timeout(3000)
                except Exception as rex:
                    sys_logger.warn(f"尝试点击列表刷新按钮发生异常: {rex}")

                # 4. 使用终极 JS 在当前页面的表格的所有行中检索包含目标订单号的行并直接触发点击
                click_success = await page.evaluate("""(orderNo) => {
                    const rows = document.querySelectorAll('.el-table__row');
                    for (let row of rows) {
                        if (row.innerText.includes(orderNo)) {
                            const buttons = row.querySelectorAll('button, .el-button');
                            for (let btn of buttons) {
                                const txt = btn.innerText.trim();
                                if (txt.includes('受理') || txt.includes('处理')) {
                                    btn.click();
                                    return true;
                                }
                            }
                        }
                    }
                    return false;
                }""", config_business.TARGET_ORDER_ID)

                if click_success:
                    sys_logger.info(f"[🎉 SUCCESS] 已成功精准定位并点击了订单号 {config_business.TARGET_ORDER_ID} 对应行的受理/处理按钮！")
                    await page.wait_for_timeout(4000)
                    has_work_order = True
                else:
                    sys_logger.warn(f"[⚠️] 在当前筛选后的列表中未匹配到包含订单号 {config_business.TARGET_ORDER_ID} 的可见行，降级使用首行数据进行受理...")
                    # 降级退路：点击首行进行受理
                    rows = page.locator(".el-table__row")
                    if await rows.count() > 0:
                        row = rows.first
                        handle_btn = row.locator("button").filter(has_text="受理")
                        if await handle_btn.count() == 0:
                            handle_btn = row.locator("button").filter(has_text="处理")
                        if await handle_btn.count() == 0:
                            handle_btn = row.locator("button").first
                        await handle_btn.scroll_into_view_if_needed()
                        await handle_btn.click(force=True)
                        await page.wait_for_timeout(4000)
                        has_work_order = True
            except Exception as e:
                sys_logger.error(f"精准行检索定位发生异常: {e}")
                
            # STEP 4: 仅填写工单处理基本信息
            if has_work_order:
                sys_logger.info("开始录入工单处理基本信息 (投诉结果为有效、责任方为取消订单、备注描述为123)...")
                try:
                    # 1. 投诉结果：选择“有效”
                    complaint_result_radio = page.locator(".el-form-item", has=page.locator(".el-form-item__label:has-text('投诉结果')")).locator(".el-radio").filter(has_text="有效").first
                    await complaint_result_radio.click()
                    await page.wait_for_timeout(1000)
                    
                    # 2. 责任方：级联菜单选择：我司承担 -> 取消订单（自适应极速查找并点击）
                    responsible_input = page.locator(".el-form-item", has=page.locator(".el-form-item__label:has-text('责任方')")).locator("input").first
                    await responsible_input.click()
                    await page.wait_for_timeout(1000)
                    
                    responsible_result = await page.evaluate("""async () => {
                        const clickNode = (text) => {
                            const nodes = Array.from(document.querySelectorAll('.el-cascader-node:visible, .el-cascader-menu li:visible, li'));
                            const target = nodes.find(n => n.innerText && n.innerText.trim().includes(text));
                            if (target) {
                                target.click();
                                return true;
                            }
                            return false;
                        };
                        
                        // 点击一级
                        const ok1 = clickNode('我司承担') || clickNode('承担');
                        if (!ok1) return 'Failed at level 1';
                        await new Promise(r => setTimeout(r, 1000));
                        
                        // 点击二级：优先找取消订单，找不到则找体验补偿
                        const ok2 = clickNode('取消订单') || clickNode('取消') || clickNode('体验补偿') || clickNode('体验');
                        if (!ok2) return 'Failed at level 2';
                        
                        return 'Responsible cascader clicked successfully!';
                    }""")
                    sys_logger.info(f"责任方点击级联反馈: {responsible_result}")
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
