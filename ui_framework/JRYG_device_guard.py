"""iOS锁屏检测与单次解锁；Mac 防休眠；不输入锁屏密码，不重放订单或支付操作。

不管执行到哪个阶段，如果设备或 Mac 熄屏，需要唤醒后继续执行，不能直接判断为错误。
"""

import argparse
import logging
import subprocess
import sys
import time

import wda


LOG = logging.getLogger("JRYG_HK_ios")


class DeviceUnlockError(RuntimeError):
    pass


RESUMABLE_APPS = {"com.sunlightmobility.client", "com.sunlightmobility.driver", "com.apple.mobilesafari"}


# ==================== Mac 防休眠 ====================

_mac_caffeinate_hold = None
_mac_display_wake = None
_mac_checked_at = float("-inf")
_mac_locked_state = None
_mac_wake_at = float("-inf")
_mac_lock_warn_at = float("-inf")


def _is_macos():
    """检测当前操作系统是否为 macOS。"""
    return sys.platform == "darwin"


def mac_is_locked():
    """检测 Mac 电脑是否锁屏。

    读取 IOConsoleLocked 或当前控制台的 CGSSessionScreenIsLocked。
    :return: True 表示已锁屏，False 表示未锁屏，None 表示无法确认
    """
    if not _is_macos():
        return None
    try:
        import plistlib
        result = subprocess.run(
            ["/usr/sbin/ioreg", "-n", "Root", "-d", "1", "-a"],
            capture_output=True, check=True, timeout=1,
        )
        value = plistlib.loads(result.stdout)
        roots = value if isinstance(value, list) else [value]
        for root in roots:
            if not isinstance(root, dict):
                continue
            locked = root.get("IOConsoleLocked")
            if isinstance(locked, bool):
                return locked
            for user in root.get("IOConsoleUsers", []):
                if (isinstance(user, dict) and user.get("kCGSSessionOnConsoleKey") is True
                        and isinstance(user.get("CGSSessionScreenIsLocked"), bool)):
                    return user["CGSSessionScreenIsLocked"]
        return None
    except Exception:
        return None


def mac_is_logged_in():
    """检测 Mac 当前用户是否已登录控制台。"""
    if not _is_macos():
        return True
    try:
        import os
        from pathlib import Path
        uid = os.getuid()
        console_uid = Path("/dev/console").stat().st_uid
        if console_uid != uid:
            return False
        result = subprocess.run(
            ["/usr/sbin/ioreg", "-n", "Root", "-d", "1", "-a"],
            capture_output=True, check=True, timeout=5,
        )
        import plistlib
        value = plistlib.loads(result.stdout)
        roots = value if isinstance(value, list) else [value]
        sessions = [
            user for root in roots if isinstance(root, dict)
            for user in root.get("IOConsoleUsers", [])
            if isinstance(user, dict)
        ]
        return any(
            user.get("kCGSSessionUserIDKey") == uid
            and user.get("kCGSSessionOnConsoleKey") is True
            and user.get("kCGSessionLoginDoneKey") is True
            for user in sessions
        )
    except Exception:
        return True


def mac_is_ac_power():
    """检测 Mac 是否接通电源。"""
    if not _is_macos():
        return True
    try:
        result = subprocess.run(
            ["/usr/bin/pmset", "-g", "batt"],
            capture_output=True, text=True, check=True, timeout=5,
        )
        return "'AC Power'" in result.stdout
    except Exception:
        return True


