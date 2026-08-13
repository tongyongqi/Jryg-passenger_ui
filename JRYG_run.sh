#!/bin/bash
# ==============================================================================
# JRYG 阳光出行 UI 自动化测试一键执行脚本
# ==============================================================================

# 获取脚本所在的根目录
BASE_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$BASE_DIR"

echo "=================================================================="
echo "          JRYG UI 自动化测试一键运行环境检查..."
echo "=================================================================="

# 1. 检查 Python 运行环境
if ! command -v python3 &> /dev/null; then
    echo "[错误] 未检测到 python3，请确保已安装 Python 环境！"
    exit 1
fi

# 2. 检查 ADB 是否可用以及真机是否在线
if ! command -v adb &> /dev/null; then
    echo "[警告] 未检测到 adb 命令行工具，请确保已配置 Android SDK 路径！"
else
    device_status=$(adb devices | grep -v "List" | grep "device")
    if [ -z "$device_status" ]; then
        echo "[警告] 未检测到任何已连接的安卓真机/模拟器，请检查 USB 调试状态！"
    else
        echo "[OK] 安卓设备已在线，准备就绪"
    fi
fi

# 3. 运行自动化测试启动器
echo ""
echo "正在启动 JRYG 阳光出行测试套件..."
if [ -f ".venv/bin/python3" ]; then
    echo "[环境] 检测到项目虚拟环境 .venv，正在使用虚拟环境中的 Python 执行测试..."
    .venv/bin/python3 JRYG_Passenger_UI/JRYG_run_main.py
else
    python3 JRYG_Passenger_UI/JRYG_run_main.py
fi

# 4. 打印报告生成地址
if [ -f "JRYG_auto_project/report/JRYG_test_report.html" ]; then
    echo ""
    echo "[完成] HTML 测试报告已成功生成，路径如下："
    echo "  file://$BASE_DIR/JRYG_auto_project/report/JRYG_test_report.html"
    echo ""
fi
