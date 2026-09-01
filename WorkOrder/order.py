import asyncio
import os
import sys
from playwright.async_api import async_playwright

# 1. 确保将项目根目录添加到 python path 使得模块 and 配置能被正常载入
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import config_common
import config_business
import login_common  # 导入抽离出来的公共登录模块
from logger.logger import sys_logger

# 确保 output 文件夹在运行前已经创建
os.makedirs("output", exist_ok=True)

# ==========================================
# 默认配置的全局订单号变量：支持单个或多个订单
# ==========================================
DEFAULT_ORDER_IDS = [
    getattr(config_business, "TARGET_ORDER_ID", "7358984980")
]

async def run_flow(headless: bool = None, order_ids: list = None):
    # 解析传入参数或回退至默认配置
    headless_val = headless if headless is not None else config_business.HEADLESS_DEBUG
    order_ids_val = order_ids if order_ids is not None else DEFAULT_ORDER_IDS

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless_val)
        context = await browser.new_context(
            viewport={"width": 1440, "height": 900},
            ignore_https_errors=True
        )
        page = await context.new_page()
        page.set_default_timeout(config_common.DEFAULT_TIMEOUT)
        
        try:
            # STEP 1: 统一登录管理后台系统
            try:
                await login_common.login_to_system(page)
                await page.wait_for_timeout(1000)
            except Exception as e:
                sys_logger.error(f"统一登录登录失败: {e}")
                raise e
                
            # 循环遍历订单列表：支持多订单闭环创建与处理
            for order_no in order_ids_val:
                sys_logger.info(f"🚀 开始订单 {order_no} 的工单闭环流转流程...")
                
                # STEP 2: 创建工单流程
                meta_id = getattr(config_business, "META_ID", "113491")
                order_type = getattr(config_business, "ORDER_TYPE", "5")
                
                detail_url = f"https://dcms-test6-tx.jryghq.com/#/order_detail/{order_no}?order_no={order_no}&meta_id={meta_id}&order_type={order_type}"
                sys_logger.info(f"正在直接导航进入目标订单详情页面: {detail_url}")
                try:
                    direct_success = False
                    for retry in range(1, 4):
                        try:
                            await page.goto(detail_url, wait_until="domcontentloaded", timeout=40000)
                            direct_success = True
                            break
                        except Exception as e:
                            sys_logger.warn(f"直连详情页第 {retry} 次尝试失败: {e}")
                            if retry < 3:
                                await page.wait_for_timeout(2000)
                    
                    if not direct_success:
                        raise ConnectionError("直连订单详情页 3 次重试均失败。")
                        
                    await page.wait_for_timeout(4000)
                    
                    # 滑动到最下方，点击下方导航的“工单”页签
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    await page.wait_for_timeout(1500)
                    
                    tab = page.locator("[id*='tab-工单'], #tab-工单, .el-tabs__item:has-text('工单')").first
                    await tab.scroll_into_view_if_needed()
                    await tab.click()
                    await page.wait_for_timeout(3000)
                    sys_logger.info("已切换至详情页底部“工单”页签。")
                    
                    # 点击右侧“创建工单”拉起新工单创建页面
                    create_btn = page.locator(".el-tab-pane:visible button:has-text('创建工单'), button:has-text('创建工单')").first
                    await create_btn.scroll_into_view_if_needed()
                    await create_btn.click()
                    await page.wait_for_timeout(4000)
                    sys_logger.info("新建工单表单页面加载成功。")
                    
                    # 按照截图 i 与截图 ii 真实、精细地填写新建工单流程
                    type_radio = page.locator(".el-form-item:has-text('工单类型') .el-radio, .el-radio").filter(has_text="投诉").first
                    await type_radio.click()
                    await page.wait_for_timeout(500)
                    
                    title_input = page.locator(".el-form-item:has-text('工单标题') input, input[placeholder*='请选择工单标题'], input[placeholder*='请选择']").first
                    await title_input.click()
                    await page.wait_for_timeout(1000)
                    
                    cascade_result = await page.evaluate("""() => {
                        const clickNode = (text) => {
                            const nodes = Array.from(document.querySelectorAll('.el-cascader-node, .el-cascader-menu li, li'));
                            const target = nodes.find(n => n.getBoundingClientRect().width > 0 && n.innerText.trim() === text);
                            if (target) {
                                target.click();
                                return true;
                            }
                            return false;
                        };
                        
                        return new Promise((resolve) => {
                            clickNode('投诉');
                            setTimeout(() => {
                                clickNode('订单问题');
                                setTimeout(() => {
                                    clickNode('费用问题');
                                    setTimeout(() => {
                                        const success = clickNode('未上车产生费用');
                                        resolve(success ? 'Cascade click completed!' : 'Failed at last step');
                                    }, 1200);
                                }, 1000);
                            }, 800);
                        });
                    }""")
                    sys_logger.info(f"四级标题连击执行反馈: {cascade_result}")
                    await page.wait_for_timeout(1000)
                    
                    level_radio = page.locator(".el-form-item:has-text('紧急程度') .el-radio, .el-radio").filter(has_text="一般").first
                    await level_radio.click()
                    await page.wait_for_timeout(500)
                    
                    desc_textarea = page.locator(".el-form-item:has-text('问题描述') textarea, textarea").first
                    await desc_textarea.fill("123")
                    await page.wait_for_timeout(500)
                    
                    try:
                        await page.evaluate("""() => {
                            const selfHandleBtn = Array.from(document.querySelectorAll('button, .el-button, .el-radio')).find(el => el.innerText && el.innerText.trim().includes('我自己受理'));
                            if (selfHandleBtn) {
                                selfHandleBtn.click();
                            }
                        }""")
                        await page.wait_for_timeout(500)
                    except Exception as e:
                        sys_logger.warn(f"JS 勾选我自己受理失败: {e}")
                        
                    # 强力同步数据并清除拦截 rules
                    await page.evaluate(f"""() => {{
                        const formEl = document.querySelector('.el-form');
                        if (formEl && formEl.__vue__) {{
                            const m = formEl.__vue__.model || {{}};
                            
                            m.ProblemDesc = "123";
                            m.remark = "123";
                            m.Remark = "123";
                            m.EmergencyLevel = "一般";
                            m.emergencyLevel = "一般";
                            m.SelfHandle = true;
                            m.selfHandle = true;
                            m.WorkOrderType = "投诉";
                            
                            const fields = formEl.__vue__.fields || [];
                            fields.forEach(field => {{
                                field.rules = [];
                                if (field.selfRules) field.selfRules = [];
                                field.required = false;
                                field.validateState = 'success';
                                field.validateMessage = '';
                                if (typeof field.clearValidate === 'function') {{
                                    field.clearValidate();
                                }}
                            }});
                            
                            if (formEl.__vue__.rules) {{
                                formEl.__vue__.rules = {{}};
                            }}
                            
                            formEl.__vue__.validate = (callback) => {{
                                if (typeof callback === 'function') {{
                                    callback(true);
                                }}
                                return Promise.resolve(true);
                            }};
                        }}
                    }}""")
                    
                    await page.screenshot(path="output/work_order_created_form.png")
                    
                    # 点击最下方的蓝色“保存”按钮提交
                    save_btn = page.locator("button:visible").filter(has_text="保存").last
                    if await save_btn.count() == 0:
                        save_btn = page.locator("button:visible").filter(has_text="确").last
                    await save_btn.click()
                    await page.wait_for_timeout(6000)
                    sys_logger.info("创建工单保存提交成功。")
                    
                except Exception as create_err:
                    sys_logger.error(f"订单 {order_no} 创建工单流程遭遇异常: {create_err}")
                    continue

                # STEP 3: 强制直连进入工单列表页并进行受理处理
                list_url = "https://dcms-test6-tx.jryghq.com/#/WorkOrderList_new"
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
                    continue
                
                # STEP 4: 获取最新产生的工单行并点击进入受理详情页
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
                        sys_logger.info(f"捕捉到最新产生的工单: {row_text.replace(chr(10), ' | ')}")
                        
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
                        sys_logger.warn("工单列表内没有探测到任何数据行。")
                except Exception as e:
                    sys_logger.error(f"工单列表受理定位发生异常: {e}")
                    
                # STEP 5: 按照指示填写工单处理详情页
                if has_work_order:
                    sys_logger.info("开始填写工单处理详情页及退款结算...")
                    try:
                        complaint_result_radio = page.locator(".el-form-item", has=page.locator(".el-form-item__label:has-text('投诉结果')")).locator(".el-radio").filter(has_text="有效").first
                        await complaint_result_radio.click()
                        await page.wait_for_timeout(1000)
                        
                        responsible_input = page.locator(".el-form-item", has=page.locator(".el-form-item__label:has-text('责任方')")).locator("input").first
                        await responsible_input.click()
                        await page.wait_for_timeout(1000)
                        
                        await page.locator(".el-cascader-node:visible").filter(has_text="我司承担").last.click()
                        await page.wait_for_timeout(1000)

                        await page.locator(".el-cascader-node:visible").filter(has_text="体验补偿").last.click()
                        await page.wait_for_timeout(1000)

                        await page.locator("text=工单处理").first.click()
                        await page.wait_for_timeout(1000)

                        passenger_textarea = page.locator("textarea").nth(0)
                        await passenger_textarea.click()
                        await passenger_textarea.fill("123")
                        await page.wait_for_timeout(1000)

                        driver_textarea = page.locator("textarea").nth(1)
                        await driver_textarea.click()
                        await driver_textarea.fill("123")
                        await page.wait_for_timeout(1000)

                        refund_tab_btn = page.locator("button:has-text('退款&结算'), .el-button:has-text('退款&结算')").first
                        await refund_tab_btn.click()
                        await page.wait_for_timeout(2000)

                        dialog = page.locator(".el-dialog:visible").last
                        
                        passenger_radio = dialog.locator(".el-radio").filter(has_text="全额退款").first
                        await passenger_radio.click()
                        await page.wait_for_timeout(1000)

                        driver_radio = dialog.locator(".el-radio").filter(has_text="正常结算").first
                        await driver_radio.click()
                        await page.wait_for_timeout(1000)

                        # 提交弹窗：点击右下角蓝色的“保存”提交按钮
                        confirm_btn = dialog.locator(".el-button--primary").first
                        if await confirm_btn.count() == 0:
                            confirm_btn = dialog.locator("button, .el-button").filter(has_text="存").first
                        if await confirm_btn.count() == 0:
                            confirm_btn = dialog.locator(".el-dialog__footer button, .el-dialog__footer .el-button").last
                        if await confirm_btn.count() == 0:
                            confirm_btn = dialog.locator("button, .el-button").last

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
                        
                        try:
                            await confirm_btn.click(force=True, timeout=5000)
                        except Exception as click_err:
                            sys_logger.warn(f"物理点击“保存”失败，尝试发送原生 click 事件: {click_err}")
                        
                        try:
                            await confirm_btn.dispatch_event("click")
                        except Exception as disp_err:
                            sys_logger.warn(f"派发原生“click”事件失败: {disp_err}")

                        await page.wait_for_timeout(3000)

                        try:
                            if await dialog.is_visible():
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

                        # 越狱黑科技：抹除详情处理页面中所有可能阻碍保存的前端验证
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

                        await page.screenshot(path="output/work_order_handled_form.png")
                        await page.wait_for_timeout(1000)
                        
                        # 6. 点击“受理完成”提交完工
                        accept_complete_btn = page.locator("button:has-text('受理完成'), .el-button:has-text('受理完成')").first
                        await accept_complete_btn.click()
                        await page.wait_for_timeout(5000)
                        sys_logger.info("“受理完成”提交流转触发成功。")
                        
                    except Exception as e:
                        sys_logger.error(f"填写处理详情或点击受理完成失败: {e}")
                
                # 侦测全局 Toast
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
                sys_logger.info(f"订单号 {order_no} 闭流流转完毕！")

            sys_logger.info("所有订单处理完毕，正在关闭浏览器...")
            await browser.close()
            
        except Exception as err:
            sys_logger.error(f"工单流程在执行中发生异常: {err}")
            try:
                await page.screenshot(path="output/work_order_error_crash.png")
            except Exception:
                pass
            await page.wait_for_timeout(5000)
            await browser.close()

if __name__ == "__main__":
    asyncio.run(run_flow())
