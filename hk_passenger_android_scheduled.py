#!/usr/bin/env python3
"""定时任务入口：执行香港乘客端Android六场景自动化，完成后发送钉钉通知。

使用方式：
  直接运行：.venv/bin/python hk_passenger_android_scheduled.py
  定时调度：通过 macOS launchd 或 crontab 定时调用本脚本

环境变量（可选）：
  DINGTALK_WEBHOOK       钉钉机器人 Webhook URL
  DINGTALK_SECRET        钉钉加签密钥
  DINGTALK_AT_MOBILES    需要 @ 的手机号（逗号分隔）

退出码：
  0  全部场景通过
  1  存在失败
  2  环境错误（未找到 Python 或启动脚本）
"""

import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime


def main() -> int:
    project = Path(__file__).resolve().parent
    python = project / ".venv/bin/python3"
    if not python.is_file() or not os.access(python, os.X_OK):
        python_alt = project / ".venv/bin/python"
        if python_alt.is_file() and os.access(python_alt, os.X_OK):
            python = python_alt
        else:
            print(f"错误：未找到 Python 环境：{python}", file=sys.stderr)
            return 2

    entry = project / "hk_passenger_android_six_scenarios.py"
    if not entry.is_file():
        print(f"错误：未找到六场景入口：{entry}", file=sys.stderr)
        return 2

    # 记录开始时间
    started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[定时任务] 六场景自动化开始：{started_at}", flush=True)

    # 确保报告目录存在，找到最新的 batch_result.json
    report_dir = project / "report"
    batches_dir = report_dir / "batches"

    # 记录运行前的最新 batch 目录，运行后找到新的
    existing_batches = set()
    if batches_dir.is_dir():
        existing_batches = {d.name for d in batches_dir.iterdir() if d.is_dir()}

    # 执行六场景
    env = os.environ.copy()
    env["HK_ANDROID_PYTHON"] = str(python)
    exit_code = subprocess.call(
        [str(python), str(entry)],
        cwd=str(project),
        env=env,
    )

    finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[定时任务] 六场景自动化结束：{finished_at}，退出码={exit_code}", flush=True)

    # 查找本次运行产生的 batch_result.json
    batch_result_path = None
    if batches_dir.is_dir():
        new_batches = [d for d in batches_dir.iterdir()
                       if d.is_dir() and d.name not in existing_batches]
        if new_batches:
            latest_batch = max(new_batches, key=lambda d: d.name)
            result_file = latest_batch / "batch_result.json"
            if result_file.is_file():
                batch_result_path = str(result_file)

    # 发送钉钉通知
    if batch_result_path:
        print(f"[定时任务] 批量结果：{batch_result_path}", flush=True)
        try:
            sys.path.insert(0, str(project))
            from passenger_android_core.JRYG_dingtalk_notify import send_batch_result
            send_batch_result(batch_result_path)
        except Exception as exc:
            print(f"[定时任务] 钉钉通知发送失败：{exc}", file=sys.stderr)
    else:
        # 没有批量结果文件（可能是 collect-only 或环境错误），发送纯文本通知
        print("[定时任务] 未找到批量结果文件，发送纯文本通知", flush=True)
        try:
            sys.path.insert(0, str(project))
            from passenger_android_core.JRYG_dingtalk_notify import send_text
            send_text(
                f"香港乘客端Android六场景自动化\n"
                f"开始：{started_at}\n"
                f"结束：{finished_at}\n"
                f"退出码：{exit_code}\n"
                f"未找到批量结果文件"
            )
        except Exception as exc:
            print(f"[定时任务] 钉钉通知发送失败：{exc}", file=sys.stderr)

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
