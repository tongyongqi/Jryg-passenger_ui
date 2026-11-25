#!/bin/bash
set -euo pipefail
export PATH=/usr/bin:/bin:/usr/sbin:/sbin

SOURCE="$(cd -- "$(dirname -- "$0")" && pwd)/JRYG_set_daily_wake.sh"
HELPER="/Library/PrivilegedHelperTools/com.jryg.hk-ios.set-wake"
RULE="/private/etc/sudoers.d/jryg_hk_ios_wake"
MODE="${1:---check}"

if [[ "$MODE" == "--root-install" ]]; then
    if [[ "$#" -ne 2 || "$(id -u)" -ne 0 || ! "$2" =~ ^[a-zA-Z_][a-zA-Z0-9_.-]*$ ]]; then
        echo "授权安装参数无效。"
        exit 2
    fi
    ACCOUNT="$2"
    if [[ "$(id -u "$ACCOUNT")" -eq 0 ]]; then
        echo "不能为root配置此用户授权。"
        exit 2
    fi
    for DIRECTORY in /Library /Library/PrivilegedHelperTools /private /private/etc /private/etc/sudoers.d; do
        if [[ ! -d "$DIRECTORY" || -L "$DIRECTORY" || "$(/usr/bin/stat -f %u "$DIRECTORY")" != 0 ]]; then
            echo "授权目录不是可信root目录，停止安装。"
            exit 2
        fi
        PERMISSIONS=$(/usr/bin/stat -f %Lp "$DIRECTORY")
        if (( (8#$PERMISSIONS & 8#022) != 0 )); then
            echo "授权目录可被非root用户修改，停止安装。"
            exit 2
        fi
    done
    if [[ -e "$HELPER" || -L "$HELPER" || -e "$RULE" || -L "$RULE" ]]; then
        echo "已有同名授权文件，停止，不覆盖现有管理员配置。"
        exit 2
    fi
    /usr/sbin/visudo -c >/dev/null
    /bin/bash -n "$SOURCE"
    CANDIDATE="$(dirname -- "$SOURCE")/wake.sudoers"
    umask 077
    printf '%s ALL=(root) NOPASSWD: NOSETENV: %s\n' "$ACCOUNT" "$HELPER" > "$CANDIDATE"
    /usr/sbin/visudo -c -f "$CANDIDATE" >/dev/null
    /usr/bin/install -o root -g wheel -m 755 "$SOURCE" "$HELPER"
    /usr/bin/install -o root -g wheel -m 440 "$CANDIDATE" "$RULE"
    if ! /usr/sbin/visudo -c >/dev/null; then
        /bin/rm -f "$RULE" "$HELPER"
        echo "sudo配置校验失败，已撤销本次新增授权。"
        exit 2
    fi
    echo "一次性授权已安装：仅可设置每日唤醒时间，不允许任意管理员命令。"
    exit 0
fi

if [[ "$#" -gt 1 || ( "$MODE" != "--check" && "$MODE" != "--install" ) || "$(uname -s)" != Darwin || "$(id -u)" -eq 0 ]]; then
    echo "请由普通macOS用户运行：bash runners/JRYG_authorize_daily_wake.sh [--check|--install]"
    exit 2
fi
if [[ -f "$HELPER" && ! -L "$HELPER" && "$(/usr/bin/stat -f %u "$HELPER")" == 0 ]] && /usr/bin/cmp -s "$SOURCE" "$HELPER" && /usr/bin/sudo -n -l "$HELPER" 10:35 >/dev/null 2>&1; then
    echo "专用每日唤醒授权已可用，不需要再次输入管理员密码。"
    exit 0
fi
if [[ "$MODE" == "--check" ]]; then
    echo "专用授权尚未就绪；使用--install完成一次性管理员授权。"
    exit 2
fi
if [[ -e "$HELPER" || -L "$HELPER" ]]; then
    echo "已有同名程序但授权或内容不匹配，停止，不覆盖。"
    exit 2
fi
STAGE=$(/usr/bin/mktemp -d "${TMPDIR:-/tmp/}jryg-wake-authorize.XXXXXX")
trap '/bin/rm -f "$STAGE/authorize.sh" "$STAGE/JRYG_set_daily_wake.sh" "$STAGE/wake.sudoers"; /bin/rmdir "$STAGE"' EXIT
/bin/cp "$0" "$STAGE/authorize.sh"
/bin/cp "$SOURCE" "$STAGE/JRYG_set_daily_wake.sh"
printf -v COMMAND '/bin/bash %q --root-install %q' "$STAGE/authorize.sh" "$(id -un)"
/usr/bin/osascript - "$COMMAND" <<'APPLESCRIPT'
on run argv
    do shell script (item 1 of argv) with administrator privileges
end run
APPLESCRIPT
/usr/bin/cmp -s "$SOURCE" "$HELPER"
/usr/bin/sudo -n -l "$HELPER" 10:35 >/dev/null 2>&1
echo "专用免重复授权验证通过；管理员密码未读取、未保存。"
