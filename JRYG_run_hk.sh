#!/bin/bash
# ==============================================================================
# JRYG 港版阳光出行 UI 自动化测试一键执行脚本
# ==============================================================================

# 获取脚本所在的根目录
BASE_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$BASE_DIR"

echo "=================================================================="
echo "          JRYG 港版阳光出行自动化环境状态检测中..."
echo "=================================================================="

# 1. 检查 Python 运行环境
if ! command -v python3 &> /dev/null; then
    echo "[错误] 未检测到 python3，请确保已安装 Python 环境！"
    exit 1
fi

# 2. 检查 ADB 物理设备连接
echo "检测本地 ADB 物理安卓设备是否就绪..."
adb_devices=$(adb devices | grep -v "List" | grep "device")
if [ -z "$adb_devices" ]; then
    echo "[警告] 未检测到已连接的 Android 物理设备！"
    echo "  >> 请确保安卓手机已开启『USB调试』并通过数据线连接到电脑。"
    echo "  >> 请在终端手动确认：adb devices"
else
    echo "[OK] 安卓物理设备连接成功！"
    echo "$adb_devices"
fi

# 3. 运行自动化测试启动器
# 当前 Vivo Android 15 会主动终止 UiAutomator2 instrumentation，
# 港版端到端流程改用稳定的 ADB + Airtest 通道，无需重复启动 Appium Server。
echo ""
echo "正在启动 JRYG 港版 UI 测试套件..."
if [ -x "JRYG_Passenger_UI_HK/.venv/bin/python3" ]; then
    JRYG_Passenger_UI_HK/.venv/bin/python3 JRYG_Passenger_UI_HK/JRYG_run_main.py "$@"
elif [ -f ".venv/bin/python3" ]; then
    echo "[环境] 检测到项目虚拟环境 .venv，正在使用虚拟环境中的 Python 执行测试..."
    .venv/bin/python3 JRYG_Passenger_UI_HK/JRYG_run_main.py "$@"
else
    python3 JRYG_Passenger_UI_HK/JRYG_run_main.py "$@"
fi
exit_code=$?

# 4. 打印报告生成地址
if [ -f "JRYG_Passenger_UI_HK/report/JRYG_test_report_hk.html" ]; then
    echo ""
    echo "[完成] 港版 HTML 测试报告已成功生成，路径如下："
    echo "  file://$BASE_DIR/JRYG_Passenger_UI_HK/report/JRYG_test_report_hk.html"
    echo ""
fi
exit "$exit_code"
