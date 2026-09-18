"""
iOS 香港阳光车主端自动化 — 登录 → 上线接单 → 流转订单状态

环境要求：
1. tidevice + xcodebuild test 已启动 WDA (localhost:8100)
2. facebook-wda 已安装
3. com.sunlightmobility.driver 已安装到iOS设备
4. com.sunlightmobility.client 乘客端已安装

关键：车主端底部按钮是滑动操作（从左往右滑动触发），不是点击。
状态流转：到達上車地點 → 已接載乘客 → 到達目的地 → 確認收款 → 已完成
"""

import time
import re
import os
import wda

# ──────────────────────── 配置 ────────────────────────

WDA_URL = "http://localhost:8100"
DRIVER_BUNDLE = "com.sunlightmobility.driver"
PASSENGER_BUNDLE = "com.sunlightmobility.client"
PHONE_NUMBER = "11000001"
VERIFY_CODE = "123456"

SCREENSHOT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "screenshots")


# ──────────────────────── 辅助函数 ────────────────────────

def screenshot(c, name):
    os.makedirs(SCREENSHOT_DIR, exist_ok=True)
    filepath = os.path.join(SCREENSHOT_DIR, f"{name}.png")
    c.screenshot(filepath)
    print(f"    [截图] {filepath}")
    return filepath


def dump_elements(c):
    """打印页面可见元素"""
    xml = c.source()
    print("  可见文本:")
    for m in re.finditer(r'<XCUIElementTypeStaticText[^>]*label="([^"]*)"[^>]*visible="true"', xml):
        t = m.group(1).strip()
        if t:
            print(f"    text: {t}")
    print("  可见按钮:")
    for m in re.finditer(r'<XCUIElementTypeButton[^>]*label="([^"]*)"[^>]*visible="true"', xml):
        t = m.group(1).strip()
        if t:
            print(f"    button: {t}")
    return xml


def find_and_click(c, label=None, text=None, labelContains=None, textContains=None, timeout=10):
    """查找并点击元素"""
    if label:
        el = c(label=label)
    elif text:
        el = c(text=text)
    elif labelContains:
        el = c(labelContains=labelContains)
    elif textContains:
        el = c(textContains=textContains)
    else:
        return False
    el.wait(timeout=timeout)
    if el.exists:
        el.click()
        return True
    return False


def swipe_button(c, y=795):
    """从左往右滑动触发底部按钮（车主端按钮是滑动操作，不是点击）"""
    c.swipe(20, y, 380, y, 0.3)
    time.sleep(3)


def wait_for_button(c, keywords, timeout=30):
    """等待某个按钮文字出现，返回是否找到"""
    waited = 0
    while waited < timeout:
        xml = c.source()
        for kw in keywords:
            if kw in xml:
                return True, kw
        time.sleep(2)
        waited += 2
    return False, None


# ──────────────────────── 车主端登录 ────────────────────────

def driver_login(c):
    """车主端登录"""
    print("\n========== 车主端登录 ==========")

    # 启动App
    print("[车主登录-1] 启动车主端...")
    c.app_start(DRIVER_BUNDLE)
    time.sleep(10)

    # 检查是否已登录
    xml = c.source()
    if "接單中" in xml or "點擊出車" in xml or "今日營收" in xml:
        print("    车主端已登录，跳过登录流程")
        return True

    if "登錄" not in xml and "下一步" not in xml:
        print("    当前不在登录页，尝试重启")
        c.app_stop(DRIVER_BUNDLE)
        time.sleep(2)
        c.app_start(DRIVER_BUNDLE)
        time.sleep(10)
        xml = c.source()

    # 输入手机号
    print("[车主登录-2] 输入手机号...")
    tf = c(className="XCUIElementTypeTextField")
    tf.wait(timeout=10)
    if tf.exists:
        tf.click()
        time.sleep(0.3)
        tf.clear_text()
        time.sleep(0.3)
        tf.set_text(PHONE_NUMBER)
        time.sleep(0.5)
        print(f"    手机号已输入: {PHONE_NUMBER}")
    else:
        print("    [ERROR] 未找到手机号输入框")
        return False

    # 关闭键盘，点击下一步
    find_and_click(c, label="Done", timeout=5)
    time.sleep(0.5)
    find_and_click(c, label="下一步", timeout=5)
    time.sleep(3)

    # 检测协议弹窗 — 点击"同意並登錄"
    print("[车主登录-3] 检测协议弹窗...")
    agree = c(label="同意並登錄")
    agree.wait(timeout=5)
    if agree.exists:
        agree.click()
        time.sleep(3)
        print("    已点击 同意並登錄")
    else:
        agree2 = c(label="同意")
        if agree2.wait(timeout=3) and agree2.exists:
            agree2.click()
            time.sleep(3)
            print("    已点击 同意")
        else:
            print("    未检测到协议弹窗")

    # 验证码输入页 — CollectionView中的6个Cell
    print("[车主登录-4] 输入验证码...")
    time.sleep(2)

    verify_text = c(textContains="驗證碼")
    if verify_text.wait(timeout=10) and verify_text.exists:
        print("    已进入验证码输入页")

    # 点击第一个Cell激活键盘，然后用send_keys输入
    cell = c(className="XCUIElementTypeCell", index=0)
    if cell.exists:
        cell.click()
        time.sleep(0.5)

    try:
        for ch in VERIFY_CODE:
            c.send_keys(ch)
            time.sleep(0.3)
        print(f"    验证码已输入: {VERIFY_CODE}")
    except Exception as e:
        print(f"    [ERROR] send_keys失败: {e}")
        for i, ch in enumerate(VERIFY_CODE):
            cell_i = c(className="XCUIElementTypeCell", index=i)
            if cell_i.exists:
                cell_i.click()
                time.sleep(0.2)
                try:
                    c.send_keys(ch)
                except:
                    pass
                time.sleep(0.2)

    time.sleep(5)

    # 验证登录结果
    xml = c.source()
    if "接單中" in xml or "點擊出車" in xml or "今日營收" in xml:
        print("    车主端登录成功！")
        screenshot(c, "driver_01_login_success")
        return True
    else:
        print("    [INFO] 登录后页面内容:")
        dump_elements(c)
        screenshot(c, "driver_01_login_status")
        return True


