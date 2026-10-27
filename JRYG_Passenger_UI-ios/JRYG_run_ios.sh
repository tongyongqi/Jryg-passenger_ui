#!/bin/bash
set -u

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$BASE_DIR" || exit 1

if [ -x "$BASE_DIR/../.venv/bin/python3" ]; then
    PYTHON="$BASE_DIR/../.venv/bin/python3"
elif [ -x "$BASE_DIR/.venv/bin/python3" ]; then
    PYTHON="$BASE_DIR/.venv/bin/python3"
else
    PYTHON="python3"
fi

for arg in "$@"; do
    case "$arg" in
        --collect-only|--co|--help|-h)
            exec "$PYTHON" "$BASE_DIR/JRYG_run_main_ios.py" "$@"
            ;;
    esac
done

echo "JRYG 大陆 iOS UI 自动化"
for tool in xcrun xcodebuild iproxy curl; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        echo "[错误] 缺少工具: $tool"
        exit 1
    fi
done

DEVICE_UDID=$("$PYTHON" -c 'from jryg_ios.JRYG_config import SETTINGS; print(SETTINGS["device"]["udid"])') || exit 1
WDA_URL=$("$PYTHON" -c 'from jryg_ios.JRYG_config import SETTINGS; print(SETTINGS["device"].get("wda_url", "http://127.0.0.1:8100"))') || exit 1

xcrun devicectl device info details -d "$DEVICE_UDID" --timeout 20 >/dev/null || {
    echo "[错误] 设备 $DEVICE_UDID 未连接"
    exit 1
}

mkdir -p "$BASE_DIR/logs"
IPROXY_PID=""
cleanup() {
    if [ -n "$IPROXY_PID" ]; then kill "$IPROXY_PID" 2>/dev/null || true; fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

wda_ready() {
    curl -fsS --max-time 3 "$WDA_URL/status" 2>/dev/null | grep -q 'WebDriverAgent is ready'
}

if ! wda_ready; then
    if [ "$WDA_URL" != "http://127.0.0.1:8100" ]; then
        echo "[错误] 指定的 WDA 地址不可用: $WDA_URL"
        exit 1
    fi
    if ! lsof -nP -iTCP:8100 -sTCP:LISTEN >/dev/null 2>&1; then
        iproxy -u "$DEVICE_UDID" 8100 8100 >"$BASE_DIR/logs/iproxy-ios.log" 2>&1 &
        IPROXY_PID=$!
        sleep 2
    fi
    if ! wda_ready; then
        echo "[警告] WDA 未就绪，请确认 WDA 已安装在设备上并启动。"
        echo "       可通过以下命令手动启动 WDA："
        echo "       xcodebuild test -project iOS-Tagent/WebDriverAgent.xcodeproj -scheme WebDriverAgentRunner -destination id=$DEVICE_UDID"
        echo "       （如 iOS-Tagent 工程不在本目录，请从港版 iOS 目录复制）"
        exit 1
    fi
fi

echo "[OK] WDA 已就绪"
"$PYTHON" "$BASE_DIR/JRYG_run_main_ios.py" "$@"
exit_code=$?
if [ -f "$BASE_DIR/report/JRYG_test_report_ios.html" ]; then
    echo "[报告] file://$BASE_DIR/report/JRYG_test_report_ios.html"
fi
exit "$exit_code"
