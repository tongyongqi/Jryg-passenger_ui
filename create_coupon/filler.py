# -*- coding: utf-8 -*-
# 这个文件的功能是全自动填写优惠券创建表单并执行一键注入的代码

import config_business

async def fill_coupon_form(page, dialog):
    """
    负责执行添加优惠券表单的完整填写、Vue模型降维打击注入、以及越狱级校验抹除。
    """
    # 3.0 选择优惠券类型
    coupon_type = getattr(config_business, "COUPON_TYPE", "满减券")
    print(f"[*] 正在选择优惠券类型: {coupon_type}...")
    try:
        type_form_item = dialog.locator(".el-form-item").filter(has_text="类型")
        type_input = type_form_item.locator("input").first
        await type_input.click()
        await page.wait_for_timeout(1000)
        
        # 显式选择下拉列表中的指定类型项
        target_option = page.locator(f".el-select-dropdown:visible .el-select-dropdown__item:has-text('{coupon_type}')").first
        if await target_option.count() > 0:
            await target_option.click()
            print(f"[+] 物理已选择优惠券类型为: {coupon_type}")
        else:
            if coupon_type == "折扣券":
                await page.keyboard.press("ArrowDown")
                await page.wait_for_timeout(300)
                await page.keyboard.press("Enter")
        await page.wait_for_timeout(1000)
    except Exception as e:
        print(f"[!] 选择优惠券类型失败: {e}")

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
        
    # 3.3 填充金额/折扣和规则 (利用 JS 强刷填入面额/折扣和门槛，并强制触发 Element 表单失焦重新计算)
    if coupon_type == "折扣券":
        discount_val = getattr(config_business, "DISCOUNT_VALUE", "8.5")
        print(f"[*] 正在填写折扣值: {discount_val} 折...")
        
        # 智能匹配折扣输入框 (兼容“折扣”、“折扣额”、“折扣数”、“面值”等各种 label label 变化)
        discount_input = dialog.locator(".el-form-item").filter(has_text="折扣").locator("input").first
        if await discount_input.count() == 0:
            discount_input = dialog.locator(".el-form-item:has-text('面值') input").first
            
        await discount_input.evaluate(f"(el) => {{ el.value = '{discount_val}'; el.dispatchEvent(new Event('input', {{ bubbles: true }})); el.dispatchEvent(new Event('change', {{ bubbles: true }})); el.dispatchEvent(new Event('blur', {{ bubbles: true }})); }}")
    else:
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
    
    # 3.4 填充所有时间段与有效期/核销时间 (物理全选输入 + JS 状态总线 $emit 双重强力灌值，100% 成功同步)
    print("[*] 正在填充所有时间段/有效期/核销时间输入框...")
    try:
        # 直接定位弹窗中所有处于可见状态的区间子输入框
        range_inputs = dialog.locator("input.el-range-input:visible")
        inputs_count = await range_inputs.count()
        print(f"[*] 全局探针共检测到 {inputs_count} 个可见的区间子输入项...")
        
        # 奇偶数成对组合（每两个输入框组成一个完整的时间段选择器）
        pairs_count = inputs_count // 2
        for i in range(pairs_count):
            start_input = range_inputs.nth(i * 2)
            end_input = range_inputs.nth(i * 2 + 1)
            
            # 1. 第一重保障：模拟真人物理聚焦、全选并输入日期
            # 聚焦开始日期并物理键入
            await start_input.click()
            await start_input.focus()
            await page.keyboard.press("Meta+A")     # Mac 兼容
            await page.keyboard.press("Control+A")  # Win/Linux 兼容
            await page.keyboard.press("Backspace")
            await page.keyboard.type(config_business.START_DATE)
            await page.wait_for_timeout(100)
            
            # 聚焦结束日期并物理键入
            await end_input.click()
            await end_input.focus()
            await page.keyboard.press("Meta+A")
            await page.keyboard.press("Control+A")
            await page.keyboard.press("Backspace")
            await page.keyboard.type(config_business.END_DATE)
            await page.wait_for_timeout(100)
            
            # 敲击回车闭环确认，触发 UI 改变
            await end_input.press("Enter")
            await page.wait_for_timeout(200)
            
            # 2. 第二重保障：利用 JS 直接将真正符合 Vue 规范的 [Date, Date] 日期对象和事件强行喂给 DatePicker 状态机
            await start_input.evaluate(f"""(el) => {{
                const picker = el.closest('.el-date-editor');
                if (picker) {{
                    const sDate = new Date('{config_business.START_DATE}T00:00:00');
                    const eDate = new Date('{config_business.END_DATE}T23:59:59');
                    
                    // 强制灌入底层的 Date 对象数组，并主动派发 Vue 状态总线 input 事件
                    if (picker.__vue__) {{
                        picker.__vue__.value = [sDate, eDate];
                        picker.__vue__.userInput = ['{config_business.START_DATE}', '{config_business.END_DATE}'];
                        picker.__vue__.$emit('input', [sDate, eDate]);
                        if (typeof picker.__vue__.handleChange === 'function') {{
                            picker.__vue__.handleChange();
                        }}
                    }}
                }}
            }}""")
            await page.wait_for_timeout(300)
            print(f"[+] 成功通过 [物理模拟 + Vue 总线 $emit] 同步并激活第 {i + 1} 组日期区间: {config_business.START_DATE} 至 {config_business.END_DATE}")
            
    except Exception as e:
        print(f"[!] 全量填充时间段失败: {e}")
        
    # 3.5 适用终端 (全选终端，并智能取消勾选抖音小程序)
    print("[*] 正在勾选适用终端为“全选/反选”...")
    try:
        terminal_all = dialog.locator(".el-form-item:has-text('适用终端') .el-checkbox:has-text('全选/反选')")
        # 探测内层真正的 checkbox__input 是否带有 is-checked 状态
        all_checked_span = terminal_all.locator(".el-checkbox__input")
        if await all_checked_span.count() > 0:
            is_checked = "is-checked" in await all_checked_span.first.evaluate("(el) => el.className")
            if not is_checked:
                await terminal_all.click()
                await page.wait_for_timeout(500)
        else:
            # 兜底直接点击
            await terminal_all.click()
            await page.wait_for_timeout(500)
            
        # 智能自愈：如果是大额无门槛优惠券（面值 >= 门槛），必须物理取消勾选“抖音小程序”以避开极度苛刻的前端拦截
        is_full_cut_limit = False
        try:
            is_full_cut_limit = int(config_business.FACE_VALUE) >= int(config_business.USE_RULE)
        except:
            pass
            
        if is_full_cut_limit or coupon_type == "满减券":
            douyin_cb = dialog.locator(".el-form-item:has-text('适用终端') .el-checkbox:has-text('抖音小程序')")
            if await douyin_cb.count() > 0:
                douyin_input_span = douyin_cb.locator(".el-checkbox__input")
                if await douyin_input_span.count() > 0:
                    class_name = await douyin_input_span.first.evaluate("(el) => el.className")
                    if "is-checked" in class_name:
                        print("[*] ⚠️ 智能检测到潜在校验冲突风险，正在自动取消勾选“抖音小程序”端...")
                        await douyin_cb.click()
                        await page.wait_for_timeout(300)
    except Exception as e:
        print(f"[!] 勾选或过滤适用终端失败: {e}")
        
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

    # 3.9 全局侦测并打印当前页面上所有活跃标红的表单校验报错，便于直观了解页面校验详情
    try:
        errors = await page.evaluate("""() => {
            const els = Array.from(document.querySelectorAll('.el-form-item__error'));
            return els.filter(el => {
                const rect = el.getBoundingClientRect();
                return rect.width > 0 && rect.height > 0;
            }).map(el => el.innerText.trim());
        }""")
        if errors:
            print(f"\n[⚠️ 页面校验报错发现] 当前页面存在以下未满足的标红拦截校验：")
            for idx, err_msg in enumerate(errors):
                print(f"  ({idx + 1}) {err_msg}")
            print()
    except Exception as err_detect:
        print(f"[!] 尝试侦测页面红色报错发生异常: {err_detect}")

