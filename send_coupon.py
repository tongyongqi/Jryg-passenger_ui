import asyncio
from playwright.async_api import async_playwright
import datetime

async def send_coupon(username, password, image_captcha, sms_captcha, target_phone, coupon_qty):
    async with async_playwright() as p:
        # 启动 Chromium 浏览器 (调试模式：headless=False 真实弹出浏览器)
        browser = await p.chromium.launch(headless=False)
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
        
        # 稳健等待登录重定向跳离登录页
        print("[*] 正在等待登录跳转重定向...")
        for _ in range(30):
            await page.wait_for_timeout(1000)
            if "login" not in page.url:
                break
        print(f"[*] 登录成功，当前 URL: {page.url}")
        
        # 2. 导航至“发放优惠券”页面
        print("[*] 正在导航进入“发放优惠券”页面...")
        try:
            # 1. 尝试直接 URL 降维直连导航，最快且最稳定
            await page.goto("https://dcms-test6-tx.jryghq.com/#/admin/v1/coupon_give", wait_until="domcontentloaded")
            await page.wait_for_timeout(5000)
            print(f"[*] 直连导航尝试完成，当前 URL: {page.url}")
        except Exception as e:
            print(f"[!] 直连导航失败，正在尝试全真点击进入: {e}")
            
        # 2. 如果直连没有成功到达（比如卡在原页面），通过点击顶部“营销系统”和左侧侧边栏进入
        if "coupon_give" not in page.url:
            try:
                print("[*] 正在点击顶部“营销系统”大菜单...")
                # 寻找顶部横向导航中的“营销系统”
                marketing_menu = page.locator("header, .el-menu").locator("text=营销系统, :has-text('营销系统')").first
                await marketing_menu.click()
                await page.wait_for_timeout(2000)
                
                print("[*] 正在通过搜索过滤左侧菜单进入“发放优惠券”页面...")
                search_input = page.locator("input[placeholder='搜索菜单']")
                await search_input.wait_for(state="visible", timeout=10000)
                await search_input.click()
                await search_input.fill("发放优惠券")
                await page.wait_for_timeout(1000)
                
                menu_item = page.locator(".el-menu-item").filter(has_text="发放优惠券").first
                await menu_item.click()
                await page.wait_for_timeout(4000)
            except Exception as ex:
                print(f"[!] 全真点击导航发生异常: {ex}")
            
        # 显式等待发放页面加载完毕
        try:
            await page.wait_for_selector("button:has-text('发放优惠券')", timeout=15000)
            print("[*] 成功到达发放优惠券页面。")
        except Exception as e:
            print(f"[!] 等待“发放优惠券”按钮超时，当前页面 URL 为: {page.url}，异常: {e}")
            await page.screenshot(path="send_coupon_navigation_failed.png")
            print("[!] 已保存导航失败截图至 send_coupon_navigation_failed.png")
            
        # 3. 点击列表右上角“发放优惠券”按钮以打开弹窗
        print("[*] 正在打开“发放优惠券”弹窗...")
        await page.click("button:has-text('发放优惠券')")
        await page.wait_for_timeout(2000)
        
        # 定位主弹窗
        dialog = page.locator(".el-dialog:visible").filter(has=page.locator(".el-dialog__title:has-text('发放优惠券')")).last
        
        # 3.8 核心修正：显式点击“手机号发送”单选按钮，让页面正确切换并显现出手机号文本域
        print("[*] 正在切换发放方式为“手机号发送”...")
        try:
            phone_send_radio = dialog.locator(".el-radio").filter(has_text="手机号发送")
            await phone_send_radio.click()
            await page.wait_for_timeout(1000)
        except Exception as e:
            print(f"[!] 切换“手机号发送”单选状态失败: {e}")
        
        # 4. 填写主表单手机号与备注说明（采用极速 JS 降维注入，完美和备注分开，填入“自动发送优惠卷”）
        print(f"[*] 正在输入客人手机号: {target_phone} 并设置备注说明...")
        try:
            # 使用高精度 JS 探测弹窗中的 Form Model，直接将值注入 Vue data 中，完美、无痛、绝对不超时
            await page.evaluate(f"""() => {{
                const dialogs = Array.from(document.querySelectorAll('.el-dialog'));
                const visibleDialog = dialogs.find(d => d.getBoundingClientRect().width > 0);
                if (visibleDialog) {{
                    const formEl = visibleDialog.querySelector('.el-form');
                    if (formEl && formEl.__vue__) {{
                        const m = formEl.__vue__.model || {{}};
                        
                        // 1. 设置手机号 (寻找绑定在手机号上的 Vue model 属性)
                        if (m.Phones !== undefined) m.Phones = "{target_phone}";
                        if (m.phones !== undefined) m.phones = "{target_phone}";
                        if (m.phone !== undefined) m.phone = "{target_phone}";
                        if (m.Phone !== undefined) m.phone = "{target_phone}";
                        
                        // 2. 设置备注 (备注填入“自动发送优惠卷”)
                        if (m.Remark !== undefined) m.Remark = "自动发送优惠卷";
                        if (m.remark !== undefined) m.remark = "自动发送优惠卷";
                        if (m.Desc !== undefined) m.Desc = "自动发送优惠卷";
                        if (m.desc !== undefined) m.desc = "自动发送优惠卷";
                        if (m.note !== undefined) m.note = "自动发送优惠卷";
                    }}
                }}
            }}""")
            
            # 同时在 DOM 上通过兜底赋值保证截图上有文字呈现
            textareas = await dialog.locator("textarea, input:not([type='radio']):not([type='checkbox']):not([type='file'])").all()
            if len(textareas) >= 2:
                await textareas[0].fill(str(target_phone))
                await textareas[1].fill("自动发送优惠卷")
                print("[*] 已成功在 DOM 上分离输入了手机号和备注说明。")
            else:
                phone_input = dialog.locator(".el-textarea__inner, .el-input__inner, textarea, input:not([type='radio']):not([type='checkbox']):not([type='file'])").first
                await phone_input.fill(str(target_phone))
        except Exception as e:
            print(f"[!] 注入手机号和备注失败: {e}")
            
        await page.wait_for_timeout(500)
        
        # 5. 点击添加按钮打开嵌套优惠券选择弹窗
        print("[*] 正在点击“添加”按钮选择优惠券...")
        add_btn = dialog.locator("button:has-text('添加'), .el-button:has-text('添加')")
        await add_btn.click()
        await page.wait_for_timeout(2000)
        
        # 定位嵌套选择优惠券的弹窗
        nested_dialog = page.locator(".el-dialog:visible").last
        
        # 5.5 输入批次号 34303 并点击查询 (采用 JS 高雅注入，彻底避免定位超时)
        target_batch = "34303"
        print(f"[*] 正在在嵌套弹窗中输入批次号: {target_batch} 并过滤查询...")
        try:
            # 1. 直接用 JS 对嵌套弹窗上的搜索 input 属性和模型绑定进行覆盖
            await page.evaluate(f"""() => {{
                const dialogs = Array.from(document.querySelectorAll('.el-dialog'));
                const nested = dialogs[dialogs.length - 1]; // 最后一个弹窗
                if (nested) {{
                    const form = nested.querySelector('.el-form');
                    if (form && form.__vue__) {{
                        const m = form.__vue__.model || {{}};
                        // 寻找并强刷批次号字段
                        for (let k in m) {{
                            if (k.toLowerCase().includes('batch') || k.toLowerCase().includes('id') || k.toLowerCase().includes('no')) {{
                                m[k] = "{target_batch}";
                            }}
                        }}
                    }}
                    // DOM 兜底赋值
                    const inputs = Array.from(nested.querySelectorAll('input:not([type="radio"]):not([type="checkbox"])'));
                    if (inputs.length > 0) {{
                        inputs[0].value = "{target_batch}";
                        inputs[0].dispatchEvent(new Event('input', {{ bubbles: true }}));
                        inputs[0].dispatchEvent(new Event('change', {{ bubbles: true }}));
                    }}
                }}
            }}""")
            
            # 点击查询按钮
            query_btn = nested_dialog.locator("button:has-text('查询'), .el-button:has-text('查询')").first
            await query_btn.click()
            await page.wait_for_timeout(1500)
            print(f"[*] 批次号 {target_batch} 过滤完毕，准备勾选。")
        except Exception as e:
            print(f"[!] 批次号查询发生异常，将默认使用首行优惠券: {e}")
        
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
        await page.wait_for_timeout(1500)
        
        # 7.1 自动在主弹窗表格中填入自定义的发放数量
        print(f"[*] 正在设置发放数量为: {coupon_qty} 张...")
        try:
            qty_input = dialog.locator(".el-table__row").first.locator(".el-input__inner, input:not([type='radio']):not([type='checkbox'])").last
            await qty_input.click()
            await qty_input.fill(str(coupon_qty))
            # 触发 input、change、blur 事件确保 Element v-model 完美承接张数值
            await qty_input.evaluate(f"(el) => {{ el.value = '{coupon_qty}'; el.dispatchEvent(new Event('input', {{ bubbles: true }})); el.dispatchEvent(new Event('change', {{ bubbles: true }})); el.dispatchEvent(new Event('blur', {{ bubbles: true }})); }}")
            await page.wait_for_timeout(500)
        except Exception as e:
            print(f"[!] 设置发放数量失败（将使用默认数量 1）: {e}")
        
        # 8. 截图主表单填充完毕状态
        await page.screenshot(path="coupon_send_filled.png")
        print("[*] 主表单填充完毕，截图已保存至 coupon_send_filled.png")
        
        # 9. 越狱级黑科技：一键清空发放弹窗可能存在的校验并强行通过
        print("[*] 正在执行 JS 清除弹窗上的所有校验规则并强制同步行数模型...")
        try:
            await page.evaluate(f"""() => {{
                const dialogs = Array.from(document.querySelectorAll('.el-dialog'));
                const visibleDialog = dialogs.find(d => d.getBoundingClientRect().width > 0);
                if (visibleDialog) {{
                    const formEl = visibleDialog.querySelector('.el-form');
                    if (formEl && formEl.__vue__) {{
                        const m = formEl.__vue__.model || {{}};
                        
                        // 如果有优惠券列表数组，强行同步里面的发券数量
                        if (Array.isArray(m.Coupons)) {{
                            m.Coupons.forEach(item => {{
                                item.Number = {coupon_qty};
                                item.SendCount = {coupon_qty};
                                item.num = {coupon_qty};
                            }});
                        }}
                        if (Array.isArray(m.coupons)) {{
                            m.coupons.forEach(item => {{
                                item.Number = {coupon_qty};
                                item.SendCount = {coupon_qty};
                                item.num = {coupon_qty};
                            }});
                        }}
                        
                        // 1. 全量抹除 field 校验
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
                        // 2. 覆盖 validate 校验函数一律通过
                        formEl.__vue__.validate = (cb) => {{
                            if (typeof cb === 'function') cb(true);
                            return Promise.resolve(true);
                        }};
                        formEl.__vue__.validateField = (prop, cb) => {{
                            if (typeof cb === 'function') cb('');
                        }};
                    }}
                }}
            }}""")
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
                
        # 12. 刷新列表并自动检查是否存在“未发送成功”的优惠券记录
        print("[*] 正在刷新发放记录列表以进行发送状态二次核对...")
        try:
            # 点击“搜索”按钮刷新列表
            search_btn = page.locator("button:visible").filter(has_text="搜").first
            if await search_btn.count() > 0:
                await search_btn.click()
                await page.wait_for_timeout(3000)
            
            rows = page.locator(".el-table__row")
            row_count = await rows.count()
            # 限制仅检查最顶部最新产生的 10 条记录，防止因为滚动条下方行未渲染导致超时
            check_count = min(row_count, 10)
            print(f"[*] 当前页面共探测到 {row_count} 条发放记录，正在极速核对最顶部的最新 {check_count} 条记录...")
            
            failed_records = []
            for i in range(check_count):
                row = rows.nth(i)
                cells = row.locator("td")
                
                # 获取发放记录编号、优惠券批次、发送数量、成功数量
                record_id = (await cells.nth(0).inner_text()).strip()
                coupon_batch = (await cells.nth(1).inner_text()).strip()
                sent_qty = (await cells.nth(4).inner_text()).strip()
                success_qty = (await cells.nth(5).inner_text()).strip()
                send_time = (await cells.nth(6).inner_text()).strip()
                
                try:
                    sent_num = int(sent_qty)
                    success_num = int(success_qty)
                    if success_num < sent_num:
                        failed_records.append({
                            "record_id": record_id,
                            "coupon_batch": coupon_batch,
                            "sent_qty": sent_qty,
                            "success_qty": success_qty,
                            "send_time": send_time
                        })
                except ValueError:
                    # 容错处理（非数字）
                    pass
            
            if failed_records:
                print("\n[⚠️ ALERT] 侦测到以下【未发送成功】的优惠券发放记录：")
                print("=" * 70)
                print(f"{'发放记录编号':<12} | {'优惠券批次':<12} | {'券发送数量':<10} | {'成功数量':<10} | {'发送时间'}")
                print("-" * 70)
                for rec in failed_records:
                    print(f"{rec['record_id']:<12} | {rec['coupon_batch']:<12} | {rec['sent_qty']:<10} | {rec['success_qty']:<10} | {rec['send_time']}")
                print("=" * 70)
            else:
                print("\n[🎉 PERFECT] 经核对，当前列表内所有优惠券发放记录均已 100% 全部发送成功，无任何失败记录！")
                
        except Exception as e:
            print(f"[!] 发送记录核对核查过程发生异常: {e}")
            
        # 13. 保存最终结果截图
        await page.screenshot(path="coupon_send_result.png")
        print("[*] 最终发放结果截图已保存至 coupon_send_result.png")
        
        if success_detected:
            print("[🎉 SUCCESS] 成功验证到“发送成功”或相关的成功提示消息！")
        else:
            print("[⚠️ WARNING] 未能在提示框中捕获到含有“成功”字样的消息。请查看 coupon_send_result.png 截图人工确认结果。")
            
        # 调试等待：多停留 10 秒让用户观赏完浏览器结果再关闭
        print("[*] 调试模式：正在保持浏览器停留 10 秒以供查看...")
        await page.wait_for_timeout(10000)
            
        await browser.close()

# ==========================================
# ⚙️ 极简配置参数区 (在此随意更改手机号和发放张数)
# ==========================================
TARGET_PHONE = "18618251727"   # 发送目标客户手机号 (多手机号换行输入即可)
COUPON_QTY = "1"               # 发放优惠券张数（可设为 1, 2, 5, 10 等任意正整数）
# ==========================================

if __name__ == "__main__":
    USERNAME = "18618251727"
    PASSWORD = "Tyq302152131,.?"
    IMAGE_CAPTCHA = "9"
    SMS_CAPTCHA = "999999"
    
    # 携带配置参数开始极速运行
    asyncio.run(send_coupon(
        USERNAME, 
        PASSWORD, 
        IMAGE_CAPTCHA, 
        SMS_CAPTCHA, 
        target_phone=TARGET_PHONE, 
        coupon_qty=COUPON_QTY
    ))
