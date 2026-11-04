#!/bin/bash
# ==============================================================================
# 港版 iOS 乘客端 UI 自动化测试启动脚本
# ==============================================================================
# 功能：
#   1. 检查依赖工具（xcrun/xcodebuild/iproxy/curl）
#   2. 从 YAML 配置读取设备 UDID 和 WDA 地址
#   3. 检测 WDA 是否已就绪，未就绪则自动启动 iproxy + xcodebuild
#   4. 执行 pytest 测试并输出 HTML 报告路径
# 普通运行可能创建订单及提交测试支付；--collect-only仅收集，不启动设备。
# 第三方WDA工程只用于设备服务，乘客/司机订单业务由Python用例通过UI操作。
#
# 用法：
#   ./runners/JRYG_run_hk_ios.sh --batch            # 包车两例→打表四例，逐例清理后等待10秒
#   ./runners/JRYG_run_hk_ios.sh                    # 兼容单pytest会话执行全部测试
#   ./runners/JRYG_run_hk_ios.sh --collect-only     # 仅收集用例不执行
#   ./runners/JRYG_run_hk_ios.sh -k meter_cash      # 按关键词筛选执行
#   ./runners/JRYG_run_hk_ios.sh --case cases/JRYG_test_ios_charter_alipay_order.py
# cases的直接Python入口同样委托本脚本准备WDA，只执行该文件。
# ==============================================================================
set -u  # 引用未定义变量时报错

# 脚本归档在runners；资源、虚拟环境和产物始终相对项目根定位。
BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$BASE_DIR" || exit 1

# Python直接入口透传原解释器；Shell独立运行仍优先使用项目虚拟环境。
if [ -n "${HK_IOS_PYTHON:-}" ]; then
    if [ ! -x "$HK_IOS_PYTHON" ]; then
        echo "[错误] 指定的 Python 解释器不可执行: $HK_IOS_PYTHON"
        exit 1
    fi
    PYTHON="$HK_IOS_PYTHON"
elif [ -x "$BASE_DIR/.venv/bin/python3" ]; then
    PYTHON="$BASE_DIR/.venv/bin/python3"
elif [ -x "$BASE_DIR/../.venv/bin/python3" ]; then
    PYTHON="$BASE_DIR/../.venv/bin/python3"
else
    PYTHON="python3"
fi

# --collect-only/--co/--help/-h 参数直接透传，跳过环境检查
for arg in "$@"; do
    case "$arg" in
        --batch|--collect-only|--co|--help|-h)
            exec "$PYTHON" "$BASE_DIR/runners/JRYG_run_main_ios.py" "$@"
            ;;
    esac
done

# 检查依赖工具是否已安装
echo "JRYG 港版 iOS UI 自动化 -ios"
for tool in xcrun xcodebuild iproxy curl lsof; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        echo "[错误] 缺少工具: $tool"
        exit 1
    fi
done

# 从 YAML 配置读取设备 UDID 和 WDA 地址
DEVICE_UDID=$("$PYTHON" -c 'from ui_framework.JRYG_config import SETTINGS; print(SETTINGS["device"]["udid"])') || exit 1
WDA_URL=$("$PYTHON" -c 'from ui_framework.JRYG_config import SETTINGS; print(SETTINGS["device"]["wda_url"])') || exit 1

# 验证设备已连接
xcrun devicectl device info details -d "$DEVICE_UDID" --timeout 20 >/dev/null || exit 1

# 创建日志目录
mkdir -p "$BASE_DIR/logs"

set -m
IPROXY_PID=""
XCODE_PID=""
TEST_PID=""

cleanup() {
    local exit_code=$? pid pending round
    trap - EXIT
    trap '' INT TERM HUP TSTP
    for pid in "$TEST_PID" "$XCODE_PID" "$IPROXY_PID"; do
        [ -n "$pid" ] || continue
        if ps -p "$pid" -o stat= 2>/dev/null | grep -q 'T'; then
            kill -KILL -- "-$pid" 2>/dev/null || true
        else
            kill -TERM -- "-$pid" 2>/dev/null || true
        fi
    done
    for ((round=0; round<25; round++)); do
        pending=0
        for pid in "$TEST_PID" "$XCODE_PID" "$IPROXY_PID"; do
            [ -n "$pid" ] || continue
            if kill -0 -- "-$pid" 2>/dev/null; then pending=1; fi
        done
        [ "$pending" -eq 1 ] || break
        sleep 0.2
    done
    for pid in "$TEST_PID" "$XCODE_PID" "$IPROXY_PID"; do
        [ -n "$pid" ] || continue
        if kill -0 -- "-$pid" 2>/dev/null; then
            kill -KILL -- "-$pid" 2>/dev/null || true
        fi
        wait "$pid" 2>/dev/null || true
    done
    if [ -n "$TEST_PID$XCODE_PID$IPROXY_PID" ]; then
        echo "[清理] 本次测试、WDA及转发进程已结束；不取消订单、不收车。"
    fi
    exit "$exit_code"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP
trap 'exit $((128 + $(kill -l TSTP)))' TSTP

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
    listeners=$(lsof -nP -t -iTCP:8100 -sTCP:LISTEN 2>/dev/null || true)
    for pid in $listeners; do
        listener_command=$(ps -p "$pid" -o command= 2>/dev/null || true)
        listener_state=$(ps -p "$pid" -o stat= 2>/dev/null | tr -d ' ')
        case "$listener_command" in
            "iproxy -u $DEVICE_UDID 8100 8100"|*/"iproxy -u $DEVICE_UDID 8100 8100")
                if [[ "$listener_state" == T* ]]; then
                    echo "[清理] 结束暂停的本设备8100转发进程 $pid，不恢复旧订单任务。"
                    kill -KILL "$pid" 2>/dev/null || true
                fi
                ;;
        esac
    done
    for ((i=0; i<10; i++)); do
        if ! lsof -nP -iTCP:8100 -sTCP:LISTEN >/dev/null 2>&1; then break; fi
        sleep 0.2
    done
    if lsof -nP -iTCP:8100 -sTCP:LISTEN >/dev/null 2>&1; then
        echo "[错误] 8100已被其他任务占用且WDA无响应；未复用、未恢复或终止外部任务，请先结束占用任务。"
        exit 1
    fi
    iproxy -u "$DEVICE_UDID" 8100 8100 >"$BASE_DIR/logs/iproxy-ios.log" 2>&1 &
    IPROXY_PID=$!
    sleep 2
    if ! kill -0 "$IPROXY_PID" 2>/dev/null; then
        echo "[错误] 本次USB转发启动失败，请检查logs/iproxy-ios.log。"
        exit 1
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
"$PYTHON" "$BASE_DIR/runners/JRYG_run_main_ios.py" "$@" &
TEST_PID=$!
wait "$TEST_PID"
exit_code=$?

REPORT_FILE="$BASE_DIR/report/JRYG_test_report_hk_ios.html"
for arg in "$@"; do
    case "$arg" in
        --report-file=*) REPORT_FILE="${arg#--report-file=}" ;;
    esac
done
if [ -f "$REPORT_FILE" ]; then
    echo "[报告] file://$REPORT_FILE"
fi
exit "$exit_code"
