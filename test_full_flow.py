"""
完整流程：乘客端下单支付 → 司机端逐状态滑动（每步切乘客端截图）→ 订单结束回乘客端查看

流程：
1. 乘客端：打开App → 登录 → 下单 → Pay Now支付
2. 司机端：接单 → 滑动"到达上车点" → 切乘客端截图 → 回司机端
3. 司机端：滑动"已接载乘客" → 切乘客端截图 → 回司机端
4. 司机端：滑动"到达目的地" → 切乘客端截图 → 回司机端
5. 司机端：输入车费 → 滑动"确认收款" → 订单完成
6. 切乘客端查看行程结束页面并截图
"""

import time
import re
import subprocess
import os
import uiautomator2 as u2

from auth_token import (
    APP_PACKAGE,
    APP_ACTIVITY,
    PHONE_NUMBER,
    VERIFY_CODE,
    set_token,
    get_token,
)

DRIVER_PACKAGE = "com.sunlightmobility.driver"
DRIVER_ACTIVITY = "com.sunlightmobility.driver/.activity.loading.YGALoadingActivity"
SCREENSHOT_DIR = "/Users/tongyongqi/AndroidStudioProjects/HK_passenger_UI/screenshots"


# ──────────────────────── 辅助函数 ────────────────────────

def wait_for_element(d, resource_id=None, text=None, text_contains=None, timeout=10):
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
    cmd = f'adb shell "run-as {APP_PACKAGE} cat shared_prefs/MC_PERSISTENT_SESSION.xml"'
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
    xml = result.stdout
    match = re.search(r'<string name="yg_new_socket_token">([^<]+)</string>', xml)
    if match:
        return match.group(1).strip()
    return None


def take_screenshot(d, name):
    """截图并保存到 screenshots 目录"""
    os.makedirs(SCREENSHOT_DIR, exist_ok=True)
    filepath = os.path.join(SCREENSHOT_DIR, f"{name}.png")
    d.screenshot(filepath)
    print(f"    [截图] 已保存: {filepath}")
    return filepath


def switch_to_passenger(d):
    """切换到乘客端"""
    d.shell(f"am start -n {APP_ACTIVITY}")
    time.sleep(5)
    current = d.app_current()
    print(f"    切换到乘客端: {current}")
    return current.get("package") == APP_PACKAGE


def switch_to_driver(d):
    """切换到司机端"""
    d.shell(f"am start -n {DRIVER_ACTIVITY}")
    time.sleep(5)
    current = d.app_current()
    print(f"    切换到司机端: {current}")
    return current.get("package") == DRIVER_PACKAGE


def slide_driver_button(d):
    """滑动司机端底部的滑动按钮"""
    arrow = d(resourceId=f"{DRIVER_PACKAGE}:id/iv_arrow")
    if not arrow.exists:
        print("    [WARN] 未找到滑动箭头 iv_arrow")
        return False
    bounds = arrow.info.get("bounds", {})
    start_x = bounds.get("left", 100) + 30
    start_y = (bounds.get("top", 2151) + bounds.get("bottom", 2293)) // 2
    end_x = d.info.get("displayWidth", 1080) - 60
    print(f"    滑动: ({start_x}, {start_y}) -> ({end_x}, {start_y})")
    d.swipe(start_x, start_y, end_x, start_y, duration=2.0)
    time.sleep(5)
    return True


def get_driver_status(d):
    """获取司机端当前状态文字"""
    tip = d(resourceId=f"{DRIVER_PACKAGE}:id/tv_next_service_tip")
    if tip.exists:
        return tip.get_text()
    return None


def dump_texts(d, package_filter=None):
    """打印当前页面的文字元素"""
    xml = d.dump_hierarchy()
    results = []
    for m in re.finditer(r'<node[^>]*text="([^"]+)"[^>]*>', xml):
        text = m.group(1).strip()
        if text and "systemui" not in text:
            if package_filter is None or package_filter in xml:
                results.append(text)
    return results


# ──────────────────────── 乘客端：登录 ────────────────────────

