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
            exec "$PYTHON" "$BASE_DIR/JRYG_run_main.py" "$@"
            ;;
    esac
done

echo "JRYG 大陆 Android UI 自动化"
if ! command -v adb >/dev/null 2>&1; then
    echo "[错误] 未检测到 adb，请配置 Android SDK。"
    exit 1
fi
adb devices || exit 1

"$PYTHON" "$BASE_DIR/JRYG_run_main.py" "$@"
exit_code=$?
if [ -f "$BASE_DIR/report/JRYG_test_report.html" ]; then
    echo "[报告] file://$BASE_DIR/report/JRYG_test_report.html"
fi
exit "$exit_code"
