"""每次任务运行前检查并重置 App 状态，确保从干净首页开始执行。

通过 WDA 检查当前前台 App：
- 非阳光出行 App（非乘客端/司机端）：关闭并回到桌面
- 阳光出行 App（乘客端/司机端）：回到首页
- 桌面（springboard）：无需操作

调试时可通过环境变量 HK_IOS_SKIP_APP_RESET=1 跳过此检查。
"""

import os
import sys
import time

import wda

PASSENGER_BUNDLE_ID = "com.sunlightmobility.client"
DRIVER_BUNDLE_ID = "com.sunlightmobility.driver"
SUNLIGHT_BUNDLE_IDS = {PASSENGER_BUNDLE_ID, DRIVER_BUNDLE_ID}
HOME_KEYWORDS = ("想去哪裡", "想去哪里", "主頁", "主页")
# 司机端首页关键词
DRIVER_HOME_KEYWORDS = ("今日營收", "今日营收", "接單中", "接单中")


def log(message):
    print(f"[App重置] {message}", flush=True)


def get_active_app(wda_client):
    """读取当前前台 App bundleId，失败返回空字符串。"""
    try:
        result = wda_client.http.get("/wda/activeAppInfo", timeout=5)
        value = result.value if hasattr(result, "value") else result
        if isinstance(value, dict):
            return value.get("bundleId") or ""
    except Exception:
        pass
    return ""


def get_visible_texts(wda_client):
    """读取当前页面所有可见文本。"""
    try:
        source = wda_client.http.get("/source?format=xml", timeout=10)
        value = source.value if hasattr(source, "value") else source
        if isinstance(value, str) and "<XCUIElementType" in value:
            import xml.etree.ElementTree as ET
            root = ET.fromstring(value)
            return [(node.get("label") or node.get("name") or node.get("value") or "").strip()
                    for node in root.iter() if node.get("visible") == "true"]
    except Exception:
        pass
    return []


def is_at_home(wda_client, bundle_id):
    """判断阳光出行 App 是否已在首页。"""
    texts = get_visible_texts(wda_client)
    if bundle_id == DRIVER_BUNDLE_ID:
        keywords = DRIVER_HOME_KEYWORDS
    else:
        keywords = HOME_KEYWORDS
    return any(any(kw in t for kw in keywords) for t in texts)


def go_home_in_app(wda_client, bundle_id):
    """在阳光出行 App 内通过连续点击返回按钮回到首页，最多尝试 8 次。"""
    app_name = "司机端" if bundle_id == DRIVER_BUNDLE_ID else "乘客端"
    if bundle_id == DRIVER_BUNDLE_ID:
        keywords = DRIVER_HOME_KEYWORDS
    else:
        keywords = HOME_KEYWORDS
    for attempt in range(8):
        texts = get_visible_texts(wda_client)
        if any(any(kw in t for kw in keywords) for t in texts):
            log(f"已回到{app_name}首页")
            return True
        # 尝试点击左上角返回箭头
        try:
            back_btn = wda_client(xpath='//XCUIElementTypeImage[contains(@name,"navi_arrow_left")]')
            if back_btn.exists:
                back_btn.click()
                time.sleep(1)
                continue
        except Exception:
            pass
        # 尝试点击导航栏返回按钮
        try:
            back_btn = wda_client(xpath='//XCUIElementTypeButton[contains(@name,"back") or contains(@name,"返回") or contains(@name,"返回")]')
            if back_btn.exists:
                back_btn.click()
                time.sleep(1)
                continue
        except Exception:
            pass
        # 没有找到返回按钮，可能已在首页或弹窗遮挡
        time.sleep(0.5)
    # 最终检查
    texts = get_visible_texts(wda_client)
    if any(any(kw in t for kw in keywords) for t in texts):
        log(f"已回到{app_name}首页")
        return True
    log(f"未能确认回到{app_name}首页，继续执行（可能已在首页但有弹窗遮挡）")
    return False


def reset_app_state(wda_url):
    """检查并重置 App 状态，确保从干净状态开始执行任务。"""
    if os.environ.get("HK_IOS_SKIP_APP_RESET", "") == "1":
        log("调试模式（HK_IOS_SKIP_APP_RESET=1），跳过 App 状态重置")
        return 0

    try:
        wda_client = wda.Client(wda_url)
    except Exception as exc:
        log(f"WDA 连接失败（{type(exc).__name__}），跳过 App 状态重置")
        return 0

    bundle_id = get_active_app(wda_client)
    log(f"当前前台 App: {bundle_id or '未知'}")

    if not bundle_id or bundle_id == "com.apple.springboard":
        log("已在桌面，无需重置")
        return 0

    if bundle_id in SUNLIGHT_BUNDLE_IDS:
        app_name = "乘客端" if bundle_id == PASSENGER_BUNDLE_ID else "司机端"
        if is_at_home(wda_client, bundle_id):
            log(f"阳光出行{app_name}已在首页，无需重置")
            return 0
        log(f"阳光出行{app_name}不在首页，尝试回到首页")
        go_home_in_app(wda_client, bundle_id)
        return 0
    else:
        log(f"非阳光出行 App（{bundle_id}），关闭并回到桌面")
        try:
            wda_client.app_activate(bundle_id)
            time.sleep(0.5)
            wda_client.home()
            time.sleep(1)
        except Exception:
            pass
        current = get_active_app(wda_client)
        if current == "com.apple.springboard" or current not in SUNLIGHT_BUNDLE_IDS:
            log("已回到桌面")
        return 0


def main():
    import argparse
    parser = argparse.ArgumentParser(description="运行任务前重置 App 状态，回到首页或桌面")
    parser.add_argument("--wda-url", required=True, help="WDA 服务地址")
    args = parser.parse_args()
    if sys.platform != "darwin":
        log("仅支持 macOS")
        return 2
    try:
        return reset_app_state(args.wda_url)
    except Exception as exc:
        log(f"App 状态重置异常（{type(exc).__name__}: {exc}），不阻断后续任务")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
