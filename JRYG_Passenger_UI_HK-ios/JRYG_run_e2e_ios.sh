#!/bin/bash
set -u

# JRYG 港版 iOS E2E 全流程自动化测试运行脚本
# 用法: bash JRYG_run_e2e_ios.sh
#       bash JRYG_run_e2e_ios.sh --collect-only
#       bash JRYG_run_e2e_ios.sh -k test_e2e

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$BASE_DIR" || exit 1

# 定位 Python 解释器
if [ -x "$BASE_DIR/.venv/bin/python3" ]; then
    PYTHON="$BASE_DIR/.venv/bin/python3"
elif [ -x "$BASE_DIR/../.venv/bin/python3" ]; then
    PYTHON="$BASE_DIR/../.venv/bin/python3"
else
    PYTHON="python3"
fi

# collect-only / help 模式直接走 Python 入口
for arg in "$@"; do
    case "$arg" in
        --collect-only|--co|--help|-h)
            exec "$PYTHON" "$BASE_DIR/JRYG_run_e2e_ios.py" "$@"
            ;;
    esac
done

echo "=================================================="
echo "  JRYG 港版 iOS E2E 全流程自动化测试"
echo "=================================================="

# 检查必要工具
for tool in xcrun xcodebuild iproxy curl; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        echo "[错误] 缺少工具: $tool"
        exit 1
    fi
done

# 读取设备配置
DEVICE_UDID=$("$PYTHON" -c 'from jryg_hk_ios.JRYG_config import SETTINGS; print(SETTINGS["device"]["udid"])') || exit 1
WDA_URL=$("$PYTHON" -c 'from jryg_hk_ios.JRYG_config import SETTINGS; print(SETTINGS["device"]["wda_url"])') || exit 1

# 确认设备已连接
echo "[设备] UDID: $DEVICE_UDID"
xcrun devicectl device info details -d "$DEVICE_UDID" --timeout 20 >/dev/null || {
    echo "[错误] 设备未连接或不可用: $DEVICE_UDID"
    exit 1
}

mkdir -p "$BASE_DIR/logs"
IPROXY_PID=""
XCODE_PID=""

cleanup() {
    if [ -n "$XCODE_PID" ]; then kill "$XCODE_PID" 2>/dev/null || true; fi
    if [ -n "$IPROXY_PID" ]; then kill "$IPROXY_PID" 2>/dev/null || true; fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# 检查 WDA 是否就绪
wda_ready() {
    curl -fsS --max-time 3 "$WDA_URL/status" 2>/dev/null | grep -q 'WebDriverAgent is ready'
}

# 如 WDA 未就绪，自动启动 iproxy + xcodebuild
if ! wda_ready; then
    echo "[WDA] 未就绪，开始自动启动..."

    if [ "$WDA_URL" != "http://127.0.0.1:8100" ]; then
        echo "[错误] 指定的 WDA 地址不可用: $WDA_URL"
        exit 1
    fi

    # 启动 iproxy 端口转发
    if ! lsof -nP -iTCP:8100 -sTCP:LISTEN >/dev/null 2>&1; then
        echo "[iproxy] 启动端口转发 8100..."
        iproxy -u "$DEVICE_UDID" 8100 8100 >"$BASE_DIR/logs/iproxy-e2e-ios.log" 2>&1 &
        IPROXY_PID=$!
        sleep 2
    fi

    # 启动 WDA
    if ! wda_ready; then
        echo "[WDA] 启动 WebDriverAgentRunner..."
        xcodebuild test \
            -project "$BASE_DIR/iOS-Tagent/WebDriverAgent.xcodeproj" \
            -scheme WebDriverAgentRunner \
            -derivedDataPath "$BASE_DIR/iOS-Tagent/DerivedData-ios" \
            -destination "id=$DEVICE_UDID" \
            >"$BASE_DIR/logs/wda-e2e-ios.log" 2>&1 &
        XCODE_PID=$!
        for ((i=0; i<90; i++)); do
            if wda_ready; then break; fi
            if ! kill -0 "$XCODE_PID" 2>/dev/null; then break; fi
            if ((i % 10 == 0)); then
                echo "[WDA] 启动中... ($((i+1))/90) 详情: $BASE_DIR/logs/wda-e2e-ios.log"
            fi
            sleep 2
        done
    fi
fi

if ! wda_ready; then
    echo "[错误] WDA 未就绪，请检查 logs/wda-e2e-ios.log、签名和设备信任状态。"
    exit 1
fi

echo "[WDA] 就绪: $WDA_URL"
echo "--------------------------------------------------"

# 运行 E2E 测试
"$PYTHON" "$BASE_DIR/JRYG_run_e2e_ios.py" "$@"
exit_code=$?

echo "--------------------------------------------------"
if [ -f "$BASE_DIR/report/JRYG_test_report_e2e_ios.html" ]; then
    echo "[报告] file://$BASE_DIR/report/JRYG_test_report_e2e_ios.html"
fi
exit "$exit_code"
