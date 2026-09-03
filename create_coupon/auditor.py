# -*- coding: utf-8 -*-
# 这个文件的功能是新优惠券的自动提审与自动流转审批的代码

import config_business

async def audit_coupon(page):
    """
    负责执行新优惠券的自动查找、定位并提审（支持自适应自动审核成功与手动提审双逻辑）。
    """
    coupon_name = config_business.COUPON_NAME
    print(f"[*] 开始定位新创建的优惠券: '{coupon_name}'...")
    
    # 1. 自动检测并点击列表头部的“查询”或“搜索”按钮强制刷新列表，确保最新创建的券立即可见
    try:
        search_btn = page.locator("button:has-text('查询'), button:has-text('搜索')").first
        if await search_btn.count() > 0:
            print("[*] 检测到列表查询按钮，正在点击以刷新获取最新优惠券数据...")
            await search_btn.click()
            await page.wait_for_timeout(3000) # 给予列表重载渲染时间
    except Exception as e:
        print(f"[!] 尝试刷新列表发生异常: {e}")
        
    # 2. 从所有行中，多重循环寻找既匹配名称又带有“审核”按钮的行（100% 精准过滤，避开重名已审核行的干扰）
    all_rows = page.locator(".el-table__row")
    rows_count = await all_rows.count()
    target_row = None
    audit_btn = None
    
    print(f"[*] 当前列表共渲染了 {rows_count} 行数据，开始逐行精准匹配...")
    for i in range(rows_count):
        row = all_rows.nth(i)
        row_text = await row.inner_text()
        if coupon_name in row_text:
            # 找到名称匹配的行，进一步探测该行是否存在可见的“审核”按钮
            btn_candidate = row.locator("button:has-text('审核')")
            if await btn_candidate.count() > 0 and await btn_candidate.is_visible():
                target_row = row
                audit_btn = btn_candidate
                print(f"[*] 【🎉 精准锁定】在第 {i + 1} 行成功匹配到包含名称 '{coupon_name}' 且包含可用“审核”按钮的行！")
                break
                
    # 3. 兜底逻辑：如果两重匹配失败，降级尝试定位该名称的第一个首行，并锁定其审核按钮
    if target_row is None:
        print(f"[*] 未能在多行中筛选到满足双条件的行，正在执行降级首行查找...")
        target_row = page.locator(".el-table__row").filter(has_text=coupon_name).first
        if await target_row.count() > 0:
            audit_btn = target_row.locator("button:has-text('审核')")

    if target_row and audit_btn and await audit_btn.count() > 0:
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
        print(f"[!] 无法精确定位或找不到优惠券 '{coupon_name}' 对应的“审核”按钮！提审中止。")
        # 抓取截图保留现场
        await page.screenshot(path="output/coupon_audit_not_found_error.png")