def do_login(d):
    """乘客端登录"""
    print("[登录-1] 启动 App...")
    d.app_stop(APP_PACKAGE)
    time.sleep(1)
    d.shell(f"am start -n {APP_ACTIVITY}")
    time.sleep(8)

    # 检查是否已登录
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
            home_tab = d(text="首頁")
            if home_tab.exists:
                home_tab.click()
                time.sleep(2)
            return True
        home_tab = d(text="首頁")
        if home_tab.exists:
            home_tab.click()
            time.sleep(1)

    # 未登录，清除数据重新登录
    print("    App 未登录，清除数据重新登录...")
    d.app_stop(APP_PACKAGE)
    time.sleep(1)
    d.shell(f"pm clear {APP_PACKAGE}")
    time.sleep(2)
    d.press("home")
    time.sleep(1)
    d.shell(f"am start -n {APP_ACTIVITY}")
    time.sleep(8)

    # 首启协议
    print("[登录-2] 检测首启协议弹窗...")
    first_agree = d(resourceId=f"{APP_PACKAGE}:id/tv_button_agree")
    first_agree.wait(timeout=15)
    if first_agree.exists:
        first_agree.click()
        time.sleep(3)
        print("    已同意首启协议")

    # App 内权限弹窗
    print("[登录-3] 检测 App 内权限请求弹窗...")
    perm_btn = d(resourceId=f"{APP_PACKAGE}:id/tv_confirm")
    perm_btn.wait(timeout=10)
    if perm_btn.exists:
        perm_btn.click()
        time.sleep(3)
        # 系统权限弹窗
        print("[登录-4] 检测系统权限弹窗...")
        sys_btn = d(resourceId="com.android.permissioncontroller:id/permission_allow_foreground_only_button")
        sys_btn.wait(timeout=10)
        if sys_btn.exists:
            sys_btn.click()
            time.sleep(3)
            print("    已授予权限")

    # 切回 App
    time.sleep(2)
    d.press("home")
    time.sleep(1)
    d.shell(f"monkey -p {APP_PACKAGE} -c android.intent.category.LAUNCHER 1")
    time.sleep(3)

    # 进入登录页
    print("[登录-5] 进入登录页...")
    mine_tab = d(text="我的")
    mine_tab.wait(timeout=10)
    if mine_tab.exists:
        mine_tab.click()
        time.sleep(2)
    login_entry = d(text="登錄/註冊")
    login_entry.wait(timeout=5)
    if login_entry.exists:
        login_entry.click()
        time.sleep(3)

    # 输入手机号
    print("[登录-6] 输入手机号...")
    phone_input = wait_for_element(d, resource_id="phone_num", timeout=15)
    if not phone_input.exists:
        print("    [ERROR] 未找到手机号输入框")
        return False
    phone_input.click()
    time.sleep(0.5)
    phone_input.clear_text()
    time.sleep(0.3)
    d.send_keys(PHONE_NUMBER)
    time.sleep(0.5)

    # 获取验证码
    print("[登录-7] 点击获取验证码...")
    agree_img = d(resourceId=f"{APP_PACKAGE}:id/agree_img")
    if agree_img.exists and agree_img.info.get("selected", False):
        agree_img.click()
        time.sleep(0.5)
    get_code_btn = wait_for_element(d, resource_id="rl_next", timeout=5)
    if not get_code_btn.exists:
        print("    [ERROR] 未找到获取验证码按钮")
        return False
    get_code_btn.click()
    time.sleep(2)

    # 协议弹窗
    print("[登录-8] 检测协议弹窗...")
    agree_btn = d(resourceId=f"{APP_PACKAGE}:id/dialog_agree")
    agree_btn.wait(timeout=5)
    if agree_btn.exists:
        agree_btn.click()
        time.sleep(3)
        print("    已同意协议")

    # 输入验证码
    print("[登录-9] 输入验证码...")
    verify_container = d(resourceId=f"{APP_PACKAGE}:id/verify_code")
    verify_container.wait(timeout=10)
    if verify_container.exists:
        verify_container.click()
        time.sleep(0.5)
        d.send_keys(VERIFY_CODE)
        time.sleep(5)

    # 验证登录
    print("[登录-10] 验证登录结果...")
    login_success = not d(text="登錄/註冊").exists
    if login_success:
        print("    登录成功！")
    token = get_token_from_device()
    if token:
        set_token(token)
        print(f"    Token 已保存: {token[:50]}...")
    return login_success


