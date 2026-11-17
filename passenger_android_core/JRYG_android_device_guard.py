"""Android 设备熄屏检测与唤醒；Mac 锁屏检测与防休眠。

不管执行到哪个阶段，如果设备熄屏，需要唤醒后继续执行，不能直接判断为错误。
Android 端已有 JRYG_device_guard.py 通过 WDA /wda/locked 检测和 /wda/unlock 唤醒；
Android 端通过 ADB 检测屏幕状态（mScreenOn / mAwake）并发送 KEYCODE_POWER 唤醒。

Mac 电脑熄屏通过 caffeinate 防休眠 + ioreg 检测锁屏状态；
锁屏时不中断测试，等待解锁后继续，不输入电脑密码。
"""

import logging
import shutil
import subprocess
import time

LOG = logging.getLogger("JRYG_HK_android")


class DeviceUnlockError(RuntimeError):
    """设备锁屏唤醒失败，不应直接判断为测试错误，需手动解锁后继续。"""
    pass


# Android 可恢复的 App 包名
RESUMABLE_PACKAGES = {
    "com.sunlightmobility.client",
    "com.sunlightmobility.driver",
}


def _adb_shell(udid, *args, timeout=10):
    """执行 adb shell 命令，返回 stdout 文本；失败抛异常。"""
    cmd = ["adb", "-s", udid, "shell", *args]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=True
        )
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        raise DeviceUnlockError(f"ADB 命令超时：{' '.join(args)}")
    except subprocess.CalledProcessError as exc:
        raise DeviceUnlockError(
            f"ADB 命令失败：{' '.join(args)}，退出码={exc.returncode}，"
            f"stderr={exc.stderr.strip()[:200]}"
        )
    except FileNotFoundError:
        raise DeviceUnlockError("未检测到 adb，请配置 Android SDK")


def _adb_device_connected(udid):
    """检测 ADB 设备是否已连接且已授权，不抛异常。"""
    if not shutil.which("adb"):
        return False
    try:
        result = subprocess.run(
            ["adb", "devices"], capture_output=True, text=True, timeout=10, check=True
        )
        devices = dict(
            line.split()[:2]
            for line in result.stdout.splitlines()[1:]
            if len(line.split()) >= 2
        )
        return devices.get(udid) == "device"
    except Exception:
        return False


def is_screen_on(udid):
    """检测 Android 设备屏幕是否点亮。

    通过 dumpsys power 读取 mScreenOn 值：
    - mScreenOn=true → 屏幕点亮
    - mScreenOn=false → 屏幕熄灭

    设备未连接时不阻断测试，返回 True 让后续设备连接步骤报更准确的错误。

    :param udid: Android 设备 UDID
    :return: True 表示屏幕点亮或设备未连接，False 表示熄屏
    """
    # 设备未连接时不阻断，让后续 ensure_device 报准确错误
    if not _adb_device_connected(udid):
        LOG.warning("[熄屏检查] 设备 %s 未连接，跳过熄屏检测", udid)
        return True
    output = _adb_shell(udid, "dumpsys", "power", timeout=10)
    for line in output.splitlines():
        line = line.strip()
        if "mScreenOn=" in line:
            # 提取 mScreenOn=true 或 mScreenOn=false
            for part in line.split():
                if part.startswith("mScreenOn="):
                    value = part.split("=", 1)[1].strip()
                    return value.lower() == "true"
    # 降级方案：检查 mAwake
    for line in output.splitlines():
        line = line.strip()
        if "mAwake=" in line:
            for part in line.split():
                if part.startswith("mAwake="):
                    value = part.split("=", 1)[1].strip()
                    return value.lower() == "true"
    # 无法确定屏幕状态，假设已亮（不阻断测试）
    LOG.warning("[熄屏检查] 无法从 dumpsys power 确定屏幕状态，假设已点亮")
    return True


