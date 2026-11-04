"""司机 UI 设备配置检查；不加载 token，不调用司机登录、接单或订单状态接口。"""

import argparse
from pathlib import Path
import sys

# 独立执行tools中的检查工具时，仍从项目根加载公共配置。
BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from ui_framework.JRYG_driver_runtime import resolve_runtime


def main(argv=None):
    """解析设备检查参数；可选只读探测WDA，失败返回2，不登录或推进订单。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-devices", action="store_true", help="只读探测 WDA /status，不启动或操作 App")
    args = parser.parse_args(argv)
    try:
        runtime = resolve_runtime()
        print("司机设备模式：", runtime.device_mode)
        print("司机 WDA：", runtime.wda_url)
        print("全 UI 顺序：司机出车 → 乘客下单 → 司机接单/滑动/账单 → 乘客支付")
        if args.check_devices:
            import requests
            from ui_framework.JRYG_config import SETTINGS
            passenger = SETTINGS["device"]["wda_url"]
            for url in dict.fromkeys((runtime.wda_url, passenger)):
                # 这里只访问自动化设备服务，不访问 App 业务接口。
                resp = requests.get(url.rstrip("/") + "/status", timeout=5)
                resp.raise_for_status()
                payload = resp.json()
                if not isinstance(payload, dict) or payload.get("status", 0) != 0 or not isinstance(payload.get("value"), dict):
                    raise RuntimeError("WDA 状态响应无效")
                print("WDA 已响应：", url)
        return 0
    except Exception as exc:
        print("设备配置未就绪：" + (str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
