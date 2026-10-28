#!/bin/bash
# ==============================================================================
# JRYG 阳光出行 UI 自动化测试一键执行脚本（安卓版）
# ==============================================================================

BASE_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$BASE_DIR" || exit 1

echo "=================================================================="
echo "          JRYG 大陆 Android UI 自动化测试一键运行..."
echo "=================================================================="

if ! command -v python3 &> /dev/null; then
    echo "[错误] 未检测到 python3"
    exit 1
fi

if ! command -v adb &> /dev/null; then
    echo "[警告] 未检测到 adb，请确保已配置 Android SDK 路径"
else
    device_status=$(adb devices | grep -v "List" | grep "device")
    if [ -z "$device_status" ]; then
        echo "[警告] 未检测到已连接的安卓真机，请检查 USB 调试状态"
    else
        echo "[OK] 安卓设备已在线"
    fi
fi

if [ -x "$BASE_DIR/.venv/bin/python3" ]; then
    .venv/bin/python3 JRYG_Passenger_UI-android/JRYG_run_main.py "$@"
else
    python3 JRYG_Passenger_UI-android/JRYG_run_main.py "$@"
fi
exit_code=$?

if [ -f "$BASE_DIR/JRYG_Passenger_UI-android/report/JRYG_test_report.html" ]; then
    echo "[报告] file://$BASE_DIR/JRYG_Passenger_UI-android/report/JRYG_test_report.html"
fi
exit "$exit_code"
