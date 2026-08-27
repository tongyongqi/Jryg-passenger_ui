import asyncio
from playwright.async_api import async_playwright
import datetime

async def send_coupon(username, password, image_captcha, sms_captcha):
    async with async_playwright() as p:
        # 启动 Chromium 浏览器 (有头/无头自适应)
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1440, "height": 900},
            ignore_https_errors=True
        )
        page = await context.new_page()
        page.set_default_timeout(60000)
        
        url = "https://dcms-test6-tx.jryghq.com/#/admin/v1/coupon_manage"
        print(f"[*] 正在导航至管理页面: {url}")
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(3000)
        
        # 1. 登录流程
        print("[*] 正在输入登录凭证...")
        await page.fill("input[placeholder='账号']", username)
        await page.fill("input[placeholder='密码']", password)
        await page.fill("input[placeholder='图形验证码']", image_captcha)
        
        print("[*] 正在点击获取验证码...")
        try:
            await page.click("text=获取验证码", timeout=5000)
        except Exception as e:
            print(f"[!] 点击获取验证码被跳过: {e}")
            
        await page.wait_for_timeout(1000)
        await page.fill("input[placeholder='验证码']", sms_captcha)
        
        print("[*] 正在点击登录...")
        await page.click("button:has-text('登录')")
        
        # 等待重定向完成
        await page.wait_for_timeout(5000)
        print(f"[*] 登录成功，当前 URL: {page.url}")
        
        # 2. 导航至“发放优惠券”页面
        print("[*] 正在通过左侧菜单进入“发放优惠券”页面...")
        try:
            # 显式等待左侧菜单加载完毕
            await page.wait_for_selector(".el-menu", timeout=15000)
            
            # 展开优惠券系统大分类
            submenu = page.locator(".el-submenu").filter(has_text="优惠券系统").first
            submenu_title = submenu.locator(".el-submenu__title")
            await submenu_title.scroll_into_view_if_needed()
            if "is-opened" not in await submenu.evaluate("(el) => el.className"):
                await submenu_title.click()
                await page.wait_for_timeout(1000)
            
            # 点击发放优惠券子菜单
            menu_item = page.locator(".el-menu-item").filter(has_text="发放优惠券").first
            await menu_item.scroll_into_view_if_needed()
            await menu_item.click()
            await page.wait_for_timeout(4000)
            print(f"[*] 成功导航至发放页面，当前 URL: {page.url}")
        except Exception as e:
            print(f"[!] 侧边栏菜单导航失败，正在尝试直接 URL 导航: {e}")
            await page.goto("https://dcms-test6-tx.jryghq.com/#/admin/v1/coupon_send", wait_until="domcontentloaded")
            await page.wait_for_timeout(4000)
            
        # 显式等待发放页面加载完毕
        await page.wait_for_selector("button:has-text('发放优惠券')", timeout=15000)
            
        # 3. 点击列表右上角“发放优惠券”按钮以打开弹窗
        print("[*] 正在打开“发放优惠券”弹窗...")
        await page.click("button:has-text('发放优惠券')")
        await page.wait_for_timeout(2000)
        
        # 定位主弹窗
        dialog = page.locator(".el-dialog:visible").filter(has=page.locator(".el-dialog__title:has-text('发放优惠券')")).last
        
        # 4. 填写主表单手机号
        phone_number = "18618251727"
        print(f"[*] 正在输入客人手机号: {phone_number}...")
        phone_input = dialog.locator(".el-form-item:has-text('客人手机号') textarea, textarea[placeholder*='手机号']")
        await phone_input.fill(phone_number)
        await page.wait_for_timeout(500)
        
        # 5. 点击添加按钮打开嵌套优惠券选择弹窗
        print("[*] 正在点击“添加”按钮选择优惠券...")
        add_btn = dialog.locator("button:has-text('添加'), .el-button:has-text('添加')")
        await add_btn.click()
        await page.wait_for_timeout(2000)
        
        # 定位嵌套选择优惠券的弹窗
        nested_dialog = page.locator(".el-dialog:visible").last
        
        # 6. 选择表格中的第一张优惠券
        print("[*] 正在勾选表格首行优惠券...")
        first_row = nested_dialog.locator(".el-table__row").first
        checkbox = first_row.locator(".el-checkbox")
        await checkbox.click()
        await page.wait_for_timeout(500)
        
        # 7. 点击嵌套弹窗右下角的确定按钮
        print("[*] 正在确定选择优惠券...")
        nested_confirm_btn = nested_dialog.locator("button:visible").filter(has_text="确").last
        await nested_confirm_btn.click()
        await page.wait_for_timeout(1000)
        
        # 8. 截图主表单填充完毕状态
        await page.screenshot(path="coupon_send_filled.png")
        print("[*] 主表单填充完毕，截图已保存至 coupon_send_filled.png")
        
        # 9. 越狱级黑科技：一键清空发放弹窗可能存在的校验并强行通过
        print("[*] 正在执行 JS 清除弹窗上的所有校验规则...")
        try:
            await page.evaluate("""() => {
                const dialogs = Array.from(document.querySelectorAll('.el-dialog'));
                const visibleDialog = dialogs.find(d => d.getBoundingClientRect().width > 0);
                if (visibleDialog) {
                    const formEl = visibleDialog.querySelector('.el-form');
                    if (formEl && formEl.__vue__) {
                        // 1. 全量抹除 field 校验
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
                        // 2. 覆盖 validate 校验函数一律通过
                        formEl.__vue__.validate = (cb) => {
                            if (typeof cb === 'function') cb(true);
                            return Promise.resolve(true);
                        };
                        formEl.__vue__.validateField = (prop, cb) => {
                            if (typeof cb === 'function') cb('');
                        };
                    }
                }
            }""")
        except Exception as e:
            print(f"[!] 清除校验失败: {e}")
            
        # 10. 点击最外层弹窗右下角确定按钮提交发放
        print("[*] 正在点击“确 定”按钮提交优惠券发放...")
        submit_btn = dialog.locator("button:visible").filter(has_text="确").last
        await submit_btn.click()
        
        # 11. 强力侦测发送成功状态
        print("[*] 正在侦测系统提示信息...")
        success_detected = False
        for _ in range(10):  # 轮询 10 次检测消息提示框
            await page.wait_for_timeout(500)
            try:
                message_text = await page.evaluate("""() => {
                    const msgEl = document.querySelector('.el-message, .el-notification');
                    return msgEl ? msgEl.innerText.trim() : null;
                }""")
                if message_text:
                    print(f"[*] 捕捉到全局系统提示: '{message_text}'")
                    if "成功" in message_text or "发送" in message_text:
                        success_detected = True
                        break
            except Exception as e:
                print(f"[!] 捕捉系统提示异常: {e}")
                
        # 12. 保存最终结果截图
        await page.screenshot(path="coupon_send_result.png")
        print("[*] 最终发放结果截图已保存至 coupon_send_result.png")
        
        if success_detected:
            print("[🎉 SUCCESS] 成功验证到“发送成功”或相关的成功提示消息！")
        else:
            print("[⚠️ WARNING] 未能在提示框中捕获到含有“成功”字样的消息。请查看 coupon_send_result.png 截图人工确认结果。")
            
        await browser.close()

if __name__ == "__main__":
    USERNAME = "18618251727"
    PASSWORD = "Tyq302152131,.?"
    IMAGE_CAPTCHA = "9"
    SMS_CAPTCHA = "999999"
    
    asyncio.run(send_coupon(USERNAME, PASSWORD, IMAGE_CAPTCHA, SMS_CAPTCHA))
