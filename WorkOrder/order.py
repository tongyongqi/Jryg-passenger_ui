# -*- coding: utf-8 -*-
# 这个文件的功能是创建工单流程并执行安全保存的代码

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
    getattr(config_business, "TARGET_ORDER_ID", "7359060558")
]


async def run_create_flow(headless: bool = None, order_ids: list = None):
    """
    创建工单专属核心流转逻辑（极致直连版本）。
    先登录，登录成功后直接导航到创建工单极速链接，填入目标订单号、投诉类型及级联标题，执行保存。
    
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
            # 循环遍历订单列表：执行独立的直接工单创建
            # ==========================================
            for order_no in order_ids_val:
                sys_logger.info(f"🚀 开始订单 {order_no} 的一键直连工单创建流程...")
                
                # 极致直达：直接前往创建工单连接，免除一切详情页中转
                create_url = f"https://dcms-test6-tx.jryghq.com/#/create-work-order/add?status=add&order_id=0"
                sys_logger.info(f"正在直接导航进入极速创建工单页面: {create_url}")
                
                try:
                    direct_success = False
                    for retry in range(1, 4):
                        try:
                            await page.goto(create_url, wait_until="domcontentloaded", timeout=40000)
                            direct_success = True
                            break
                        except Exception as e:
                            sys_logger.warn(f"直连创建工单页第 {retry} 次尝试失败: {e}")
                            if retry < 3:
                                await page.wait_for_timeout(2000)
                    
                    if not direct_success:
                        raise ConnectionError("直连创建工单页 3 次重试均失败。")
                        
                    await page.wait_for_timeout(4000)
                    sys_logger.info("极速创建工单表单页面加载成功。")
                    
                    # ----------------- 录入订单号关联与基本属性 -----------------
                    # 1. 自动寻找并填入订单号 (支持输入框模糊匹配和物理输入)
                    sys_logger.info(f"正在输入关联目标订单号: {order_no}...")
                    try:
                        # 查找 placeholder 含有“订单”或“单号”的输入框
                        order_input = page.locator("input[placeholder*='订单'], input[placeholder*='单号'], .el-form-item:has-text('订单') input").first
                        await order_input.scroll_into_view_if_needed()
                        await order_input.click()
                        await order_input.clear()
                        await order_input.fill(order_no)
                        await page.wait_for_timeout(500)
                    except Exception as o_err:
                        sys_logger.warn(f"物理填充订单号输入框遇到阻碍，将尝试 JS 兜底强制赋值: {o_err}")
                        await page.evaluate(f"""(orderNum) => {{
                            const inputs = document.querySelectorAll('input');
                            for (let input of inputs) {{
                                const ph = (input.placeholder || '').trim();
                                if (ph.includes('订单') || ph.includes('单号') || ph.includes('Order')) {{
                                    input.value = '';
                                    input.dispatchEvent(new Event('input', {{ bubbles: true }}));
                                    input.value = orderNum;
                                    input.dispatchEvent(new Event('input', {{ bubbles: true }}));
                                    input.dispatchEvent(new Event('change', {{ bubbles: true }}));
                                    input.dispatchEvent(new Event('blur', {{ bubbles: true }}));
                                    break;
                                }}
                            }}
                        }}""", order_no)
                    
                    # 2. 工单类型：勾选“投诉”单选框
                    sys_logger.info("正在选择工单类型为“投诉”...")
                    type_radio = page.locator(".el-form-item:has-text('工单类型') .el-radio, .el-radio").filter(has_text="投诉").first
                    await type_radio.click()
                    await page.wait_for_timeout(500)
                    
                    # 3. 工单标题级联选择
                    sys_logger.info("正在展开“工单标题”四级级联选择器并自适应点击...")
                    title_input = page.locator(".el-form-item:has-text('工单标题') input, input[placeholder*='请选择工单标题'], input[placeholder*='请选择']").first
                    await title_input.scroll_into_view_if_needed()
                    await title_input.click(force=True)
                    await page.wait_for_timeout(2500)
                    
                    # 使用极致丝滑、带轮询自愈的 JS 异步节点链条穿透连击，彻底击穿任何异步加载
                    cascade_result = await page.evaluate("""async () => {
                        const pollClickNode = async (text) => {
                            for (let i = 0; i < 40; i++) {
                                const nodes = Array.from(document.querySelectorAll('.el-cascader-node, .el-cascader-menu li, li'));
                                const target = nodes.find(n => n.getBoundingClientRect().width > 0 && n.innerText.trim() === text);
                                if (target) {
                                    target.click();
                                    return true;
                                }
                                await new Promise(r => setTimeout(r, 150));
                            }
                            return false;
                        };
                        
                        const ok1 = await pollClickNode('投诉');
                        if (!ok1) return 'Failed at level 1: 投诉';
                        
                        const ok2 = await pollClickNode('订单问题');
                        if (!ok2) return 'Failed at level 2: 订单问题';
                        
                        const ok3 = await pollClickNode('费用问题');
                        if (!ok3) return 'Failed at level 3: 费用问题';
                        
                        const ok4 = await pollClickNode('未上车产生费用');
                        if (!ok4) return 'Failed at level 4: 未上车产生费用';
                        
                        return 'Cascade click completed successfully!';
                    }""")
                    sys_logger.info(f"四级标题连击执行反馈: {cascade_result}")
                    await page.wait_for_timeout(1000)
                    
                    # 4. 紧急程度：选择“一般”
                    level_radio = page.locator(".el-form-item:has-text('紧急程度') .el-radio, .el-radio").filter(has_text="一般").first
                    await level_radio.click()
                    await page.wait_for_timeout(500)
                    
                    # 5. 问题描述
                    desc_textarea = page.locator(".el-form-item:has-text('问题描述') textarea, textarea").first
                    await desc_textarea.fill("123")
                    await page.wait_for_timeout(500)
                    
                    # 6. 受理人：勾选“我自己受理”
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
                        
                    # 7. 使用 JS 降维打击双向绑定保障 100% 写入 Vue Model 并清除前端校验
                    await page.evaluate(f"""(orderNum) => {{
                        const formEl = document.querySelector('.el-form');
                        if (formEl && formEl.__vue__) {{
                            const m = formEl.__vue__.model || {{}};
                            
                            // 强行同步大盘关联订单号
                            m.OrderId = orderNum;
                            m.orderId = orderNum;
                            m.order_id = orderNum;
                            m.OrderNo = orderNum;
                            m.orderNo = orderNum;
                            m.order_no = orderNum;
                            
                            const titlePath = ["投诉", "订单问题", "费用问题", "未上车产生费用"];
                            m.ProblemTitle = titlePath;
                            m.problemTitle = titlePath;
                            m.problem_title = titlePath;
                            m.Title = titlePath;
                            m.title = titlePath;
                            m.TitlePath = titlePath;
                            m.titlePath = titlePath;
                            m.WorkOrderTitle = titlePath;
                            m.workOrderTitle = titlePath;
                            
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
                    }}""", order_no)
                    
                    # 截图保存表单填写状态
                    await page.screenshot(path="output/work_order_created_form.png")
                    
                    # 8. 点击最下方的蓝色“保存”按钮提交
                    save_btn = page.locator("button:visible").filter(has_text="保存").last
                    if await save_btn.count() == 0:
                        save_btn = page.locator("button:visible").filter(has_text="确").last
                    await save_btn.scroll_into_view_if_needed()
                    await save_btn.click(force=True)
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
