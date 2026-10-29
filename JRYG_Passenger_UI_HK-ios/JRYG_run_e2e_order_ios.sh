#!/bin/bash
# ==============================================================
# JRYG 港版 iOS E2E 下单全流程测试运行脚本
# 流程: 准备token → 打开App → 登录 → 包车价下单 → 打表下单(后付+现金)
# ==============================================================

set -e

# 切换到脚本所在目录
cd "$(dirname "$0")"

echo "=================================================="
echo "  JRYG 港版 iOS E2E 下单全流程测试 (Start)"
echo "=================================================="

# --------------------------------------------------
# 1. 准备乘客端 token 和司机端会话文件
# --------------------------------------------------
echo "  >> 准备乘客端 token 和司机端会话..."

# 优先使用已有的 token/会话文件（避免频繁触发验证码频率限制）
REUSE=0
if [ -f tmp/passenger_token.txt ] && [ -f tmp/driver_session.json ]; then
    # 检查文件是否在 1 小时内生成（token 有效期约 2 小时，留余量）
    TOKEN_AGE=$(( $(date +%s) - $(stat -f %m tmp/passenger_token.txt 2>/dev/null || echo 0) ))
    if [ "$TOKEN_AGE" -lt 3600 ]; then
        REUSE=1
        export HK_PASSENGER_ACCESS_TOKEN="$(cat tmp/passenger_token.txt)"
        export HK_DRIVER_SESSION_FILE="$(pwd)/tmp/driver_session.json"
        echo "  >> 复用已有 token（${TOKEN_AGE}s 前生成）"
    fi
fi

if [ "$REUSE" -eq 0 ]; then
    echo "  >> 重新登录获取 token..."
    # 运行准备脚本，从输出末尾提取 export 命令并 eval
    PREPARE_OUT="$(python3 JRYG_prepare_tokens.py 2>&1)" || {
        echo "$PREPARE_OUT"
        echo "  >> 准备 token 失败，终止测试"
        exit 1
    }
    # 显示准备过程日志（除最后两行 export 外）
    echo "$PREPARE_OUT" | sed '$d' | sed '$d'
    # eval 最后两行 export 命令
    eval "$(echo "$PREPARE_OUT" | tail -2)"
    echo "  >> token 已就绪: ${HK_PASSENGER_ACCESS_TOKEN:0:16}..."
fi

echo "--------------------------------------------------"

# --------------------------------------------------
# 2. 运行 E2E 测试
# --------------------------------------------------
EXIT_CODE=0
python3 JRYG_run_e2e_order_ios.py "$@" || EXIT_CODE=$?

echo "=================================================="
echo "  运行结束 (exit_code=$EXIT_CODE)，订单校验结果以上方报告为准"
echo "=================================================="

exit $EXIT_CODE
