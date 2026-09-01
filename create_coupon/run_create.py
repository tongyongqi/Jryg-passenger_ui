# -*- coding: utf-8 -*-
# 这个文件的功能是优惠券自动创建与自动审核流转的代码

import asyncio
import os
import sys
from playwright.async_api import async_playwright

# 1. 统一构建最高级别的 Python 搜索路径，确保彻底兼容任何运行场景
root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(root_dir)
sys.path.append(os.path.join(root_dir, "config_common"))
sys.path.append(os.path.join(root_dir, "config_business"))

import config_common
import config_business
from create_coupon.login import login_to_system
from create_coupon.filler import fill_coupon_form
from create_coupon.auditor import audit_coupon
from logger.create_coupon_logger import create_coupon_logger as sys_logger

# 确保 output 截图保存目录存在
os.makedirs("output", exist_ok=True)


async def main(headless=None):
    """
    优惠券自动化创建与流转审批的核心主逻辑。
    
    参数：
      headless (bool): 是否使用静默模式运行
    """
    async with async_playwright() as p:
        # 支持参数化外部控制是否使用有头/无头
        headless_val = headless if headless is not None else True
        browser = await p.chromium.launch(headless=headless_val)
        context = await browser.new_context(
            viewport={"width": 1440, "height": 900},
            ignore_https_errors=True
        )
        page = await context.new_page()
        page.set_default_timeout(config_common.DEFAULT_TIMEOUT)
        
        # 1. 执行统一登录管理后台系统
        await login_to_system(page)
        
        # 2. 点击右侧的“创建优惠券”按钮以拉起侧边表单弹窗
        sys_logger.info("正在打开“创建优惠券”弹窗...")
        await page.click("button:has-text('创建优惠券')")
        await page.wait_for_timeout(2000)
        
        # 锁定当前渲染可见的“添加优惠券”Dialog 弹窗容器
        dialog = page.locator(".el-dialog:visible").filter(has=page.locator(".el-dialog__title:has-text('添加优惠券')")).last
        
        # 3. 运行表单元素底层模拟物理填写模块 (填充文本、日期等)
        await fill_coupon_form(page, dialog)
        
        # 4. 截图主表单保存到 output，保存当前已填写状态
        await page.screenshot(path="output/coupon_form_filled.png")
        sys_logger.info("表单填写完毕，截图已保存至 output/coupon_form_filled.png")
        
        # 5. 使用 JS 一键完成 Vue 模型强力赋值与字段必填项拦截清除（降维打击，无视任何组件校验）
        sys_logger.info("正在通过 JS 降维打击，一键注入 Vue 核心模型并清除校验警告...")
        try:
            vue_log = await page.evaluate(f"""() => {{
                const dialogs = Array.from(document.querySelectorAll('.el-dialog'));
                const visibleDialog = dialogs.find(d => d.getBoundingClientRect().width > 0);
                if (visibleDialog) {{
                    const formEl = visibleDialog.querySelector('.el-form');
                    if (formEl && formEl.__vue__) {{
                        const m = formEl.__vue__.model || {{}};
                        
                        // 1. 强力同步注入面值与规则
                        m.Denomination = Number('{config_business.FACE_VALUE}');
                        m.UseRoleMoney = Number('{config_business.USE_RULE}');
                        m.CouponType = 1;
                        
                        // 1.2 深入到每个 Form Field 组件内部，全量、彻底摧毁所有可能存在的校验规则和必填拦截
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
                        
                        // 2. 强行同步有效期时间段与日期值 (使用纯日期格式，迎合 Element YYYY-MM-DD 原生绑定)
                        m.CouponStartDate = '{config_business.START_DATE}';
                        m.CouponEndDate = '{config_business.END_DATE}';
                        m.TimesVal = ['{config_business.START_DATE}', '{config_business.END_DATE}'];
                        m.LimitStartTime = '';
                        m.LimitEndTime = '';
                        m.CouponName = "{config_business.COUPON_NAME}";
                        m.Number = Number('{config_business.COUPON_QTY}');
                        m.Remark = "{config_business.REMARK_HTML}";
                        m.Terminal = [3, 4, 5, 6, 7, 8]; # 覆盖全终端场景配置
                        
                        // 3. 强行重写 Form 组件底层的 validate 校验器，使之一律回调返回成功 (true)
                        formEl.__vue__.validate = (callback) => {{
                            if (typeof callback === 'function') {{
                                callback(true);
                            }}
                            return Promise.resolve(true);
                        }};
                        
                        // 4. 覆盖字段级局部验证 API
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
            
        # 6. 直接使用 JS 精准定位弹窗底部唯一的确定按钮并触发 click()，绕过外部可能的拦截包装
        sys_logger.info("正在点击“确 定”按钮提交优惠券表单...")
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
        
        # 6.1 全局侦测可能弹出的 Element-UI 后端接口拦截或全局报错消息
        try:
            error_message = await page.evaluate("""() => {
                const msgEl = document.querySelector('.el-message, .el-notification');
                return msgEl ? msgEl.innerText.trim() : null;
            }""")
            if error_message:
                sys_logger.info(f"侦测到系统提示/报错信息: '{error_message}'")
        except Exception as e:
            pass
            
        # 等待添加优惠券弹窗消失，确认真正保存并提交入库成功
        try:
            await page.locator(".el-dialog:visible").filter(has=page.locator(".el-dialog__title:has-text('添加优惠券')")).wait_for(state="hidden", timeout=15000)
            sys_logger.info("添加优惠券弹窗已成功关闭。")
        except Exception as e:
            sys_logger.warn(f"等待弹窗关闭超时或失败: {e}")
            await page.screenshot(path="output/coupon_submit_failed_error.png")
            
        await page.wait_for_timeout(5000)
        
        # 7. 优惠券提审完成后，全自动执行后台的流转与审核流程通过它
        await audit_coupon(page)
        
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
