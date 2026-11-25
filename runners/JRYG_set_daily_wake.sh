#!/bin/bash
set -euo pipefail
export PATH=/usr/bin:/bin:/usr/sbin:/sbin

if [[ "$#" -ne 1 || ! "$1" =~ ^([01][0-9]|2[0-3]):[0-5][0-9]$ ]]; then
    echo "仅接受一个HH:MM时间参数，用于每日系统唤醒。"
    exit 2
fi
if [[ "$(/usr/bin/id -u)" -ne 0 ]]; then
    echo "请通过专用sudo授权调用此唤醒设置程序。"
    exit 2
fi

SCHEDULE=$(/usr/bin/pmset -g sched)
REPEATING=$(printf '%s\n' "$SCHEDULE" | /usr/bin/awk '/^Repeating power events:/{active=1; next} /^Scheduled power events:/{active=0} active && NF{print}')
if [[ -n "$REPEATING" ]]; then
    if [[ "$(printf '%s\n' "$REPEATING" | /usr/bin/wc -l | /usr/bin/tr -d ' ')" != "1" ]] || ! printf '%s\n' "$REPEATING" | /usr/bin/grep -Eq '^[[:space:]]*wake at [0-9]{1,2}:[0-9]{2}(AM|PM) every day[[:space:]]*$'; then
        echo "已有其他重复电源计划，停止，不覆盖休眠、关机或其他唤醒设置。"
        exit 2
    fi
fi
/usr/bin/pmset repeat wake MTWRFSU "$1:00"
echo "已设置每日$1系统唤醒；未执行订单，不读取或保存管理员密码。"
