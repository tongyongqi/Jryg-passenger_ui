"""
测试用例：打开App → 登录 → 下单（合并流程）。

流程：
1. 打开 App，检查是否已登录
2. 未登录则：清除数据 → 首启协议 → 权限弹窗 → 登录页 → 输入手机号 → 获取验证码 → 同意协议 → 输入验证码 → 登录成功
3. 登录成功后点击底部"首頁"tab
4. 如果起点提示框显示"当前城市暂未开通服务"，点击它进入搜索页
5. 输入起点"铜锣湾地铁"，选择结果
6. 输入终点"香港大学"，选择结果
7. 点击确认呼叫
8. 处理支付确认页，点击确认支付并呼叫
9. 处理 WebView 支付页面，点击 Pay Now
10. 支付成功后点击 Done，切回 App
"""

import time
import re
import subprocess
import uiautomator2 as u2

from auth_token import (
    APP_PACKAGE,
    APP_ACTIVITY,
    PHONE_NUMBER,
    VERIFY_CODE,
    set_token,
    get_token,
)


# ──────────────────────── 辅助函数 ────────────────────────

def wait_for_element(d, resource_id=None, text=None, text_contains=None, timeout=10):
    """等待元素出现并返回。"""
    if resource_id:
        el = d(resourceId=f"{APP_PACKAGE}:id/{resource_id}")
    elif text:
        el = d(text=text)
    elif text_contains:
        el = d(textContains=text_contains)
    else:
        raise ValueError("必须提供 resource_id / text / text_contains 之一")
    el.wait(timeout=timeout)
    return el


def get_token_from_device():
    """通过 adb 读取设备上 SharedPreferences 中的 token。"""
    cmd = (
        f'adb shell "run-as {APP_PACKAGE} cat shared_prefs/MC_PERSISTENT_SESSION.xml"'
    )
    result = subprocess.run(
        cmd, shell=True, capture_output=True, text=True, timeout=10
    )
    xml = result.stdout
    match = re.search(
        r'<string name="yg_new_socket_token">([^<]+)</string>', xml
    )
    if match:
        return match.group(1).strip()
    return None


# ──────────────────────── 登录流程 ────────────────────────

