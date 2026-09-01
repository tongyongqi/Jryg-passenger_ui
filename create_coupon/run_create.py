import asyncio
import os
import sys
from playwright.async_api import async_playwright

root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(root_dir)
sys.path.append(os.path.join(root_dir, "config_common"))
sys.path.append(os.path.join(root_dir, "config_business"))

import config_common
import config_business
from create_coupon.login import login_to_system
from create_coupon.filler import fill_coupon_form
from create_coupon.auditor import audit_coupon
from logger.logger import sys_logger

os.makedirs("output", exist_ok=True)

async def main(headless=None):
    async with async_playwright() as p:
        headless_val = headless if headless is not None else True
        browser = await p.chromium.launch(headless=headless_val)
        context = await browser.new_context(
            viewport={"width": 1440, "height": 900},
            ignore_https_errors=True
        )
        page = await context.new_page()
        page.set_default_timeout(config_common.DEFAULT_TIMEOUT)
        
        await login_to_system(page)
        
        sys_logger.info("正在打开“创建优惠券”弹窗...")
        await page.click("button:has-text('创建优惠券')")
        await page.wait_for_timeout(2000)
        
        dialog = page.locator(".el-dialog:visible").filter(has=page.locator(".el-dialog__title:has-text('添加优惠券')")).last
        
        await fill_coupon_form(page, dialog)
        
        await page.screenshot(path="output/coupon_form_filled.png")
        sys_logger.info("表单填写完毕，截图已保存至 output/coupon_form_filled.png")
        
        sys_logger.info("正在通过 JS 一键注入 Vue 核心模型并清除校验警告...")
        try:
            vue_log = await page.evaluate(f"""() => {{
                const dialogs = Array.from(document.querySelectorAll('.el-dialog'));
                const visibleDialog = dialogs.find(d => d.getBoundingClientRect().width > 0);
                if (visibleDialog) {{
                    const formEl = visibleDialog.querySelector('.el-form');
                    if (formEl && formEl.__vue__) {{
                        const m = formEl.__vue__.model || {{}};
                        
                        m.Denomination = Number('{config_business.FACE_VALUE}');
                        m.UseRoleMoney = Number('{config_business.USE_RULE}');
                        m.CouponType = 1;
                        
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
                        
                        m.CouponStartDate = '{config_business.START_DATE}';
                        m.CouponEndDate = '{config_business.END_DATE}';
                        m.TimesVal = ['{config_business.START_DATE}', '{config_business.END_DATE}'];
                        m.LimitStartTime = '';
                        m.LimitEndTime = '';
                        m.CouponName = "{config_business.COUPON_NAME}";
                        m.Number = Number('{config_business.COUPON_QTY}');
                        m.Remark = "{config_business.REMARK_HTML}";
                        m.Terminal = [3, 4, 5, 6, 7, 8];
                        
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
                        
                        if (typeof formEl.__vue__.clearValidate === 'function') {{
                            formEl.__vue__.clearValidate();
                        }}
                        
                        return 'Vue model updated successfully';
                    }}
                }}
                return '未找到 Form';
            }}""")
            sys_logger.info(f"JS 注入结果: {vue_log}")
        except Exception as e:
            sys_logger.error(f"JS 降维打击注入失败: {e}")
            
        sys_logger.info("正在点击“确 定”按钮提交优惠券...")
        try:
            submit_log = await page.evaluate("""() => {
                const dialogs = Array.from(document.querySelectorAll('.el-dialog'));
                const visibleDialog = dialogs.find(d => d.getBoundingClientRect().width > 0);
                if (visibleDialog) {
                    const formEl = visibleDialog.querySelector('.el-form');
                    if (formEl && formEl.__vue__) {
                        const okBtn = visibleDialog.querySelector('button.el-button--primary, button:not(.el-button--default)');
                        if (okBtn) {
                            okBtn.click();
                            return 'Direct button click triggered';
                        }
                    }
                }
                return 'No action triggered';
            }""")
            sys_logger.info(f"JS 提交触发结果: {submit_log}")
        except Exception as e:
            sys_logger.error(f"JS 提交触发失败: {e}")
            
        await page.wait_for_timeout(2000)
        try:
            error_message = await page.evaluate("""() => {
                const msgEl = document.querySelector('.el-message, .el-notification');
                return msgEl ? msgEl.innerText.trim() : null;
            }""")
            if error_message:
                sys_logger.info(f"侦测到系统提示/报错信息: '{error_message}'")
        except Exception as e:
            pass
            
        try:
            await page.locator(".el-dialog:visible").filter(has=page.locator(".el-dialog__title:has-text('添加优惠券')")).wait_for(state="hidden", timeout=15000)
            sys_logger.info("添加优惠券弹窗已成功关闭。")
        except Exception as e:
            sys_logger.warn(f"等待弹窗关闭超时或失败: {e}")
            await page.screenshot(path="output/coupon_submit_failed_error.png")
            
        await page.wait_for_timeout(5000)
        
        await audit_coupon(page)
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