# ──────────────────────── 乘客端：下单 ────────────────────────

def do_order(d):
    """乘客端下单+支付"""
    # 确保在首页
    print("[下单-1] 回到首页...")
    for _ in range(5):
        if d(resourceId=f"{APP_PACKAGE}:id/tv_start_address").exists or \
           d(resourceId=f"{APP_PACKAGE}:id/ll_start").exists:
            break
        d.press("back")
        time.sleep(2)

    home_tab = d(text="首頁")
    home_tab.wait(timeout=10)
    if home_tab.exists:
        home_tab.click()
        time.sleep(3)

    # 进搜索页
    print("[下单-2] 进入起点搜索页...")
    for attempt in range(3):
        start_address = d(resourceId=f"{APP_PACKAGE}:id/tv_start_address")
        if start_address.exists:
            addr = start_address.get_text()
            print(f"    起点提示框: {addr}")
            start_address.click()
            time.sleep(3)
            search_input = d(resourceId=f"{APP_PACKAGE}:id/et_search")
            search_input.wait(timeout=5)
            if search_input.exists:
                break
        start_area = d(resourceId=f"{APP_PACKAGE}:id/ll_start")
        if start_area.exists:
            start_area.click()
            time.sleep(3)
            search_input = d(resourceId=f"{APP_PACKAGE}:id/et_search")
            search_input.wait(timeout=5)
            if search_input.exists:
                break
        time.sleep(1)

    search_input = d(resourceId=f"{APP_PACKAGE}:id/et_search")
    if not search_input.exists:
        print("    [ERROR] 未找到搜索输入框")
        return False

    # 输入起点
    print("[下单-3] 输入起点：铜锣湾地铁...")
    search_input.click()
    time.sleep(0.5)
    search_input.clear_text()
    time.sleep(0.3)
    d.send_keys("铜锣湾地铁")
    time.sleep(3)
    start_result = d(resourceId=f"{APP_PACKAGE}:id/tv_address_name", text="銅鑼灣(地鐵站)")
    start_result.wait(timeout=10)
    if start_result.exists:
        start_result.click()
        print("    已选择起点：銅鑼灣(地鐵站)")
    else:
        first_item = d(resourceId=f"{APP_PACKAGE}:id/tv_address_name", instance=0)
        if first_item.exists:
            first_item.click()
    time.sleep(3)

    # 输入终点
    print("[下单-4] 输入终点：香港大学...")
    dest_area = d(resourceId=f"{APP_PACKAGE}:id/rl_destination_layout")
    dest_area.wait(timeout=10)
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
    dest_result = d(resourceId=f"{APP_PACKAGE}:id/tv_address_name", text="香港大學")
    dest_result.wait(timeout=10)
    if dest_result.exists:
        dest_result.click()
        print("    已选择终点：香港大學")
    else:
        first_item = d(resourceId=f"{APP_PACKAGE}:id/tv_address_name", instance=0)
        if first_item.exists:
            first_item.click()
    time.sleep(5)

    # 确认呼叫
    print("[下单-5] 点击确认呼叫...")
    call_btn = d(resourceId=f"{APP_PACKAGE}:id/btn_call")
    call_btn.wait(timeout=10)
    call_btn.click()
    time.sleep(3)

    # 确认支付
    print("[下单-6] 确认支付并呼叫...")
    pay_btn = d(resourceId=f"{APP_PACKAGE}:id/tv_pay")
    pay_btn.wait(timeout=10)
    if pay_btn.exists:
        bounds = pay_btn.info.get("bounds", {})
        cx = (bounds.get("left", 540) + bounds.get("right", 540)) // 2
        cy = (bounds.get("top", 2214) + bounds.get("bottom", 2214)) // 2
        d.click(cx, cy)
        time.sleep(5)
        print(f"    已点击确认支付 (坐标: {cx},{cy})")

    # Pay Now
    print("[下单-7] 检测 Pay Now...")
    pay_now = d(descriptionContains="Pay now")
    pay_now.wait(timeout=15)
    if pay_now.exists:
        pay_now.click()
        time.sleep(5)
        print("    已点击 Pay Now")
        # Done
        done_btn = d(descriptionContains="Done")
        done_btn.wait(timeout=15)
        if done_btn.exists:
            done_btn.click()
            time.sleep(3)
            print("    已点击 Done，支付完成")
        # 切回乘客端
        d.shell("am force-stop com.iap.linker_portal")
        time.sleep(1)
        d.shell(f"monkey -p {APP_PACKAGE} -c android.intent.category.LAUNCHER 1")
        time.sleep(5)

    print("    下单+支付完成")
    return True


