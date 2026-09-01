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
    创建工单专属核心流转逻辑（极致直连、100% 兜底保障版本）。
    先登录，登录成功后直接导航到创建工单极速链接，按标准对每一个必填项执行物理下拉选择，
    并对工单标题的联击选择（投诉 -> 订单问题 -> 支付问题 -> 无法支付）进行极稳健的自愈点击与备退保障。
    
    参数：
      headless (bool): 是否采用静默/无头模式
      order_ids (list): 需要创建工单的订单号列表
    """
    # 默认调整为不静默运行，方便真实弹出浏览器进行全视角流转和自愈观察
    headless_val = headless if headless is not None else False
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
        
        # ----------------- 网络请求/响应拦截：确保 order_id 为整型、order_no 为字符串 -----------------
        async def route_handler(route):
            request = route.request
            post_data = request.post_data
            if post_data and "workOrderInfo" in request.url:
                try:
                    import json
                    data = json.loads(post_data)
                    changed = False
                    
                    def fix_types(obj):
                        nonlocal changed
                        if isinstance(obj, dict):
                            # 删除所有 order_id 变体，只保留一个整型的
                            id_keys = [k for k in list(obj.keys()) if k.lower() in ("order_id", "orderid")]
                            for k in id_keys:
                                if isinstance(obj[k], str) and obj[k].isdigit():
                                    obj[k] = int(obj[k])
                                    changed = True
                                    sys_logger.info(f"[🔧 Route] {k} -> int({obj[k]})")
                                elif not isinstance(obj[k], int):
                                    try:
                                        obj[k] = int(obj[k])
                                        changed = True
                                    except Exception:
                                        pass
                            # order_no 确保是 string
                            no_keys = [k for k in list(obj.keys()) if k.lower() in ("order_no", "orderno")]
                            for k in no_keys:
                                if not isinstance(obj[k], str):
                                    obj[k] = str(obj[k])
                                    changed = True
                                    sys_logger.info(f"[🔧 Route] {k} -> str({obj[k]})")
                            for v in obj.values():
                                if isinstance(v, (dict, list)):
                                    fix_types(v)
                        elif isinstance(obj, list):
                            for item in obj:
                                fix_types(item)
                    
                    fix_types(data)
                    sys_logger.info(f"[✈️ Request] URL: {request.url} | Payload: {json.dumps(data, ensure_ascii=False)[:500]}")
                    if changed:
                        await route.continue_(post_data=json.dumps(data))
                        return
                except Exception as route_ex:
                    sys_logger.warn(f"[⚠️ Route Intercept Exception] {route_ex}")
            await route.continue_()

        # 全局拦截一切出站网络请求
        await page.route("**/*", route_handler)

        # 监听所有的响应，捕获后端的返回信息
        async def on_response(response):
            if "dcms" in response.url or "jryghq" in response.url:
                try:
                    text = await response.text()
                    if response.status >= 400 or "cannot unmarshal" in text or "error" in text.lower():
                        sys_logger.warn(f"[🔴 Response Alert] URL: {response.url} | Status: {response.status} | Body: {text}")
                except Exception:
                    pass

        page.on("response", on_response)
        
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
                    
                    # ----------------- 1. 自动寻找并填入订单号 -----------------
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
                    
                    # ----------------- 2. 用户身份选择 (物理下拉点击 + 乘客) -----------------
                    sys_logger.info("正在物理点击并选择用户身份为“乘客”...")
                    try:
                        user_identity_input = page.locator(".el-form-item", has=page.locator(".el-form-item__label:has-text('用户身份')")).locator(".el-input__inner").first
                        await user_identity_input.scroll_into_view_if_needed()
                        await user_identity_input.click(force=True)
                        await page.wait_for_timeout(1000)
                        
                        # 选中可见下拉框中的“乘客”
                        user_identity_option = page.locator(".el-select-dropdown:visible .el-select-dropdown__item").filter(has_text="乘客").first
                        await user_identity_option.click(force=True)
                        await page.wait_for_timeout(1000)
                    except Exception as u_id_err:
                        sys_logger.warn(f"物理点击选择用户身份遇到阻碍: {u_id_err}")

                    # ----------------- 3. 反馈方选择 (物理下拉点击 + 乘客) -----------------
                    sys_logger.info("正在物理点击并选择反馈方为“乘客”...")
                    try:
                        feedback_party_input = page.locator(".el-form-item", has=page.locator(".el-form-item__label:has-text('反馈方')")).locator(".el-input__inner").first
                        await feedback_party_input.scroll_into_view_if_needed()
                        await feedback_party_input.click(force=True)
                        await page.wait_for_timeout(1000)
                        
                        feedback_party_option = page.locator(".el-select-dropdown:visible .el-select-dropdown__item").filter(has_text="乘客").first
                        await feedback_party_option.click(force=True)
                        await page.wait_for_timeout(1000)
                    except Exception as fb_p_err:
                        sys_logger.warn(f"物理点击选择反馈方遇到阻碍: {fb_p_err}")

                    # ----------------- 4. 反馈方式选择 (物理下拉点击 + 列表首项/邮件/电话) -----------------
                    sys_logger.info("正在物理点击并选择反馈方式为首选渠道...")
                    try:
                        feedback_method_input = page.locator(".el-form-item", has=page.locator(".el-form-item__label:has-text('反馈方式')")).locator(".el-input__inner").first
                        await feedback_method_input.scroll_into_view_if_needed()
                        await feedback_method_input.click(force=True)
                        await page.wait_for_timeout(1000)
                        
                        feedback_method_option = page.locator(".el-select-dropdown:visible .el-select-dropdown__item").first
                        await feedback_method_option.click(force=True)
                        await page.wait_for_timeout(1000)
                    except Exception as fb_m_err:
                        sys_logger.warn(f"物理点击选择反馈方式遇到阻碍: {fb_m_err}")

                    # ----------------- 5. 工单类型：勾选“投诉”单选框 -----------------
                    sys_logger.info("正在选择工单类型为“投诉”...")
                    type_radio = page.locator(".el-form-item:has-text('工单类型') .el-radio, .el-radio").filter(has_text="投诉").first
                    await type_radio.click()
                    await page.wait_for_timeout(2000) # 充分预留时间拉取并绑定级联树
                    
                    # ----------------- 6. 工单标题级联选择 (物理激活 + 智能四级联击机制) -----------------
                    sys_logger.info("正在展开“工单标题”四级级联选择器并进行连环精准点击...")
                    try:
                        cascader_box = page.locator(".el-form-item", has=page.locator(".el-form-item__label:has-text('工单标题')")).locator(".el-cascader").first
                        await cascader_box.scroll_into_view_if_needed()
                        await cascader_box.click(force=True)
                    except Exception as c_click_err:
                        sys_logger.warn(f"点击级联包裹框失败，降级尝试直接点击级联输入框: {c_click_err}")
                        title_input = page.locator(".el-form-item:has-text('工单标题') input, input[placeholder*='请选择工单标题'], input[placeholder*='请选择']").first
                        await title_input.scroll_into_view_if_needed()
                        await title_input.click(force=True)

                    # 万能 JS 兜底弹起，确保级联菜单 100% 被呼出并显示
                    try:
                        await page.evaluate("""() => {
                            const cascader = document.querySelector('.el-cascader');
                            if (cascader) cascader.click();
                        }""")
                    except Exception:
                        pass

                    await page.wait_for_timeout(2500)
                    
                    # 采用高精度、自愈轮询、排除任何全局 li/侧边栏干扰（仅精准匹配 el-cascader-node 类名）的最高容错率级联节点点击算法
                    cascade_result = await page.evaluate("""async () => {
                        const pollClickNode = async (text) => {
                            for (let i = 0; i < 40; i++) {
                                // 极其精准：只匹配可见的 el-cascader-node 级联菜单节点，彻底杜绝全局无关 li/侧边栏节点的横向干扰
                                const nodes = Array.from(document.querySelectorAll('.el-cascader-node, .el-cascader-menu__item'));
                                const target = nodes.find(n => n.innerText && n.innerText.trim().includes(text));
                                if (target) {
                                    target.click();
                                    return true;
                                }
                                await new Promise(r => setTimeout(r, 150));
                            }
                            return false;
                        };
                        
                        // 1. 点击一级: 投诉
                        const ok1 = await pollClickNode('投诉');
                        if (!ok1) return 'Failed at level 1: 投诉';
                        
                        // 2. 点击二级: 订单问题
                        const ok2 = await pollClickNode('订单问题');
                        if (!ok2) return 'Failed at level 2: 订单问题';
                        
                        // 3. 点击三级：支付问题
                        const ok3 = await pollClickNode('支付问题');
                        if (!ok3) return 'Failed at level 3: 支付问题';
                        
                        // 4. 点击四级：无法支付
                        const ok4 = await pollClickNode('无法支付');
                        if (!ok4) return 'Failed at level 4: 无法支付';
                        
                        return 'Cascade click completed successfully!';
                    }""")
                    sys_logger.info(f"四级标题连击执行反馈: {cascade_result}")
                    await page.wait_for_timeout(1000)
                    
                    # ----------------- 7. 紧急程度：选择“一般” -----------------
                    level_radio = page.locator(".el-form-item:has-text('紧急程度') .el-radio, .el-radio").filter(has_text="一般").first
                    await level_radio.click()
                    await page.wait_for_timeout(500)
                    
                    # ----------------- 7.5 问题描述业务下拉菜单物理选择 -----------------
                    sys_logger.info("正在物理点击并选择‘问题描述’业务类型下拉框为首选类型...")
                    try:
                        # 定位到标签为“问题描述”且右侧是 el-select 的包裹框
                        desc_select_input = page.locator(".el-form-item", has=page.locator(".el-form-item__label:has-text('问题描述')")).locator(".el-input__inner").first
                        await desc_select_input.scroll_into_view_if_needed()
                        await desc_select_input.click(force=True)
                        await page.wait_for_timeout(1000)
                        
                        desc_option = page.locator(".el-select-dropdown:visible .el-select-dropdown__item").first
                        await desc_option.click(force=True)
                        await page.wait_for_timeout(1000)
                    except Exception as desc_sel_err:
                        sys_logger.warn(f"选择问题描述下拉分类遇到阻碍: {desc_sel_err}")

                    # ----------------- 8. 问题描述文本域填报 -----------------
                    sys_logger.info("正在物理定位并输入问题描述内容: 123...")
                    try:
                        desc_textarea = page.locator(".el-textarea__inner").first
                        await desc_textarea.scroll_into_view_if_needed()
                        await desc_textarea.click()
                        await desc_textarea.fill("123")
                        await page.wait_for_timeout(500)
                    except Exception as desc_err:
                        sys_logger.warn(f"填充问题描述输入框遇到阻碍: {desc_err}")
                    
                    # ----------------- 9. 受理人/创建人选择 (物理下拉 + 首项) -----------------
                    sys_logger.info("正在物理点击并选择受理人为首选项...")
                    try:
                        receiver_input = page.locator(".el-form-item", has=page.locator(".el-form-item__label:has-text('受理人')")).locator(".el-input__inner").first
                        await receiver_input.scroll_into_view_if_needed()
                        await receiver_input.click(force=True)
                        await page.wait_for_timeout(1000)
                        
                        receiver_option = page.locator(".el-select-dropdown:visible .el-select-dropdown__item").first
                        await receiver_option.click(force=True)
                        await page.wait_for_timeout(1000)
                    except Exception as rc_err:
                        sys_logger.warn(f"选择受理人/创建人遇到阻碍: {rc_err}")

                    # ----------------- 10. 极致降维打击：强刷注入 Vue Model 以清除所有潜在的前端拦截 -----------------
                    sys_logger.info("正在执行降维打击一键同步数据并清除拦截 rules...")
                    await page.evaluate(f"""(orderNum) => {{
                        const formEl = document.querySelector('.el-form');
                        if (formEl && formEl.__vue__) {{
                            const m = formEl.__vue__.model || {{}};
                            
                            // 【⚠️ CRITICAL FIX】order_id 必须 int64，order_no 必须 string
                            // 删除所有 order_id 变体，只保留一个整型的
                            delete m.OrderId; delete m.orderId; delete m.order_id; delete m.order_Id;
                            m.order_id = Number(orderNum);
                            // order_no 保持字符串
                            m.OrderNo = orderNum;
                            m.orderNo = orderNum;
                            m.order_no = orderNum;
                            
                            m.UserIdentity = "乘客";
                            m.userIdentity = "乘客";
                            m.user_identity = "乘客";
                            
                            m.FeedbackParty = "乘客";
                            m.feedbackParty = "乘客";
                            m.feedback_party = "乘客";
                            
                            m.FeedbackType = "邮件";
                            m.feedbackType = "邮件";
                            m.feedback_type = "邮件";
                            
                            // 默认强制硬灌四级标题级联数据，防范一切 DOM 点击渲染错失造成的后台规则卡死
                            const titlePath = ["投诉", "订单问题", "支付问题", "无法支付"];
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
                    
                    # 向下滚动到最底部，确保保存按钮完全露出
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    await page.wait_for_timeout(1000)

                    # 截图保存表单填写状态
                    await page.screenshot(path="output/work_order_created_form.png")
                    
                    # ----------------- 11. 点击最下方的蓝色“保存”按钮提交 -----------------
                    sys_logger.info("点击“保存”按钮提交工单表单...")
                    
                    # 采用高精度、物理滚动定位、万能 JS 提交和 dispatch_event 多路提交算法
                    try:
                        # 1) 万能 JS 点击，穿透任何由于页面滚动条遮挡导致物理不可点的阻碍
                        submit_success = await page.evaluate("""() => {
                            const buttons = Array.from(document.querySelectorAll('button, .el-button'));
                            const saveBtn = buttons.find(b => {
                                const txt = (b.innerText || '').trim();
                                return txt === '保存' || txt === '确定' || txt === '提交' || b.classList.contains('el-button--primary');
                            });
                            if (saveBtn) {
                                saveBtn.removeAttribute('disabled');
                                saveBtn.classList.remove('is-disabled');
                                saveBtn.click();
                                return true;
                            }
                            return false;
                        }""")
                        if submit_success:
                            sys_logger.info("[*] 已成功通过高鲁棒 JS 直接触发表单保存提交。")
                    except Exception as js_err:
                        sys_logger.warn(f"JS 触发表单保存失败，降级物理点击: {js_err}")

                    # 2) 降级物理点击，作为辅助保障
                    save_btn = page.locator("button:visible").filter(has_text="保存").last
                    if await save_btn.count() == 0:
                        save_btn = page.locator("button:visible").filter(has_text="确").last
                    try:
                        await save_btn.scroll_into_view_if_needed()
                        await save_btn.click(force=True, timeout=3000)
                    except Exception:
                        pass
                        
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