def do_login(d):
    """执行登录流程，返回是否成功。"""

    # 先启动 App，检查是否已登录（不清数据，保留城市设置）
    print("[登录-1] 启动 App...")
    d.app_stop(APP_PACKAGE)
    time.sleep(1)
    d.shell(f"am start -n {APP_ACTIVITY}")
    time.sleep(8)

    # 检查是否已登录（首页有 tv_mine_name 且不是"登錄/註冊"）
    mine_tab = d(text="我的")
    mine_tab.wait(timeout=5)
    if mine_tab.exists:
        mine_tab.click()
        time.sleep(2)
        mine_name = d(resourceId=f"{APP_PACKAGE}:id/tv_mine_name")
        login_entry = d(text="登錄/註冊")
        if mine_name.exists and not login_entry.exists:
            print("    App 已登录，跳过登录流程")
            token = get_token_from_device()
            if token:
                set_token(token)
                print(f"    Token 已保存: {token[:50]}...")
            # 切回首页
            home_tab = d(text="首頁")
            if home_tab.exists:
                home_tab.click()
                time.sleep(2)
            return True
        # 没登录，切回首页再继续
        home_tab = d(text="首頁")
        if home_tab.exists:
            home_tab.click()
            time.sleep(1)

    # 未登录，需要清除数据重新登录
    print("    App 未登录，清除数据重新登录...")
    d.app_stop(APP_PACKAGE)
    time.sleep(1)
    d.shell(f"pm clear {APP_PACKAGE}")
    time.sleep(2)
    d.press("home")
    time.sleep(1)
    d.shell(f"am start -n {APP_ACTIVITY}")
    time.sleep(8)

    # 处理首启协议弹窗
    print("[登录-2] 检测首启协议弹窗...")
    first_agree_btn = d(resourceId=f"{APP_PACKAGE}:id/tv_button_agree")
    first_agree_btn.wait(timeout=15)
    if first_agree_btn.exists:
        print("    检测到首启协议弹窗，点击同意...")
        first_agree_btn.click()
        time.sleep(3)
        print("    已同意首启协议")
    else:
        print("    未检测到首启协议弹窗（可能已同意过）")

    # 处理 App 内权限请求弹窗 — 点击"去授权"
    print("[登录-3] 检测 App 内权限请求弹窗...")
    perm_confirm_btn = d(resourceId=f"{APP_PACKAGE}:id/tv_confirm")
    perm_confirm_btn.wait(timeout=10)
    if perm_confirm_btn.exists:
        print("    检测到权限请求弹窗，点击去授权...")
        perm_confirm_btn.click()
        time.sleep(3)

        # 处理系统权限弹窗 — 点击"仅在使用该应用时允许"
        print("[登录-4] 检测系统权限弹窗...")
        sys_allow_btn = d(
            resourceId="com.android.permissioncontroller:id/permission_allow_foreground_only_button"
        )
        sys_allow_btn.wait(timeout=10)
        if sys_allow_btn.exists:
            print("    检测到系统权限弹窗，点击仅在使用该应用时允许...")
            sys_allow_btn.click()
            time.sleep(3)
            print("    已授予权限")
        else:
            print("    [WARN] 未找到系统权限弹窗按钮，尝试文字匹配...")
            for text_pattern in [
                "仅在使用该应用时允许",
                "僅在使用該應用時允許",
                "While using the app",
            ]:
                btn = d(text=text_pattern)
                if btn.wait(timeout=3):
                    btn.click()
                    time.sleep(3)
                    print(f"    已点击: {text_pattern}")
                    break
    else:
        print("    未检测到 App 内权限请求弹窗")

    # 权限弹窗处理后切回 App
    time.sleep(2)
    d.press("home")
    time.sleep(1)
    d.shell(f"monkey -p {APP_PACKAGE} -c android.intent.category.LAUNCHER 1")
    time.sleep(3)

    # 进入"我的"tab，点击"登錄/註冊"进入登录页
    print("[登录-5] 进入登录页...")
    mine_tab = d(text="我的")
    mine_tab.wait(timeout=10)
    if mine_tab.exists:
        mine_tab.click()
        time.sleep(2)
        print("    已点击我的tab")

    login_entry = d(text="登錄/註冊")
    login_entry.wait(timeout=5)
    if login_entry.exists:
        login_entry.click()
        time.sleep(3)
        print("    已点击登录/注册")
    else:
        if d(resourceId=f"{APP_PACKAGE}:id/phone_num").exists:
            print("    已在登录页")

    # 输入手机号
    print("[登录-6] 输入手机号...")
    phone_input = wait_for_element(d, resource_id="phone_num", timeout=15)
    if not phone_input.exists:
        print("    [ERROR] 未找到手机号输入框")
        print(f"    当前页面: {d.app_current()}")
        with open("/tmp/ui_debug.xml", "w") as f:
            f.write(d.dump_hierarchy())
        return False
    phone_input.click()
    time.sleep(0.5)
    phone_input.clear_text()
    time.sleep(0.3)
    d.send_keys(PHONE_NUMBER)
    time.sleep(0.5)
    print(f"    手机号已输入: {PHONE_NUMBER}")

    # 协议未勾选，点获取验证码时会弹出协议
    agree_img = d(resourceId=f"{APP_PACKAGE}:id/agree_img")
    if agree_img.exists and agree_img.info.get("selected", False):
        agree_img.click()
        time.sleep(0.5)
        print("    已取消协议勾选（用于触发协议弹窗）")
    elif agree_img.exists and not agree_img.info.get("selected", False):
        print("    协议未勾选（获取验证码时会自动弹出协议）")

    # 点击获取验证码
    print("[登录-7] 点击获取验证码...")
    get_code_btn = wait_for_element(d, resource_id="rl_next", timeout=5)
    if not get_code_btn.exists:
        print("    [ERROR] 未找到获取验证码按钮")
        return False
    get_code_btn.click()
    time.sleep(2)

    # 处理使用者协议隐私政策弹窗 - 点击同意
    print("[登录-8] 检测使用者协议隐私政策弹窗...")
    agree_btn = d(resourceId=f"{APP_PACKAGE}:id/dialog_agree")
    agree_btn.wait(timeout=5)
    if agree_btn.exists:
        print("    检测到协议弹窗，点击同意...")
        agree_btn.click()
        time.sleep(3)
        print("    已同意协议")
    else:
        print("    未检测到协议弹窗（可能已同意过）")

    # 验证码输入页
    print("[登录-9] 进入验证码输入页，输入验证码...")
    verify_title = wait_for_element(
        d, resource_id="verification_title_txt", timeout=10
    )
    if not verify_title.exists:
        verify_container = d(resourceId=f"{APP_PACKAGE}:id/verify_code")
        if not verify_container.exists:
            print("    [ERROR] 未进入验证码输入页")
            print(f"    当前页面: {d.app_current()}")
            return False

    verify_container = d(resourceId=f"{APP_PACKAGE}:id/verify_code")
    verify_container.click()
    time.sleep(0.5)
    d.send_keys(VERIFY_CODE)
    print(f"    验证码已输入: {VERIFY_CODE}")
    time.sleep(5)

    # 验证登录是否成功
    print("[登录-10] 验证登录结果...")
    current = d.app_current()
    print(f"    当前 App: {current}")

    login_success = not d(text="登錄/註冊").exists
    home_indicators = [
        d(resourceId=f"{APP_PACKAGE}:id/tv_mine_name"),
        d(text="首頁"),
        d(text="我的"),
    ]
    if not login_success:
        error_msg = d(textContains="錯誤")
        if error_msg.exists:
            print(f"    [ERROR] 登录失败，发现错误提示: {error_msg.get_text()}")
            return False
        print("    [WARN] 仍显示登录/注册，登录可能未成功")
    elif any(el.exists for el in home_indicators):
        print("    登录成功！已进入首页")
    else:
        print("    [INFO] 登录可能成功，但未检测到明确首页元素")

    # 提取 token
    print("[登录-11] 提取 token...")
    token = get_token_from_device()
    if token:
        set_token(token)
        print(f"    Token 已保存: {token[:50]}...")
    else:
        print("    [WARN] 未能从设备提取 token")

    return login_success


