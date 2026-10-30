#!/bin/bash
# ==============================================================================
# 港版 iOS 乘客端 UI 自动化测试启动脚本
# ==============================================================================
# 功能：
#   1. 检查依赖工具（xcrun/xcodebuild/iproxy/curl）
#   2. 从 YAML 配置读取设备 UDID 和 WDA 地址
#   3. 检测 WDA 是否已就绪，未就绪则自动启动 iproxy + xcodebuild
#   4. 执行 pytest 测试并输出 HTML 报告路径
#
# 用法：
#   ./JRYG_run_hk_ios.sh                    # 执行全部测试
#   ./JRYG_run_hk_ios.sh --collect-only     # 仅收集用例不执行
#   ./JRYG_run_hk_ios.sh -k meter_cash      # 按关键词筛选执行
# ==============================================================================
set -u  # 引用未定义变量时报错

# 确定脚本所在目录并 cd 进去
BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$BASE_DIR" || exit 1

# 选择 Python 解释器：优先使用 .venv 虚拟环境，其次项目根 .venv，最后回退系统 python3
if [ -x "$BASE_DIR/.venv/bin/python3" ]; then
    PYTHON="$BASE_DIR/.venv/bin/python3"
elif [ -x "$BASE_DIR/../.venv/bin/python3" ]; then
    PYTHON="$BASE_DIR/../.venv/bin/python3"
else
    PYTHON="python3"
fi

# --collect-only/--co/--help/-h 参数直接透传，跳过环境检查
for arg in "$@"; do
    case "$arg" in
        --collect-only|--co|--help|-h)
            exec "$PYTHON" "$BASE_DIR/JRYG_run_main_ios.py" "$@"
            ;;
    esac
done

# 检查依赖工具是否已安装
echo "JRYG 港版 iOS UI 自动化 -ios"
for tool in xcrun xcodebuild iproxy curl; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        echo "[错误] 缺少工具: $tool"
        exit 1
    fi
done

# 从 YAML 配置读取设备 UDID 和 WDA 地址
DEVICE_UDID=$("$PYTHON" -c 'from jryg_hk_ios.JRYG_config import SETTINGS; print(SETTINGS["device"]["udid"])') || exit 1
WDA_URL=$("$PYTHON" -c 'from jryg_hk_ios.JRYG_config import SETTINGS; print(SETTINGS["device"]["wda_url"])') || exit 1

# 验证设备已连接
xcrun devicectl device info details -d "$DEVICE_UDID" --timeout 20 >/dev/null || exit 1

# 创建日志目录
mkdir -p "$BASE_DIR/logs"

# 进程 PID 占位，用于退出时清理
IPROXY_PID=""
XCODE_PID=""

# 清理函数：退出时终止 iproxy 和 xcodebuild 子进程
cleanup() {
    if [ -n "$XCODE_PID" ]; then kill "$XCODE_PID" 2>/dev/null || true; fi
    if [ -n "$IPROXY_PID" ]; then kill "$IPROXY_PID" 2>/dev/null || true; fi
}
# 注册退出、Ctrl+C、kill 信号的处理函数
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# 检测 WDA 是否已就绪（返回 /status 包含 "WebDriverAgent is ready"）
wda_ready() {
    curl -fsS --max-time 3 "$WDA_URL/status" 2>/dev/null | grep -q 'WebDriverAgent is ready'
}

# WDA 未就绪时自动启动
if ! wda_ready; then
    # 非 localhost 地址无法自动启动，直接报错
    if [ "$WDA_URL" != "http://127.0.0.1:8100" ]; then
        echo "[错误] 指定的 WDA 地址不可用: $WDA_URL"
        exit 1
    fi
    # 检查 8100 端口是否已被监听，未监听则启动 iproxy 转发
    if ! lsof -nP -iTCP:8100 -sTCP:LISTEN >/dev/null 2>&1; then
        iproxy -u "$DEVICE_UDID" 8100 8100 >"$BASE_DIR/logs/iproxy-ios.log" 2>&1 &
        IPROXY_PID=$!
        sleep 2
    fi
    # iproxy 就绪后再次检查 WDA，仍未就绪则通过 xcodebuild 编译启动
    if ! wda_ready; then
        xcodebuild test \
            -project "$BASE_DIR/iOS-Tagent/WebDriverAgent.xcodeproj" \
            -scheme WebDriverAgentRunner \
            -derivedDataPath "$BASE_DIR/iOS-Tagent/DerivedData-ios" \
            -destination "id=$DEVICE_UDID" \
            >"$BASE_DIR/logs/wda-ios.log" 2>&1 &
        XCODE_PID=$!
        # 轮询等待 WDA 就绪（最多 90 次 × 2 秒 = 180 秒）
        for ((i=0; i<90; i++)); do
            if wda_ready; then break; fi
            if ! kill -0 "$XCODE_PID" 2>/dev/null; then break; fi
            if ((i % 10 == 0)); then
                echo "[准备设备] WDA 启动中，探测 $((i+1))/90；详情: $BASE_DIR/logs/wda-ios.log"
            fi
            sleep 2
        done
    fi
fi

# 最终确认 WDA 已就绪
if ! wda_ready; then
    echo "[错误] WDA 未就绪，请检查 logs/wda-ios.log、签名和设备信任状态。"
    exit 1
fi

# 执行 pytest 测试
"$PYTHON" "$BASE_DIR/JRYG_run_main_ios.py" "$@"
exit_code=$?

# 输出 HTML 报告路径
if [ -f "$BASE_DIR/report/JRYG_test_report_hk_ios.html" ]; then
    echo "[报告] file://$BASE_DIR/report/JRYG_test_report_hk_ios.html"
fi
exit "$exit_code"
