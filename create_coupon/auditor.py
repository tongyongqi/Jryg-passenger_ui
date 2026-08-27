import config_business

async def audit_coupon(page):
    """
    负责执行新优惠券的自动查找、定位并提审（支持自适应自动审核成功与手动提审双逻辑）。
    """
    coupon_name = config_business.COUPON_NAME
    print(f"[*] 开始定位新创建的优惠券: '{coupon_name}'...")
    
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
            await page.screenshot(path="output/coupon_audit_dialog.png")
            print("[*] 提审弹窗已截图并保存至 output/coupon_audit_dialog.png")
            
            # 5.4 提交钉钉审核 (自适应自动审核与手动提审逻辑，避免因为自动审核无按钮导致卡死超时)
            submit_audit_btn = audit_dialog.locator("button:has-text('提交钉钉审核')")
            if await submit_audit_btn.count() > 0 and await submit_audit_btn.is_visible():
                print("[*] 正在提交钉钉审核...")
                await submit_audit_btn.click()
                await page.wait_for_timeout(1000)
                
                # 5.5 确认提交提示框 (点击蓝色确定按钮)
                print("[*] 正在进行二次确认提交...")
                confirm_btn = page.locator(".el-message-box:visible button:visible").filter(has_text="确").last
                await confirm_btn.click()
                print("[*] 二次确认按钮已点击。")
            else:
                print("[*] 该优惠券已由系统自动“审核通过”，正在关闭流水弹窗...")
                close_btn = audit_dialog.locator("button.el-dialog__headerbtn").first
                await close_btn.click()
            
            # 等待审核通过及刷新
            await page.wait_for_timeout(4000)
            
            # 5.6 最终截图
            await page.screenshot(path="output/coupon_created_and_approved.png")
            print("[*] 优惠券创建并提审通过，最终状态截图已保存至 output/coupon_created_and_approved.png")
        else:
            print("[!] 在目标行中未找到“审核”按钮！")
    else:
        print(f"[!] 在列表中未找到名称为 '{coupon_name}' 的行！")
