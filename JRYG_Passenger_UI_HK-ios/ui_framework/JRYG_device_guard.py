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


def _is_macos():
    """检测当前操作系统是否为 macOS。"""
    return sys.platform == "darwin"


def mac_is_locked():
    """检测 Mac 电脑是否锁屏。

    通过 ioreg 读取 IOConsoleLocked 字段。
    :return: True 表示已锁屏，False 表示未锁屏，None 表示无法确认
    """
    if not _is_macos():
        return None
    try:
        import plistlib
        result = subprocess.run(
            ["/usr/sbin/ioreg", "-n", "Root", "-d", "1", "-a"],
            capture_output=True, check=True, timeout=5,
        )
        value = plistlib.loads(result.stdout)
        roots = value if isinstance(value, list) else [value]
        locked = next(
            (root.get("IOConsoleLocked") for root in roots
             if isinstance(root, dict)
             and isinstance(root.get("IOConsoleLocked"), bool)),
            None,
        )
        return locked
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


def mac_prevent_sleep():
    """启动 caffeinate 防止 Mac 休眠。

    使用 -i（防系统空闲休眠）+ -s（防系统休眠）+ -w（绑定当前进程）。
    同时用 -u -t 5 点亮显示器。
    """
    global _mac_caffeinate_hold
    if not _is_macos():
        return
    try:
        # 点亮显示器
        subprocess.run(
            ["/usr/bin/caffeinate", "-u", "-t", "5"],
            check=True, timeout=8,
        )
        # 如果已有防休眠进程且仍在运行，不重复启动
        if _mac_caffeinate_hold is not None and _mac_caffeinate_hold.poll() is None:
            return
        # 启动防休眠进程，绑定当前进程
        import os
        _mac_caffeinate_hold = subprocess.Popen(
            ["/usr/bin/caffeinate", "-i", "-s", "-w", str(os.getpid())]
        )
        LOG.info("[Mac 防休眠] 已启动 caffeinate 防休眠进程")
    except Exception as exc:
        LOG.warning("[Mac 防休眠] 启动失败（%s），继续执行", type(exc).__name__)


def mac_stop_prevent_sleep():
    """停止 Mac 防休眠进程。"""
    global _mac_caffeinate_hold
    if _mac_caffeinate_hold is not None and _mac_caffeinate_hold.poll() is None:
        try:
            _mac_caffeinate_hold.terminate()
            _mac_caffeinate_hold.wait(timeout=5)
        except Exception:
            try:
                _mac_caffeinate_hold.kill()
                _mac_caffeinate_hold.wait(timeout=5)
            except Exception:
                pass
    _mac_caffeinate_hold = None


def ensure_mac_awake():
    """检测 Mac 锁屏状态并尝试唤醒，不输入电脑密码。

    不管执行到哪个阶段，如果 Mac 熄屏，尝试点亮显示器后继续，不中断测试。
    如果 Mac 已锁屏，使用 caffeinate -u 尝试点亮显示器，等待用户解锁后继续。

    :return: True 表示 Mac 可用，False 表示锁屏中等待
    """
    if not _is_macos():
        return True

    locked = mac_is_locked()
    if locked is False:
        # 未锁屏，启动防休眠
        mac_prevent_sleep()
        return True

    if locked is True:
        LOG.warning(
            "[Mac 锁屏检测] Mac 已锁屏，尝试点亮显示器，不输入电脑密码；"
            "等待解锁后继续，不中断测试"
        )
        try:
            subprocess.run(
                ["/usr/bin/caffeinate", "-u", "-t", "5"],
                check=True, timeout=8,
            )
        except Exception:
            pass
        # 再次检查
        time.sleep(2)
        locked = mac_is_locked()
        if locked is False:
            mac_prevent_sleep()
            LOG.info("[Mac 锁屏检测] Mac 已解锁，继续执行")
            return True
        LOG.warning(
            "[Mac 锁屏检测] Mac 仍处于锁屏状态，请手动解锁；"
            "测试将等待，不直接判定为错误"
        )
        return False

    # 无法确认锁屏状态，启动防休眠后继续
    mac_prevent_sleep()
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
    # 不管执行到哪个阶段，先检测 Mac 熄屏并唤醒
    if check_mac:
        ensure_mac_awake()

    deadline = min(deadline, time.monotonic() + 15) if deadline is not None else time.monotonic() + 15
    resume_bundle = resume_bundle or client.__dict__.get("_hk_last_foreground")
    if resume_bundle is not None and resume_bundle not in RESUMABLE_APPS:
        raise DeviceUnlockError("解锁恢复App不在香港UI自动化允许范围内，停止操作")

    def request(method, endpoint, maximum, data=None):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise DeviceUnlockError("锁屏检查或解锁等待超时，请手动解锁iPhone后继续；未重做订单或付款")
        try:
            args = (endpoint,) if data is None else (endpoint, data)
            return getattr(client.http, method)(*args, timeout=min(maximum, remaining)).value
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
                request("post", "/wda/apps/activate", 3, {"bundleId": resume_bundle})
            LOG.info("[锁屏检查] 已确认iPhone解锁，继续读取当前状态，不重跑下单或付款")
            return True
        time.sleep(min(0.5, max(0, deadline - time.monotonic())))
    raise DeviceUnlockError(
        "iPhone仍处于锁屏状态，可能需要锁屏密码或Face ID；请手动解锁。"
        "WDA不能代替密码验证，已停止，不重复下单或付款"
    )


def main():
    parser = argparse.ArgumentParser(description="仅检测iPhone锁屏并尝试一次解锁，不执行订单")
    parser.add_argument("--wda-url", required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        ensure_unlocked(wda.Client(args.wda_url))
    except DeviceUnlockError as exc:
        LOG.error("[锁屏检查] %s", exc)
        return 1
    LOG.info("[锁屏检查] iPhone已解锁，可以执行UI自动化")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
