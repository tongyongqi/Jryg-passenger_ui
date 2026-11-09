#!/bin/bash
set -euo pipefail

# 当前目录（打包与部署/）
SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
# .venv-deploy 与脚本同级（打包与部署/）
PYTHON="$SCRIPT_DIR/.venv-deploy/bin/python"

if [[ ! -x "$PYTHON" ]]; then
    printf '未找到独立部署环境：%s\n' "$PYTHON" >&2
    printf '请先在 %s 目录创建 .venv-deploy，并安装 %s/requirements-deploy.txt 中的依赖。\n' "$SCRIPT_DIR" "$SCRIPT_DIR" >&2
    exit 1
fi

cd "$SCRIPT_DIR"
exec "$PYTHON" "$SCRIPT_DIR/香港环境部署.py" "$@"
