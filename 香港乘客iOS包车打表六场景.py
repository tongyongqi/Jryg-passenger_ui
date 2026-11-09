#!/usr/bin/env python3
"""香港iOS包车与打表六场景入口；默认执行真实订单和支付。

传入--collect-only只收集用例，不准备设备或执行订单。
"""

import os
from pathlib import Path
import sys
from typing import Optional, Sequence


def main(argv: Optional[Sequence[str]] = None) -> int:
    project = Path(__file__).resolve().parent
    python = project / ".venv/bin/python"
    runner = project / "runners/JRYG_run_hk_ios.sh"
    if sys.platform != "darwin":
        print("错误：iOS真机自动化需要在macOS上运行。", file=sys.stderr)
        return 2
    if not python.is_file() or not os.access(python, os.X_OK):
        print(f"错误：未找到iOS自动化Python环境：{python}", file=sys.stderr)
        return 2
    if not runner.is_file():
        print(f"错误：未找到iOS自动化启动脚本：{runner}", file=sys.stderr)
        return 2

    args = list(sys.argv[1:] if argv is None else argv)
    print("香港乘客端iOS：包车两例 + 打表四例", flush=True)
    print("默认执行下单、司机操作及支付；失败停止，不自动重试付款。", flush=True)
    print("请连接USB并信任开发者证书；会检测锁屏并尝试解锁，密码锁无法自动通过时请手动解锁。", flush=True)
    print(f"报告目录：{project / 'report/batches'}", flush=True)
    environment = os.environ.copy()
    environment["HK_IOS_PYTHON"] = str(python)
    os.execve("/bin/bash", ["/bin/bash", str(runner), "--batch", *args], environment)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except OSError as exc:
        print(f"启动失败：{exc}", file=sys.stderr)
        raise SystemExit(2)