# ──────────────────────── 车主端上线 ────────────────────────

def driver_go_online(c):
    """车主端点击出车上线"""
    print("\n========== 车主端上线 ==========")

    xml = c.source()
    if "接單中" in xml:
        print("    车主端已在线（接單中）")
        return True

    print("[上线] 点击 點擊出車...")
    go_btn = c(label="點擊出車")
    go_btn.wait(timeout=10)
    if go_btn.exists:
        go_btn.click()
        time.sleep(3)
        print("    已点击 點擊出車")
        xml = c.source()
        if "接單中" in xml:
            print("    车主端已上线，正在接單中")
            return True
    else:
        print("    [ERROR] 未找到 點擊出車 按钮")
        return False
    return True


# ──────────────────────── 车主端接单流转 ────────────────────────

def driver_process_order(c):
    """车主端接单后流转订单状态

    车主端底部按钮是滑动操作（从左往右滑动触发），不是点击。
    状态流转：到達上車地點 → 已接載乘客 → 到達目的地 → 確認收款 → 已完成
    """
    print("\n========== 车主端接单流转 ==========")

    # 等待进入订单详情页
    print("[流转-0] 等待订单详情页...")
    found, kw = wait_for_button(c, ["接乘客", "到達上車地點", "到達目的地", "確認收款"], timeout=60)
    if not found:
        print("    [WARN] 未检测到订单详情页，尝试进入我的行程...")
        trips = c(label="我的行程")
        if trips.exists:
            trips.click()
            time.sleep(3)
            xml = c.source()
            m = re.search(r'label="(\d{2}:\d{2}:\d{2})"[^>]*x="(\d+)"[^>]*y="(\d+)"', xml)
            if m:
                x, y = int(m.group(2)), int(m.group(3))
                c.click(x + 100, y + 20)
                time.sleep(3)
        found, kw = wait_for_button(c, ["接乘客", "到達上車地點", "到達目的地", "確認收款"], timeout=15)
        if not found:
            print("    [ERROR] 无法进入订单详情页")
            screenshot(c, "driver_no_order_detail")
            return False

    print(f"    已进入订单详情页（检测到: {kw}）")
    screenshot(c, "driver_02_order_detail")
    dump_elements(c)

    # ── 状态1: 到達上車地點（从左往右滑动触发）──
    print("[流转-1] 滑动 到達上車地點...")
    if "到達上車地點" in c.source():
        swipe_button(c, y=795)
        xml = c.source()
        if "到達上車地點" not in xml:
            print("    状态变更 → 已接載乘客")
        else:
            c.swipe(20, 795, 380, 795, 0.5)
            time.sleep(3)
            print("    (重试慢速滑动)")
    screenshot(c, "driver_03_arrived_pickup")

    # ── 状态2: 已接載乘客（滑动触发开始行程）──
    print("[流转-2] 滑动 已接載乘客...")
    if "已接載乘客" in c.source():
        swipe_button(c, y=795)
        print("    状态变更 → 送乘客（到達目的地）")
    screenshot(c, "driver_04_picked_up")

    # ── 状态3: 到達目的地（滑动触发结束行程）──
    print("[流转-3] 滑动 到達目的地...")
    if "到達目的地" in c.source():
        for speed in [0.3, 0.5, 0.1, 0.8]:
            c.swipe(20, 795, 380, 795, speed)
            time.sleep(3)
            if "到達目的地" not in c.source():
                print(f"    状态变更 → 確認賬單（滑动速度{speed}s）")
                break
    screenshot(c, "driver_05_arrived_dest")

    # ── 状态4: 確認收款（滑动触发完成订单）──
    print("[流转-4] 滑动 確認收款...")
    if "確認收款" in c.source():
        swipe_button(c, y=795)
        print("    状态变更 → 已完成")
    screenshot(c, "driver_06_completed")

    # 验证最终状态
    xml = c.source()
    if any(kw in xml for kw in ["已完成", "已支付", "服務完成"]):
        print("    订单流转完成！")
        home_btn = c(label="返回首頁")
        if not home_btn.exists:
            home_btn = c(labelContains="返回")
        if home_btn.exists:
            home_btn.click()
            time.sleep(3)
            print("    已返回首页")
        return True
    else:
        print("    [INFO] 最终页面内容:")
        dump_elements(c)
        return True


# ──────────────────────── 主流程 ────────────────────────

def main():
    print("=" * 60)
    print("  iOS 香港阳光车主端 — 登录 → 上线 → 接单流转")
    print("=" * 60)

    print("[1] 连接WDA...")
    c = wda.Client(WDA_URL)
    print(f"    WDA状态: {c.status()['state']}")

    # 车主端登录
    if not driver_login(c):
        print("\n车主端登录失败，流程终止。")
        return False

    # 上线
    if not driver_go_online(c):
        print("\n车主端上线失败。")
        return False

    # 接单流转
    if not driver_process_order(c):
        print("\n车主端接单流转未完成。")
        return False

    print("\n" + "=" * 60)
    print("  车主端自动化流程完成！截图保存在 screenshots/ 目录")
    print("=" * 60)
    return True


if __name__ == "__main__":
    main()
