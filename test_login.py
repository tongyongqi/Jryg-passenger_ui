"""
测试用例：打开香港乘客端 App，输入手机号登录。

流程：
1. 清除 App 数据，打开 App
2. 处理首启协议弹窗（Loading 页），点击同意
3. 处理 App 内权限请求弹窗，点击"去授权"
4. 处理系统权限弹窗，选择"仅在使用该应用时允许"
5. 进入登录页，输入手机号 11000090
6. 点击获取验证码
7. 弹出使用者协议隐私政策，点击同意
8. 进入验证码输入页，输入固定验证码 123456
9. 登录成功，提取 token 保存到 auth_token 模块供后续用例使用
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
)


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


def main():
    # 连接设备
    print("[1] 连接设备...")
    d = u2.connect()
    print(f"    设备信息: {d.info}")

    # 2. 清除 App 数据（确保从登录页开始）并启动
    print("[2] 清除 App 数据并启动...")
    d.app_stop(APP_PACKAGE)
    time.sleep(1)
    d.shell(f"pm clear {APP_PACKAGE}")
    time.sleep(2)
    d.press("home")
    time.sleep(1)
    d.shell(f"am start -n {APP_ACTIVITY}")
    time.sleep(8)

    # 3. 处理首启协议弹窗（Loading 页的协议）
    # 清除数据后首次启动会弹出系统级协议弹窗
    print("[3] 检测首启协议弹窗...")
    first_agree_btn = d(resourceId=f"{APP_PACKAGE}:id/tv_button_agree")
    first_agree_btn.wait(timeout=15)
    if first_agree_btn.exists:
        print("    检测到首启协议弹窗，点击同意...")
        first_agree_btn.click()
        time.sleep(3)
        print("    已同意首启协议")
    else:
        print("    未检测到首启协议弹窗（可能已同意过）")

    # 4. 处理 App 内权限请求弹窗 — 点击"去授权"
    print("[3.5] 检测 App 内权限请求弹窗...")
    perm_confirm_btn = d(resourceId=f"{APP_PACKAGE}:id/tv_confirm")
    perm_confirm_btn.wait(timeout=10)
    if perm_confirm_btn.exists:
        print("    检测到权限请求弹窗，点击去授权...")
        perm_confirm_btn.click()
        time.sleep(3)

        # 5. 处理系统权限弹窗 — 点击"仅在使用该应用时允许"
        # 系统权限弹窗 package 为 com.android.permissioncontroller
        print("[3.6] 检测系统权限弹窗...")
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

    # 权限弹窗处理完成后 App 会自动回到首页
    # 如果 SafetyCenter 窗口在后台叠加，按 home 再启动 App
    time.sleep(2)
    d.press("home")
    time.sleep(1)
    d.shell(f"monkey -p {APP_PACKAGE} -c android.intent.category.LAUNCHER 1")
    time.sleep(3)

    # 4. 进入"我的"tab，点击"登錄/註冊"进入登录页
    # 清除数据后 App 默认在首页但未登录，需要手动进入登录页
    print("[3.7] 进入登录页...")
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
        # 可能已经在登录页
        if d(resourceId=f"{APP_PACKAGE}:id/phone_num").exists:
            print("    已在登录页")

    # 5. 在登录页输入手机号
    print("[4] 输入手机号...")
    phone_input = wait_for_element(d, resource_id="phone_num", timeout=15)
    if not phone_input.exists:
        print("    [ERROR] 未找到手机号输入框")
        print(f"    当前页面: {d.app_current()}")
        # dump XML 用于调试
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

    # 6. 如果协议未勾选，先取消勾选以触发协议弹窗
    agree_img = d(resourceId=f"{APP_PACKAGE}:id/agree_img")
    if agree_img.exists and agree_img.info.get("selected", False):
        # 已勾选，先取消勾选，这样点获取验证码时会弹出协议
        agree_img.click()
        time.sleep(0.5)
        print("    已取消协议勾选（用于触发协议弹窗）")
    elif agree_img.exists and not agree_img.info.get("selected", False):
        print("    协议未勾选（获取验证码时会自动弹出协议）")

    # 7. 点击获取验证码
    print("[5] 点击获取验证码...")
    get_code_btn = wait_for_element(d, resource_id="rl_next", timeout=5)
    if not get_code_btn.exists:
        print("    [ERROR] 未找到获取验证码按钮")
        return False
    get_code_btn.click()
    time.sleep(2)

    # 8. 处理使用者协议隐私政策弹窗 - 点击同意
    print("[6] 检测使用者协议隐私政策弹窗...")
    agree_btn = d(resourceId=f"{APP_PACKAGE}:id/dialog_agree")
    agree_btn.wait(timeout=5)
    if agree_btn.exists:
        print("    检测到协议弹窗，点击同意...")
        agree_btn.click()
        time.sleep(3)
        print("    已同意协议")
    else:
        # 可能协议已勾选，没有弹窗，直接在验证码页
        print("    未检测到协议弹窗（可能已同意过）")

    # 9. 验证码输入页 - 输入固定验证码 123456
    print("[7] 进入验证码输入页，输入验证码...")
    verify_title = wait_for_element(
        d, resource_id="verification_title_txt", timeout=10
    )
    if not verify_title.exists:
        # 可能当前已经在验证码页
        verify_container = d(resourceId=f"{APP_PACKAGE}:id/verify_code")
        if not verify_container.exists:
            print("    [ERROR] 未进入验证码输入页")
            print(f"    当前页面: {d.app_current()}")
            return False

    # 点击验证码区域使隐藏的 EditText 获得焦点
    verify_container = d(resourceId=f"{APP_PACKAGE}:id/verify_code")
    verify_container.click()
    time.sleep(0.5)

    # 输入6位验证码
    d.send_keys(VERIFY_CODE)
    print(f"    验证码已输入: {VERIFY_CODE}")
    time.sleep(5)

    # 10. 验证登录是否成功
    print("[8] 验证登录结果...")
    current = d.app_current()
    print(f"    当前 App: {current}")

    # 检查是否回到了首页（登录成功后不应再显示"登錄/註冊"）
    login_success = not d(text="登錄/註冊").exists
    home_indicators = [
        d(resourceId=f"{APP_PACKAGE}:id/tv_mine_name"),
        d(text="首頁"),
        d(text="我的"),
    ]
    if not login_success:
        # 检查是否有错误提示
        error_msg = d(textContains="錯誤")
        if error_msg.exists:
            print(f"    [ERROR] 登录失败，发现错误提示: {error_msg.get_text()}")
            return False
        print("    [WARN] 仍显示登录/注册，登录可能未成功")
    elif any(el.exists for el in home_indicators):
        print("    登录成功！已进入首页")
    else:
        print("    [INFO] 登录可能成功，但未检测到明确首页元素")

    # 11. 提取 token
    print("[9] 提取 token...")
    token = get_token_from_device()
    if token:
        set_token(token)
        print(f"    Token 已保存: {token[:50]}...")
    else:
        print("    [WARN] 未能从设备提取 token")

    print("\n[完成] 登录测试结束。")
    return login_success


if __name__ == "__main__":
    success = main()
    if success:
        from auth_token import get_token
        print(f"\n当前 Token: {get_token()[:50]}...")
    else:
        print("\n登录测试失败！")