def wake_screen(udid):
    """唤醒 Android 设备屏幕：发送 KEYCODE_POWER（26）。

    如果屏幕已点亮则不重复发送；
    如果屏幕熄灭则发送一次电源键唤醒，不输入锁屏密码。
    """
    if is_screen_on(udid):
        return False
    LOG.info("[熄屏检查] Android 设备已熄屏，发送 KEYCODE_POWER 唤醒，不输入密码")
    _adb_shell(udid, "input", "keyevent", "26", timeout=5)
    time.sleep(2)
    # 唤醒后再次检查
    if is_screen_on(udid):
        LOG.info("[熄屏检查] Android 设备已唤醒，继续执行")
        return True
    # 可能需要上滑解锁（防锁屏壁纸页）
    try:
        _adb_shell(udid, "input", "swipe", "500", "1500", "500", "500", "300", timeout=5)
        time.sleep(1)
    except DeviceUnlockError:
        pass
    if is_screen_on(udid):
        LOG.info("[熄屏检查] Android 设备已唤醒（上滑后），继续执行")
        return True
    raise DeviceUnlockError(
        "Android 设备仍处于熄屏状态，可能需要锁屏密码或手动解锁。"
        "已停止，不重复下单或付款，但不直接判定为测试错误"
    )


def ensure_unlocked(udid, *, deadline=None):
    """检测 Android 设备熄屏并唤醒，不管执行到哪个阶段都唤醒后继续。

    与 Android 端 JRYG_device_guard.ensure_unlocked 接口对齐，
    供共享订单流程在关键节点调用。

    设备未连接时不阻断测试，返回 False 让后续设备连接步骤报更准确的错误。

    :param udid: Android 设备 UDID
    :param deadline: 可选，截止时间（monotonic）；默认 30 秒超时
    :return: True 表示执行了唤醒，False 表示无需唤醒或设备未连接
    :raises DeviceUnlockError: 唤醒超时或失败（设备已连接但无法唤醒）
    """
    # 设备未连接时不阻断，让后续 ensure_device 报准确错误
    if not _adb_device_connected(udid):
        LOG.warning("[熄屏检查] 设备 %s 未连接，跳过熄屏检测", udid)
        return False

    if deadline is None:
        deadline = time.monotonic() + 30
    deadline = min(deadline, time.monotonic() + 30)

    if is_screen_on(udid):
        return False

    while time.monotonic() < deadline:
        try:
            return wake_screen(udid)
        except DeviceUnlockError:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise
            LOG.info(
                "[熄屏检查] 唤醒未确认，剩余 %.0f 秒，等待后重试", remaining
            )
            time.sleep(min(2, max(0, deadline - time.monotonic())))

    raise DeviceUnlockError(
        "Android 设备锁屏唤醒超时（30秒），可能需要锁屏密码或手动解锁。"
        "请手动解锁后重试，不应直接判定为测试错误"
    )


def resume_app(udid, package):
    """唤醒后恢复指定 App 到前台。

    :param udid: Android 设备 UDID
    :param package: 要恢复的 App 包名
    """
    if package not in RESUMABLE_PACKAGES:
        raise DeviceUnlockError(
            f"恢复 App 不在允许范围内：{package}，停止操作"
        )
    try:
        _adb_shell(udid, "am", "start", "-n", f"{package}/", timeout=5)
    except DeviceUnlockError:
        # am start 可能因没有指定 Activity 而失败，降级用 monkey 启动
        try:
            _adb_shell(udid, "monkey", "-p", package, "-c",
                       "android.intent.category.LAUNCHER", "1", timeout=5)
        except DeviceUnlockError:
            LOG.warning("[熄屏检查] 恢复 App 前台失败，继续执行")


# ==================== Mac 电脑熄屏保护 ====================

def mac_is_locked():
    """检测 Mac 电脑是否锁屏。

    通过 ioreg 读取 IOConsoleLocked 字段。
    :return: True 表示已锁屏，False 表示未锁屏，None 表示无法确认
    """
    if not _is_macos():
        return None
    try:
        result = subprocess.run(
            ["/usr/sbin/ioreg", "-n", "Root", "-d", "1", "-a"],
            capture_output=True, check=True, timeout=5,
        )
        import plistlib
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


def _is_macos():
    """检测当前操作系统是否为 macOS。"""
    import sys
    return sys.platform == "darwin"


# Mac 防休眠进程引用
_mac_caffeinate_hold = None


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
        _mac_caffeinate_hold = subprocess.Popen(
            ["/usr/bin/caffeinate", "-i", "-s", "-w", str(_get_pid())]
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


def _get_pid():
    """获取当前进程 PID。"""
    import os
    return os.getpid()


def ensure_mac_awake():
    """检测 Mac 锁屏状态并尝试唤醒，不输入电脑密码。

    如果 Mac 已锁屏，不中断测试，使用 caffeinate -u 尝试点亮显示器，
    等待用户解锁后继续。如果未锁屏则启动防休眠保护。

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
