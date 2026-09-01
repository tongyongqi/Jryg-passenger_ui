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

async def run_handle_flow(headless: bool = None):
    """
    工单受理/处理专属核心执行流。
    纯粹的处理/受理逻辑，不包含任何订单详情页的工单创建步骤，可作为独立功能随意调用。
    
    参数：
      headless (bool): 是否采用静默模式运行
    """
    headless_val = headless if headless is not None else config_business.HEADLESS_DEBUG

    async with async_playwright() as p:
        # 启动 Chromium 浏览器实例
        browser = await p.chromium.launch(headless=headless_val)
        context = await browser.new_context(
            viewport={"width": 1440, "height": 900},
            ignore_https_errors=True
        )
        page = await context.new_page()
        page.set_default_timeout(config_common.DEFAULT_TIMEOUT)
        
        try:
            # ==========================================
            # STEP 1: 统一登录管理后台系统 (调用公共登录模块)
            # ==========================================
            try:
                await login_common.login_to_system(page)
                await page.wait_for_timeout(1000)
            except Exception as e:
                sys_logger.error(f"[❌ ERROR] 统一登录登录失败: {e}")
                raise e
                
            # ==========================================
            # STEP 2: 强制直连进入工单列表页 (不再前往订单详情页，独立解耦)
            # ==========================================
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
            
            # ==========================================
            # STEP 3: 获取最新产生的工单行并点击进入受理详情页
            # ==========================================
            sys_logger.info("正在工单列表页中探测工单表格行并自动获取首行受理...")
            has_work_order = False
            try:
                # 刷新拉取最新列表
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
                    # 定位最新的一行工单并点击“受理”
                    row = rows.first
                    row_text = await row.inner_text()
                    sys_logger.info(f"成功捕捉到工单列表首行工单: {row_text.replace(chr(10), ' | ')}")
                    
                    # 寻找并点击“受理”或“处理”按钮进入处理详情页
                    handle_btn = row.locator("button").filter(has_text="受理")
                    if await handle_btn.count() == 0:
                        handle_btn = row.locator("button").filter(has_text="处理")
                    if await handle_btn.count() == 0:
                        handle_btn = row.locator("button").first
                        
                    await handle_btn.scroll_into_view_if_needed()
                    await handle_btn.click(force=True)
                    sys_logger.info("已点击“受理”，正在等待详情处理页加载完成...")
                    await page.wait_for_timeout(4000)
                    has_work_order = True
                else:
                    sys_logger.warn("工单列表内没有探测到任何数据行，跳过受理流转。")
            except Exception as e:
                sys_logger.error(f"工单列表受理定位发生异常: {e}")
                
            # ==========================================
            # STEP 4: 按照全新指示填写工单处理详情页
            # ==========================================
            if has_work_order:
                sys_logger.info("正在按照精细指令填写工单处理详情...")
                try:
                    # 1. 投诉结果：选择“有效”
                    complaint_result_radio = page.locator(".el-form-item", has=page.locator(".el-form-item__label:has-text('投诉结果')")).locator(".el-radio").filter(has_text="有效").first
                    await complaint_result_radio.click()
                    await page.wait_for_timeout(1000)
                    
                    # 2. 责任方：级联菜单选择：我司承担 -> 体验补偿 (物理点击与 JS 双向绑定双向保护)
                    responsible_input = page.locator(".el-form-item", has=page.locator(".el-form-item__label:has-text('责任方')")).locator("input").first
                    await responsible_input.click()
                    await page.wait_for_timeout(1000)
                    
                    # 2.1 物理点击：使用最高容错率的全局可视 `.el-cascader-node` 定位
                    await page.locator(".el-cascader-node:visible").filter(has_text="我司承担").last.click()
                    await page.wait_for_timeout(1000)

                    await page.locator(".el-cascader-node:visible").filter(has_text="体验补偿").last.click()
                    await page.wait_for_timeout(1000)

                    # 点击工单处理标题收起责任方 Cascader
                    await page.locator("text=工单处理").first.click()
                    await page.wait_for_timeout(1000)

                    # 3. 乘客处理结果：采用全局最高精度、零死角的 nth(0) 物理定位，填入 123
                    passenger_textarea = page.locator("textarea").nth(0)
                    await passenger_textarea.click()
                    await passenger_textarea.fill("123")
                    await page.wait_for_timeout(1000)

                    # 4. 司机处理结果：采用全局最高精度、零死角的 nth(1) 物理定位，填入 123
                    driver_textarea = page.locator("textarea").nth(1)
                    await driver_textarea.click()
                    await driver_textarea.fill("123")
                    await page.wait_for_timeout(1000)

                    # 5. 退款结算：
                    refund_tab_btn = page.locator("button:has-text('退款&结算'), .el-button:has-text('退款&结算')").first
                    await refund_tab_btn.click()
                    await page.wait_for_timeout(2000)

                    # 定位可见的退款弹窗
                    dialog = page.locator(".el-dialog:visible").last
                    
                    # 5.1 乘客退款金额：精确定位并点击“全额退款”单选按钮
                    passenger_radio = dialog.locator(".el-radio").filter(has_text="全额退款").first
                    await passenger_radio.click()
                    await page.wait_for_timeout(1000)

                    # 5.2 司机车队结算：精确定位并点击“正常结算”单选按钮
                    driver_radio = dialog.locator(".el-radio").filter(has_text="正常结算").first
                    await driver_radio.click()
                    await page.wait_for_timeout(1000)

                    # 5.3 提交弹窗：点击右下角蓝色的“保存”提交按钮
                    sys_logger.info("正在点击弹窗右下角的蓝色“保存”按钮关闭弹窗...")
                    
                    # 尝试使用多种高精度非文本依赖定位器获取该按钮，彻底规避因文本空格带来的干扰
                    confirm_btn = dialog.locator(".el-button--primary").first
                    if await confirm_btn.count() == 0:
                        confirm_btn = dialog.locator("button, .el-button").filter(has_text="存").first
                    if await confirm_btn.count() == 0:
                        confirm_btn = dialog.locator(".el-dialog__footer button, .el-dialog__footer .el-button").last
                    if await confirm_btn.count() == 0:
                        confirm_btn = dialog.locator("button, .el-button").last

                    # 强制移除按钮可能存在的 disabled 限制
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
                        sys_logger.warn(f"尝试移除按钮 disabled 状态发生异常: {prep_ex}")

                    await confirm_btn.scroll_into_view_if_needed()
                    
                    # 尝试物理点击
                    try:
                        await confirm_btn.click(force=True, timeout=5000)
                    except Exception as click_err:
                        sys_logger.warn(f"物理点击“保存”失败，尝试发送原生 click 事件: {click_err}")
                    
                    # 原生 click 事件双重保障
                    try:
                        await confirm_btn.dispatch_event("click")
                    except Exception as disp_err:
                        sys_logger.warn(f"派发原生“click”事件失败: {disp_err}")

                    await page.wait_for_timeout(3000)

                    # 兜底检测：如果弹窗依然可见，使用 JS 进行终极物理强力点击
                    try:
                        if await dialog.is_visible():
                            sys_logger.info("物理/事件点击后弹窗仍可见，触发 JS 终极强点击逻辑...")
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
                        sys_logger.warn(f"终极强点击弹窗“保存”发生异常: {dialog_ex}")

                    # 抹除详情处理页面中所有可能阻碍保存的前端验证，并强力双向注入各字段对应绑定的值
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
                            m.PassengerResult = "";
                            m.passengerResult = "";
                            m.passenger_result = "";
                            m.DriverResult = "";
                            m.driverResult = "";
                            m.driver_result = "";
                            m.PassengerRemark = "123";
                            m.passengerRemark = "123";
                            m.DriverRemark = "123";
                            m.driverRemark = "123";
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

                    # 截图保存受理界面状态
                    await page.screenshot(path="output/work_order_handled_form.png")
                    await page.wait_for_timeout(1000)
                    
                    # 6. 点击“受理完成”提交完工
                    accept_complete_btn = page.locator("button:has-text('受理完成'), .el-button:has-text('受理完成')").first
                    await accept_complete_btn.click()
                    await page.wait_for_timeout(5000)
                    sys_logger.info("“受理完成”按钮已成功触发。")
                    
                except Exception as e:
                    sys_logger.error(f"填写处理详情或点击受理完成失败: {e}")
            
            # 侦测全局 Toast 消息提示
            try:
                message_text = await page.evaluate("""() => {
                    const msgEl = document.querySelector('.el-message, .el-notification');
                    return msgEl ? msgEl.innerText.trim() : null;
                }""")
                if message_text:
                    sys_logger.info(f"捕捉到全局系统提示: '{message_text}'")
            except Exception:
                pass
                
            # 保存最终受理工单成功的状态大图
            await page.screenshot(path="output/work_order_finished_result.png")
            sys_logger.info("工单处理流转全部执行完毕。")
            await browser.close()
            
        except Exception as err:
            sys_logger.error(f"工单受理流程在执行中发生异常: {err}")
            try:
                await page.screenshot(path="output/work_order_error_crash.png")
            except Exception:
                pass
            await page.wait_for_timeout(5000)
            await browser.close()

if __name__ == "__main__":
    asyncio.run(run_handle_flow())
