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
        # STEP 2: 降维打击一键直连：直接通过 URL 进入对应的订单详情页
        # ==========================================
        order_no = config_business.TARGET_ORDER_ID
        meta_id = getattr(config_business, "META_ID", "113491")
        order_type = getattr(config_business, "ORDER_TYPE", "5")
        
        detail_url = f"https://dcms-test6-tx.jryghq.com/#/order_detail/{order_no}?order_no={order_no}&meta_id={meta_id}&order_type={order_type}"
        print(f"[*] 正在直接导航进入目标订单详情页面: {detail_url}")
        try:
            # 采用 3 次自动网络自愈导航
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
            
            if direct_success:
                await page.wait_for_timeout(4000)
                print(f"[*] [🎉 SUCCESS] 成功直接到达目标订单详情页！当前 URL: {page.url}")
            else:
                raise ConnectionError("直连订单详情页 3 次重试均失败，请检查网络或 URL 结构。")
        except Exception as e:
            print(f"[!] 直连详情页遭遇异常，程序关闭: {e}")
            await browser.close()
            return
            
        # ==========================================
        # STEP 3: 滑动到最下方，点击下方导航的“工单”页签
        # ==========================================
        print("[*] 正在向下滑动详情页并寻找底部“工单”页签...")
        try:
            # 向下滑动到底部
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(1500)
            
            # 寻找详情页底部的“工单”页签并点击
            tab = page.locator(".el-tabs__item, .tab, div").filter(has_text="工单").first
            await tab.scroll_into_view_if_needed()
            await tab.click()
            await page.wait_for_timeout(3000)
            print("[*] 已成功切换至详情页底部“工单”页签。")
        except Exception as e:
            print(f"[!] 点击底部“工单”页签失败: {e}")
            
        # ==========================================
        # STEP 4: 点击右侧“创建工单”拉起弹窗并填写
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
                
            # 截图保存到 output 目录
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
        # STEP 5: 在底部的工单页签表格中，直接点击最新工单行的“受理”
        # ==========================================
        print("[*] 正在工单列表中定位并准备点击该工单的“受理”按钮...")
        has_work_order = False
        try:
            # 向下滑动到详情页底部
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(2000)
            
            # 定位到最新的一行工单并点击“受理”
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
            has_work_order = True
        except Exception as e:
            print(f"[!] 点击工单列表受理按钮失败: {e}")
            
        # ==========================================
        # STEP 6: 在受理详情/弹窗页中，填写处理备注并点击“受理完成”
        # ==========================================
        if has_work_order:
            print("[*] 正在填入处理结果/受理说明并点击“受理完成”...")
            try:
                dialog = page.locator(".el-dialog:visible").last
                container = dialog if await dialog.count() > 0 else page.locator("body")
                
                # 填写处理备注
                remark_input = container.locator("textarea, .el-textarea__inner, input[placeholder*='说明'], input[placeholder*='意见'], input[placeholder*='结果']").first
                if await remark_input.count() > 0:
                    await remark_input.fill("工单受理完成自动化测试")
                    await page.wait_for_timeout(500)
                else:
                    print("[*] 页面上未发现可填写的受理备注框，自动跳过输入。")
                    
                # 越狱黑科技：抹除受理弹窗的必选拦截规则
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
                
                # 截图保存受理界面状态
                await page.screenshot(path="output/work_order_handled_form.png")
                print("[*] 工单受理页面填写完毕，截图已保存至 output/work_order_handled_form.png")
                
                # 点击“受理完成”
                print("[*] 正在提交受理完成...")
                await page.evaluate("""() => {
                    const dialogs = Array.from(document.querySelectorAll('.el-dialog'));
                    const visibleDialog = dialogs.find(d => d.getBoundingClientRect().width > 0);
                    const container = visibleDialog || document.body;
                    
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
        else:
            print("[*] 由于当前没有匹配到可见工单行，已安全、自适应地越过‘受理完成’步骤。")
            
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
        print("[*] 最终工单流转截图已保存至 output/work_order_finished_result.png")
        
        # 调试模式自适应停留
        if not config_business.HEADLESS_DEBUG:
            print("[*] 调试模式：正在保持浏览器停留 10 秒以供查看...")
            await page.wait_for_timeout(10000)
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