def mac_prevent_sleep(*, hold_pid=None):
    """异步点亮显示器并防系统/显示器休眠，绑定本次进程，不解除密码锁。"""
    global _mac_caffeinate_hold, _mac_display_wake, _mac_wake_at
    if not _is_macos():
        return
    try:
        now = time.monotonic()
        if _mac_display_wake is not None and _mac_display_wake.poll() is not None:
            _mac_display_wake.wait()
            _mac_display_wake = None
        if _mac_display_wake is None and now - _mac_wake_at >= 30:
            _mac_display_wake = subprocess.Popen(
                ["/usr/bin/caffeinate", "-u", "-t", "5"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            _mac_wake_at = now
        if _mac_caffeinate_hold is not None and _mac_caffeinate_hold.poll() is None:
            return
        if _mac_caffeinate_hold is not None:
            _mac_caffeinate_hold.wait()
        import os
        _mac_caffeinate_hold = subprocess.Popen(
            ["/usr/bin/caffeinate", "-d", "-i", "-s", "-w", str(hold_pid or os.getpid())],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        LOG.info("[Mac 自动唤醒] 已请求点亮显示器并启动防休眠，不输入电脑密码")
    except Exception as exc:
        LOG.warning("[Mac 自动唤醒] 系统请求失败（%s），未修改系统锁屏设置", type(exc).__name__)


def mac_stop_prevent_sleep():
    """仅释放本次创建的防休眠/显示器唤醒进程，并重置轮询缓存。"""
    global _mac_caffeinate_hold, _mac_display_wake, _mac_checked_at, _mac_locked_state
    global _mac_wake_at, _mac_lock_warn_at
    for process in (_mac_caffeinate_hold, _mac_display_wake):
        if process is None:
            continue
        try:
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=5)
        except Exception:
            try:
                process.kill()
                process.wait(timeout=5)
            except Exception:
                pass
    _mac_caffeinate_hold = _mac_display_wake = None
    _mac_checked_at = _mac_wake_at = _mac_lock_warn_at = float("-inf")
    _mac_locked_state = None


def ensure_mac_awake():
    """自动点亮并防休眠，不解除电脑密码锁；WDA运行无需进入Mac桌面。

    每5秒核对一次控制台锁定状态；唤醒非阻塞，不延长订单/付款等待预算。
    返回True表示已处理唤醒请求，不是密码锁已解除的凭据。
    """
    global _mac_checked_at, _mac_locked_state, _mac_lock_warn_at
    if not _is_macos():
        return True
    now = time.monotonic()
    if now - _mac_checked_at >= 5:
        previously_locked = _mac_locked_state
        _mac_locked_state = mac_is_locked()
        _mac_checked_at = now
        if previously_locked is True and _mac_locked_state is False:
            LOG.info("[Mac 锁屏检测] 控制台已解锁，自动化继续原步骤")
    mac_prevent_sleep()
    if _mac_locked_state is True and now - _mac_lock_warn_at >= 30:
        _mac_lock_warn_at = now
        LOG.warning("[Mac 自动唤醒] 已请求点亮屏幕；电脑密码锁仍需本人解锁，"
                    "WDA继续原步骤，不输入电脑密码、不重做业务操作")
    return True


def remember_foreground(client, root):
    application = next((node for node in root.iter() if node.tag == "XCUIElementTypeApplication"), None)
    if application is not None and application.get("bundleId") in RESUMABLE_APPS:
        client.__dict__["_hk_last_foreground"] = application.get("bundleId")
    else:
        client.__dict__.pop("_hk_last_foreground", None)


def ensure_unlocked(client, *, deadline=None, resume_bundle=None, check_mac=True):
    """不管执行到哪个阶段，检测 iPhone 和 Mac 熄屏并唤醒后继续。

    不输入锁屏密码，不重放订单或支付操作，不直接判定为错误。
    先检测 Mac 锁屏并尝试唤醒，再检测 iPhone 锁屏并尝试唤醒。
    check_mac=False 时跳过 Mac 检测（供单元测试使用）。
    """
    deadline = min(deadline, time.monotonic() + 15) if deadline is not None else time.monotonic() + 15
    if time.monotonic() >= deadline:
        raise DeviceUnlockError("锁屏检查或解锁等待超时，未操作设备或重做订单付款")
    if check_mac:
        ensure_mac_awake()

    resume_bundle = resume_bundle or client.__dict__.get("_hk_last_foreground")
    if resume_bundle is not None and resume_bundle not in RESUMABLE_APPS:
        raise DeviceUnlockError("解锁恢复App不在香港UI自动化允许范围内，停止操作")

    def request(method, endpoint, maximum, data=None, *, session=False):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise DeviceUnlockError("锁屏检查或解锁等待超时，请手动解锁iPhone后继续；未重做订单或付款")
        try:
            args = (endpoint,) if data is None else (endpoint, data)
            transport = client._session_http if session else client.http
            return getattr(transport, method)(*args, timeout=min(maximum, remaining)).value
        except Exception as exc:
            raise DeviceUnlockError(
                f"iPhone锁屏检测/解锁通信失败（{type(exc).__name__}）；"
                "请确认WDA可用并手动解锁，未重复解锁或业务操作"
            ) from None

    def locked():
        value = request("get", "/wda/locked", 3)
        if not isinstance(value, bool):
            raise DeviceUnlockError("WDA未返回有效锁屏状态，停止操作，不假定手机已解锁")
        return value

    if not locked():
        return False
    LOG.info("[锁屏检查] iPhone已锁屏，尝试单次唤醒并解锁，不输入锁屏密码")
    request("post", "/wda/unlock", 10)
    while time.monotonic() < deadline:
        if not locked():
            if resume_bundle is not None:
                request("post", "/wda/apps/launch", 3, {"bundleId": resume_bundle}, session=True)
                while True:
                    current = request("get", "/wda/activeAppInfo", 3)
                    bundle = current.get("bundleId") if isinstance(current, dict) else None
                    if bundle == resume_bundle:
                        break
                    if bundle != "com.apple.springboard":
                        raise DeviceUnlockError("手机已解锁但原App前台未确认，停止操作，不重做下单或付款")
                    time.sleep(min(0.5, max(0, deadline - time.monotonic())))
            LOG.info("[锁屏检查] 已确认iPhone解锁及原App恢复，继续读取当前状态，不重跑下单或付款")
            return True
        time.sleep(min(0.5, max(0, deadline - time.monotonic())))
    raise DeviceUnlockError(
        "iPhone仍处于锁屏状态，可能需要锁屏密码或Face ID；请手动解锁。"
        "WDA不能代替密码验证，已停止，不重复下单或付款"
    )


def main():
    parser = argparse.ArgumentParser(description="自动唤醒Mac/iPhone，不输入锁屏密码或执行订单")
    parser.add_argument("--wda-url")
    parser.add_argument("--mac-only", action="store_true", help="WDA启动前仅唤醒电脑")
    parser.add_argument("--hold-pid", type=int, help="绑定调用Shell的防休眠生命周期")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if args.mac_only:
        import os
        if args.hold_pid is not None and args.hold_pid != os.getppid():
            parser.error("--hold-pid仅允许绑定当前父进程")
        mac_prevent_sleep(hold_pid=args.hold_pid)
        return 0
    if not args.wda_url or args.hold_pid is not None:
        parser.error("手机唤醒需要--wda-url；--hold-pid只用于--mac-only")
    try:
        ensure_unlocked(wda.Client(args.wda_url))
    except DeviceUnlockError as exc:
        LOG.error("[锁屏检查] %s", exc)
        return 1
    LOG.info("[锁屏检查] iPhone已解锁，可以执行UI自动化")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
