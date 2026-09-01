# -*- coding: utf-8 -*-
# 这个文件的功能是全自动填写优惠券创建表单并执行一键注入的代码

import config_business

async def fill_coupon_form(page, dialog):
    """
    负责执行添加优惠券表单的完整填写、Vue模型降维打击注入、以及越狱级校验抹除。
    """
    # 3. 填写表单 (完全从 config_business 载入配置属性)
    coupon_name = config_business.COUPON_NAME
    print(f"[*] 正在填写优惠券名称: {coupon_name}...")
    name_input = dialog.locator(".el-form-item:has-text('名称') input").first
    await name_input.fill(coupon_name)
    
    # 3.1 选择优惠券标签（显式点击列表中的第一项，绝对避开抖音相关的标签）
    print("[*] 正在选择优惠券标签...")
    try:
        tag_form_item = dialog.locator(".el-form-item").filter(has_text="优惠券标签")
        tag_input = tag_form_item.locator("input").first
        await tag_input.click()
        await page.wait_for_timeout(1000)
        
        # 显式点击可见下拉菜单中的第一项，安全避开带有抖音属性的下拉标签
        first_option = page.locator(".el-select-dropdown:visible .el-select-dropdown__item").first
        await first_option.click()
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
    print("[*] 正在选择适用商家...")
    try:
        for merchant in config_business.MERCHANTS:
            merchant_cb = dialog.locator(f".el-form-item:has-text('适用商家') .el-checkbox:has-text('{merchant}')")
            if "is-checked" not in await merchant_cb.evaluate("(el) => el.className"):
                await merchant_cb.click()
                await page.wait_for_timeout(200)
    except Exception as e:
        print(f"[!] 选择适用商家失败: {e}")
        
    # 3.3 填充金额和规则 (利用 JS 强刷填入面额和门槛，并强制触发 Element 表单失焦重新计算)
    print(f"[*] 正在填写面值: {config_business.FACE_VALUE} 元...")
    face_value_input = dialog.locator(".el-form-item:has-text('面值') input").first
    await face_value_input.evaluate(f"(el) => {{ el.value = '{config_business.FACE_VALUE}'; el.dispatchEvent(new Event('input', {{ bubbles: true }})); el.dispatchEvent(new Event('change', {{ bubbles: true }})); el.dispatchEvent(new Event('blur', {{ bubbles: true }})); }}")
    await page.wait_for_timeout(300)
    
    print(f"[*] 正在填写使用规则: 满 {config_business.USE_RULE} 元可用...")
    rule_input = dialog.locator(".el-form-item:has-text('使用规则') input").first
    await rule_input.evaluate(f"(el) => {{ el.value = '{config_business.USE_RULE}'; el.dispatchEvent(new Event('input', {{ bubbles: true }})); el.dispatchEvent(new Event('change', {{ bubbles: true }})); el.dispatchEvent(new Event('blur', {{ bubbles: true }})); }}")
    await page.wait_for_timeout(300)
    
    print(f"[*] 正在填写最高抵扣: {config_business.MAX_DISCOUNT} %...")
    max_discount_input = dialog.locator(".el-form-item:has-text('最高抵扣') input").first
    await max_discount_input.fill(config_business.MAX_DISCOUNT)
    await max_discount_input.press("Enter")
    
    # 3.4 填充有效期时间段
    print("[*] 正在填充有效期...")
    try:
        time_form_item_1 = dialog.locator(".el-form-item").filter(has_text="有效期")
        start_input_1 = time_form_item_1.locator(".el-range-input").nth(0)
        end_input_1 = time_form_item_1.locator(".el-range-input").nth(1)
        await start_input_1.evaluate(f"(el) => {{ el.value = '{config_business.START_DATE}'; el.dispatchEvent(new Event('input', {{ bubbles: true }})); el.dispatchEvent(new Event('change', {{ bubbles: true }})); }}")
        await page.wait_for_timeout(300)
        await end_input_1.evaluate(f"(el) => {{ el.value = '{config_business.END_DATE}'; el.dispatchEvent(new Event('input', {{ bubbles: true }})); el.dispatchEvent(new Event('change', {{ bubbles: true }})); }}")
        print(f"[*] 已成功通过 JS 填入有效期: {config_business.START_DATE} 至 {config_business.END_DATE}")
    except Exception as e:
        print(f"[!] 填充时间段失败: {e}")
        
    # 3.5 适用终端 (全选终端)
    print("[*] 正在勾选适用终端为“全选/反选”...")
    try:
        terminal_all = dialog.locator(".el-form-item:has-text('适用终端') .el-checkbox:has-text('全选/反选')")
        if "is-checked" not in await terminal_all.evaluate("(el) => el.className"):
            await terminal_all.click()
            await page.wait_for_timeout(500)
    except Exception as e:
        print(f"[!] 勾选适用终端失败: {e}")
        
    # 3.6 填写发行量
    print(f"[*] 正在填写发行量: {config_business.COUPON_QTY}...")
    qty_input = dialog.locator(".el-form-item:has-text('发行量') input").first
    await qty_input.fill(config_business.COUPON_QTY)
    
    # 3.7 选择发送城市
    print(f"[*] 正在选择券发送城市为“{config_business.CITY_LIMIT}”...")
    try:
        city_radio = dialog.locator(f".el-form-item:has-text('选择券发送城市') .el-radio:has-text('{config_business.CITY_LIMIT}')")
        await city_radio.click()
    except Exception as e:
        print(f"[!] 选择券发送城市失败: {e}")
        
    # 3.8 填写使用说明 (TinyMCE 智能绑定，填入 '123')
    print("[*] 正在填写富文本使用说明...")
    try:
        is_tinymce_active = await page.evaluate("() => typeof tinymce !== 'undefined'")
        if is_tinymce_active:
            await page.evaluate("() => { tinymce.activeEditor.setContent('123'); }")
            print("[*] 已通过 tinymce API 成功设置富文本使用说明。")
        else:
            editor_frame = dialog.frame_locator(".el-form-item:has-text('使用说明') iframe")
            body = editor_frame.locator("body#tinymce")
            await body.click()
            await body.fill("123")
            await body.evaluate("(el) => { el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })); }")
            await dialog.locator(".el-dialog__title:has-text('添加优惠券')").click()
            print("[*] 已通过富文本 iframe 填充。")
    except Exception as e:
        print(f"[!] 填写使用说明失败: {e}")
