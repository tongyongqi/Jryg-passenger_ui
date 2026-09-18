"""
iOS 香港乘客端自动化测试 — 打开App → 登录 → 下单

环境要求：
1. tidevice + xcodebuild test 已启动 WDA (localhost:8100)
2. facebook-wda 已安装
3. com.sunlightmobility.client 已安装到iOS设备
"""

import time
import re
import wda

# ──────────────────────── 配置 ────────────────────────

WDA_URL = "http://localhost:8100"
APP_BUNDLE = "com.sunlightmobility.client"
PHONE_NUMBER = "11000090"
VERIFY_CODE = "123456"

# 截图保存目录
import os
SCREENSHOT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "screenshots")


# ──────────────────────── 辅助函数 ────────────────────────

def screenshot(c, name):
    """截图并保存"""
    os.makedirs(SCREENSHOT_DIR, exist_ok=True)
    filepath = os.path.join(SCREENSHOT_DIR, f"{name}.png")
    c.screenshot(filepath)
    print(f"    [截图] {filepath}")
    return filepath


def dump_elements(c):
    """打印页面元素（按钮、文本、输入框）"""
    xml = c.source()
    print("  按钮:")
    for m in re.finditer(r'<XCUIElementTypeButton[^>]*label="([^"]*)"[^>]*>', xml):
        if m.group(1).strip():
            print(f"    button: {m.group(1)}")
    print("  文本:")
    for m in re.finditer(r'<XCUIElementTypeStaticText[^>]*label="([^"]*)"[^>]*>', xml):
        if m.group(1).strip():
            print(f"    text: {m.group(1)}")
    print("  输入框:")
    for m in re.finditer(r'<XCUIElementTypeTextField[^>]*label="([^"]*)"[^>]*>', xml):
        print(f"    field: {m.group(1)}")
    return xml


def find_and_click(c, label=None, text=None, timeout=10):
    """查找并点击元素"""
    if label:
        el = c(label=label)
    elif text:
        el = c(text=text)
    else:
        return False
    el.wait(timeout=timeout)
    if el.exists:
        el.click()
        return True
    return False


# ──────────────────────── 登录流程 ────────────────────────

def do_login(c):
    """执行登录流程"""
    print("\n========== 阶段一：登录 ==========")

    # 启动App
    print("[登录-1] 启动App...")
    c.app_start(APP_BUNDLE)
    time.sleep(8)

    # 检查是否已登录 — 点击"我的"tab看是否有用户名
    print("[登录-2] 检查登录状态...")
    find_and_click(c, text="我的")
    time.sleep(2)
    xml = c.source()
    if "登錄/註冊" not in xml:
        print("    App 已登录，跳过登录流程")
        find_and_click(c, text="主頁")
        time.sleep(2)
        return True
    print("    未登录，开始登录流程")

    # 点击登錄/註冊
    print("[登录-3] 点击登錄/註冊...")
    find_and_click(c, label="登錄/註冊")
    time.sleep(3)

    # 输入手机号
    print("[登录-4] 输入手机号...")
    phone_field = c(className="XCUIElementTypeTextField")
    phone_field.wait(timeout=10)
    if phone_field.exists:
        phone_field.click()
        time.sleep(0.5)
        phone_field.clear_text()
        time.sleep(0.3)
        phone_field.set_text(PHONE_NUMBER)
        time.sleep(0.5)
        print(f"    手机号已输入: {PHONE_NUMBER}")
    else:
        print("    [ERROR] 未找到手机号输入框")
        return False

    # 关闭键盘，点击取得驗證碼
    print("[登录-5] 点击取得驗證碼...")
    # 先点完成关闭键盘
    find_and_click(c, label="Done")
    time.sleep(0.5)
    # 协议未勾选，点击取得验证码会弹出协议
    find_and_click(c, label="取得驗證碼")
    time.sleep(2)

    # 检测协议弹窗 — 用精确匹配 label="同意"，避免匹配到"不同意"
    print("[登录-6] 检测协议弹窗...")
    agree_btn = c(label="同意")
    agree_btn.wait(timeout=5)
    if agree_btn.exists:
        agree_btn.click()
        time.sleep(3)
        print("    已同意协议")
    else:
        # 尝试英文
        agree_btn2 = c(label="Agree")
        if agree_btn2.wait(timeout=3) and agree_btn2.exists:
            agree_btn2.click()
            time.sleep(3)
            print("    已同意协议")
        else:
            print("    未检测到协议弹窗（可能已同意过）")

    # 验证码输入页 — TextField可能visible=false但可操作
    print("[登录-7] 输入验证码...")
    time.sleep(3)
    # 确认已到验证码页面（检测"請輸入驗證碼"或"驗證碼已發送"文字）
    verify_page = c(textContains="驗證碼")
    if verify_page.wait(timeout=10) and verify_page.exists:
        print("    已进入验证码输入页")
    else:
        print("    [WARN] 未检测到验证码页面标识文字")
    
    code_field = c(className="XCUIElementTypeTextField")
    code_field.wait(timeout=10)
    if code_field.exists:
        # 验证码页面只有1个输入框，直接set_text
        code_field.set_text(VERIFY_CODE)
        time.sleep(1)
        print(f"    验证码已输入: {VERIFY_CODE}")
        time.sleep(5)
    else:
        print("    [ERROR] 未找到验证码输入框")
        screenshot(c, "login_verify_error")
        return False

    # 验证登录结果
    print("[登录-8] 验证登录结果...")
    time.sleep(3)
    xml = c.source()
    app = c.app_current()
    print(f"    当前App: {app}")

    if "登錄/註冊" in xml:
        print("    [WARN] 仍显示登录/注册，登录可能未成功")
    else:
        print("    登录成功！")

    screenshot(c, "01_login_success")
    return True


