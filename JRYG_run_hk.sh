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

# 2. 检查 WDA 服务在线情况（针对 iOS 端默认开启，避免盲目运行）
echo "检测本地 WDA 转发通道 (localhost:8100/status) 是否就绪..."
status_code=$(curl -o /dev/null -s -w "%{http_code}" http://localhost:8100/status)

if [ "$status_code" != "200" ]; then
    echo "[警告] WDA 物理转发服务未就绪 (HTTP 响应状态码: $status_code)"
    echo "  >> 请确认您已在终端启动了: tidevice relay 8100 8100"
    echo "  >> 或者已启动 WDA 并使用 iproxy 转发。"
    echo "  >> 脚本仍将尝试拉起，但若物理通道断开用例将跳过。"
else
    echo "[OK] iOS 物理 WDA 连接通道已在线！"
fi

# 3. 运行自动化测试启动器
echo ""
echo "正在启动 JRYG 港版测试套件..."
if [ -f ".venv/bin/python3" ]; then
    echo "[环境] 检测到项目虚拟环境 .venv，正在使用虚拟环境中的 Python 执行测试..."
    .venv/bin/python3 JRYG_Passenger_UI-HK/JRYG_run_main.py
else
    python3 JRYG_Passenger_UI-HK/JRYG_run_main.py
fi

# 4. 打印报告生成地址
if [ -f "JRYG_Passenger_UI-HK/report/JRYG_test_report_hk.html" ]; then
    echo ""
    echo "[完成] 港版 HTML 测试报告已成功生成，路径如下："
    echo "  file://$BASE_DIR/JRYG_Passenger_UI-HK/report/JRYG_test_report_hk.html"
    echo ""
fi