# ──────────────────────── 司机端：逐状态滑动 ────────────────────────

def driver_flow(d):
    """司机端接单后逐状态滑动，每个状态切乘客端截图"""

    # 进入司机端
    print("\n[司机-1] 启动司机端...")
    d.shell(f"am start -n {DRIVER_ACTIVITY}")
    time.sleep(8)
    print(f"    current: {d.app_current()}")

    # 进入订单详情
    print("[司机-2] 进入订单详情...")
    tv_status = d(resourceId=f"{DRIVER_PACKAGE}:id/tv_status")
    tv_status.wait(timeout=10)
    if tv_status.exists:
        tv_status.click()
        time.sleep(3)
        print(f"    current: {d.app_current()}")

    # 确认在订单详情页
    tip = d(resourceId=f"{DRIVER_PACKAGE}:id/tv_next_service_tip")
    tip.wait(timeout=10)
    if not tip.exists:
        print("    [ERROR] 未进入订单详情页")
        return False
    print(f"    当前状态: {tip.get_text()}")

    # 截图：司机端初始状态（接乘客中）
    take_screenshot(d, "01_driver_接乘客中_司机端")

    # ── 状态1: 到達上車地點 ──
    print("\n[司机-3] 滑动：到達上車地點...")
    slide_driver_button(d)
    status = get_driver_status(d)
    print(f"    滑动后状态: {status}")

    # 切乘客端截图
    print("    切换到乘客端截图...")
    switch_to_passenger(d)
    # 处理可能弹出的温馨提示
    positive_btn = d(resourceId=f"{APP_PACKAGE}:id/positive_btn")
    if positive_btn.exists:
        print("    检测到温馨提示弹窗，点击我知道了...")
        positive_btn.click()
        time.sleep(2)
    time.sleep(2)
    take_screenshot(d, "02_passenger_司机赶来回上车_乘客端")

    # 回司机端
    print("    返回司机端...")
    switch_to_driver(d)
    # 重新进入订单详情
    tv_status = d(resourceId=f"{DRIVER_PACKAGE}:id/tv_status")
    if not d(resourceId=f"{DRIVER_PACKAGE}:id/tv_next_service_tip").exists:
        if tv_status.exists:
            tv_status.click()
            time.sleep(3)

    # ── 状态2: 已接載乘客 ──
    print("\n[司机-4] 滑动：已接載乘客...")
    slide_driver_button(d)
    status = get_driver_status(d)
    print(f"    滑动后状态: {status}")

    # 切乘客端截图
    print("    切换到乘客端截图...")
    switch_to_passenger(d)
    time.sleep(2)
    take_screenshot(d, "03_passenger_行程进行中_乘客端")

    # 回司机端
    print("    返回司机端...")
    switch_to_driver(d)
    if not d(resourceId=f"{DRIVER_PACKAGE}:id/tv_next_service_tip").exists:
        tv_status = d(resourceId=f"{DRIVER_PACKAGE}:id/tv_status")
        if tv_status.exists:
            tv_status.click()
            time.sleep(3)

    # ── 状态3: 到達目的地 ──
    print("\n[司机-5] 滑动：到達目的地...")
    slide_driver_button(d)
    status = get_driver_status(d)
    print(f"    滑动后状态: {status}")

    # 切乘客端截图
    print("    切换到乘客端截图...")
    switch_to_passenger(d)
    time.sleep(2)
    take_screenshot(d, "04_passenger_到达目的地_乘客端")

    # 回司机端
    print("    返回司机端...")
    switch_to_driver(d)
    if not d(resourceId=f"{DRIVER_PACKAGE}:id/tv_next_service_tip").exists:
        tv_status = d(resourceId=f"{DRIVER_PACKAGE}:id/tv_status")
        if tv_status.exists:
            tv_status.click()
            time.sleep(3)

    # ── 状态4: 確認收款 ──
    print("\n[司机-6] 输入车费并滑动：確認收款...")
    # 输入车费
    fee_input = d(resourceId=f"{DRIVER_PACKAGE}:id/et_input_fee")
    fee_input.wait(timeout=5)
    if fee_input.exists:
        fee_input.click()
        time.sleep(0.5)
        fee_input.clear_text()
        time.sleep(0.3)
        d.send_keys("50")
        time.sleep(0.5)
        print("    已输入车费: 50")

    slide_driver_button(d)
    time.sleep(3)
    print(f"    滑动后 current: {d.app_current()}")

    # 截图：司机端确认收款后
    take_screenshot(d, "05_driver_确认收款完成_司机端")

    # ── 订单结束后切乘客端查看行程结束页面 ──
    print("\n[司机-7] 订单结束，切换到乘客端查看行程结束页面...")
    # 先在司机端截图（订单完成页）
    take_screenshot(d, "06_driver_订单完成_司机端")

    # 点返回首页
    back_btn = d(description="返回首页")
    back_btn.wait(timeout=10)
    if back_btn.exists:
        back_btn.click()
        time.sleep(3)

    # 切乘客端
    switch_to_passenger(d)
    time.sleep(3)

    # 检测乘客端是否显示行程结束页面
    print("    乘客端 current:", d.app_current())
    take_screenshot(d, "07_passenger_行程结束_乘客端")

    # 打印页面文字
    xml = d.dump_hierarchy()
    texts = re.findall(r'text="([^"]*)"', xml)
    passenger_texts = [t for t in texts if t.strip() and "systemui" not in t]
    print("    乘客端页面文字:", passenger_texts[:15])

    # 如果有返回首页按钮，点击
    back_home = d(description="返回首頁")
    if not back_home.exists:
        back_home = d(description="返回首页")
    if back_home.exists:
        back_home.click()
        time.sleep(3)
        print("    已点击返回首页")
        take_screenshot(d, "08_passenger_返回首页_乘客端")

    return True


# ──────────────────────── 主流程 ────────────────────────

def main():
    print("=" * 60)
    print("  完整流程：乘客下单支付 → 司机逐状态滑动(每步截图) → 行程结束")
    print("=" * 60)

    print("[1] 连接设备...")
    d = u2.connect()
    print(f"    设备: {d.info}")

    # 阶段一：乘客端登录
    print("\n========== 阶段一：乘客端登录 ==========")
    if not do_login(d):
        print("登录失败，流程终止。")
        return False

    # 阶段二：乘客端下单+支付
    print("\n========== 阶段二：乘客端下单+支付 ==========")
    if not do_order(d):
        print("下单失败，流程终止。")
        return False

    # 阶段三：司机端逐状态滑动+乘客端截图
    print("\n========== 阶段三：司机端逐状态滑动+截图 ==========")
    driver_flow(d)

    print("\n" + "=" * 60)
    print("  完整流程结束！截图已保存到 screenshots/ 目录")
    print("=" * 60)
    return True


if __name__ == "__main__":
    main()
