#!/bin/bash
set -euo pipefail

PROJECT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
PYTHON="$PROJECT/.venv/bin/python"
LABEL="com.jryg.hk-ios.daily"
SOURCE="$PROJECT/runners/$LABEL.plist"
DESTINATION="$HOME/Library/LaunchAgents/$LABEL.plist"
MODE="${1:---check}"

if [[ "$#" -gt 1 || ( "$MODE" != "--check" && "$MODE" != "--install" && "$MODE" != "--update" ) ]]; then
    echo "用法：bash runners/JRYG_install_daily_ios.sh [--check|--install|--update]"
    exit 2
fi
if [[ "$(uname -s)" != "Darwin" || "$(id -u)" -eq 0 ]]; then
    echo "请由已登录的普通macOS用户运行；不要使用sudo运行整个脚本。"
    exit 2
fi
if [[ ! -x "$PYTHON" || ! -f "$SOURCE" ]]; then
    echo "项目Python或任务配置不存在，不能安装。"
    exit 2
fi
/usr/bin/plutil -lint "$SOURCE"
"$PYTHON" "$PROJECT/runners/JRYG_run_scheduled_ios.py"

if [[ "$MODE" == "--check" ]]; then
    echo "每日计划：09:50系统唤醒；09:55执行香港iOS六场景。"
    echo "当前只读检查，未安装任务、未设置唤醒、未执行订单。"
    echo "使用--install首次启用，--update备份并更新；专用唤醒程序只需一次授权，不保存管理员密码。"
    exit 0
fi

DOMAIN="gui/$(id -u)"
LOADED=false
if JOB=$(/bin/launchctl print "$DOMAIN/$LABEL" 2>/dev/null); then
    LOADED=true
fi
if [[ "$MODE" == "--install" ]]; then
    if [[ "$LOADED" == true || -e "$DESTINATION" ]]; then
        echo "已有同名任务或配置，未覆盖、未重新加载；核对后使用--update。"
        exit 2
    fi
else
    if [[ ! -f "$DESTINATION" || -L "$DESTINATION" || "$(/usr/bin/stat -f %u "$DESTINATION")" != "$(id -u)" ]]; then
        echo "既有任务配置缺失、不是普通文件或不属于当前用户，停止更新。"
        exit 2
    fi
    if [[ "$(/usr/bin/plutil -extract Label raw -o - "$DESTINATION")" != "$LABEL" ]]; then
        echo "既有配置Label不一致，停止更新。"
        exit 2
    fi
    outside_start_windows() {
        local CURRENT_HOUR CURRENT_MINUTE CURRENT START_HOUR START_MINUTE START CONFIG
        CURRENT_HOUR=$(/bin/date +%H)
        CURRENT_MINUTE=$(/bin/date +%M)
        CURRENT=$((10#$CURRENT_HOUR * 60 + 10#$CURRENT_MINUTE))
        for CONFIG in "$DESTINATION" "$SOURCE"; do
            START_HOUR=$(/usr/bin/plutil -extract StartCalendarInterval.Hour raw -o - "$CONFIG")
            START_MINUTE=$(/usr/bin/plutil -extract StartCalendarInterval.Minute raw -o - "$CONFIG")
            START=$((10#$START_HOUR * 60 + 10#$START_MINUTE))
            if (( CURRENT >= START && CURRENT < START + 10 )); then
                echo "处于原任务或新任务的启动窗口，停止更新，避免触发或中断真实订单。"
                return 1
            fi
        done
    }
    outside_start_windows || exit 2
    if [[ "$LOADED" == true ]] && printf '%s\n' "$JOB" | /usr/bin/grep -Eq '^[[:space:]]*(pid =|state = running)'; then
        echo "既有任务正在运行，停止更新，不终止当前批次。"
        exit 2
    fi
fi
WAKE_HELPER="/Library/PrivilegedHelperTools/com.jryg.hk-ios.set-wake"
WAKE_TIME="09:50"
SCHEDULE=$(/usr/bin/pmset -g sched)
if printf '%s\n' "$SCHEDULE" | /usr/bin/grep -qi 'wake at 9:50AM every day'; then
    echo "系统已有每天09:50唤醒计划，复用配置，不申请管理员授权。"
else
    if [[ ! -f "$WAKE_HELPER" || -L "$WAKE_HELPER" || "$(/usr/bin/stat -f %u "$WAKE_HELPER")" != 0 ]]; then
        echo "请先运行bash runners/JRYG_authorize_daily_wake.sh --install完成一次性专用授权。"
        exit 2
    fi
    if ! /usr/bin/sudo -n "$WAKE_HELPER" "$WAKE_TIME"; then
        echo "专用授权不可用或电源计划不兼容，停止，不弹出密码窗口、不覆盖其他电源计划。"
        exit 2
    fi
fi
/bin/mkdir -p "$HOME/Library/LaunchAgents" "$PROJECT/logs/scheduled"
if [[ "$MODE" == "--update" ]]; then
    BACKUP="$DESTINATION.backup.$(/bin/date +%Y%m%d-%H%M%S)"
    if [[ -e "$BACKUP" ]]; then
        echo "备份文件已存在，停止更新，未覆盖。"
        exit 2
    fi
    /bin/cp -p "$DESTINATION" "$BACKUP"
    /bin/chmod 600 "$BACKUP"
    echo "原任务已备份：$BACKUP"
    outside_start_windows || exit 2
    if [[ "$LOADED" == true ]]; then
        JOB=$(/bin/launchctl print "$DOMAIN/$LABEL")
        if printf '%s\n' "$JOB" | /usr/bin/grep -Eq '^[[:space:]]*(pid =|state = running)'; then
            echo "任务已开始运行，停止更新，保留原任务。"
            exit 2
        fi
        /bin/launchctl bootout "$DOMAIN/$LABEL"
    fi
    /bin/cp "$SOURCE" "$DESTINATION"
else
    /bin/cp -n "$SOURCE" "$DESTINATION"
fi
/bin/chmod 600 "$DESTINATION"
if ! /bin/launchctl bootstrap "$DOMAIN" "$DESTINATION"; then
    echo "任务加载失败；唤醒计划和复制的配置可能已生效，请检查pmset -g sched及LaunchAgents配置。"
    echo "未立即执行订单，未自动删除电源计划或重试安装。"
    exit 2
fi
/usr/bin/pmset -g sched
echo "已启用每日09:55任务；加载时不立即下单，也不补跑10:05之后的旧任务。"
echo "日志：$PROJECT/logs/scheduled/daily.log"
