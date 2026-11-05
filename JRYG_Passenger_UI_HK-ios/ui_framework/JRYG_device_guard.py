"""iOS锁屏检测与单次解锁；不输入锁屏密码，不重放订单或支付操作。"""

import argparse
import logging
import time

import wda


LOG = logging.getLogger("JRYG_HK_ios")


class DeviceUnlockError(RuntimeError):
    pass


RESUMABLE_APPS = {"com.sunlightmobility.client", "com.sunlightmobility.driver", "com.apple.mobilesafari"}


def remember_foreground(client, root):
    application = next((node for node in root.iter() if node.tag == "XCUIElementTypeApplication"), None)
    if application is not None and application.get("bundleId") in RESUMABLE_APPS:
        client.__dict__["_hk_last_foreground"] = application.get("bundleId")
    else:
        client.__dict__.pop("_hk_last_foreground", None)


def ensure_unlocked(client, *, deadline=None, resume_bundle=None):
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
