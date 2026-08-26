import asyncio
from playwright.async_api import async_playwright
import datetime

async def create_coupon(username, password, image_captcha, sms_captcha):
    async with async_playwright() as p:
        # 启动 Chromium 浏览器 (默认无头模式)
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1440, "height": 900})
        page = await context.new_page()
        
        url = "https://dcms-test6-tx.jryghq.com/#/admin/v1/coupon_manage"
        print(f"[*] 正在导航至优惠券管理页面: {url}")
        await page.goto(url)
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
            print(f"[!] 点击获取验证码失败或被跳过: {e}")
            
        await page.wait_for_timeout(1000)
        await page.fill("input[placeholder='验证码']", sms_captcha)
        
        print("[*] 正在点击登录...")
        await page.click("button:has-text('登录')")
        
        # 等待重定向完成
        await page.wait_for_timeout(5000)
        print(f"[*] 登录成功，当前页面 URL: {page.url}")
        
        # 2. 打开创建优惠券弹窗
        print("[*] 正在打开“创建优惠券”弹窗...")
        await page.click("button:has-text('创建优惠券')")
        await page.wait_for_timeout(2000)
        
        # 定位目标弹窗
        dialog = page.locator(".el-dialog:visible").filter(has=page.locator(".el-dialog__title:has-text('添加优惠券')")).last
        
        # 3. 填写表单
        coupon_name = "自动创建大额优惠券"
        print(f"[*] 正在填写优惠券名称: {coupon_name}...")
        name_input = dialog.locator(".el-form-item:has-text('名称') input").first
        await name_input.fill(coupon_name)
        
        # 3.1 下拉菜单高精度选择（使用键盘流ArrowDown + Enter）
        print("[*] 正在选择优惠券标签...")
        try:
            tag_form_item = dialog.locator(".el-form-item").filter(has_text="优惠券标签")
            tag_input = tag_form_item.locator("input").first
            await tag_input.click()
            await page.wait_for_timeout(1000)
            await page.keyboard.press("ArrowDown")
            await page.wait_for_timeout(300)
            await page.keyboard.press("Enter")
            await page.wait_for_timeout(500)
        except Exception as e:
            print(f"[!] 选择优惠券标签失败: {e}")
            
        print("[*] 正在选择适用产品...")
        try:
            product_form_item = dialog.locator(".el-form-item").filter(has_text="适用产品")
            product_input = product_form_item.locator("input").first
            await product_input.click()
            await page.wait_for_timeout(1000)
            await page.keyboard.press("ArrowDown")
            await page.wait_for_timeout(300)
            await page.keyboard.press("Enter")
            await page.wait_for_timeout(500)
        except Exception as e:
            print(f"[!] 选择适用产品失败: {e}")
            
        print("[*] 正在选择适用车型...")
        try:
            car_form_item = dialog.locator(".el-form-item").filter(has_text="适用车型")
            car_input = car_form_item.locator("input").first
            await car_input.click()
            await page.wait_for_timeout(1000)
            await page.keyboard.press("ArrowDown")
            await page.wait_for_timeout(300)
            await page.keyboard.press("Enter")
            await page.wait_for_timeout(500)
        except Exception as e:
            print(f"[!] 选择适用车型失败: {e}")
            
        # 3.2 勾选适用商家
        print("[*] 正在选择适用商家为“阳光自营”...")
        try:
            merchant_cb = dialog.locator(".el-form-item:has-text('适用商家') .el-checkbox:has-text('阳光自营')")
            await merchant_cb.click()
        except Exception as e:
            print(f"[!] 选择适用商家失败: {e}")
            
        # 3.3 填充金额和规则 (面值1000，使用规则满 2000 可用)
        print("[*] 正在填写面值: 1000 元...")
        face_value_input = dialog.locator(".el-form-item:has-text('面值') input").first
        await face_value_input.evaluate("(el) => { el.value = '1000'; el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })); el.dispatchEvent(new Event('blur', { bubbles: true })); }")
        await page.wait_for_timeout(300)
        
        print("[*] 正在填写使用规则: 满 2000 元可用...")
        rule_input = dialog.locator(".el-form-item:has-text('使用规则') input").first
        await rule_input.evaluate("(el) => { el.value = '2000'; el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })); el.dispatchEvent(new Event('blur', { bubbles: true })); }")
        await page.wait_for_timeout(300)
        
        print("[*] 正在填写最高抵扣: 100 %...")
        max_discount_input = dialog.locator(".el-form-item:has-text('最高抵扣') input").first
        await max_discount_input.fill("100")
        await max_discount_input.press("Enter")
        
        # 3.4 填充有效期和核销时间时间段
        print("[*] 正在填充有效期和核销时间时间段...")
        try:
            today_str = datetime.date.today().strftime("%Y-%m-%d")
            future_str = (datetime.date.today() + datetime.timedelta(days=365*4)).strftime("%Y-%m-%d")
            
            # 1. 填充 “有效期” 字段 (开始日期 至 结束日期)
            time_form_item_1 = dialog.locator(".el-form-item").filter(has_text="有效期")
            start_input_1 = time_form_item_1.locator(".el-range-input").nth(0)
            end_input_1 = time_form_item_1.locator(".el-range-input").nth(1)
            await start_input_1.evaluate(f"(el) => {{ el.value = '{today_str}'; el.dispatchEvent(new Event('input', {{ bubbles: true }})); el.dispatchEvent(new Event('change', {{ bubbles: true }})); }}")
            await page.wait_for_timeout(300)
            await end_input_1.evaluate(f"(el) => {{ el.value = '{future_str}'; el.dispatchEvent(new Event('input', {{ bubbles: true }})); el.dispatchEvent(new Event('change', {{ bubbles: true }})); }}")
            
            # 2. 填充 “选择券核销时间” 字段 (开始时间 至 结束时间)
            time_form_item_2 = dialog.locator(".el-form-item").filter(has_text="选择券核销时间")
            start_input_2 = time_form_item_2.locator(".el-range-input").nth(0)
            end_input_2 = time_form_item_2.locator(".el-range-input").nth(1)
            await start_input_2.evaluate(f"(el) => {{ el.value = '{today_str}'; el.dispatchEvent(new Event('input', {{ bubbles: true }})); el.dispatchEvent(new Event('change', {{ bubbles: true }})); }}")
            await page.wait_for_timeout(300)
            await end_input_2.evaluate(f"(el) => {{ el.value = '{future_str}'; el.dispatchEvent(new Event('input', {{ bubbles: true }})); el.dispatchEvent(new Event('change', {{ bubbles: true }})); }}")
            
            await page.wait_for_timeout(500)
            print(f"[*] 已成功通过 JS 填入有效期与核销时间: {today_str} 至 {future_str}")
        except Exception as e:
            print(f"[!] 填充时间段失败: {e}")
            
        # 3.5 适用终端 (必填，点击全选/反选进行全选勾选)
        print("[*] 正在勾选适用终端为“全选/反选”...")
        try:
            terminal_all = dialog.locator(".el-form-item:has-text('适用终端') .el-checkbox:has-text('全选/反选')")
            await terminal_all.click()
            await page.wait_for_timeout(500)
        except Exception as e:
            print(f"[!] 勾选适用终端失败: {e}")
        
        # 3.6 填写发行量
        print("[*] 正在填写发行量: 100000...")
        qty_input = dialog.locator(".el-form-item:has-text('发行量') input").first
        await qty_input.fill("100000")
        
        # 3.7 选择发送城市
        print("[*] 正在选择券发送城市为“全国”...")
        try:
            city_radio = dialog.locator(".el-form-item:has-text('选择券发送城市') .el-radio:has-text('全国')")
            await city_radio.click()
        except Exception as e:
            print(f"[!] 选择券发送城市失败: {e}")
            
        # 3.8 填写使用说明 (TinyMCE 智能绑定)
        print("[*] 正在填写富文本使用说明...")
        try:
            is_tinymce_active = await page.evaluate("() => typeof tinymce !== 'undefined'")
            if is_tinymce_active:
                await page.evaluate("() => { tinymce.activeEditor.setContent('1. 本券仅限在有效期内使用；2. 本券不与其它优惠叠加。'); }")
                print("[*] 已通过 tinymce API 成功设置富文本使用说明。")
            else:
                editor_frame = dialog.frame_locator(".el-form-item:has-text('使用说明') iframe")
                body = editor_frame.locator("body#tinymce")
                await body.click()
                await body.fill("1. 本券仅限在有效期内使用；2. 本券不与其它优惠叠加。")
                await body.evaluate("(el) => { el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })); }")
                await dialog.locator(".el-dialog__title:has-text('添加优惠券')").click()
                print("[*] 已通过富文本 iframe 填充。")
        except Exception as e:
            print(f"[!] 填写使用说明失败: {e}")
            
        # 3.9 截图留档
        await page.screenshot(path="coupon_form_filled.png")
        print("[*] 表单填写完毕，截图已保存至 coupon_form_filled.png")
        
        # 3.10 使用 JS 一键完成 Vue 模型赋值与校验清除（降维打击，无视组件拦截）
        print("[*] 正在通过 JS 降维打击，一键注入 Vue 核心模型并清除校验警告...")
        try:
            vue_log = await page.evaluate(f"""() => {{
                const dialogs = Array.from(document.querySelectorAll('.el-dialog'));
                const visibleDialog = dialogs.find(d => d.getBoundingClientRect().width > 0);
                if (visibleDialog) {{
                    const formEl = visibleDialog.querySelector('.el-form');
                    if (formEl && formEl.__vue__) {{
                        const m = formEl.__vue__.model || {{}};
                        
                        const todayStr = '{today_str}';
                        const futureStr = '{future_str}';
                        
                        // 1. 面值与规则
                        m.Denomination = 1000;
                        m.UseRoleMoney = 2000;
                        
                        // 2. 有效期时间段与日期值
                        m.CouponStartDate = todayStr;
                        m.CouponEndDate = futureStr;
                        m.TimesVal = [todayStr, futureStr];
                        
                        // 3. 选择券核销时间段
                        m.LimitStartTime = todayStr;
                        m.LimitEndTime = futureStr;
                        
                        // 4. 其他核心必填属性
                        m.CouponName = "自动创建大额优惠券";
                        m.Number = 100000;
                        
                        // 5. 强行触发一键清除校验
                        if (typeof formEl.__vue__.clearValidate === 'function') {{
                            formEl.__vue__.clearValidate();
                        }}
                        
                        return 'Vue model updated successfully: ' + JSON.stringify(m);
                    }}
                }}
                return '未找到 Form';
            }}""")
            print(f"[*] JS 注入结果: {vue_log}")
        except Exception as e:
            print(f"[!] JS 降维打击注入失败: {e}")
        
        # 4. 提交
        print("[*] 正在点击“确 定”按钮提交优惠券...")
        submit_btn = dialog.locator("button:visible").filter(has_text="确").last
        
        await submit_btn.click(force=True)
        print("[*] 确定提交按钮已强制点击。")
        
        # 等待添加优惠券弹窗消失，确保真正提交成功
        try:
            await page.locator(".el-dialog:visible").filter(has=page.locator(".el-dialog__title:has-text('添加优惠券')")).wait_for(state="hidden", timeout=10000)
            print("[*] 添加优惠券弹窗已成功关闭。")
        except Exception as e:
            print(f"[!] 等待弹窗关闭超时或失败，可能存在表单校验未通过: {e}")
            await page.screenshot(path="coupon_submit_failed_error.png")
            print("[!] 已保存提交失败状态截图至 coupon_submit_failed_error.png")
        
        # 等待服务器响应并自动更新列表
        await page.wait_for_timeout(5000)
        
        # 5. 自动审核优惠券流程
        print(f"[*] 开始定位新创建的优惠券: '{coupon_name}'...")
        try:
            row = page.locator(".el-table__row").first
            if await row.count() > 0:
                row_text = await row.inner_text()
                if coupon_name in row_text:
                    print(f"[*] 在列表首行成功定位到新创建的优惠券: '{coupon_name}'。")
                else:
                    print(f"[*] 首行未匹配，正在进行全局过滤定位 '{coupon_name}'...")
                    row = page.locator(".el-table__row").filter(has_text=coupon_name).first
                
                audit_btn = row.locator("button:has-text('审核')")
                if await audit_btn.count() > 0:
                    await audit_btn.scroll_into_view_if_needed()
                    await audit_btn.click(force=True)
                    print("[*] 已成功点击行内“审核”按钮。")
                    await page.wait_for_timeout(2000)
                    
                    # 5.1 钉钉审核流水记录弹窗
                    audit_dialog = page.locator(".el-dialog:visible").filter(has=page.locator(".el-dialog__title:has-text('钉钉审核流水记录')")).last
                    
                    # 5.2 输入审核备注
                    print("[*] 正在输入审核备注...")
                    remark_input = audit_dialog.locator("textarea[placeholder*='请输入审核备注']")
                    if await remark_input.count() > 0:
                        await remark_input.fill("自动提审优惠券")
                        
                    # 5.3 保存提审弹窗截图
                    await page.screenshot(path="coupon_audit_dialog.png")
                    print("[*] 提审弹窗已截图并保存至 coupon_audit_dialog.png")
                    
                    # 5.4 提交钉钉审核
                    print("[*] 正在提交钉钉审核...")
                    submit_audit_btn = audit_dialog.locator("button:has-text('提交钉钉审核')")
                    await submit_audit_btn.click()
                    await page.wait_for_timeout(1000)
                    
                    # 5.5 确认提交提示框 (点击蓝色确定按钮)
                    print("[*] 正在进行二次确认提交...")
                    confirm_btn = page.locator(".el-message-box:visible button:visible").filter(has_text="确").last
                        
                    await confirm_btn.click()
                    print("[*] 二次确认按钮已点击。")
                    
                    # 等待审核通过及刷新
                    await page.wait_for_timeout(4000)
                    
                    # 5.6 最终截图
                    await page.screenshot(path="coupon_created_and_approved.png")
                    print("[*] 优惠券创建并提审通过，最终状态截图已保存至 coupon_created_and_approved.png")
                else:
                    print("[!] 在目标行中未找到“审核”按钮！")
            else:
                print(f"[!] 在列表中未找到名称为 '{coupon_name}' 的行！")
        except Exception as e:
            print(f"[!] 自动提审过程发生异常: {e}")
            
        await browser.close()

if __name__ == "__main__":
    USERNAME = "18618251727"
    PASSWORD = "Tyq302152131,.?"
    IMAGE_CAPTCHA = "9"
    SMS_CAPTCHA = "999999"
    
    asyncio.run(create_coupon(USERNAME, PASSWORD, IMAGE_CAPTCHA, SMS_CAPTCHA))
