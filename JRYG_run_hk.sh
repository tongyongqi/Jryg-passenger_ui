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

# 2.5 检查并自动启动 Appium Server
echo "检测本地 Appium Server (localhost:4723) 是否已启动..."
nc -z 127.0.0.1 4723 &>/dev/null
appium_running=$?

if [ $appium_running -ne 0 ]; then
    echo "[提示] 未检测到运行中的 Appium Server，正在尝试在后台自动拉起..."
    if command -v appium &> /dev/null; then
        mkdir -p JRYG_Passenger_UI_HK/logs
        nohup appium > JRYG_Passenger_UI_HK/logs/appium_server.log 2>&1 &
        
        # 轮询检测 Appium 端口是否成功启动（最多等待 8 秒）
        for i in {1..8}; do
            sleep 1
            nc -z 127.0.0.1 4723 &>/dev/null
            if [ $? -eq 0 ]; then
                echo "[OK] Appium Server 已成功在后台拉起并就绪！"
                appium_running=0
                break
            fi
        done
        if [ $appium_running -ne 0 ]; then
            echo "[错误] 自动拉起 Appium Server 失败，请检查端口 4723 是否被占用，或在终端手动运行 'appium' 启动。"
            exit 1
        fi
    else
        echo "[错误] 未检测到 'appium' 命令，请确保已全局安装 Appium：npm install -g appium"
        exit 1
    fi
else
    echo "[OK] Appium Server 已在线！"
fi

# 3. 运行自动化测试启动器
echo ""
echo "正在启动 JRYG 港版测试套件..."
if [ -f ".venv/bin/python3" ]; then
    echo "[环境] 检测到项目虚拟环境 .venv，正在使用虚拟环境中的 Python 执行测试..."
    .venv/bin/python3 JRYG_Passenger_UI_HK/JRYG_run_main.py
else
    python3 JRYG_Passenger_UI_HK/JRYG_run_main.py
fi

# 4. 打印报告生成地址
if [ -f "JRYG_Passenger_UI_HK/report/JRYG_test_report_hk.html" ]; then
    echo ""
    echo "[完成] 港版 HTML 测试报告已成功生成，路径如下："
    echo "  file://$BASE_DIR/JRYG_Passenger_UI_HK/report/JRYG_test_report_hk.html"
    echo ""
fi
