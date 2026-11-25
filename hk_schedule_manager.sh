#!/bin/bash
# 安装/卸载/查看 macOS launchd 定时任务
# 用法：
#   ./hk_schedule_manager.sh install   安装定时任务
#   ./hk_schedule_manager.sh uninstall 卸载定时任务
#   ./hk_schedule_manager.sh status    查看定时任务状态
#   ./hk_schedule_manager.sh run       立即执行一次（带钉钉通知）

set -u

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLIST_NAME="com.jryg.hk-android-six-scenarios"
PLIST_SRC="${BASE_DIR}/${PLIST_NAME}.plist"
PLIST_DST="$HOME/Library/LaunchAgents/${PLIST_NAME}.plist"

case "${1:-}" in
    install)
        if [ ! -f "$PLIST_SRC" ]; then
            echo "[错误] plist 文件不存在：$PLIST_SRC"
            exit 1
        fi
        mkdir -p "$HOME/Library/LaunchAgents"
        cp "$PLIST_SRC" "$PLIST_DST"
        # 替换 plist 中的用户目录为实际路径
        sed -i '' "s|/Users/tongyongqi/Desktop/codebuddy-daima/JRYG_Passenger_UI_HK-android_副本|${BASE_DIR}|g" "$PLIST_DST"
        launchctl load "$PLIST_DST"
        echo "[成功] 定时任务已安装：$PLIST_NAME"
        echo "       plist: $PLIST_DST"
        echo "       修改 plist 中的 DINGTALK_WEBHOOK 等环境变量后重新 install"
        echo "       查看日志：tail -f ${BASE_DIR}/logs/scheduled_stdout.log"
        ;;

    uninstall)
        if [ -f "$PLIST_DST" ]; then
            launchctl unload "$PLIST_DST"
            rm -f "$PLIST_DST"
            echo "[成功] 定时任务已卸载：$PLIST_NAME"
        else
            echo "[提示] 定时任务未安装，无需卸载"
        fi
        ;;

    status)
        launchctl list | grep "$PLIST_NAME" && echo "[状态] 定时任务已加载" || echo "[状态] 定时任务未加载"
        ;;

    run)
        echo "[执行] 立即运行六场景（带钉钉通知）"
        PYTHON="${BASE_DIR}/.venv/bin/python3"
        if [ ! -x "$PYTHON" ]; then
            PYTHON="${BASE_DIR}/.venv/bin/python"
        fi
        "$PYTHON" "${BASE_DIR}/hk_passenger_android_scheduled.py"
        ;;

    *)
        echo "用法：$0 {install|uninstall|status|run}"
        echo ""
        echo "  install    安装 macOS launchd 定时任务（每天 10:30）"
        echo "  uninstall  卸载定时任务"
        echo "  status     查看定时任务状态"
        echo "  run        立即执行一次六场景（带钉钉通知）"
        echo ""
        echo "钉钉配置："
        echo "  编辑 ${PLIST_SRC} 中的 DINGTALK_WEBHOOK / DINGTALK_SECRET / DINGTALK_AT_MOBILES"
        echo "  或在环境中设置后直接 ./hk_schedule_manager.sh run"
        exit 1
        ;;
esac
