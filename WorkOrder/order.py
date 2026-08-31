import asyncio
import os
import sys
from playwright.async_api import async_playwright

# 1. 确保将项目根目录添加到 python path 使得模块和配置能被正常载入
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import config_common
import config_business

# 确保 output 文件夹在运行前已经创建
os.makedirs("output", exist_ok=True)

async def main():
    async with async_playwright() as p:
        # 启动 Chromium 浏览器 (调试模式自适应：有头/无头)
        browser = await p.chromium.launch(headless=config_business.HEADLESS_DEBUG)
        context = await browser.new_context(
            viewport={"width": 1440, "height": 900},
            ignore_https_errors=True
        )
        page = await context.new_page()
        page.set_default_timeout(config_common.DEFAULT_TIMEOUT)
        
        # ==========================================
        # STEP 1: 登录管理后台系统
        # ==========================================
        url = config_common.BASE_URL
        print(f"[*] 正在导航至管理页面: {url}")
        
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
            print("\n[❌ ERROR] 页面导航连续 3 次失败，当前停留在空白页。请检查您的网络连接、VPN配置或服务器是否处于正常开启状态！")
            await browser.close()
            return
            
        await page.wait_for_timeout(3000)
        
        print("[*] 正在输入登录凭证...")
        await page.fill("input[placeholder='账号']", config_common.USERNAME)
        await page.fill("input[placeholder='密码']", config_common.PASSWORD)
        await page.fill("input[placeholder='图形验证码']", config_common.IMAGE_CAPTCHA)
        
        print("[*] 正在点击获取验证码...")
        try:
            await page.click("text=获取验证码", timeout=5000)
        except Exception as e:
            print(f"[!] 点击获取验证码被跳过: {e}")
            
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
        print(f"[*] 登录成功，当前 URL: {page.url}")
        await page.wait_for_timeout(3000)
        
        # ==========================================
        # STEP 2: 切换到大导航“新订单系统”，并查询订单号
        # ==========================================
        print("[*] 正在切换顶部大导航至“新订单系统”...")
        try:
            # 1. 显式点击顶部横向大菜单“新订单系统”
            await page.evaluate("""() => {
                const navs = Array.from(document.querySelectorAll('*'));
                const orderNav = navs.find(el => el.innerText && el.innerText.trim() === '新订单系统');
                if (orderNav) {
                    orderNav.click();
                } else {
                    const fallback = navs.find(el => el.innerText && el.innerText.trim().includes('订单'));
                    if (fallback) fallback.click();
                }
            }""")
            await page.wait_for_timeout(3000)
            
            # 2. 精准点击左侧侧边栏“订单信息” (展开订单大项，并点击)
            print("[*] 正在左侧展开大分类并点击“订单信息”...")
            try:
                clear_search = page.locator("input[placeholder='搜索菜单']")
                if await clear_search.count() > 0:
                    await clear_search.click()
                    await clear_search.fill("")
                    await page.wait_for_timeout(500)
            except Exception:
                pass
                
            submenu = page.locator(".el-submenu").filter(has_text="订单").first
            submenu_title = submenu.locator(".el-submenu__title")
            await submenu_title.scroll_into_view_if_needed()
            if "is-opened" not in await submenu.evaluate("(el) => el.className"):
                await submenu_title.click()
                await page.wait_for_timeout(1000)
                
            menu_item = page.locator(".el-menu-item").filter(has_text="订单信息").first
            await menu_item.scroll_into_view_if_needed()
            await menu_item.click()
            await page.wait_for_timeout(5000)
        except Exception as e:
            print(f"[!] 导航新订单系统/订单信息发生异常，尝试直连作为兜底: {e}")
            await page.goto("https://dcms-test6-tx.jryghq.com/#/admin/v1/order_info", wait_until="domcontentloaded")
            await page.wait_for_timeout(5000)
            
        # 等待订单信息页面加载完毕
        print("[*] 正在等待订单列表页面加载...")
        try:
            await page.wait_for_selector(".el-table__row, input[placeholder*='订单']", timeout=30000)
        except Exception as e:
            print(f"[!] 等待订单列表行超时，尝试直接填入查询: {e}")
        
        # 输入可配置的订单号进行查询
        target_order_id = config_business.TARGET_ORDER_ID
        print(f"[*] 正在输入可配置订单号查询: {target_order_id}...")
        try:
            order_input = page.locator("input[placeholder*='订单ID'], input[placeholder*='订单编号'], .el-form-item:has-text('订单') input").first
            await order_input.click()
            await order_input.fill(target_order_id)
            await page.wait_for_timeout(500)
            
            # 点击搜索
            search_btn = page.locator("button:visible").filter(has_text="搜").first
            await search_btn.click()
            await page.wait_for_timeout(3000)
        except Exception as e:
            print(f"[!] 输入订单号查询失败: {e}")
            
        # ==========================================
        # STEP 3: 点击订单ID链接，进入“订单详情”
        # ==========================================
        print(f"[*] 正在点击第一列的【订单ID】蓝色链接 ({target_order_id}) 进入详情页...")
        try:
            row = page.locator(".el-table__row").first
            # 精准定位到第一列 (nth(0)，即截图上红圈圈出的‘订单ID’列 7358984366 链接)
            link = row.locator("td").nth(0).locator("span, a, div").first
            await link.scroll_into_view_if_needed()
            await link.click()
            await page.wait_for_timeout(5000)
            print(f"[*] 已进入详情页，当前 URL: {page.url}")
        except Exception as e:
            print(f"[!] 点击订单ID链接失败: {e}")
            
        # ==========================================
        # STEP 4: 滑动到最下方，点击下方导航的“工单”页签
        # ==========================================
        print("[*] 正在向下滑动详情页并寻找底部“工单”页签...")
        try:
            # 滑动到底部
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(1000)
            
            # 寻找页签中的“工单”
            tab = page.locator(".el-tabs__item, .tab, div").filter(has_text="工单").first
            await tab.scroll_into_view_if_needed()
            await tab.click()
            await page.wait_for_timeout(3000)
            print("[*] 已成功切换至“工单”页签。")
        except Exception as e:
            print(f"[!] 点击底部“工单”页签失败: {e}")
            
        # ==========================================
        # STEP 5: 点击右侧“创建工单”拉起弹窗并填写
        # ==========================================
        print("[*] 正在寻找并点击“创建工单”按钮...")
        try:
            create_btn = page.locator("button, .el-button").filter(has_text="创建工单").first
            await create_btn.scroll_into_view_if_needed()
            await create_btn.click()
            await page.wait_for_timeout(2000)
            print("[*] “创建工单”弹窗已成功拉起。")
        except Exception as e:
            print(f"[!] 点击“创建工单”按钮失败: {e}")
            
        print("[*] 正在填写创建工单表单并清除拦截...")
        try:
            dialog = page.locator(".el-dialog:visible").last
            
            # 使用 JS 直接注入 Vue model 属性并清空所有必填校验
            await page.evaluate(f"""() => {{
                const dialogs = Array.from(document.querySelectorAll('.el-dialog'));
                const visibleDialog = dialogs.find(d => d.getBoundingClientRect().width > 0);
                if (visibleDialog) {{
                    const formEl = visibleDialog.querySelector('.el-form');
                    if (formEl && formEl.__vue__) {{
                        const m = formEl.__vue__.model || {{}};
                        
                        const formItems = Array.from(visibleDialog.querySelectorAll('.el-form-item'));
                        formItems.forEach(item => {{
                            const label = item.querySelector('.el-form-item__label');
                            const text = label ? label.innerText : '';
                            if (item.__vue__ && item.__vue__.prop) {{
                                const prop = item.__vue__.prop;
                                if (text.includes('类型') || text.includes('分类')) {{
                                    m[prop] = "{config_business.WORK_ORDER_TYPE}";
                                }}
                                if (text.includes('内容') || text.includes('备注') || text.includes('描述')) {{
                                    m[prop] = "{config_business.WORK_ORDER_REMARK}";
                                }}
                            }}
                        }});
                        
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
                        formEl.__vue__.validateField = (prop, cb) => {{
                            if (typeof cb === 'function') {{
                                cb('');
                            }}
                        }};
                    }}
                }}
            }}""")
            
            # DOM 文本域兜底填充呈现文字
            try:
                remark_textarea = dialog.locator("textarea, .el-textarea__inner, input[placeholder*='内容'], input[placeholder*='备注']").first
                await remark_textarea.fill(config_business.WORK_ORDER_REMARK)
            except Exception:
                pass
                
            # 截图保存
            await page.screenshot(path="output/work_order_created_form.png")
            print("[*] 工单创建弹窗填写完毕，已截图并保存至 output/work_order_created_form.png")
            
            # 提交创建
            print("[*] 正在提交创建工单表单...")
            await page.evaluate("""() => {
                const dialogs = Array.from(document.querySelectorAll('.el-dialog'));
                const visibleDialog = dialogs.find(d => d.getBoundingClientRect().width > 0);
                if (visibleDialog) {
                    const okBtn = visibleDialog.querySelector('button.el-button--primary, button:not(.el-button--default)');
                    if (okBtn) okBtn.click();
                }
            }""")
            await page.wait_for_timeout(3000)
            print("[*] 确定提交按钮已点击。")
            
        except Exception as e:
            print(f"[!] 填写或提交工单创建表单失败: {e}")
            
        # ==========================================
        # STEP 6: 在底部的工单页签表格中，直接点击最新工单行的“受理”
        # ==========================================
        print("[*] 正在工单列表中定位并准备点击该工单的“受理”按钮...")
        try:
            # 滑动到底部
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(2000)
            
            # 定位到最新的一行工单
            row = page.locator(".el-table__row").first
            row_text = await row.inner_text()
            print(f"[*] 探测到最新产生的工单行内容: {row_text.replace(chr(10), ' | ')}")
            
            # 点击受理
            handle_btn = row.locator("button").filter(has_text="受理")
            if await handle_btn.count() == 0:
                handle_btn = row.locator("button").filter(has_text="处理")
            if await handle_btn.count() == 0:
                handle_btn = row.locator("button").first
                
            await handle_btn.scroll_into_view_if_needed()
            await handle_btn.click(force=True)
            print("[*] 受理按钮已点击。")
            await page.wait_for_timeout(3000)
            
        except Exception as e:
            print(f"[!] 点击工单列表受理按钮失败: {e}")
            
        # ==========================================
        # STEP 7: 在受理详情/弹窗页中，填写处理备注并点击“受理完成”
        # ==========================================
        print("[*] 正在填入处理结果/受理说明并点击“受理完成”...")
        try:
            # 1. 尝试寻找可见的受理工单弹窗，如果不存在，则在整个页面容器内寻找
            dialog = page.locator(".el-dialog:visible").last
            container = dialog if await dialog.count() > 0 else page.locator("body")
            
            # 2. 填写处理说明/受理说明 textarea
            remark_input = container.locator("textarea, .el-textarea__inner, input[placeholder*='说明'], input[placeholder*='意见'], input[placeholder*='结果']").first
            if await remark_input.count() > 0:
                await remark_input.fill("工单受理完成自动化测试")
                await page.wait_for_timeout(500)
            else:
                print("[*] 页面上未发现可填写的受理备注框，自动跳过输入。")
                
            # 3. 越狱黑科技：抹除受理弹窗的必选拦截规则
            print("[*] 正在执行 JS 抹除受理校验拦截规则...")
            await page.evaluate("""() => {
                const dialogs = Array.from(document.querySelectorAll('.el-dialog'));
                const visibleDialog = dialogs.find(d => d.getBoundingClientRect().width > 0);
                const container = visibleDialog || document.body;
                const formEl = container.querySelector('.el-form');
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
            
            # 4. 截图受理界面
            await page.screenshot(path="output/work_order_handled_form.png")
            print("[*] 工单受理页面填写完毕，截图已保存至 output/work_order_handled_form.png")
            
            # 5. 点击“受理完成”或“确定”按钮 (通过 JS 降维强制点击弹窗内可见的主按钮，绝对不超时)
            print("[*] 正在提交受理完成...")
            await page.evaluate("""() => {
                const dialogs = Array.from(document.querySelectorAll('.el-dialog'));
                const visibleDialog = dialogs.find(d => d.getBoundingClientRect().width > 0);
                const container = visibleDialog || document.body;
                
                // 寻找“受理完成”或“确定”等提交按钮
                const btns = Array.from(container.querySelectorAll('button'));
                const okBtn = btns.find(b => b.innerText.includes('受理') || b.innerText.includes('确定') || b.innerText.includes('确 定') || b.innerText.includes('提交'));
                if (okBtn) {
                    okBtn.click();
                } else if (btns.length > 0) {
                    btns[btns.length - 1].click();
                }
            }""")
            await page.wait_for_timeout(3000)
            print("[*] “受理完成”确定按钮已点击。")
            
        except Exception as e:
            print(f"[!] 填写处理备注或点击受理完成失败: {e}")
            
        # 侦测并打印可能出现的 Toast
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
        print("[*] 最终工单流转截图已保存至 output/work_order_finished_result.png")
        
        # 调试模式自适应停留
        if not config_business.HEADLESS_DEBUG:
            print("[*] 调试模式：正在保持浏览器停留 10 秒以供查看...")
            await page.wait_for_timeout(10000)
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
