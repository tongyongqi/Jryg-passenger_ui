#!/bin/bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "$0")" && pwd)"
PROJECT="$ROOT/JRYG_Passenger_UI_HK-ios"
PYTHON="$ROOT/.venv/bin/python"
RUNNER="$PROJECT/runners/JRYG_run_hk_ios.sh"

if [[ ! -x "$PYTHON" ]]; then
    printf '未找到iOS自动化Python环境：%s\n' "$PYTHON" >&2
    exit 1
fi
if [[ ! -f "$RUNNER" ]]; then
    printf '未找到iOS自动化启动脚本：%s\n' "$RUNNER" >&2
    exit 1
fi

printf '香港乘客端iOS：包车两例 + 打表四例\n'
printf '默认执行下单、司机操作及支付；失败停止，不自动重试付款。\n'
printf '请连接USB并信任开发者证书；会检测锁屏并尝试解锁，密码锁无法自动通过时请手动解锁。\n'
printf '顺序：包车Alipay → 包车银行卡 → 打表现金 → 电子支付后付银行卡 → 电子支付后付Alipay → 直接Alipay\n'
printf '用例间隔10秒；报告：%s/report/batches/\n\n' "$PROJECT"

export HK_IOS_PYTHON="$PYTHON"
cd "$PROJECT"
exec /bin/bash "$RUNNER" --batch "$@"
