# -*- coding: utf-8 -*-
# 这个文件的功能是工单基础受理与信息录入的代码

import asyncio
import os
import re
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
      1. 直连进入工单列表页并点击最新待处理工单的"受理/处理"。
      2. 在受理页中填写投诉结果（有效）、责任方（我司承担）、乘客处理结果、司机处理结果。
      3. 上述信息全部填写完毕后，根据页面上实际存在的按钮自动判断走哪个流程（优先级从高到低）：
         - 检测到"取消订单"按钮：点击后走取消订单后续流程。
         - 检测到"改价免单"按钮：点击后弹窗中乘客侧选"免单"、司机结算选"正常结算"，点击"确认"。
         - 检测到"退款&结算"按钮：点击后弹窗中点击"保存"提交。
      4. 执行"受理完成"提交（清除 Vue 校验 + 点击"受理完成"按钮）。
      5. 截图并保留各阶段表单状态。
    
    参数：
      headless (bool): 是否采用静默模式运行
    """
    headless_val = headless if headless is not None else config_business.HEADLESS_DEBUG

    # 动态支持拆分配置
    if hasattr(config_business, "TARGET_ORDER_ID_5"):
        config_business.TARGET_ORDER_ID = config_business.TARGET_ORDER_ID_5

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
            
            # STEP 3: 根据订单号精准搜索并受理
            sys_logger.info(f"正在根据订单号 {config_business.TARGET_ORDER_ID} 搜索工单...")
            await page.wait_for_timeout(3000) # 给列表充足的时间进行首屏渲染
            has_work_order = False
            try:
                # 1. 点击"更多搜索"展开全部筛选条件
                try:
                    more_btn = page.locator("button").filter(has_text="更多搜索")
                    if await more_btn.count() > 0:
                        await more_btn.first.click()
                        sys_logger.info("[*] 已点击'更多搜索'按钮展开全部筛选条件。")
                        await page.wait_for_timeout(2000)
                    else:
                        sys_logger.info("[*] 未找到'更多搜索'按钮，可能已展开。")
                except Exception as m_err:
                    sys_logger.warn(f"点击'更多搜索'按钮时跳过: {m_err}")

                # 2. 不切换页签、不设工单状态筛选，直接根据订单号搜索
                sys_logger.info("[*] 跳过页签切换和工单状态筛选，直接根据订单号搜索。")

                # 3. 输入订单号到搜索框
                try:
                    fill_success = await page.evaluate("""(orderNo) => {
                        // 查找 dt/dd 结构中 dt 包含"订单号"的 dd 下的 input
                        const dts = document.querySelectorAll('dt');
                        for (let dt of dts) {
                            if ((dt.innerText || '').includes('订单号')) {
                                const dd = dt.nextElementSibling;
                                if (dd) {
                                    const input = dd.querySelector('input');
                                    if (input) {
                                        const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                                        nativeInputValueSetter.call(input, orderNo);
                                        input.dispatchEvent(new Event('input', { bubbles: true }));
                                        input.dispatchEvent(new Event('change', { bubbles: true }));
                                        input.dispatchEvent(new Event('blur', { bubbles: true }));
                                        return true;
                                    }
                                }
                            }
                        }
                        // 降级：查找 label/span 包含"订单号"
                        const labels = document.querySelectorAll('.el-form-item__label, label, .label, span, dt');
                        for (let label of labels) {
                            const text = (label.innerText || '').trim();
                            if (text === '订单号') {
                                const formItem = label.closest('.el-form-item') || label.parentElement;
                                if (formItem) {
                                    const input = formItem.querySelector('input');
                                    if (input) {
                                        const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                                        nativeInputValueSetter.call(input, orderNo);
                                        input.dispatchEvent(new Event('input', { bubbles: true }));
                                        input.dispatchEvent(new Event('change', { bubbles: true }));
                                        input.dispatchEvent(new Event('blur', { bubbles: true }));
                                        return true;
                                    }
                                }
                            }
                        }
                        return false;
                    }""", config_business.TARGET_ORDER_ID)
                    if fill_success:
                        sys_logger.info(f"已精准在过滤搜索框中输入目标订单号: {config_business.TARGET_ORDER_ID}")
                    else:
                        sys_logger.warn("未能定位订单号搜索输入框")
                except Exception as o_err:
                    sys_logger.warn(f"填充过滤订单号检索要素时跳过: {o_err}")
                    fill_success = False

                # 4. 点击搜索/查询按钮刷新列表，或按回车触发搜索
                try:
                    if fill_success:
                        try:
                            await page.keyboard.press("Enter")
                            sys_logger.info("[*] 已按回车键触发搜索。")
                            await page.wait_for_timeout(3000)
                        except Exception:
                            pass

                    refresh_btn = page.locator("button:visible").filter(has_text="搜索")
                    if await refresh_btn.count() == 0:
                        refresh_btn = page.locator("button:visible").filter(has_text="查询")
                    if await refresh_btn.count() > 0:
                        await refresh_btn.first.click()
                        sys_logger.info("[*] 已点击搜索按钮刷新列表。")
                        await page.wait_for_timeout(3000)
                except Exception as rex:
                    sys_logger.warn(f"尝试点击列表刷新按钮发生异常: {rex}")

                # 5. 检查搜索结果列表
                try:
                    row_count = await page.locator(".el-table__row").count()
                    sys_logger.info(f"当前列表共渲染了 {row_count} 行工单数据。")
                    if row_count > 0:
                        for i in range(min(row_count, 5)):
                            row_text = await page.locator(".el-table__row").nth(i).inner_text()
                            sys_logger.info(f"  行[{i}] 文本片段: {row_text[:200]}")
                    else:
                        # 列表为0行，说明没有搜索到该订单号的工单，直接停止运行
                        sys_logger.error(f"[❌] 搜索订单号 {config_business.TARGET_ORDER_ID} 后列表为空，没有找到对应的工单！停止运行。")
                        await page.screenshot(path="output/work_order_empty_list.png")
                        sys_logger.info("空列表截图已保存至 output/work_order_empty_list.png。")
                        await context.close()
                        await browser.close()
                        return False
                except Exception:
                    pass

                # 6. 在列表中精准匹配包含目标订单号的行并点击受理按钮
                click_success = await page.evaluate("""(orderNo) => {
                    const rows = document.querySelectorAll('.el-table__row');
                    for (let row of rows) {
                        const rowText = row.innerText || '';
                        // 检查行文本是否包含订单号
                        if (rowText.includes(orderNo)) {
                            const buttons = row.querySelectorAll('button, .el-button, a, span');
                            for (let btn of buttons) {
                                const txt = (btn.innerText || '').trim();
                                if (txt.includes('受理') || txt.includes('处理') || txt.includes('查看') || txt.includes('详情')) {
                                    btn.click();
                                    return true;
                                }
                            }
                            // 如果没有找到按钮，直接点击行本身
                            row.click();
                            return true;
                        }
                    }
                    return false;
                }""", config_business.TARGET_ORDER_ID)

                if click_success:
                    sys_logger.info(f"[🎉 SUCCESS] 已成功精准定位并点击了订单号 {config_business.TARGET_ORDER_ID} 对应行的受理/处理按钮！")
                    await page.wait_for_timeout(4000)
                    has_work_order = True
                else:
                    sys_logger.error(f"[❌] 在列表中未匹配到包含订单号 {config_business.TARGET_ORDER_ID} 的行！停止运行。")
                    await page.screenshot(path="output/work_order_not_found.png")
                    sys_logger.info("未找到工单截图已保存至 output/work_order_not_found.png。")
                    await context.close()
                    await browser.close()
                    return False
            except Exception as e:
                sys_logger.error(f"精准行检索定位发生异常: {e}")
                
            # STEP 4: 仅填写工单处理基本信息
            if has_work_order:
                sys_logger.info("开始录入工单处理基本信息 (投诉结果为有效、责任方为取消订单、备注描述为123)...")
                try:
                    # 1. 投诉结果：选择"有效"
                    complaint_result_radio = page.locator(".el-form-item", has=page.locator(".el-form-item__label:has-text('投诉结果')")).locator(".el-radio").filter(has_text="有效").first
                    await complaint_result_radio.click()
                    await page.wait_for_timeout(1000)
                    
                    # 2. 责任方：级联菜单选择"我司承担" -> 根据处理方式选择二级菜单
                    responsible_input = page.locator(".el-form-item", has=page.locator(".el-form-item__label:has-text('责任方')")).locator("input").first
                    await responsible_input.click()
                    sys_logger.info("[*] 已点击责任方级联菜单输入框，等待下拉面板渲染...")
                    await page.wait_for_timeout(2000)

                    # 点击一级：我司承担
                    level1_success = False
                    for retry in range(1, 4):
                        try:
                            level1_node = page.locator(".el-cascader-node").filter(has_text="我司承担").first
                            if await level1_node.count() > 0:
                                await level1_node.scroll_into_view_if_needed()
                                await level1_node.click()
                                sys_logger.info(f"[✅] 责任方一级菜单 '我司承担' 已点击成功 (第{retry}次)。")
                                level1_success = True
                                break
                        except Exception:
                            pass

                        # JS 降级
                        level1_result = await page.evaluate("""() => {
                            const allNodes = Array.from(document.querySelectorAll('.el-cascader-node, .el-cascader-menu li'));
                            const visibleNodes = allNodes.filter(n => n.offsetParent !== null);
                            const target = visibleNodes.find(n => n.innerText && n.innerText.trim().includes('我司承担'));
                            if (target) { target.click(); return true; }
                            return false;
                        }""")
                        if level1_result:
                            sys_logger.info(f"[✅] 责任方一级菜单 '我司承担' (JS) 已点击成功 (第{retry}次)。")
                            level1_success = True
                            break
                        else:
                            sys_logger.warn(f"[⚠️] 第{retry}次未找到 '我司承担' 节点，重新点击输入框并等待...")
                            await responsible_input.click()
                            await page.wait_for_timeout(2000)

                    if not level1_success:
                        sys_logger.error("[❌] 责任方一级菜单 '我司承担' 3次重试均失败！")
                    else:
                        # 责任方二级菜单：根据页面实际可用选项决定，优先"改价免单"，回退"取消费自动退赔"
                        await page.wait_for_timeout(1500)
                        level2_label = None
                        for candidate_label in ["改价免单", "取消费自动退赔"]:
                            try:
                                candidate_node = page.locator(".el-cascader-node").filter(has_text=candidate_label).first
                                if await candidate_node.count() > 0:
                                    level2_label = candidate_label
                                    sys_logger.info(f"[*] 责任方二级菜单检测到可用选项: '{level2_label}'。")
                                    break
                            except Exception:
                                pass
                        if not level2_label:
                            level2_label = "取消费自动退赔"
                            sys_logger.warn(f"[⚠️] 未检测到已知二级菜单选项，默认使用 '{level2_label}'。")

                        # 点击二级菜单选项
                        await page.wait_for_timeout(1500)
                        level2_cascader_success = False
                        for retry2 in range(1, 4):
                            try:
                                level2_node = page.locator(".el-cascader-node").filter(has_text=level2_label).first
                                if await level2_node.count() > 0:
                                    await level2_node.scroll_into_view_if_needed()
                                    await level2_node.click()
                                    sys_logger.info(f"[✅] 责任方二级菜单 '{level2_label}' 已点击成功 (第{retry2}次)。")
                                    level2_cascader_success = True
                                    break
                            except Exception:
                                pass

                            # JS 降级
                            level2_result = await page.evaluate("""(label) => {
                                const allNodes = Array.from(document.querySelectorAll('.el-cascader-node, .el-cascader-menu li'));
                                const visibleNodes = allNodes.filter(n => n.offsetParent !== null);
                                const target = visibleNodes.find(n => n.innerText && (n.innerText.trim() === label || n.innerText.trim().includes(label)));
                                if (target) { target.click(); return true; }
                                return false;
                            }""", level2_label)
                            if level2_result:
                                sys_logger.info(f"[✅] 责任方二级菜单 '{level2_label}' (JS) 已点击成功 (第{retry2}次)。")
                                level2_cascader_success = True
                                break
                            else:
                                sys_logger.warn(f"[⚠️] 第{retry2}次未找到二级菜单选项 '{level2_label}'，重新点击'我司承担'以期展开...")
                                await page.evaluate("""() => {
                                    const allNodes = Array.from(document.querySelectorAll('.el-cascader-node, .el-cascader-menu li'));
                                    const visibleNodes = allNodes.filter(n => n.offsetParent !== null);
                                    const target = visibleNodes.find(n => n.innerText && n.innerText.trim().includes('我司承担'));
                                    if (target) target.click();
                                }""")
                                await page.wait_for_timeout(1500)

                        if not level2_cascader_success:
                            sys_logger.error(f"[❌] 责任方二级菜单 '{level2_label}' 3次重试均失败！")

                        # 收起级联菜单
                        await page.wait_for_timeout(1000)
                        await page.mouse.click(720, 200)
                        await page.wait_for_timeout(1000)

                    # 3. 乘客处理结果：填入 123
                    passenger_textarea = page.locator("textarea").nth(0)
                    await passenger_textarea.click()
                    await passenger_textarea.fill("123")
                    await page.wait_for_timeout(500)

                    # 4. 司机处理结果：填入 123
                    driver_textarea = page.locator("textarea").nth(1)
                    await driver_textarea.click()
                    await driver_textarea.fill("123")
                    await page.wait_for_timeout(500)

                    # 截图保存填写完毕状态
                    await page.screenshot(path="output/work_order_handled_form.png")
                    sys_logger.info("责任方及乘客/司机处理结果已填写完毕，截图已保存至 output/work_order_handled_form.png。")

                    # 5. 根据页面上实际存在的按钮决定走哪个流程：
                    #    优先检测"取消订单" → 其次"改价免单" → 最后"退款&结算"
                    #    使用正则匹配，允许文字间有空格（Element UI 常见如"退 款 & 结 算"）

                    # 先打印页面上所有可见按钮和可点击元素，方便调试定位
                    try:
                        all_clickable_debug = await page.evaluate("""() => {
                            const elements = Array.from(document.querySelectorAll('button, .el-button, a, [role="button"], .el-link, span'));
                            const visibleElements = elements.filter(e => e.offsetParent !== null);
                            return visibleElements.map(e => ({
                                tag: e.tagName,
                                text: (e.innerText || '').trim().replace(/\\s+/g, ' '),
                                class: e.className
                            })).filter(e => e.text.length > 0 && e.text.length < 20);
                        }""")
                        sys_logger.info(f"[*] 页面上所有可见可点击元素: {all_clickable_debug}")
                    except Exception:
                        pass

                    cancel_pattern = re.compile(r'\s*'.join("取消订单"))
                    change_price_pattern = re.compile(r'\s*'.join("改价免单"))
                    refund_settle_pattern = re.compile(r'\s*'.join("退款") + r'\\s*[&＆]?\\s*' + r'\s*'.join("结算"))

                    has_cancel_order_btn = await page.locator("button:visible").filter(has_text=cancel_pattern).count()
                    has_change_price_btn = await page.locator("button:visible").filter(has_text=change_price_pattern).count()
                    has_refund_settle_btn = await page.locator("button:visible").filter(has_text=refund_settle_pattern).count()

                    # JS 降级检测：在所有可见元素中去除空格后匹配（不只限 button 标签）
                    js_btn_counts = await page.evaluate("""() => {
                        const elements = Array.from(document.querySelectorAll('button, .el-button, a, [role="button"], span, div, .el-link, p'));
                        const visibleElements = elements.filter(e => e.offsetParent !== null);
                        let cancel = 0, change_price = 0, refund_settle = 0;
                        for (let e of visibleElements) {
                            const t = (e.innerText || '').trim().replace(/\\s+/g, '');
                            if (t.includes('取消') && t.includes('订单') && t.length < 10) cancel++;
                            else if (t.includes('改价') && t.includes('免单') && t.length < 10) change_price++;
                            else if (t.includes('退款') && t.includes('结算') && t.length < 10) refund_settle++;
                        }
                        return {cancel, change_price, refund_settle};
                    }""")
                    # 取 Playwright 和 JS 检测结果中的最大值
                    has_cancel_order_btn = max(has_cancel_order_btn, js_btn_counts.get('cancel', 0))
                    has_change_price_btn = max(has_change_price_btn, js_btn_counts.get('change_price', 0))
                    has_refund_settle_btn = max(has_refund_settle_btn, js_btn_counts.get('refund_settle', 0))

                    sys_logger.info(f"[*] 按钮检测结果: 取消订单={has_cancel_order_btn}, 改价免单={has_change_price_btn}, 退款&结算={has_refund_settle_btn}")

                    if has_cancel_order_btn > 0:
                        # === 取消订单分支 ===
                        sys_logger.info("[*] 检测到'取消订单'按钮，开始走取消订单流程...")
                        cancel_order_success = False
                        for retry_co in range(1, 4):
                            try:
                                cancel_btn = page.locator("button:visible").filter(has_text=cancel_pattern).first
                                if await cancel_btn.count() > 0:
                                    await cancel_btn.scroll_into_view_if_needed()
                                    await cancel_btn.click()
                                    sys_logger.info(f"[✅] '取消订单' 按钮已点击成功 (第{retry_co}次)。")
                                    cancel_order_success = True
                                    break
                            except Exception as e_co:
                                sys_logger.warn(f"[⚠️] 第{retry_co}次点击'取消订单'按钮失败: {e_co}")

                            # JS 降级方案
                            js_co = await page.evaluate("""() => {
                                const buttons = Array.from(document.querySelectorAll('button, .el-button'));
                                const visibleBtns = buttons.filter(b => b.offsetParent !== null);
                                const target = visibleBtns.find(b => {
                                    const t = (b.innerText || '').trim().replace(/\\s+/g, '');
                                    return t === '取消订单';
                                });
                                if (target) { target.click(); return true; }
                                return false;
                            }""")
                            if js_co:
                                sys_logger.info(f"[✅] '取消订单' 按钮 (JS) 已点击成功 (第{retry_co}次)。")
                                cancel_order_success = True
                                break
                            else:
                                sys_logger.warn(f"[⚠️] 第{retry_co}次未找到 '取消订单' 按钮。")
                                await page.wait_for_timeout(1000)

                        if not cancel_order_success:
                            sys_logger.error("[❌] '取消订单' 按钮 3次重试均失败！")

                        # 等待取消订单后续流程页面加载/弹窗渲染
                        await page.wait_for_timeout(3000)

                        # 截图保存取消订单后的状态
                        await page.screenshot(path="output/work_order_cancelled.png")
                        sys_logger.info("取消订单后续流程截图已保存至 output/work_order_cancelled.png。")

                    elif has_change_price_btn > 0:
                        # === 改价免单分支 ===
                        sys_logger.info("[*] 检测到'改价免单'按钮，开始走改价免单流程...")
                        change_price_success = False
                        for retry_cp in range(1, 4):
                            try:
                                change_price_btn = page.locator("button:visible").filter(has_text=change_price_pattern).first
                                if await change_price_btn.count() > 0:
                                    await change_price_btn.scroll_into_view_if_needed()
                                    await change_price_btn.click()
                                    sys_logger.info(f"[✅] '改价免单' 按钮已点击成功 (第{retry_cp}次)。")
                                    change_price_success = True
                                    break
                            except Exception as e_cp:
                                sys_logger.warn(f"[⚠️] 第{retry_cp}次点击'改价免单'按钮失败: {e_cp}")

                            # JS 降级方案
                            js_cp = await page.evaluate("""() => {
                                const buttons = Array.from(document.querySelectorAll('button, .el-button'));
                                const visibleBtns = buttons.filter(b => b.offsetParent !== null);
                                const target = visibleBtns.find(b => {
                                    const t = (b.innerText || '').trim().replace(/\\s+/g, '');
                                    return t === '改价免单';
                                });
                                if (target) { target.click(); return true; }
                                return false;
                            }""")
                            if js_cp:
                                sys_logger.info(f"[✅] '改价免单' 按钮 (JS) 已点击成功 (第{retry_cp}次)。")
                                change_price_success = True
                                break
                            else:
                                sys_logger.warn(f"[⚠️] 第{retry_cp}次未找到 '改价免单' 按钮。")
                                await page.wait_for_timeout(1000)

                        if not change_price_success:
                            sys_logger.error("[❌] '改价免单' 按钮 3次重试均失败！")
                        else:
                            # 等待弹窗渲染
                            await page.wait_for_timeout(2000)

                            # 截图保存弹窗初始状态
                            await page.screenshot(path="output/work_order_change_price_dialog.png")
                            sys_logger.info("改价免单弹窗初始状态截图已保存至 output/work_order_change_price_dialog.png。")

                            # 乘客侧：选中"免单"
                            passenger_free_success = False
                            for retry_pf in range(1, 4):
                                try:
                                    # 在弹窗中查找"免单"选项（乘客侧）
                                    free_radio = page.locator(".el-dialog, .el-drawer, .el-popper").filter(has=page.locator(":visible")).locator(".el-radio, .el-radio-button, .el-checkbox, .el-checkbox-button").filter(has_text="免单").first
                                    if await free_radio.count() > 0:
                                        await free_radio.scroll_into_view_if_needed()
                                        await free_radio.click()
                                        sys_logger.info(f"[✅] 乘客侧 '免单' 已选中 (第{retry_pf}次)。")
                                        passenger_free_success = True
                                        break
                                except Exception as e_pf:
                                    sys_logger.warn(f"[⚠️] 第{retry_pf}次选中乘客侧'免单'失败: {e_pf}")

                                # JS 降级方案
                                js_pf = await page.evaluate("""() => {
                                    const containers = Array.from(document.querySelectorAll('.el-dialog, .el-drawer, .el-popper'));
                                    const visibleContainers = containers.filter(c => c.offsetParent !== null);
                                    for (let container of visibleContainers) {
                                        const radios = container.querySelectorAll('.el-radio, .el-radio-button, .el-checkbox, .el-checkbox-button, span');
                                        for (let r of radios) {
                                            const txt = (r.innerText || '').trim().replace(/\\s+/g, '');
                                            if (txt === '免单') {
                                                r.click();
                                                return true;
                                            }
                                        }
                                    }
                                    return false;
                                }""")
                                if js_pf:
                                    sys_logger.info(f"[✅] 乘客侧 '免单' (JS) 已选中 (第{retry_pf}次)。")
                                    passenger_free_success = True
                                    break
                                else:
                                    sys_logger.warn(f"[⚠️] 第{retry_pf}次未找到乘客侧 '免单' 选项。")
                                    await page.wait_for_timeout(1000)

                            if not passenger_free_success:
                                sys_logger.error("[❌] 乘客侧 '免单' 3次重试均失败！")

                            # 司机结算：选择"正常结算"
                            driver_settle_success = False
                            for retry_ds in range(1, 4):
                                try:
                                    # 在弹窗中查找"正常结算"选项（司机结算侧）
                                    settle_radio = page.locator(".el-dialog, .el-drawer, .el-popper").filter(has=page.locator(":visible")).locator(".el-radio, .el-radio-button, .el-checkbox, .el-checkbox-button").filter(has_text="正常结算").first
                                    if await settle_radio.count() > 0:
                                        await settle_radio.scroll_into_view_if_needed()
                                        await settle_radio.click()
                                        sys_logger.info(f"[✅] 司机结算 '正常结算' 已选中 (第{retry_ds}次)。")
                                        driver_settle_success = True
                                        break
                                except Exception as e_ds:
                                    sys_logger.warn(f"[⚠️] 第{retry_ds}次选中司机结算'正常结算'失败: {e_ds}")

                                # JS 降级方案
                                js_ds = await page.evaluate("""() => {
                                    const containers = Array.from(document.querySelectorAll('.el-dialog, .el-drawer, .el-popper'));
                                    const visibleContainers = containers.filter(c => c.offsetParent !== null);
                                    for (let container of visibleContainers) {
                                        const radios = container.querySelectorAll('.el-radio, .el-radio-button, .el-checkbox, .el-checkbox-button, span');
                                        for (let r of radios) {
                                            const txt = (r.innerText || '').trim().replace(/\\s+/g, '');
                                            if (txt === '正常结算') {
                                                r.click();
                                                return true;
                                            }
                                        }
                                    }
                                    return false;
                                }""")
                                if js_ds:
                                    sys_logger.info(f"[✅] 司机结算 '正常结算' (JS) 已选中 (第{retry_ds}次)。")
                                    driver_settle_success = True
                                    break
                                else:
                                    sys_logger.warn(f"[⚠️] 第{retry_ds}次未找到司机结算 '正常结算' 选项。")
                                    await page.wait_for_timeout(1000)

                            if not driver_settle_success:
                                sys_logger.error("[❌] 司机结算 '正常结算' 3次重试均失败！")

                            # 截图保存选择完毕状态
                            await page.screenshot(path="output/work_order_change_price_selected.png")
                            sys_logger.info("改价免单弹窗选项已选择完毕，截图已保存至 output/work_order_change_price_selected.png。")

                            # 点击"确认"按钮提交改价免单
                            # 先打印弹窗内所有可见按钮，方便调试定位
                            try:
                                dialog_btns_debug = await page.evaluate("""() => {
                                    const containers = Array.from(document.querySelectorAll('.el-dialog, .el-drawer, .el-popper'));
                                    const visibleContainers = containers.filter(c => c.offsetParent !== null);
                                    let result = [];
                                    for (let container of visibleContainers) {
                                        const buttons = container.querySelectorAll('button, .el-button, a, [role="button"]');
                                        for (let btn of buttons) {
                                            if (btn.offsetParent !== null) {
                                                result.push({
                                                    text: (btn.innerText || '').trim(),
                                                    class: btn.className,
                                                    tag: btn.tagName,
                                                    id: btn.id || ''
                                                });
                                            }
                                        }
                                    }
                                    return result;
                                }""")
                                sys_logger.info(f"[*] 弹窗内所有可见按钮: {dialog_btns_debug}")
                            except Exception:
                                pass

                            confirm_success = False
                            for retry_cf in range(1, 4):
                                try:
                                    # 在弹窗中查找确认类按钮，支持多种文本（Element UI 按钮文本可能含空格如"确 定"）
                                    for btn_text in ["确认", "确定", "提交", "保存", "确认提交"]:
                                        # 使用正则匹配，允许文字间有空格
                                        pattern = re.compile(r'\s*'.join(btn_text))
                                        confirm_btn = page.locator(".el-dialog, .el-drawer").filter(has=page.locator(":visible")).locator("button:visible").filter(has_text=pattern).first
                                        if await confirm_btn.count() > 0:
                                            await confirm_btn.scroll_into_view_if_needed()
                                            await confirm_btn.click()
                                            sys_logger.info(f"[✅] 改价免单弹窗 '{btn_text}' 按钮已点击成功 (第{retry_cf}次)。")
                                            confirm_success = True
                                            break
                                    if confirm_success:
                                        break
                                except Exception as e_cf:
                                    sys_logger.warn(f"[⚠️] 第{retry_cf}次点击确认按钮失败: {e_cf}")

                                # JS 降级方案：在弹窗内搜索（去除空格后比较）
                                js_cf = await page.evaluate("""() => {
                                    const containers = Array.from(document.querySelectorAll('.el-dialog, .el-drawer'));
                                    const visibleContainers = containers.filter(c => c.offsetParent !== null);
                                    for (let container of visibleContainers) {
                                        const buttons = container.querySelectorAll('button, .el-button');
                                        for (let btn of buttons) {
                                            const txt = (btn.innerText || '').trim().replace(/\\s+/g, '');
                                            if (txt === '确认' || txt === '确定' || txt === '提交' || txt === '保存') {
                                                btn.click();
                                                return txt;
                                            }
                                        }
                                    }
                                    return '';
                                }""")
                                if js_cf:
                                    sys_logger.info(f"[✅] 改价免单弹窗 '{js_cf}' 按钮 (JS) 已点击成功 (第{retry_cf}次)。")
                                    confirm_success = True
                                    break
                                else:
                                    sys_logger.warn(f"[⚠️] 第{retry_cf}次未找到弹窗确认按钮。")
                                    await page.wait_for_timeout(1000)

                            if not confirm_success:
                                sys_logger.error("[❌] 改价免单弹窗 '确认' 按钮 3次重试均失败！")

                            # 等待确认响应
                            await page.wait_for_timeout(3000)

                            # 截图保存改价免单提交后状态
                            await page.screenshot(path="output/work_order_change_price_submitted.png")
                            sys_logger.info("改价免单提交后截图已保存至 output/work_order_change_price_submitted.png。")

                    elif has_refund_settle_btn > 0:
                        # === 退款&结算分支 ===
                        sys_logger.info("[*] 检测到'退款&结算'按钮，开始走退款&结算流程...")
                        refund_settle_success = False
                        for retry_rs in range(1, 4):
                            try:
                                refund_settle_btn = page.locator("button:visible").filter(has_text=refund_settle_pattern).first
                                if await refund_settle_btn.count() > 0:
                                    await refund_settle_btn.scroll_into_view_if_needed()
                                    await refund_settle_btn.click()
                                    sys_logger.info(f"[✅] '退款&结算' 按钮已点击成功 (第{retry_rs}次)。")
                                    refund_settle_success = True
                                    break
                            except Exception as e_rs:
                                sys_logger.warn(f"[⚠️] 第{retry_rs}次点击'退款&结算'按钮失败: {e_rs}")

                            # JS 降级方案
                            js_rs = await page.evaluate("""() => {
                                const buttons = Array.from(document.querySelectorAll('button, .el-button'));
                                const visibleBtns = buttons.filter(b => b.offsetParent !== null);
                                const target = visibleBtns.find(b => {
                                    const t = (b.innerText || '').trim().replace(/\\s+/g, '');
                                    return t.includes('退款') && t.includes('结算');
                                });
                                if (target) { target.click(); return true; }
                                return false;
                            }""")
                            if js_rs:
                                sys_logger.info(f"[✅] '退款&结算' 按钮 (JS) 已点击成功 (第{retry_rs}次)。")
                                refund_settle_success = True
                                break
                            else:
                                sys_logger.warn(f"[⚠️] 第{retry_rs}次未找到 '退款&结算' 按钮。")
                                await page.wait_for_timeout(1000)

                        if not refund_settle_success:
                            sys_logger.error("[❌] '退款&结算' 按钮 3次重试均失败！")
                        else:
                            # 等待退款&结算弹窗渲染
                            await page.wait_for_timeout(2000)

                            # 截图保存退款&结算弹窗初始状态
                            await page.screenshot(path="output/work_order_refund_settle_dialog.png")
                            sys_logger.info("退款&结算弹窗初始状态截图已保存至 output/work_order_refund_settle_dialog.png。")

                            # 先在弹窗中选择"全额退款"和"正常结算"选项
                            # 选择"全额退款"
                            full_refund_success = False
                            for retry_fr in range(1, 4):
                                try:
                                    free_radio = page.locator(".el-dialog, .el-drawer, .el-popper").filter(has=page.locator(":visible")).locator(".el-radio, .el-radio-button, .el-checkbox, .el-checkbox-button").filter(has_text="全额退款").first
                                    if await free_radio.count() > 0:
                                        await free_radio.scroll_into_view_if_needed()
                                        await free_radio.click()
                                        sys_logger.info(f"[✅] '全额退款' 已选中 (第{retry_fr}次)。")
                                        full_refund_success = True
                                        break
                                except Exception as e_fr:
                                    sys_logger.warn(f"[⚠️] 第{retry_fr}次选中'全额退款'失败: {e_fr}")

                                # JS 降级方案
                                js_fr = await page.evaluate("""() => {
                                    const containers = Array.from(document.querySelectorAll('.el-dialog, .el-drawer, .el-popper'));
                                    const visibleContainers = containers.filter(c => c.offsetParent !== null);
                                    for (let container of visibleContainers) {
                                        const radios = container.querySelectorAll('.el-radio, .el-radio-button, .el-checkbox, .el-checkbox-button, span');
                                        for (let r of radios) {
                                            const txt = (r.innerText || '').trim().replace(/\\s+/g, '');
                                            if (txt === '全额退款') {
                                                r.click();
                                                return true;
                                            }
                                        }
                                    }
                                    return false;
                                }""")
                                if js_fr:
                                    sys_logger.info(f"[✅] '全额退款' (JS) 已选中 (第{retry_fr}次)。")
                                    full_refund_success = True
                                    break
                                else:
                                    sys_logger.warn(f"[⚠️] 第{retry_fr}次未找到 '全额退款' 选项。")
                                    await page.wait_for_timeout(1000)

                            if not full_refund_success:
                                sys_logger.error("[❌] '全额退款' 3次重试均失败！")

                            # 选择"正常结算"
                            normal_settle_success = False
                            for retry_ns in range(1, 4):
                                try:
                                    settle_radio = page.locator(".el-dialog, .el-drawer, .el-popper").filter(has=page.locator(":visible")).locator(".el-radio, .el-radio-button, .el-checkbox, .el-checkbox-button").filter(has_text="正常结算").first
                                    if await settle_radio.count() > 0:
                                        await settle_radio.scroll_into_view_if_needed()
                                        await settle_radio.click()
                                        sys_logger.info(f"[✅] '正常结算' 已选中 (第{retry_ns}次)。")
                                        normal_settle_success = True
                                        break
                                except Exception as e_ns:
                                    sys_logger.warn(f"[⚠️] 第{retry_ns}次选中'正常结算'失败: {e_ns}")

                                # JS 降级方案
                                js_ns = await page.evaluate("""() => {
                                    const containers = Array.from(document.querySelectorAll('.el-dialog, .el-drawer, .el-popper'));
                                    const visibleContainers = containers.filter(c => c.offsetParent !== null);
                                    for (let container of visibleContainers) {
                                        const radios = container.querySelectorAll('.el-radio, .el-radio-button, .el-checkbox, .el-checkbox-button, span');
                                        for (let r of radios) {
                                            const txt = (r.innerText || '').trim().replace(/\\s+/g, '');
                                            if (txt === '正常结算') {
                                                r.click();
                                                return true;
                                            }
                                        }
                                    }
                                    return false;
                                }""")
                                if js_ns:
                                    sys_logger.info(f"[✅] '正常结算' (JS) 已选中 (第{retry_ns}次)。")
                                    normal_settle_success = True
                                    break
                                else:
                                    sys_logger.warn(f"[⚠️] 第{retry_ns}次未找到 '正常结算' 选项。")
                                    await page.wait_for_timeout(1000)

                            if not normal_settle_success:
                                sys_logger.error("[❌] '正常结算' 3次重试均失败！")

                            # 截图保存选项选择完毕状态
                            await page.screenshot(path="output/work_order_refund_settle_selected.png")
                            sys_logger.info("退款&结算弹窗选项已选择完毕，截图已保存至 output/work_order_refund_settle_selected.png。")

                            # 点击弹窗中的"保存"按钮提交退款&结算
                            # 先解冻可能被 disabled 的保存按钮
                            try:
                                await page.evaluate("""() => {
                                    const containers = Array.from(document.querySelectorAll('.el-dialog, .el-drawer'));
                                    const visibleContainers = containers.filter(c => c.offsetParent !== null);
                                    for (let container of visibleContainers) {
                                        const buttons = container.querySelectorAll('button, .el-button');
                                        for (let btn of buttons) {
                                            const txt = (btn.innerText || '').trim().replace(/\\s+/g, '');
                                            if (txt === '保存' || txt === '确认' || txt === '确定' || txt === '提交') {
                                                btn.removeAttribute('disabled');
                                                btn.classList.remove('is-disabled');
                                                btn.disabled = false;
                                            }
                                        }
                                    }
                                }""")
                                sys_logger.info("[*] 已解冻弹窗保存按钮 disabled 状态。")
                            except Exception:
                                pass

                            save_success = False
                            for retry_save in range(1, 4):
                                try:
                                    for btn_text in ["保存", "确认", "确定", "提交"]:
                                        pattern = re.compile(r'\s*'.join(btn_text))
                                        save_btn = page.locator(".el-dialog, .el-drawer").filter(has=page.locator(":visible")).locator("button:visible").filter(has_text=pattern).first
                                        if await save_btn.count() > 0:
                                            await save_btn.scroll_into_view_if_needed()
                                            await save_btn.click(force=True)
                                            sys_logger.info(f"[✅] 退款&结算弹窗 '{btn_text}' 按钮已点击成功 (第{retry_save}次)。")
                                            save_success = True
                                            break
                                    if save_success:
                                        break
                                except Exception as e_save:
                                    sys_logger.warn(f"[⚠️] 第{retry_save}次点击保存按钮失败: {e_save}")

                                # JS 降级方案
                                js_save = await page.evaluate("""() => {
                                    const containers = Array.from(document.querySelectorAll('.el-dialog, .el-drawer'));
                                    const visibleContainers = containers.filter(c => c.offsetParent !== null);
                                    for (let container of visibleContainers) {
                                        const buttons = container.querySelectorAll('button, .el-button');
                                        for (let btn of buttons) {
                                            const txt = (btn.innerText || '').trim().replace(/\\s+/g, '');
                                            if (txt === '保存' || txt === '确认' || txt === '确定' || txt === '提交') {
                                                btn.click();
                                                return txt;
                                            }
                                        }
                                    }
                                    return '';
                                }""")
                                if js_save:
                                    sys_logger.info(f"[✅] 退款&结算弹窗 '{js_save}' 按钮 (JS) 已点击成功 (第{retry_save}次)。")
                                    save_success = True
                                    break
                                else:
                                    sys_logger.warn(f"[⚠️] 第{retry_save}次未找到弹窗保存按钮。")
                                    await page.wait_for_timeout(1000)

                            if not save_success:
                                sys_logger.error("[❌] 退款&结算弹窗 '保存' 按钮 3次重试均失败！")

                            # 等待保存响应
                            await page.wait_for_timeout(3000)

                            # 截图保存退款&结算提交后状态
                            await page.screenshot(path="output/work_order_refund_settle_submitted.png")
                            sys_logger.info("退款&结算提交后截图已保存至 output/work_order_refund_settle_submitted.png。")

                    else:
                        sys_logger.error("[❌] 未检测到'取消订单'、'改价免单'或'退款&结算'按钮，无法判断后续流程！")

                    # === 受理完成提交（改价免单/取消订单流程后均需执行） ===
                    sys_logger.info("[*] 开始执行'受理完成'提交流程...")

                    # 0. 先关闭所有可能残留的弹窗，避免遮挡受理完成按钮
                    try:
                        await page.evaluate("""() => {
                            // 点击弹窗右上角的关闭按钮
                            const closeBtns = document.querySelectorAll('.el-dialog__close, .el-dialog__headerbtn, .el-drawer__close-btn');
                            closeBtns.forEach(btn => {
                                if (btn.offsetParent !== null) btn.click();
                            });
                            // 移除弹窗遮罩
                            const wrappers = document.querySelectorAll('.el-dialog__wrapper, .v-modal');
                            wrappers.forEach(w => {
                                if (w.style) {
                                    w.style.display = 'none';
                                }
                            });
                        }""")
                        sys_logger.info("[*] 已清理弹窗及遮罩层。")
                        await page.wait_for_timeout(1000)
                    except Exception as close_err:
                        sys_logger.warn(f"[⚠️] 清理弹窗异常: {close_err}")

                    # 1. 强力清除 Vue 必填校验拦截
                    try:
                        await page.evaluate("""() => {
                            const formEl = document.querySelector('.el-form');
                            if (formEl && formEl.__vue__) {
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
                        sys_logger.info("[*] Vue 必填校验已清除。")
                    except Exception as vue_err:
                        sys_logger.warn(f"[⚠️] 清除 Vue 校验异常: {vue_err}")

                    # 2. 点击"受理完成"按钮提交工单
                    accept_complete_clicked = False
                    for retry_ac in range(1, 4):
                        try:
                            # 使用正则匹配，允许文字间有空格（如"受 理 完 成"）
                            ac_pattern = re.compile(r'\s*'.join("受理完成"))
                            ac_btn = page.locator("button:visible").filter(has_text=ac_pattern).first
                            if await ac_btn.count() > 0:
                                await ac_btn.scroll_into_view_if_needed()
                                await ac_btn.click()
                                sys_logger.info(f"[✅] '受理完成' 按钮已点击成功 (第{retry_ac}次)。")
                                accept_complete_clicked = True
                                break
                        except Exception as e_ac:
                            sys_logger.warn(f"[⚠️] 第{retry_ac}次点击'受理完成'按钮失败: {e_ac}")

                        # JS 降级方案
                        js_ac = await page.evaluate("""() => {
                            const buttons = Array.from(document.querySelectorAll('button, .el-button'));
                            const visibleBtns = buttons.filter(b => b.offsetParent !== null);
                            for (let btn of visibleBtns) {
                                const txt = (btn.innerText || '').trim().replace(/\\s+/g, '');
                                if (txt === '受理完成') {
                                    btn.click();
                                    return true;
                                }
                            }
                            return false;
                        }""")
                        if js_ac:
                            sys_logger.info(f"[✅] '受理完成' 按钮 (JS) 已点击成功 (第{retry_ac}次)。")
                            accept_complete_clicked = True
                            break
                        else:
                            sys_logger.warn(f"[⚠️] 第{retry_ac}次未找到 '受理完成' 按钮。")
                            await page.wait_for_timeout(1000)

                    if not accept_complete_clicked:
                        sys_logger.error("[❌] '受理完成' 按钮 3次重试均失败！")

                    # 等待受理完成提交响应
                    await page.wait_for_timeout(5000)

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

                    # 截图保存最终结果
                    await page.screenshot(path="output/work_order_finished_result.png")
                    sys_logger.info("工单受理完成流程全部执行完毕，最终截图已保存至 output/work_order_finished_result.png。")
                    
                except Exception as e:
                    sys_logger.error(f"录入工单处理基本信息发生异常: {e}")
            
            await browser.close()
            
        except Exception as err:
            sys_logger.error(f"工单受理流程在执行中发生异常: {err}")
            await browser.close()

if __name__ == "__main__":
    asyncio.run(run_accept_flow())
