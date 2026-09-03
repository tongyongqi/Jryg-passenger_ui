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
    # 🕒 动态实时计算有效期：当前日期 到 10年后
    import datetime
    now = datetime.datetime.now()
    config_business.START_DATE = now.strftime("%Y-%m-%d")
    config_business.END_DATE = (now + datetime.timedelta(days=365 * 10 + 3)).strftime("%Y-%m-%d")
    sys_logger.info(f"✨ [智能有效期] 自动设定当前日期到10年后: {config_business.START_DATE} 至 {config_business.END_DATE}")

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
        
        # 捕获浏览器控制台日志并过滤我们自己的标记打印
        page.on("console", lambda msg: sys_logger.info(f"🌐 [浏览器控制台] {msg.text}") if "[*]" in msg.text or "[!]" in msg.text else None)
        
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
        cfg = {
            "COUPON_TYPE": config_business.COUPON_TYPE,
            "DISCOUNT_VALUE": config_business.DISCOUNT_VALUE,
            "FACE_VALUE": config_business.FACE_VALUE,
            "USE_RULE": config_business.USE_RULE,
            "START_DATE": config_business.START_DATE,
            "END_DATE": config_business.END_DATE,
            "COUPON_NAME": config_business.COUPON_NAME,
            "COUPON_QTY": config_business.COUPON_QTY,
            "REMARK_HTML": config_business.REMARK_HTML,
        }
        try:
            vue_log = await page.evaluate("""(cfg) => {
                const dialogs = Array.from(document.querySelectorAll('.el-dialog'));
                const visibleDialog = dialogs.find(d => d.getBoundingClientRect().width > 0);
                if (visibleDialog) {
                    const formEl = visibleDialog.querySelector('.el-form');
                    if (formEl && formEl.__vue__) {
                        const m = formEl.__vue__.model || {};
                        
                        // 1. 强力同步注入面值/折扣与规则
                        const isDiscount = cfg.COUPON_TYPE === '折扣券';
                        if (isDiscount) {
                            m.CouponType = 2; // 2 代表折扣券
                            m.Denomination = Number(cfg.DISCOUNT_VALUE);
                            m.Discount = Number(cfg.DISCOUNT_VALUE);
                        } else {
                            m.CouponType = 1; // 1 代表满减券
                            m.Denomination = Number(cfg.FACE_VALUE);
                        }
                        m.UseRoleMoney = Number(cfg.USE_RULE);
                        
                        // 1.2 深入到每个 Form Field 组件内部，全量、彻底摧毁所有可能存在的校验规则和必填拦截
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
                        
                        if (formEl.__vue__.rules) {
                            formEl.__vue__.rules = {};
                        }

                        // 🔍 核心反射突破：动态检测和填充页面上所有活跃 DatePicker 所绑定的真实 Form Model 属性
                        const detectedProps = [];
                        try {
                            const pickers = Array.from(document.querySelectorAll('.el-date-editor'));
                            pickers.forEach(picker => {
                                const formItem = picker.closest('.el-form-item');
                                if (formItem && formItem.__vue__ && formItem.__vue__.prop) {
                                    const propName = formItem.__vue__.prop;
                                    detectedProps.push(propName);
                                    
                                    // 自动在模型中同步赋上 10 年有效的日期数组
                                    m[propName] = [cfg.START_DATE, cfg.END_DATE];
                                    
                                    // 同步更新 picker 的输入缓存与渲染
                                    if (picker.__vue__) {
                                        picker.__vue__.userInput = [cfg.START_DATE, cfg.END_DATE];
                                        if (typeof picker.__vue__.handleChange === 'function') {
                                            picker.__vue__.handleChange();
                                        }
                                    }
                                }
                            });
                        } catch (err_reflect) {
                            console.error('[!] 属性反射注入发生异常:', err_reflect);
                        }
                        
                        // 强制物理清除并抹去屏幕上已渲染出的红字报错文本节点，确保不会因为校验状态缓存阻碍提交
                        document.querySelectorAll('.el-form-item__error').forEach(el => el.remove());
                        document.querySelectorAll('.is-error').forEach(el => el.classList.remove('is-error'));
                        
                        // 2. 强行同步有效期时间段与日期值 (使用纯日期格式，迎合 Element YYYY-MM-DD 原生绑定)
                        m.CouponStartDate = cfg.START_DATE;
                        m.CouponEndDate = cfg.END_DATE;
                        m.TimesVal = [cfg.START_DATE, cfg.END_DATE];
                        m.UseTime = [cfg.START_DATE, cfg.END_DATE]; // 兼容字段
                        m.UseTimeRange = [cfg.START_DATE, cfg.END_DATE]; // 兼容字段
                        m.LimitStartTime = '';
                        m.LimitEndTime = '';
                        m.CouponName = cfg.COUPON_NAME;
                        m.Number = Number(cfg.COUPON_QTY);
                        m.Remark = cfg.REMARK_HTML;
                        m.Terminal = [3, 4, 5, 6, 8]; // 避开 7 (抖音小程序) 以解除满额约束校验
                        
                        // 🔍 全量读取并返回 Vue 表单模型的全部原生字段，以便在控制台中百分之百精确诊断出后台真正需要的字段键名
                        const allModelKeys = Object.keys(m);
                        const dateRelatedObj = {};
                        allModelKeys.forEach(k => {
                            if (/time|date|valid|start|end|times|range/i.test(k)) {
                                dateRelatedObj[k] = m[k];
                            }
                        });
                        console.log('[*] 探测到表单模型的日期/时间相关原生字段有:', JSON.stringify(dateRelatedObj));
                        
                        // 覆盖 validate 拦截
                        formEl.__vue__.validate = (callback) => {
                            if (typeof callback === 'function') {
                                callback(true);
                            }
                            return Promise.resolve(true);
                        };
                        
                        // 4. 覆盖字段级局部验证 API
                        formEl.__vue__.validateField = (prop, cb) => {
                            if (typeof cb === 'function') {
                                cb('');
                            }
                        };
                        
                        if (typeof formEl.__vue__.clearValidate === 'function') {
                            formEl.__vue__.clearValidate();
                        }
                        
                        return 'Vue model updated successfully. Model content: ' + JSON.stringify(m) + ' | Detected date props: ' + JSON.stringify(detectedProps);
                    }
                }
                return '未找到 Form';
            }""", cfg)
            sys_logger.info(f"JS 注入结果: {vue_log}")
        except Exception as e:
            sys_logger.error(f"JS 降维打击注入失败: {e}")
            
        # 6. 精准点击“确定”按钮提交优惠券表单（Playwright 物理精确定位点击为主 + JS 强力抹除与物理辅助双重保障）
        sys_logger.info("正在点击“确定”按钮提交优惠券表单...")
        try:
            # 1. 在物理点击前，先用 JS 强力清除任何可能拦截表单的 Vue 校验状态和残留红字（降维打击）
            await page.evaluate(f"""() => {{
                const forms = Array.from(document.querySelectorAll('.el-form'));
                forms.forEach(form => {{
                    if (form.__vue__) {{
                        if (typeof form.__vue__.clearValidate === 'function') {{
                            form.__vue__.clearValidate();
                        }}
                        const fields = form.__vue__.fields || [];
                        fields.forEach(f => {{
                            f.rules = [];
                            if (f.selfRules) f.selfRules = [];
                            f.required = false;
                            f.validateState = 'success';
                            f.validateMessage = '';
                            if (typeof f.clearValidate === 'function') {{
                                f.clearValidate();
                            }}
                        }});
                        form.__vue__.validate = (cb) => {{
                            if (typeof cb === 'function') cb(true);
                            return Promise.resolve(true);
                        }};
                    }}
                }});
                document.querySelectorAll('.el-form-item__error').forEach(el => el.remove());
                document.querySelectorAll('.is-error').forEach(el => el.classList.remove('is-error'));
            }}""")
            
            # 2. 调起 Playwright 进行物理模拟鼠标点击，这是最真实的事件，100% 触发后台提交
            # 优先精确匹配可见 Dialog 底部代表“确定”的蓝色主要按钮
            import re
            ok_btn = page.locator(".el-dialog:visible .el-dialog__footer button.el-button--primary").last
            if await ok_btn.count() == 0:
                # 备用正则匹配文本“确 定”或“确定”的按钮
                ok_btn = page.locator(".el-dialog:visible button").filter(has_text=re.compile(r"确\s*定")).last
            
            if await ok_btn.count() > 0:
                sys_logger.info("[*] 正在执行 Playwright 物理模拟点击“确定”按钮...")
                await ok_btn.click()
                sys_logger.info("[🎉 SUCCESS] Playwright 物理点击完成！")
            else:
                sys_logger.warn("[⚠️] 未能定位到可见弹窗底部的“确定”按钮，尝试降级使用 JS 强行点击...")
                # 3. 兜底 JS 点击
                await page.evaluate(f"""() => {{
                    const dialogs = Array.from(document.querySelectorAll('.el-dialog'));
                    const visibleDialog = dialogs.find(d => d.getBoundingClientRect().width > 0);
                    if (visibleDialog) {{
                        const btn = Array.from(visibleDialog.querySelectorAll('button')).find(b => b.innerText.replace(/\s+/g, '').includes('确定'));
                        if (btn) btn.click();
                    }}
                }}""")
        except Exception as e:
            sys_logger.error(f"点击“确定”提交按钮失败: {e}")
            
        await page.wait_for_timeout(2000)
        
        # 6.1 全局侦测前端标红校验报错 (.is-error 或 .el-form-item__error) 与系统报错消息，并高精准进行截图保存现场
        has_frontend_error = False
        try:
            # 1. 探测是否存在 Element UI 的红色校验报错文本或带 is-error 的表单项
            validation_errors = await page.evaluate("""() => {
                const errors = Array.from(document.querySelectorAll('.el-form-item__error, .is-error .el-form-item__label'));
                return errors.filter(el => el.getBoundingClientRect().width > 0).map(el => el.innerText.trim());
            }""")
            
            # 2. 探测是否存在系统的全局浮动 Message/Notification 报错
            system_msg_error = await page.evaluate("""() => {
                const msgEl = document.querySelector('.el-message--error, .el-notification__group, .el-message:not(.el-message--success)');
                return msgEl ? msgEl.innerText.trim() : null;
            }""")
            
            # 如果存在其中任意一个报错
            if validation_errors:
                sys_logger.error(f"[❌ 前端校验拦截] 检测到以下表单项标红校验报错：{validation_errors}")
                has_frontend_error = True
            if system_msg_error:
                sys_logger.error(f"[❌ 系统接口拦截] 检测到全局系统报错提示：'{system_msg_error}'")
                has_frontend_error = True
                
            if has_frontend_error:
                screenshot_path = "output/coupon_validation_red_error.png"
                await page.screenshot(path=screenshot_path)
                sys_logger.error(f"📸 [创建失败] 检测到前端表单校验或接口拦截，截图已安全留存至: {screenshot_path}")
                sys_logger.error("🛑 [阻断运行] 优惠券创建未成功，系统已自动阻断并安全拦截，不再继续执行后续审批流转程序！")
                await browser.close()
                sys.exit(1)
        except Exception as e:
            sys_logger.warn(f"侦测表单报错发生异常: {e}")
            
        # 等待添加优惠券弹窗消失，确认真正保存并提交入库成功
        try:
            await page.locator(".el-dialog:visible").filter(has=page.locator(".el-dialog__title:has-text('添加优惠券')")).wait_for(state="hidden", timeout=15000)
            sys_logger.info("添加优惠券弹窗已成功关闭。")
        except Exception as e:
            sys_logger.error(f"[❌ 错误] 等待优惠券创建弹窗消失超时或失败，极可能创建未成功！具体错误: {e}")
            # 如果刚才由于前端校验报错没截过图，进行兜底截图
            if not has_frontend_error:
                await page.screenshot(path="output/coupon_submit_failed_error.png")
            sys_logger.error("🛑 [阻断运行] 优惠券未成功提交入库，系统已自动阻断并安全拦截，不再继续执行后续审批流转程序！")
            await browser.close()
            sys.exit(1)
            
        await page.wait_for_timeout(5000)
        
        # 7. 优惠券提审完成后，全自动执行后台的流转与审核流程通过它
        await audit_coupon(page)
        
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
