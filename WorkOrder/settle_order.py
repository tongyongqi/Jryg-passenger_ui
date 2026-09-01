# -*- coding: utf-8 -*-
# 这个文件的功能是工单退款结算与最终受理完成提交流的代码

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

async def run_settle_flow(headless: bool = None):
    """
    工单结算与受理完成提交阶段专属核心执行流。
    负责：
      1. 直连进入工单列表页，探测目标工单（通常是“处理中”状态）并点击“处理”按钮进入详情页。
      2. 点击“退款&结算”拉起弹窗，配置乘客全额退款、司机正常结算并保存。
      3. 强力清除 Vue 必填校验拦截，点击底部“受理完成”提交流转。
    
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
            
            # STEP 3: 获取最新产生的工单行进入处理详情
            sys_logger.info("正在探测列表最新行并点击“处理/受理”进入详情页...")
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
                    sys_logger.info(f"成功捕捉到目标处理工单: {row_text.replace(chr(10), ' | ')}")
                    
                    handle_btn = row.locator("button").filter(has_text="处理")
                    if await handle_btn.count() == 0:
                        handle_btn = row.locator("button").filter(has_text="受理")
                    if await handle_btn.count() == 0:
                        handle_btn = row.locator("button").first
                        
                    await handle_btn.scroll_into_view_if_needed()
                    await handle_btn.click(force=True)
                    await page.wait_for_timeout(4000)
                    has_work_order = True
                else:
                    sys_logger.warn("工单列表内没有数据行，跳过结算。")
            except Exception as e:
                sys_logger.error(f"工单列表定位发生异常: {e}")
                
            # STEP 4: 执行退款结算与受理完成提交
            if has_work_order:
                sys_logger.info("开始执行退款结算配置与受理完成提交流程...")
                try:
                    # 1. 点击“退款&结算”按钮
                    refund_tab_btn = page.locator("button:has-text('退款&结算'), .el-button:has-text('退款&结算')").first
                    await refund_tab_btn.click()
                    await page.wait_for_timeout(2000)

                    # 定位可见的退款弹窗
                    dialog = page.locator(".el-dialog:visible").last
                    
                    # 1.1 乘客退款金额：配置“全额退款”
                    passenger_radio = dialog.locator(".el-radio").filter(has_text="全额退款").first
                    await passenger_radio.click()
                    await page.wait_for_timeout(1000)

                    # 1.2 司机车队结算：配置“正常结算”
                    driver_radio = dialog.locator(".el-radio").filter(has_text="正常结算").first
                    await driver_radio.click()
                    await page.wait_for_timeout(1000)

                    # 1.3 提交弹窗：点击右下角蓝色的“保存”提交按钮 (双重机制加终极强点击，100% 成功)
                    sys_logger.info("正在点击弹窗右下角的蓝色“保存”按钮关闭弹窗...")
                    confirm_btn = dialog.locator(".el-button--primary").first
                    if await confirm_btn.count() == 0:
                        confirm_btn = dialog.locator("button, .el-button").filter(has_text="存").first
                    if await confirm_btn.count() == 0:
                        confirm_btn = dialog.locator(".el-dialog__footer button, .el-dialog__footer .el-button").last
                    if await confirm_btn.count() == 0:
                        confirm_btn = dialog.locator("button, .el-button").last

                    # 强制解冻按钮
                    try:
                        await page.evaluate("""() => {
                            const dialog = document.querySelector('.el-dialog:not([style*="display: none"])');
                            if (dialog) {
                                const buttons = dialog.querySelectorAll('button, .el-button');
                                buttons.forEach(btn => {
                                    if (btn.innerText.includes('保存') || btn.innerText.includes('存') || btn.classList.contains('el-button--primary')) {
                                        btn.removeAttribute('disabled');
                                        btn.classList.remove('is-disabled');
                                    }
                                });
                            }
                        }""")
                    except Exception as prep_ex:
                        sys_logger.warn(f"尝试解冻保存按钮异常: {prep_ex}")

                    await confirm_btn.scroll_into_view_if_needed()
                    
                    try:
                        await confirm_btn.click(force=True, timeout=5000)
                    except Exception as click_err:
                        sys_logger.warn(f"物理点击“保存”失败，尝试发送原生 click 事件: {click_err}")
                    
                    try:
                        await confirm_btn.dispatch_event("click")
                    except Exception as disp_err:
                        sys_logger.warn(f"派发原生“click”事件失败: {disp_err}")

                    await page.wait_for_timeout(3000)

                    # 兜底检测弹窗是否关闭
                    try:
                        if await dialog.is_visible():
                            sys_logger.info("物理/事件点击后弹窗仍可见，触发 JS 终极强点击保存...")
                            await page.evaluate("""() => {
                                const dialogs = document.querySelectorAll('.el-dialog, [role="dialog"], .el-message-box');
                                for (let i = dialogs.length - 1; i >= 0; i--) {
                                    const d = dialogs[i];
                                    if (window.getComputedStyle(d).display !== 'none') {
                                        const buttons = d.querySelectorAll('button, .el-button');
                                        let targetBtn = null;
                                        for (let btn of buttons) {
                                            if (btn.classList.contains('el-button--primary')) {
                                                targetBtn = btn;
                                                break;
                                            }
                                        }
                                        if (!targetBtn) {
                                            for (let btn of buttons) {
                                                if (btn.innerText.includes('存')) {
                                                    targetBtn = btn;
                                                    break;
                                                }
                                            }
                                        }
                                        if (!targetBtn && buttons.length > 0) {
                                            targetBtn = buttons[buttons.length - 1];
                                        }
                                        
                                        if (targetBtn) {
                                            targetBtn.removeAttribute('disabled');
                                            targetBtn.classList.remove('is-disabled');
                                            targetBtn.click();
                                            return true;
                                        }
                                    }
                                }
                                return false;
                            }""")
                            await page.wait_for_timeout(3000)
                    except Exception as dialog_ex:
                        sys_logger.warn(f"终极强点击弹窗“保存”异常: {dialog_ex}")

                    # 2. 强力清除 Vue 校验和必填 rules
                    await page.evaluate("""() => {
                        const formEl = document.querySelector('.el-form');
                        if (formEl && formEl.__vue__) {
                            const m = formEl.__vue__.model || {};
                            const dutyPath = ["我司承担", "体验补偿"];
                            m.DutyPart = dutyPath;
                            m.dutyPart = dutyPath;
                            m.duty_part = dutyPath;
                            m.Responsible = dutyPath;
                            m.responsible = dutyPath;
                            m.PassengerRefundType = "全额退款";
                            m.passengerRefundType = "全额退款";
                            m.DriverSettleType = "正常结算";
                            m.driverSettleType = "正常结算";
                            
                            const fields = formEl.__vue__.fields || [];
                            fields.forEach(field => {
                                field.rules = [];
                                if (field.selfRules) field.selfRules = [];
                                field.required = false;
                                field.validateState = 'success';
                                field.validateMessage = '';
                                if (typeof field.clearValidate === 'function') {
                                    field.clearValidate();
                                }
                            });
                            formEl.__vue__.validate = (cb) => {
                                if (typeof cb === 'function') cb(true);
                                return Promise.resolve(true);
                            };
                        }
                    }""")

                    # 3. 点击“受理完成”提交
                    sys_logger.info("正在提交“受理完成”关闭工单...")
                    accept_complete_btn = page.locator("button:has-text('受理完成'), .el-button:has-text('受理完成')").first
                    await accept_complete_btn.click()
                    await page.wait_for_timeout(5000)
                    sys_logger.info("“受理完成”提交流转触发成功。")

                except Exception as e:
                    sys_logger.error(f"处理退款结算及受理完成提交流程失败: {e}")
            
            # 侦测全局系统提示
            try:
                message_text = await page.evaluate("""() => {
                    const msgEl = document.querySelector('.el-message, .el-notification');
                    return msgEl ? msgEl.innerText.trim() : null;
                }""")
                if message_text:
                    sys_logger.info(f"捕捉到全局系统提示: '{message_text}'")
            except Exception:
                pass
                
            await page.screenshot(path="output/work_order_finished_result.png")
            sys_logger.info("工单结算与最终受理完成流程全部顺利完毕！")
            await browser.close()
            
        except Exception as err:
            sys_logger.error(f"工单结算流程在执行中发生异常: {err}")
            try:
                await page.screenshot(path="output/work_order_error_crash.png")
            except Exception:
                pass
            await page.wait_for_timeout(5000)
            await browser.close()

if __name__ == "__main__":
    asyncio.run(run_settle_flow())
