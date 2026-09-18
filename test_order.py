"""
测试用例：下单流程。

前置条件：已通过 test_login.py 完成登录（token 已保存）。

流程：
1. 确认在首页
2. 点击起点输入框，输入"铜锣湾地铁"，选择第一条搜索结果
3. 点击终点输入框，输入"香港大学"，选择第一条搜索结果
4. 进入下单确认页，点击"確認呼叫"
5. 处理支付确认页，点击"確認支付並呼叫"
6. 处理 WebView 支付页面，点击"Pay Now"
7. 支付成功后点击"Done"，切回 App
"""

import time
import re
import uiautomator2 as u2

from auth_token import APP_PACKAGE, APP_ACTIVITY, get_token


def main():
    # 检查 token 是否就绪
    try:
        token = get_token()
        print(f"[0] Token 就绪: {token[:30]}...")
    except RuntimeError as e:
        print(f"[0] [ERROR] {e}")
        return False

    # 连接设备
    print("[1] 连接设备...")
    d = u2.connect()
    print(f"    设备信息: {d.info}")

    # 确认 App 在前台
    current = d.app_current()
    if current.get("package") != APP_PACKAGE:
        print("    App 不在前台，启动 App...")
        # 先清理可能残留的支付SDK
        d.shell("am force-stop com.iap.linker_portal")
        time.sleep(1)
        d.shell(f"am start -n {APP_ACTIVITY}")
        time.sleep(10)
    else:
        time.sleep(3)

    # 等待首页加载完成（ll_start 出现）
    print("    等待首页加载...")
    home_ready = False
    for _ in range(10):
        if d(resourceId=f"{APP_PACKAGE}:id/ll_start").exists:
            home_ready = True
            break
        # 清理可能残留的页面
        if d(resourceId=f"{APP_PACKAGE}:id/ivClose").exists:
            d(resourceId=f"{APP_PACKAGE}:id/ivClose").click()
            time.sleep(2)
            continue
        if d(resourceId=f"{APP_PACKAGE}:id/btn_call").exists:
            d.press("back")
            time.sleep(2)
            continue
        if d(resourceId=f"{APP_PACKAGE}:id/et_search").exists:
            d.press("back")
            time.sleep(2)
            continue
        if d(resourceId=f"{APP_PACKAGE}:id/btnReselect").exists:
            d.press("back")
            time.sleep(1)
            continue
        time.sleep(1)

    if home_ready:
        print("    首页已加载")
    else:
        # 最后尝试：强制停止支付SDK后重启App
        print("    首页未加载，强制重启 App...")
        d.shell("am force-stop com.iap.linker_portal")
        d.app_stop(APP_PACKAGE)
        time.sleep(1)
        d.shell(f"am start -n {APP_ACTIVITY}")
        time.sleep(10)
        # 再次清理
        for _ in range(5):
            if d(resourceId=f"{APP_PACKAGE}:id/ll_start").exists:
                break
            if d(resourceId=f"{APP_PACKAGE}:id/ivClose").exists:
                d(resourceId=f"{APP_PACKAGE}:id/ivClose").click()
                time.sleep(2)
                continue
            if d(resourceId=f"{APP_PACKAGE}:id/btn_call").exists:
                d.press("back")
                time.sleep(2)
                continue
            if d(resourceId=f"{APP_PACKAGE}:id/et_search").exists:
                d.press("back")
                time.sleep(2)
                continue
            d.press("back")
            time.sleep(2)

    # 最终检查
    if not d(resourceId=f"{APP_PACKAGE}:id/ll_start").exists:
        print("    [WARN] 仍未在首页，尝试继续执行...")

    # 2. 点击首页起点区域进入起点搜索页
    print("[2] 进入起点搜索页...")
    # 如果已经在搜索页（et_search 存在），直接使用
    search_input = d(resourceId=f"{APP_PACKAGE}:id/et_search")
    if not search_input.exists:
        # 还在首页，点击起点输入区域（ll_start 是 clickable=True）
        start_area = d(resourceId=f"{APP_PACKAGE}:id/ll_start")
        start_area.wait(timeout=15)
        if start_area.exists:
            start_area.click()
            time.sleep(2)
        else:
            print("    [ERROR] 未找到首页起点输入区域")
            with open("/tmp/ui_order_debug.xml", "w") as f:
                f.write(d.dump_hierarchy())
            return False

    # 等待搜索页输入框出现
    search_input = d(resourceId=f"{APP_PACKAGE}:id/et_search")
    search_input.wait(timeout=10)
    if not search_input.exists:
        print("    [ERROR] 未找到起点搜索输入框")
        return False

    # 3. 输入起点：铜锣湾地铁
    print("[3] 输入起点：铜锣湾地铁...")
    search_input.click()
    time.sleep(0.5)
    d.send_keys("铜锣湾地铁")
    time.sleep(3)
    print("    已输入起点关键词")

    # 选择第一条搜索结果
    start_result = d(
        resourceId=f"{APP_PACKAGE}:id/tv_address_name",
        text="銅鑼灣(地鐵站)",
    )
    start_result.wait(timeout=10)
    if not start_result.exists:
        # 尝试点击列表第一条
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

    # 4. 输入终点：香港大学
    print("[4] 输入终点：香港大学...")
    # 点击终点输入区域（rl_destination_layout 是 clickable=True）
    dest_area = d(resourceId=f"{APP_PACKAGE}:id/rl_destination_layout")
    dest_area.wait(timeout=10)
    if not dest_area.exists:
        print("    [ERROR] 未找到终点输入区域")
        return False
    dest_area.click()
    time.sleep(2)

    # 在终点搜索页输入
    dest_search = d(resourceId=f"{APP_PACKAGE}:id/et_search")
    dest_search.wait(timeout=5)
    if dest_search.exists:
        dest_search.click()
        time.sleep(0.3)
        d.send_keys("香港大学")
        time.sleep(3)
        print("    已输入终点关键词")
    else:
        print("    [WARN] 终点搜索框未出现，尝试直接输入...")
        d.send_keys("香港大学")
        time.sleep(3)

    # 选择第一条搜索结果
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

    # 5. 下单确认页 — 点击"確認呼叫"
    print("[5] 点击确认呼叫...")
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

    # 5.5 支付确认页 — 点击"確認支付並呼叫"
    print("[5.5] 检测支付确认页...")
    pay_btn = d(resourceId=f"{APP_PACKAGE}:id/tv_pay")
    pay_btn.wait(timeout=10)
    if pay_btn.exists:
        print("    检测到支付确认页，点击确认支付并呼叫...")
        # tv_pay 虽然标记 clickable=True，但直接 .click() 可能不生效
        # 使用坐标点击更可靠
        bounds = pay_btn.info.get("bounds", {})
        cx = (bounds.get("left", 540) + bounds.get("right", 540)) // 2
        cy = (bounds.get("top", 2214) + bounds.get("bottom", 2214)) // 2
        d.click(cx, cy)
        time.sleep(5)
        print(f"    已点击确认支付并呼叫 (坐标: {cx},{cy})")
    else:
        print("    未检测到支付确认页（可能直接下单了）")
        time.sleep(2)

    # 6. 处理 WebView 支付页面 — 点击 "Pay Now"
    print("[6] 检测 WebView 支付页面...")
    # WebView 支付页面由 com.iap.linker_portal 渲染，元素在 content-desc 中
    pay_now_btn = d(descriptionContains="Pay Now")
    pay_now_btn.wait(timeout=15)
    if pay_now_btn.exists:
        print("    检测到 Pay Now 按钮，点击支付...")
        pay_now_btn.click()
        time.sleep(5)
        print("    已点击 Pay Now")

        # 7. 支付成功后点击 "Done"
        print("[7] 检测支付结果页...")
        done_btn = d(descriptionContains="Done")
        done_btn.wait(timeout=15)
        if done_btn.exists:
            print("    支付成功！点击 Done 返回...")
            done_btn.click()
            time.sleep(3)
        else:
            print("    [WARN] 未找到 Done 按钮，尝试等待...")
            time.sleep(5)

        # 切回乘客端 App（Done 后可能跳到支付宝主页）
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

    # 8. 验证下单+支付结果
    print("[8] 验证下单+支付结果...")
    xml = d.dump_hierarchy()
    # 检查是否进入了等待接单/支付处理页面
    # 直接在 XML 和 content-desc 中搜索关键词
    full_xml = xml + str(d.dump_hierarchy())  # 确保获取最新
    order_placed = any(kw in full_xml for kw in [
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

    print("\n[完成] 下单流程测试结束。")
    return order_placed


if __name__ == "__main__":
    success = main()
    print("\n结果:", "成功" if success else "失败")