# ──────────────────────── 下单流程 ────────────────────────

def do_order(d):
    """执行下单流程，返回是否成功。"""

    # 确认 App 在前台
    current = d.app_current()
    if current.get("package") != APP_PACKAGE:
        print("    App 不在前台，启动 App...")
        d.shell("am force-stop com.iap.linker_portal")
        time.sleep(1)
        d.shell(f"am start -n {APP_ACTIVITY}")
        time.sleep(10)
    else:
        time.sleep(3)

    # 清理残留页面，确保回到首页
    print("[下单-1] 回到首页...")
    for _ in range(5):
        if d(resourceId=f"{APP_PACKAGE}:id/tv_start_address").exists or \
           d(resourceId=f"{APP_PACKAGE}:id/ll_start").exists:
            break
        if d(resourceId=f"{APP_PACKAGE}:id/ivClose").exists:
            d(resourceId=f"{APP_PACKAGE}:id/ivClose").click()
            time.sleep(2)
            continue
        if d(resourceId=f"{APP_PACKAGE}:id/et_search").exists or \
           d(resourceId=f"{APP_PACKAGE}:id/btn_call").exists:
            d.press("back")
            time.sleep(2)
            continue
        d.press("back")
        time.sleep(2)

    # 点击底部"首頁"tab，确保在首页
    print("[下单-2] 点击底部首页tab...")
    home_tab = d(text="首頁")
    home_tab.wait(timeout=10)
    if home_tab.exists:
        home_tab.click()
        time.sleep(3)
        print("    已点击首页tab")
    else:
        print("    [WARN] 未找到首页tab，尝试继续...")

    # 进入起点搜索页
    # 如果起点提示框显示"当前城市暂未开通服务"，点击它进入搜索页
    # 如果起点显示正常地址，点击 ll_start 进入搜索页
    print("[下单-3] 进入起点搜索页...")
    search_input = d(resourceId=f"{APP_PACKAGE}:id/et_search")

    for attempt in range(3):
        # 方式1: 点击起点提示文字 tv_start_address（城市未开通时显示"当前城市暂未开通服务"）
        start_address = d(resourceId=f"{APP_PACKAGE}:id/tv_start_address")
        if start_address.exists:
            addr_text = start_address.get_text()
            print(f"    起点提示框文字: {addr_text}")
            start_address.click()
            time.sleep(3)
            search_input = d(resourceId=f"{APP_PACKAGE}:id/et_search")
            search_input.wait(timeout=5)
            if search_input.exists:
                print(f"    搜索页已打开 (尝试 {attempt+1}, 点击起点提示框)")
                break
        else:
            print(f"    tv_start_address 不存在 (尝试 {attempt+1})")

        # 方式2: 点击 ll_start 起点区域
        start_area = d(resourceId=f"{APP_PACKAGE}:id/ll_start")
        if start_area.exists:
            start_area.click()
            time.sleep(3)
            search_input = d(resourceId=f"{APP_PACKAGE}:id/et_search")
            search_input.wait(timeout=5)
            if search_input.exists:
                print(f"    搜索页已打开 (尝试 {attempt+1}, 点击ll_start)")
                break

        time.sleep(1)

    search_input = d(resourceId=f"{APP_PACKAGE}:id/et_search")
    if not search_input.exists:
        print("    [ERROR] 未找到起点搜索输入框")
        with open("/tmp/ui_order_debug2.xml", "w") as f:
            f.write(d.dump_hierarchy())
        return False

    # 输入起点
    print("[下单-4] 输入起点：铜锣湾地铁...")
    search_input.click()
    time.sleep(0.5)
    search_input.clear_text()
    time.sleep(0.3)
    d.send_keys("铜锣湾地铁")
    time.sleep(3)
    print("    已输入起点关键词")

    start_result = d(
        resourceId=f"{APP_PACKAGE}:id/tv_address_name",
        text="銅鑼灣(地鐵站)",
    )
    start_result.wait(timeout=10)
    if not start_result.exists:
        first_item = d(resourceId=f"{APP_PACKAGE}:id/tv_address_name", instance=0)
        if first_item.exists:
            first_item.click()
            print("    已选择第一条搜索结果")
        else:
            print("    [ERROR] 未找到起点搜索结果")
            return False
    else:
        start_result.click()
        print("    已选择起点：銅鑼灣(地鐵站)")
    time.sleep(3)

    # 输入终点
    print("[下单-5] 输入终点：香港大学...")
    dest_area = d(resourceId=f"{APP_PACKAGE}:id/rl_destination_layout")
    dest_area.wait(timeout=10)
    if not dest_area.exists:
        print("    [ERROR] 未找到终点输入区域")
        return False
    dest_area.click()
    time.sleep(2)

    dest_search = d(resourceId=f"{APP_PACKAGE}:id/et_search")
    dest_search.wait(timeout=5)
    if dest_search.exists:
        dest_search.click()
        time.sleep(0.3)
        dest_search.clear_text()
        time.sleep(0.3)
        d.send_keys("香港大学")
        time.sleep(3)
        print("    已输入终点关键词")
    else:
        print("    [WARN] 终点搜索框未出现，尝试直接输入...")
        d.send_keys("香港大学")
        time.sleep(3)

    dest_result = d(
        resourceId=f"{APP_PACKAGE}:id/tv_address_name",
        text="香港大學",
    )
    dest_result.wait(timeout=10)
    if not dest_result.exists:
        first_item = d(resourceId=f"{APP_PACKAGE}:id/tv_address_name", instance=0)
        if first_item.exists:
            first_item.click()
            print("    已选择第一条搜索结果")
        else:
            print("    [ERROR] 未找到终点搜索结果")
            return False
    else:
        dest_result.click()
        print("    已选择终点：香港大學")
    time.sleep(5)

    # 确认呼叫
    print("[下单-6] 点击确认呼叫...")
    call_btn = d(resourceId=f"{APP_PACKAGE}:id/btn_call")
    call_btn.wait(timeout=10)
    if not call_btn.exists:
        print("    [ERROR] 未找到确认呼叫按钮")
        with open("/tmp/ui_order_debug.xml", "w") as f:
            f.write(d.dump_hierarchy())
        return False
    call_btn.click()
    print("    已点击确认呼叫")
    time.sleep(3)

    # 支付确认页 — 点击确认支付并呼叫
    print("[下单-7] 检测支付确认页...")
    pay_btn = d(resourceId=f"{APP_PACKAGE}:id/tv_pay")
    pay_btn.wait(timeout=10)
    if pay_btn.exists:
        print("    检测到支付确认页，点击确认支付并呼叫...")
        bounds = pay_btn.info.get("bounds", {})
        cx = (bounds.get("left", 540) + bounds.get("right", 540)) // 2
        cy = (bounds.get("top", 2214) + bounds.get("bottom", 2214)) // 2
        d.click(cx, cy)
        time.sleep(5)
        print(f"    已点击确认支付并呼叫 (坐标: {cx},{cy})")
    else:
        print("    未检测到支付确认页（可能直接下单了）")
        time.sleep(2)

    # WebView 支付页面 — 点击 Pay Now
    print("[下单-8] 检测 WebView 支付页面...")
    pay_now_btn = d(descriptionContains="Pay now")
    pay_now_btn.wait(timeout=15)
    if pay_now_btn.exists:
        print("    检测到 Pay Now 按钮，点击支付...")
        pay_now_btn.click()
        time.sleep(5)
        print("    已点击 Pay Now")

        # 支付成功后点击 Done
        print("[下单-9] 检测支付结果页...")
        done_btn = d(descriptionContains="Done")
        done_btn.wait(timeout=15)
        if done_btn.exists:
            print("    支付成功！点击 Done 返回...")
            done_btn.click()
            time.sleep(3)
        else:
            print("    [WARN] 未找到 Done 按钮，尝试等待...")
            time.sleep(5)

        # 切回乘客端 App
        current = d.app_current()
        if current.get("package") != APP_PACKAGE:
            print("    切回乘客端 App...")
            d.shell("am force-stop com.iap.linker_portal")
            time.sleep(1)
            d.shell(f"monkey -p {APP_PACKAGE} -c android.intent.category.LAUNCHER 1")
            time.sleep(5)
    else:
        print("    未检测到 WebView 支付页面（可能无需 WebView 支付）")
        time.sleep(2)

    # 验证下单+支付结果
    print("[下单-10] 验证下单+支付结果...")
    xml = d.dump_hierarchy()
    order_placed = any(kw in xml for kw in [
        "等待", "尋找", "司機", "已下單", "訂單",
        "付款處理", "處理中", "支付",
        "付款", "下單成功", "正在",
        "Payment Successful", "查詢結果",
    ])
    if order_placed:
        print("    下单成功！已进入支付/等待接单流程")
    else:
        print("    [WARN] 未明确检测到下单成功页面，请检查")
        texts = re.findall(r'text="([^"]*)"', xml)
        print("    当前页面文字:", [t for t in texts if t][:15])

    return order_placed


# ──────────────────────── 主流程 ────────────────────────

def main():
    print("=" * 60)
    print("  香港乘客端 — 完整流程：打开App → 登录 → 下单")
    print("=" * 60)

    # 连接设备
    print("[1] 连接设备...")
    d = u2.connect()
    print(f"    设备信息: {d.info}")

    # 登录
    print("\n========== 阶段一：登录 ==========")
    login_ok = do_login(d)
    if not login_ok:
        print("\n登录失败，流程终止。")
        return False
    print("\n登录阶段完成。")

    # 下单
    print("\n========== 阶段二：下单 ==========")
    order_ok = do_order(d)

    print("\n" + "=" * 60)
    print(f"  流程结束 — 登录: {'成功' if login_ok else '失败'}, 下单: {'成功' if order_ok else '失败'}")
    print("=" * 60)
    return order_ok


if __name__ == "__main__":
    success = main()
    if success:
        print(f"\n当前 Token: {get_token()[:50]}...")
    print("\n结果:", "成功" if success else "失败")
