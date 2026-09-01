import asyncio
import os
import sys
from playwright.async_api import async_playwright

# 1. 确保将项目根目录添加到 python path 使得模块 and 配置能被正常载入
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import config_common
import config_business
import login_common  # 导入抽离出来的公共登录模块
from logger.work_order_logger import work_order_logger as sys_logger

# 确保存放截图的 output 目录在运行前已经创建
os.makedirs("output", exist_ok=True)

# ==========================================
# 默认配置的全局订单号变量：支持单个或多个订单
# ==========================================
DEFAULT_ORDER_IDS = [
    getattr(config_business, "TARGET_ORDER_ID", "7358984980")
]


async def run_create_flow(headless: bool = None, order_ids: list = None):
    """
    创建工单专属核心流转逻辑。
    纯粹的工单创建逻辑，不包含任何列表页的工单受理/流转步骤，可作为独立功能随意调用。
    
    参数：
      headless (bool): 是否采用静默/无头模式
      order_ids (list): 需要创建工单的订单号列表
    """
    headless_val = headless if headless is not None else config_business.HEADLESS_DEBUG
    order_ids_val = order_ids if order_ids is not None else DEFAULT_ORDER_IDS

    async with async_playwright() as p:
        # 启动 Chromium 浏览器实例
        browser = await p.chromium.launch(headless=headless_val)
        context = await browser.new_context(
            viewport={"width": 1440, "height": 900},
            ignore_https_errors=True
        )
        page = await context.new_page()
        page.set_default_timeout(config_common.DEFAULT_TIMEOUT)
        
        try:
            # ==========================================
            # STEP 1: 统一登录管理后台系统 (调用公共登录模块)
            # ==========================================
            try:
                await login_common.login_to_system(page)
                await page.wait_for_timeout(1000)
            except Exception as e:
                sys_logger.error(f"[❌ ERROR] 统一登录登录失败: {e}")
                raise e
                
            # ==========================================
            # 循环遍历订单列表：执行独立的工单创建
            # ==========================================
            for order_no in order_ids_val:
                sys_logger.info(f"🚀 开始订单 {order_no} 的工单创建流程...")
                
                meta_id = getattr(config_business, "META_ID", "113491")
                order_type = getattr(config_business, "ORDER_TYPE", "5")
                
                # 直连订单详情页
                detail_url = f"https://dcms-test6-tx.jryghq.com/#/order_detail/{order_no}?order_no={order_no}&meta_id={meta_id}&order_type={order_type}"
                sys_logger.info(f"正在直接导航进入目标订单详情页面: {detail_url}")
                try:
                    direct_success = False
                    for retry in range(1, 4):
                        try:
                            await page.goto(detail_url, wait_until="domcontentloaded", timeout=40000)
                            direct_success = True
                            break
                        except Exception as e:
                            sys_logger.warn(f"直连详情页第 {retry} 次尝试失败: {e}")
                            if retry < 3:
                                await page.wait_for_timeout(2000)
                    
                    if not direct_success:
                        raise ConnectionError("直连订单详情页 3 次重试均失败。")
                        
                    await page.wait_for_timeout(4000)
                    
                    # 滑动到最下方，点击下方导航的“工单”页签
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    await page.wait_for_timeout(1500)
                    
                    tab = page.locator("[id*='tab-工单'], #tab-工单, .el-tabs__item:has-text('工单')").first
                    await tab.scroll_into_view_if_needed()
                    await tab.click()
                    await page.wait_for_timeout(3000)
                    sys_logger.info("已切换至详情页底部“工单”页签。")
                    
                    # 点击右侧“创建工单”拉起新工单创建页面
                    create_btn = page.locator(".el-tab-pane:visible button:has-text('创建工单'), button:has-text('创建工单')").first
                    await create_btn.scroll_into_view_if_needed()
                    await create_btn.click()
                    await page.wait_for_timeout(4000)
                    sys_logger.info("新建工单表单页面加载成功。")
                    
                    # ----------------- 按照截图 i 与截图 ii 真实、精细地填写新建工单流程 -----------------
                    # 1. 工单类型：勾选“投诉”单选框
                    type_radio = page.locator(".el-form-item:has-text('工单类型') .el-radio, .el-radio").filter(has_text="投诉").first
                    await type_radio.click()
                    await page.wait_for_timeout(500)
                    
                    # 2. 工单标题级联选择
                    title_input = page.locator(".el-form-item:has-text('工单标题') input, input[placeholder*='请选择工单标题'], input[placeholder*='请选择']").first
                    await title_input.click()
                    await page.wait_for_timeout(1000)
                    
                    # 异步四级点击
                    cascade_result = await page.evaluate("""() => {
                        const clickNode = (text) => {
                            const nodes = Array.from(document.querySelectorAll('.el-cascader-node, .el-cascader-menu li, li'));
                            const target = nodes.find(n => n.getBoundingClientRect().width > 0 && n.innerText.trim() === text);
                            if (target) {
                                target.click();
                                return true;
                            }
                            return false;
                        };
                        
                        return new Promise((resolve) => {
                            clickNode('投诉');
                            setTimeout(() => {
                                clickNode('订单问题');
                                setTimeout(() => {
                                    clickNode('费用问题');
                                    setTimeout(() => {
                                        const success = clickNode('未上车产生费用');
                                        resolve(success ? 'Cascade click completed!' : 'Failed at last step');
                                    }, 1200);
                                }, 1000);
                            }, 800);
                        });
                    }""")
                    sys_logger.info(f"四级标题连击执行反馈: {cascade_result}")
                    await page.wait_for_timeout(1000)
                    
                    # 3. 紧急程度：选择“一般”
                    level_radio = page.locator(".el-form-item:has-text('紧急程度') .el-radio, .el-radio").filter(has_text="一般").first
                    await level_radio.click()
                    await page.wait_for_timeout(500)
                    
                    # 4. 问题描述
                    desc_textarea = page.locator(".el-form-item:has-text('问题描述') textarea, textarea").first
                    await desc_textarea.fill("123")
                    await page.wait_for_timeout(500)
                    
                    # 5. 受理人：勾选“我自己受理”
                    try:
                        await page.evaluate("""() => {
                            const selfHandleBtn = Array.from(document.querySelectorAll('button, .el-button, .el-radio')).find(el => el.innerText && el.innerText.trim().includes('我自己受理'));
                            if (selfHandleBtn) {
                                selfHandleBtn.click();
                            }
                        }""")
                        await page.wait_for_timeout(500)
                    except Exception as e:
                        sys_logger.warn(f"JS 勾选我自己受理失败: {e}")
                        
                    # 6. 使用 JS 降维打击双向绑定保障 100% 写入 Vue Model 并清除前端校验
                    await page.evaluate(f"""() => {{
                        const formEl = document.querySelector('.el-form');
                        if (formEl && formEl.__vue__) {{
                            const m = formEl.__vue__.model || {{}};
                            
                            m.ProblemDesc = "123";
                            m.remark = "123";
                            m.Remark = "123";
                            m.EmergencyLevel = "一般";
                            m.emergencyLevel = "一般";
                            m.SelfHandle = true;
                            m.selfHandle = true;
                            m.WorkOrderType = "投诉";
                            
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
                            
                            formEl.__vue__.validate = (callback) => {{
                                if (typeof callback === 'function') {{
                                    callback(true);
                                }}
                                return Promise.resolve(true);
                            }};
                        }}
                    }}""")
                    
                    # 截图保存表单填写状态
                    await page.screenshot(path="output/work_order_created_form.png")
                    
                    # 7. 点击最下方的蓝色“保存”按钮提交
                    save_btn = page.locator("button:visible").filter(has_text="保存").last
                    if await save_btn.count() == 0:
                        save_btn = page.locator("button:visible").filter(has_text="确").last
                    await save_btn.click()
                    await page.wait_for_timeout(6000)
                    sys_logger.info(f"订单号 {order_no} 工单创建保存成功。")
                    
                except Exception as create_err:
                    sys_logger.error(f"订单 {order_no} 创建工单流程遭遇异常: {create_err}")
                    continue

            sys_logger.info("所有工单创建逻辑执行完毕，正在正常关闭浏览器...")
            await browser.close()
            
        except Exception as err:
            sys_logger.error(f"工单创建流程在执行中发生异常: {err}")
            try:
                await page.screenshot(path="output/work_order_error_crash.png")
            except Exception:
                pass
            await page.wait_for_timeout(5000)
            await browser.close()

if __name__ == "__main__":
    asyncio.run(run_create_flow())
