#!/usr/bin/env python3
"""香港安卓包车与打表六场景入口；默认执行真实订单和支付。

传入--collect-only只收集用例，不准备设备或执行订单。
"""

import os
from pathlib import Path
import sys
from typing import List, Optional, Sequence


def _runner_arguments(args: Sequence[str]) -> List[str]:
    has_case = any(arg == "--case" or arg.startswith("--case=") for arg in args)
    return [*([] if has_case else ["--batch"]), *args]


def main(argv: Optional[Sequence[str]] = None) -> int:
    project = Path(__file__).resolve().parent
    python = project / ".venv/bin/python"
    if not python.is_file() or not os.access(python, os.X_OK):
        python_alt = project / ".venv/bin/python3"
        if python_alt.is_file() and os.access(python_alt, os.X_OK):
            python = python_alt
        else:
            print(f"错误：未找到Android自动化Python环境：{python}", file=sys.stderr)
            return 2
    runner = project / "JRYG_run_hk.sh"
    if not runner.is_file():
        print(f"错误：未找到Android自动化启动脚本：{runner}", file=sys.stderr)
        return 2

    args = list(sys.argv[1:] if argv is None else argv)
    print("香港乘客端Android：包车两例 + 打表四例", flush=True)
    print("默认执行下单、司机操作及支付；失败停止，不自动重试付款。", flush=True)
    print("请连接Android设备并确保adb可用；会检测设备状态并尝试唤醒屏幕。", flush=True)
    print(f"报告目录：{project / 'report'}", flush=True)
    environment = os.environ.copy()
    environment["HK_ANDROID_PYTHON"] = str(python)
    os.execve("/bin/bash", ["/bin/bash", str(runner), *_runner_arguments(args)], environment)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except OSError as exc:
        print(f"启动失败：{exc}", file=sys.stderr)
        raise SystemExit(2)
