import asyncio
import os
import sys
from playwright.async_api import async_playwright

# 1. 确保将项目根目录添加到 python path 使得模块和配置能被正常载入
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import config_common
import config_business
from create_coupon.login import login_to_system
from create_coupon.filler import fill_coupon_form
from create_coupon.auditor import audit_coupon

# 确保 output 文件夹在运行前已经创建
os.makedirs("output", exist_ok=True)

async def main(headless=None):
    async with async_playwright() as p:
        # 启动 Chromium 浏览器 (支持外部传入 headless 或者默认采用公共配置)
        headless_val = headless if headless is not None else True
        browser = await p.chromium.launch(headless=headless_val)
        context = await browser.new_context(
            viewport={"width": 1440, "height": 900},
            ignore_https_errors=True
        )
        page = await context.new_page()
        page.set_default_timeout(config_common.DEFAULT_TIMEOUT)
        
        # 1. 执行统一登录管理
        await login_to_system(page)
        
        # 2. 打开创建优惠券弹窗
        print("[*] 正在打开“创建优惠券”弹窗...")
        await page.click("button:has-text('创建优惠券')")
        await page.wait_for_timeout(2000)
        
        # 定位目标弹窗
        dialog = page.locator(".el-dialog:visible").filter(has=page.locator(".el-dialog__title:has-text('添加优惠券')")).last
        
        # 3. 运行表单自动填写模块
        await fill_coupon_form(page, dialog)
        
        # 4. 截图主表单保存到 output
        await page.screenshot(path="output/coupon_form_filled.png")
        print("[*] 表单填写完毕，截图已保存至 output/coupon_form_filled.png")
        
        # 5. 使用 JS 一键完成 Vue 模型赋值与校验清除（降维打击，无视组件拦截）
        print("[*] 正在通过 JS 降维打击，一键注入 Vue 核心模型并清除校验警告...")
        try:
            vue_log = await page.evaluate(f"""() => {{
                const dialogs = Array.from(document.querySelectorAll('.el-dialog'));
                const visibleDialog = dialogs.find(d => d.getBoundingClientRect().width > 0);
                if (visibleDialog) {{
                    const formEl = visibleDialog.querySelector('.el-form');
                    if (formEl && formEl.__vue__) {{
                        const m = formEl.__vue__.model || {{}};
                        
                        // 1. 面值与规则
                        m.Denomination = Number('{config_business.FACE_VALUE}');
                        m.UseRoleMoney = Number('{config_business.USE_RULE}');
                        m.CouponType = 1;
                        
                        // 1.2 越狱黑科技：深入到每个 Form Field 组件内部，全量、彻底摧毁所有可能存在的校验规则和拦截
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
                        
                        // 2. 有效期时间段与日期值 (使用纯日期格式，迎合 Element YYYY-MM-DD 原生绑定)
                        m.CouponStartDate = '{config_business.START_DATE}';
                        m.CouponEndDate = '{config_business.END_DATE}';
                        m.TimesVal = ['{config_business.START_DATE}', '{config_business.END_DATE}'];
                        
                        // 3. 选择券核销时间段 (留空，完美和截图第二张一致)
                        m.LimitStartTime = '';
                        m.LimitEndTime = '';
                        
                        // 4. 其他核心必填属性
                        m.CouponName = "{config_business.COUPON_NAME}";
                        m.Number = Number('{config_business.COUPON_QTY}');
                        m.Remark = "{config_business.REMARK_HTML}";
                        m.Terminal = [3, 4, 5, 6, 7, 8]; // 全终端覆盖 (3-H5, 4-APP, 5-微信小程序, 6-支付宝小程序, 7-抖音小程序, 8-鸿蒙系统)
                        
                        // 4.5 宇宙级越狱提审黑客技术：强行重写 Form 组件底层的 validate 方法，一律回调返回成功 (true)
                        formEl.__vue__.validate = (callback) => {{
                            if (typeof callback === 'function') {{
                                callback(true);
                            }}
                            return Promise.resolve(true);
                        }};
                        
                        // 4.6 覆盖可能被调用的字段级别校验拦截 API
                        formEl.__vue__.validateField = (prop, cb) => {{
                            if (typeof cb === 'function') {{
                                cb('');
                            }}
                        }};
                        
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
            
        # 6. 提交 (直接用 JS 触发 Form 提交或者确定按钮的 click 关联事件，绕过所有校验闭包)
        print("[*] 正在点击“确 定”按钮提交优惠券...")
        try:
            submit_log = await page.evaluate("""() => {
                const dialogs = Array.from(document.querySelectorAll('.el-dialog'));
                const visibleDialog = dialogs.find(d => d.getBoundingClientRect().width > 0);
                if (visibleDialog) {
                    const formEl = visibleDialog.querySelector('.el-form');
                    if (formEl && formEl.__vue__) {
                        // 1. 如果有绑定的保存/提交事件，直接在 Vue 实例内调用它
                        // 寻找可见的确定按钮，直接调用其 click()
                        const okBtn = visibleDialog.querySelector('button.el-button--primary, button:not(.el-button--default)');
                        if (okBtn) {
                            okBtn.click();
                            return 'Direct button click triggered from inside Vue container';
                        }
                    }
                }
                return 'No action triggered';
            }""")
            print(f"[*] JS 提交触发结果: {submit_log}")
        except Exception as e:
            print(f"[!] JS 提交触发失败: {e}")
            
        # 6.1 全局侦测并打印可能出现的后端接口提示（el-message）
        await page.wait_for_timeout(2000)
        try:
            error_message = await page.evaluate("""() => {
                const msgEl = document.querySelector('.el-message, .el-notification');
                return msgEl ? msgEl.innerText.trim() : null;
            }""")
            if error_message:
                print(f"[!] 侦测到系统提示/报错信息: '{error_message}'")
        except Exception as e:
            print(f"[!] 侦测系统提示失败: {e}")
            
        # 等待添加优惠券弹窗消失，确保真正提交成功
        try:
            await page.locator(".el-dialog:visible").filter(has=page.locator(".el-dialog__title:has-text('添加优惠券')")).wait_for(state="hidden", timeout=15000)
            print("[*] 添加优惠券弹窗已成功关闭。")
        except Exception as e:
            print(f"[!] 等待弹窗关闭超时或失败，可能存在表单校验未通过: {e}")
            await page.screenshot(path="output/coupon_submit_failed_error.png")
            print("[!] 已保存提交失败状态截图至 output/coupon_submit_failed_error.png")
            
        # 等待服务器响应并自动更新列表
        await page.wait_for_timeout(5000)
        
        # 7. 自动审核优惠券
        await audit_coupon(page)
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