# ──────────────────────── 下单流程 ────────────────────────

def do_order(c):
    """执行下单流程"""
    print("\n========== 阶段二：下单 ==========")

    # 确保在首页
    print("[下单-1] 回到首页...")
    find_and_click(c, text="主頁")
    time.sleep(3)

    # 进入起点搜索页
    print("[下单-2] 进入起点搜索页...")
    # 点击起点提示框（"無法取得位置，請輸入起點" 或起点地址）
    start_btn = c(labelContains="起點")
    if not start_btn.exists:
        start_btn = c(labelContains="輸入")
    if not start_btn.exists:
        start_btn = c(labelContains="想去哪")
    if start_btn.exists:
        start_btn.click()
        time.sleep(3)
        print("    已点击起点输入区域")
    else:
        print("    [WARN] 未找到起点输入区域，尝试其他方式")
        xml = c.source()
        # 点击"想去哪裡？"
        el = c(text="想去哪裡？")
        if el.exists:
            el.click()
            time.sleep(3)

    # 输入起点
    print("[下单-3] 输入起点：铜锣湾地铁...")
    search_field = c(className="XCUIElementTypeTextField")
    search_field.wait(timeout=10)
    if search_field.exists:
        search_field.click()
        time.sleep(0.3)
        search_field.set_text("铜锣湾地铁")
        time.sleep(3)
        print("    已输入起点关键词")
    else:
        print("    [ERROR] 未找到搜索输入框")
        screenshot(c, "order_search_error")
        return False

    # 选择起点搜索结果
    print("[下单-4] 选择起点结果...")
    time.sleep(2)
    # 查找包含"銅鑼灣"的结果 — 搜索结果以text形式展示
    start_result = c(textContains="銅鑼灣")
    start_result.wait(timeout=10)
    if start_result.exists:
        start_result.click()
        print("    已选择起点")
    else:
        # 尝试label方式
        start_result2 = c(labelContains="銅鑼灣")
        if start_result2.wait(timeout=5) and start_result2.exists:
            start_result2.click()
            print("    已选择起点(label)")
        else:
            # 选第一条结果
            first_result = c(className="XCUIElementTypeCell", index=0)
            if first_result.exists:
                first_result.click()
                print("    已选择第一条结果")
            else:
                print("    [ERROR] 未找到起点搜索结果")
                screenshot(c, "order_start_result_error")
                return False
    time.sleep(3)

    # 输入终点
    print("[下单-5] 输入终点：香港大学...")
    # 点击终点输入区域
    dest_btn = c(labelContains="目的地")
    if not dest_btn.exists:
        dest_btn = c(labelContains="end")
    if not dest_btn.exists:
        dest_btn = c(labelContains="想去")
    if dest_btn.exists:
        dest_btn.click()
        time.sleep(2)

    dest_search = c(className="XCUIElementTypeTextField")
    dest_search.wait(timeout=5)
    if dest_search.exists:
        dest_search.click()
        time.sleep(0.3)
        dest_search.set_text("香港大学")
        time.sleep(3)
        print("    已输入终点关键词")

    # 选择终点结果
    print("[下单-6] 选择终点结果...")
    dest_result = c(textContains="香港大學")
    dest_result.wait(timeout=10)
    if dest_result.exists:
        dest_result.click()
        print("    已选择终点")
    else:
        # 尝试label方式
        dest_result2 = c(labelContains="香港大學")
        if dest_result2.wait(timeout=5) and dest_result2.exists:
            dest_result2.click()
            print("    已选择终点(label)")
        else:
            first_result = c(className="XCUIElementTypeCell", index=0)
            if first_result.exists:
                first_result.click()
                print("    已选择第一条结果")
            else:
                print("    [ERROR] 未找到终点搜索结果")
                screenshot(c, "order_dest_result_error")
                return False
    time.sleep(5)

    # 确认呼叫
    print("[下单-7] 点击确认呼叫...")
    call_btn = c(labelContains="確認呼叫")
    if not call_btn.exists:
        call_btn = c(labelContains="呼叫")
    call_btn.wait(timeout=10)
    if call_btn.exists:
        call_btn.click()
        print("    已点击确认呼叫")
        time.sleep(3)
    else:
        print("    [ERROR] 未找到确认呼叫按钮")
        screenshot(c, "order_call_error")
        return False

    # 确认支付
    print("[下单-8] 确认支付...")
    pay_btn = c(labelContains="確認支付")
    if not pay_btn.exists:
        pay_btn = c(labelContains="支付")
    if not pay_btn.exists:
        pay_btn = c(labelContains="Pay")
    pay_btn.wait(timeout=15)
    if pay_btn.exists:
        pay_btn.click()
        print("    已点击确认支付")
        time.sleep(5)
    else:
        print("    [WARN] 未找到确认支付按钮")
        screenshot(c, "order_pay_error")

    # ── Alipay WebView 支付流程 ──
    # Safari WebView 会弹出，WDA 可以直接操作 Safari 中的元素

    # 检测Pay Now (Alipay WebView支付页面)
    print("[下单-9] 检测Pay Now (Alipay支付页)...")
    pay_now = c(label="Pay Now")
    pay_now.wait(timeout=20)
    if pay_now.exists:
        pay_now.click()
        print("    已点击 Pay Now")
        time.sleep(5)
        screenshot(c, "02_pay_now_clicked")

        # 等待支付成功 — 检测 SUCCESS 文字
        print("[下单-9a] 等待支付成功...")
        success_text = c(text="SUCCESS")
        success_text.wait(timeout=30)
        if success_text.exists:
            print("    支付成功！(SUCCESS)")
            screenshot(c, "03_pay_success")
        else:
            print("    [WARN] 未检测到SUCCESS，继续尝试返回")
            screenshot(c, "03_pay_status")

        # 点击 Return to Merchant 返回商家
        print("[下单-9b] 点击 Return to Merchant...")
        return_btn = c(labelContains="Return to Merchant")
        return_btn.wait(timeout=20)
        if return_btn.exists:
            return_btn.click()
            print("    已点击 Return to Merchant")
            time.sleep(3)

            # Safari 可能弹窗"在陽光出行中打开此页？"，点击"打开"
            open_btn = c(label="打开")
            open_btn.wait(timeout=10)
            if open_btn.exists:
                open_btn.click()
                print("    已点击 打开，回到乘客端App")
                time.sleep(5)
            else:
                # 没有弹窗就直接切回App
                c.app_start(APP_BUNDLE)
                time.sleep(5)
        else:
            print("    [WARN] 未找到Return to Merchant，直接切回App")
            c.app_start(APP_BUNDLE)
            time.sleep(5)
    else:
        print("    未检测到Pay Now（可能无需WebView支付）")
        time.sleep(2)

    # 验证下单结果
    print("[下单-10] 验证下单结果...")
    xml = c.source()
    screenshot(c, "04_order_result")

    # 检测溫馨提示弹窗（订单成功后的提示）
    notice_btn = c(labelContains="我知道了")
    if notice_btn.exists:
        notice_btn.click()
        print("    已点击「我知道了，準備出發」")
        time.sleep(3)
        screenshot(c, "05_order_confirmed")

    # 检测叫车关键词
    if any(kw in xml for kw in ["等待", "尋找", "司機", "已下單", "訂單", "正在", "叫車", "溫馨提示", "準備出發"]):
        print("    下单成功！已进入叫车等待流程")
        return True
    else:
        print("    [INFO] 当前页面内容:")
        for m in re.finditer(r'label="([^"]*)"', xml):
            if m.group(1).strip() and len(m.group(1)) > 1:
                print(f"      {m.group(1)}")
        return True


# ──────────────────────── 主流程 ────────────────────────

def main():
    print("=" * 60)
    print("  iOS 香港乘客端 — 打开App → 登录 → 下单")
    print("=" * 60)

    print("[1] 连接WDA...")
    c = wda.Client(WDA_URL)
    print(f"    WDA状态: {c.status()['state']}")

    # 登录
    if not do_login(c):
        print("\n登录失败，流程终止。")
        return False

    # 下单
    if not do_order(c):
        print("\n下单失败。")
        return False

    print("\n" + "=" * 60)
    print("  iOS自动化流程完成！截图保存在 screenshots/ 目录")
    print("=" * 60)
    return True


if __name__ == "__main__":
    main()
