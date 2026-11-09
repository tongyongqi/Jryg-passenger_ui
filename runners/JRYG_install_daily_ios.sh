#!/bin/bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "$0")/../.." && pwd)"
PROJECT="$ROOT/JRYG_Passenger_UI_HK-ios"
PYTHON="$ROOT/.venv/bin/python"
LABEL="com.jryg.hk-ios.daily"
SOURCE="$PROJECT/runners/$LABEL.plist"
DESTINATION="$HOME/Library/LaunchAgents/$LABEL.plist"
MODE="${1:---check}"

if [[ "$#" -gt 1 || ( "$MODE" != "--check" && "$MODE" != "--install" ) ]]; then
    echo "用法：bash runners/JRYG_install_daily_ios.sh [--check|--install]"
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
    echo "每日计划：10:40系统唤醒；10:45执行香港iOS六场景。"
    echo "当前只读检查，未安装任务、未设置唤醒、未执行订单。"
    echo "确认每日真实下单和支付后，使用--install启用；仅设置电源计划时需要管理员密码。"
    exit 0
fi

if /bin/launchctl print "gui/$(id -u)/$LABEL" >/dev/null 2>&1 || [[ -e "$DESTINATION" ]]; then
    echo "已有同名任务或配置，未覆盖、未重新加载；请先核对原任务。"
    exit 2
fi
SCHEDULE=$(/usr/bin/pmset -g sched)
if printf '%s\n' "$SCHEDULE" | /usr/bin/grep -qi 'Repeating power events'; then
    if printf '%s\n' "$SCHEDULE" | /usr/bin/grep -qi 'wake at 10:40AM every day'; then
        echo "系统已有每天10:40唤醒计划，跳过pmset设置，继续安装launchd任务。"
    else
        echo "系统已有其他重复电源计划，pmset repeat会覆盖原计划，因此停止安装。"
        echo "请先核对系统电源计划；未删除或修改现有计划。"
        exit 2
    fi
else
    echo "正在启用每日真实订单与支付：10:40唤醒，10:45执行，失败不自动重试。"
    echo "Mac需接电并保持账号已登录；合盖、关机及FileVault登录不能保证执行。"
    /usr/bin/sudo /usr/bin/pmset repeat wake MTWRFSU 10:40:00
fi
/bin/mkdir -p "$HOME/Library/LaunchAgents" "$PROJECT/logs/scheduled"
/bin/cp -n "$SOURCE" "$DESTINATION"
/bin/chmod 600 "$DESTINATION"
if ! /bin/launchctl bootstrap "gui/$(id -u)" "$DESTINATION"; then
    echo "任务加载失败；唤醒计划和复制的配置可能已生效，请检查pmset -g sched及LaunchAgents配置。"
    echo "未立即执行订单，未自动删除电源计划或重试安装。"
    exit 2
fi
/usr/bin/pmset -g sched
echo "已启用每日10:45任务；加载时不立即下单，也不补跑10:55之后的旧任务。"
echo "日志：$PROJECT/logs/scheduled/daily.log"
