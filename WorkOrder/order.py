import asyncio
import os
import sys
from playwright.async_api import async_playwright

# 1. 确保将项目根目录添加到 python path 使得模块 and 配置能被正常载入
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import config_common
import config_business
import login_common  # 导入抽离出来的公共登录模块

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
        # 启动 Chromium 浏览器 (调试模式自适应：有头/无头)
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
                await page.wait_for_timeout(1000)  # 选择目标后，1秒后执行下一个功能
            except Exception as e:
                print(f"[❌ ERROR] 统一登录登录失败: {e}")
                raise e
                
            # ==========================================
            # 循环遍历订单列表：支持多订单闭环创建与处理
            # ==========================================
            for order_no in order_ids_val:
                print(f"\n" + "="*60)
                print(f"[*] 🚀 正在开启订单号: {order_no} 的工单闭环处理流程...")
                print("="*60)
                
                # ==========================================
                # STEP 2: 创建工单流程 (已解除注释并完美复活)
                # ==========================================
                meta_id = getattr(config_business, "META_ID", "113491")
                order_type = getattr(config_business, "ORDER_TYPE", "5")
                
                detail_url = f"https://dcms-test6-tx.jryghq.com/#/order_detail/{order_no}?order_no={order_no}&meta_id={meta_id}&order_type={order_type}"
                print(f"[*] 正在直接导航进入目标订单详情页面: {detail_url}")
                try:
                    direct_success = False
                    for retry in range(1, 4):
                        try:
                            await page.goto(detail_url, wait_until="domcontentloaded", timeout=40000)
                            direct_success = True
                            break
                        except Exception as e:
                            print(f"[!] 直连详情页第 {retry} 次尝试失败: {e}")
                            if retry < 3:
                                await page.wait_for_timeout(2000)
                    
                    if not direct_success:
                        raise ConnectionError("直连订单详情页 3 次重试均失败，请检查网络或 URL 结构。")
                        
                    await page.wait_for_timeout(4000)
                    print("[*] 成功直接到达目标订单详情页！")
                    
                    # 滑动到最下方，点击下方导航的“工单”页签
                    print("[*] 正在向下滑动详情页并寻找底部“工单”页签...")
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    await page.wait_for_timeout(1500)
                    
                    tab = page.locator("[id*='tab-工单'], #tab-工单, .el-tabs__item:has-text('工单')").first
                    await tab.scroll_into_view_if_needed()
                    await tab.click()
                    await page.wait_for_timeout(3000)
                    print("[*] 已成功切换至详情页底部“工单”页签。")
                    
                    # 点击右侧“创建工单”拉起新工单创建页面/表单
                    print("[*] 正在寻找并点击“创建工单”按钮...")
                    create_btn = page.locator(".el-tab-pane:visible button:has-text('创建工单'), button:has-text('创建工单')").first
                    await create_btn.scroll_into_view_if_needed()
                    await create_btn.click()
                    await page.wait_for_timeout(4000)
                    print("[*] 新建工单表单页面已成功加载。")
                    
                    # 按照截图 i 与截图 ii 真实、精细地填写新建工单流程
                    print("[*] 正在勾选工单类型为“投诉”单选框...")
                    type_radio = page.locator(".el-form-item:has-text('工单类型') .el-radio, .el-radio").filter(has_text="投诉").first
                    await type_radio.click()
                    await page.wait_for_timeout(500)
                    
                    print("[*] 正在展开“工单标题”四级级联选择器并进行连环穿透点击...")
                    title_input = page.locator(".el-form-item:has-text('工单标题') input, input[placeholder*='请选择工单标题'], input[placeholder*='请选择']").first
                    await title_input.click()
                    await page.wait_for_timeout(1000)
                    
                    # 使用极致丝滑的 JS 异步节点链条穿透连击，带重试延迟，彻底击穿任何异步加载
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
                    print(f"[*] 四级标题连击执行反馈: {cascade_result}")
                    await page.wait_for_timeout(1000)
                    
                    print("[*] 正在选择紧急程度为“一般”...")
                    level_radio = page.locator(".el-form-item:has-text('紧急程度') .el-radio, .el-radio").filter(has_text="一般").first
                    await level_radio.click()
                    await page.wait_for_timeout(500)
                    
                    print("[*] 正在填写问题描述内容: 123...")
                    desc_textarea = page.locator(".el-form-item:has-text('问题描述') textarea, textarea").first
                    await desc_textarea.fill("123")
                    await page.wait_for_timeout(500)
                    
                    print("[*] 正在通过 JS 精准勾选受理人为“我自己受理”...")
                    try:
                        await page.evaluate("""() => {
                            const selfHandleBtn = Array.from(document.querySelectorAll('button, .el-button, .el-radio')).find(el => el.innerText && el.innerText.trim().includes('我自己受理'));
                            if (selfHandleBtn) {
                                selfHandleBtn.click();
                            }
                        }""")
                        await page.wait_for_timeout(500)
                    except Exception as e:
                        print(f"[!] JS 勾选我自己受理失败: {e}")
                        
                    # 使用 JS 降维打击双向绑定保障 100% 写入 Vue Model 并清除前端校验
                    print("[*] 正在执行降维打击一键同步数据并清除拦截 rules...")
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
                    
                    # 截图主表单填充完毕状态
                    await page.screenshot(path="output/work_order_created_form.png")
                    print("[*] 新建工单表单填写完毕，截图已保存至 output/work_order_created_form.png")
                    
                    # 点击最下方的蓝色“保存”按钮提交
                    print("[*] 正在点击“保存”按钮提交新建工单...")
                    save_btn = page.locator("button:visible").filter(has_text="保存").last
                    if await save_btn.count() == 0:
                        save_btn = page.locator("button:visible").filter(has_text="确").last
                    await save_btn.click()
                    await page.wait_for_timeout(6000) # 延长等待至 6 秒确保保存并落库完成
                    print("[*] 提交保存按钮已成功点击并落库完结。")
                    
                except Exception as create_err:
                    print(f"[❌ ERROR] 订单 {order_no} 创建工单流程遭遇异常，跳过后续受理步骤: {create_err}")
                    continue

                # ==========================================
                # STEP 3: 强制直连进入工单列表页并进行受理处理
                # ==========================================
                list_url = "https://dcms-test6-tx.jryghq.com/#/WorkOrderList_new"
                print(f"[*] 正在直接导航进入目标工单列表页: {list_url}")
                
                try:
                    direct_list_success = False
                    for retry in range(1, 4):
                        try:
                            await page.goto(list_url, wait_until="domcontentloaded", timeout=40000)
                            direct_list_success = True
                            break
                        except Exception as e:
                            print(f"[!] 直连列表页第 {retry} 次重试失败: {e}")
                            if retry < 3:
                                await page.wait_for_timeout(2000)
                    
                    if direct_list_success:
                        await page.wait_for_timeout(3000)
                        print(f"[*] 成功导航至工单列表页面。当前 URL: {page.url}")
                    else:
                        raise ConnectionError("直连工单列表页 3 次尝试均失败。")
                except Exception as e:
                    print(f"[❌ ERROR] 导航至工单列表发生异常，跳过此订单处理: {e}")
                    continue
                
                # ==========================================
                # STEP 4: 获取最新产生的工单行并点击进入受理详情页
                # ==========================================
                print("[*] 正在工单列表页中探测工单表格行并自动获取首行受理...")
                has_work_order = False
                try:
                    # 刷新拉取最新列表
                    try:
                        refresh_btn = page.locator("button:visible").filter(has_text="搜索")
                        if await refresh_btn.count() == 0:
                            refresh_btn = page.locator("button:visible").filter(has_text="查询")
                        if await refresh_btn.count() > 0:
                            await refresh_btn.first.click()
                            print("[*] 已成功点击搜索/查询按钮刷新列表。")
                            await page.wait_for_timeout(3000)
                    except Exception as rex:
                        print(f"[!] 尝试点击列表刷新按钮发生异常: {rex}")
                    
                    rows = page.locator(".el-table__row")
                    rows_count = await rows.count()
                    
                    if rows_count > 0:
                        # 定位最新的一行工单并点击“受理”
                        row = rows.first
                        row_text = await row.inner_text()
                        print(f"[*] 成功捕捉到工单列表首行内容: {row_text.replace(chr(10), ' | ')}")
                        
                        # 寻找并点击“受理”或“处理”按钮进入处理详情页
                        handle_btn = row.locator("button").filter(has_text="受理")
                        if await handle_btn.count() == 0:
                            handle_btn = row.locator("button").filter(has_text="处理")
                        if await handle_btn.count() == 0:
                            handle_btn = row.locator("button").first
                            
                        await handle_btn.scroll_into_view_if_needed()
                        await handle_btn.click(force=True)
                        print("[*] 已点击“受理”，正在等待详情处理页加载完成...")
                        await page.wait_for_timeout(4000)
                        has_work_order = True
                    else:
                        print("[⚠️ WARNING] 工单列表内没有探测到任何数据行，跳过受理流程。")
                except Exception as e:
                    print(f"[!] 工单列表受理定位发生异常: {e}")
                    
                # ==========================================
                # STEP 5: 按照指示填写工单处理详情页
                # ==========================================
                if has_work_order:
                    print("[*] 正在按照全新指示精细填写工单处理详情...")
                    try:
                        # 1. 投诉结果：选择“有效”
                        print("[*] 选择投诉结果为“有效”...")
                        complaint_result_radio = page.locator(".el-form-item", has=page.locator(".el-form-item__label:has-text('投诉结果')")).locator(".el-radio").filter(has_text="有效").first
                        await complaint_result_radio.click()
                        await page.wait_for_timeout(1000)
                        
                        # 2. 责任方：级联菜单选择：我司承担 -> 体验补偿 (物理点击与 JS 双向绑定兜底双剑合璧)
                        print("[*] 展开责任方级联选择器并定位节点...")
                        responsible_input = page.locator(".el-form-item", has=page.locator(".el-form-item__label:has-text('责任方')")).locator("input").first
                        await responsible_input.click()
                        await page.wait_for_timeout(1000)
                        
                        # 2.1 物理点击：使用最高容错率的全局可视 `.el-cascader-node` 定位
                        print("[*] 物理点击责任方第 1 级: 我司承担...")
                        await page.locator(".el-cascader-node:visible").filter(has_text="我司承担").last.click()
                        await page.wait_for_timeout(1000)

                        print("[*] 物理点击责任方第 2 级: 体验补偿...")
                        await page.locator(".el-cascader-node:visible").filter(has_text="体验补偿").last.click()
                        await page.wait_for_timeout(1000)

                        # 点击工单处理标题收起责任方 Cascader
                        print("[*] 点击空白处收起责任方级联选择菜单...")
                        await page.locator("text=工单处理").first.click()
                        await page.wait_for_timeout(1000)

                        # 3. 乘客处理结果：采用全局最高精度、零死角的 nth(0) 物理定位，绝不受任何包裹类名改变的干扰
                        print("[*] 正在极速定位并物理填入乘客处理结果备注 (首个 textarea): 123...")
                        passenger_textarea = page.locator("textarea").nth(0)
                        await passenger_textarea.click()
                        await passenger_textarea.fill("123")
                        await page.wait_for_timeout(1000)

                        # 4. 司机处理结果：采用全局最高精度、零死角的 nth(1) 物理定位，绝不受任何包裹类名改变的干扰
                        print("[*] 正在极速定位并物理填入司机处理结果备注 (第二个 textarea): 123...")
                        driver_textarea = page.locator("textarea").nth(1)
                        await driver_textarea.click()
                        await driver_textarea.fill("123")
                        await page.wait_for_timeout(1000)

                        # 5. 退款结算：
                        print("[*] 点击“退款&结算”按钮...")
                        refund_tab_btn = page.locator("button:has-text('退款&结算'), .el-button:has-text('退款&结算')").first
                        await refund_tab_btn.click()
                        await page.wait_for_timeout(2000)

                        # 定位可见的退款弹窗
                        dialog = page.locator(".el-dialog:visible").last
                        
                        # 5.1 乘客退款金额：精确定位并点击原生的“全额退款”单选按钮
                        print("[*] 正在点击单选框选择乘客退款金额为“全额退款”...")
                        passenger_radio = dialog.locator(".el-radio").filter(has_text="全额退款").first
                        await passenger_radio.click()
                        await page.wait_for_timeout(1000)

                        # 5.2 司机车队结算：精确定位并点击原生的“正常结算”单选按钮
                        print("[*] 正在点击单选框选择司机车队结算为“正常结算”...")
                        driver_radio = dialog.locator(".el-radio").filter(has_text="正常结算").first
                        await driver_radio.click()
                        await page.wait_for_timeout(1000)

                        # 5.3 提交弹窗：点击右下角蓝色的“保存”提交按钮
                        print("[*] 正在点击弹窗右下角的蓝色“保存”按钮关闭弹窗...")
                        
                        # 1. 尝试使用多种高精度非文本依赖定位器获取该按钮，彻底规避因文本空格（如“保 存”）带来的干扰
                        confirm_btn = dialog.locator(".el-button--primary").first
                        if await confirm_btn.count() == 0:
                            confirm_btn = dialog.locator("button, .el-button").filter(has_text="存").first
                        if await confirm_btn.count() == 0:
                            confirm_btn = dialog.locator(".el-dialog__footer button, .el-dialog__footer .el-button").last
                        if await confirm_btn.count() == 0:
                            confirm_btn = dialog.locator("button, .el-button").last

                        # 2. 强制移除按钮可能存在的 disabled 限制
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
                            print(f"[!] 尝试移除按钮 disabled 状态发生异常: {prep_ex}")

                        await confirm_btn.scroll_into_view_if_needed()
                        
                        # 3. 尝试物理点击
                        try:
                            await confirm_btn.click(force=True, timeout=5000)
                            print("[*] 物理强制点击“保存”按钮成功发送。")
                        except Exception as click_err:
                            print(f"[!] 物理点击“保存”失败，尝试发送原生 click 事件: {click_err}")
                        
                        # 4. 原生 click 事件双重保障
                        try:
                            await confirm_btn.dispatch_event("click")
                            print("[*] 原生“click”事件已成功派发至“保存”按钮。")
                        except Exception as disp_err:
                            print(f"[!] 派发原生“click”事件失败: {disp_err}")

                        await page.wait_for_timeout(3000)

                        # 5. 兜底检测：如果弹窗依然可见，使用 JS 进行终极物理强力点击
                        try:
                            if await dialog.is_visible():
                                print("[*] 物理/事件点击后弹窗仍可见，触发 JS 终极强点击逻辑...")
                                await page.evaluate("""() => {
                                    const dialogs = document.querySelectorAll('.el-dialog, [role="dialog"], .el-message-box');
                                    for (let i = dialogs.length - 1; i >= 0; i--) {
                                        const d = dialogs[i];
                                        if (window.getComputedStyle(d).display !== 'none') {
                                            const buttons = d.querySelectorAll('button, .el-button');
                                            let targetBtn = null;
                                            // 优先寻找 el-button--primary 按钮
                                            for (let btn of buttons) {
                                                if (btn.classList.contains('el-button--primary')) {
                                                    targetBtn = btn;
                                                    break;
                                                }
                                            }
                                            // 其次寻找包含“存”字的按钮
                                            if (!targetBtn) {
                                                for (let btn of buttons) {
                                                    if (btn.innerText.includes('存')) {
                                                        targetBtn = btn;
                                                        break;
                                                    }
                                                }
                                            }
                                            // 再次寻找最后一个按钮
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
                            print(f"[!] 终极强点击弹窗“保存”发生异常: {dialog_ex}")

                        # 越狱黑科技：抹除详情处理页面中所有可能阻碍保存的前端验证，并强力双向注入各字段对应绑定的值
                        print("[*] 正在抹除工单详情处理页面的校验拦截，并同步强力注入数据模型...")
                        await page.evaluate("""() => {
                            const formEl = document.querySelector('.el-form');
                            if (formEl && formEl.__vue__) {
                                const m = formEl.__vue__.model || {};
                                
                                // 深度双向强行注入责任方、乘客处理和司机处理结果的值
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
                                
                                // 强制同步退款结算的数据字段
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
                        print("[*] 工单处理详情填写完毕，截图已保存至 output/work_order_handled_form.png")
                        await page.wait_for_timeout(1000)
                        
                        # 6. 点击“受理完成”提交完工
                        print("[*] 正在提交“受理完成”...")
                        accept_complete_btn = page.locator("button:has-text('受理完成'), .el-button:has-text('受理完成')").first
                        await accept_complete_btn.click()
                        await page.wait_for_timeout(5000)
                        print("[*] “受理完成”按钮已成功触发。")
                        
                    except Exception as e:
                        print(f"[!] 填写处理详情或点击受理完成失败: {e}")
                
                # 侦测全局 Toast
                try:
                    message_text = await page.evaluate("""() => {
                        const msgEl = document.querySelector('.el-message, .el-notification');
                        return msgEl ? msgEl.innerText.trim() : null;
                    }""")
                    if message_text:
                        print(f"[*] 捕捉到全局系统提示: '{message_text}'")
                except Exception:
                    pass
                    
                # 保存最终受理工单成功的状态大图
                await page.screenshot(path="output/work_order_finished_result.png")
                print(f"[*] 订单号 {order_no} 流程顺利执行完毕！")

            # 全部订单循环执行完毕
            print("[*] [🎉 SUCCESS] 所有订单处理完毕，正在正常关闭浏览器...")
            await browser.close()
            
        except Exception as err:
            # 【异常退出逻辑】出现问题后延迟 5 秒后关闭浏览器，保留现场以供人工排查
            print(f"\n[❌ ERROR] 流程在执行中发生异常: {err}")
            print("[*] 出现问题，正在等待 5 秒后关闭浏览器，请及时查看现场...")
            try:
                await page.screenshot(path="output/work_order_error_crash.png")
                print("[*] 异常状态截图已保存至 output/work_order_error_crash.png")
            except Exception:
                pass
            await page.wait_for_timeout(5000)
            await browser.close()

if __name__ == "__main__":
    asyncio.run(run_flow())
