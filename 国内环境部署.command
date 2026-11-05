#!/bin/bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "$0")" && pwd)"
PYTHON="$ROOT/.venv-deploy/bin/python"

if [[ ! -x "$PYTHON" ]]; then
    printf '未找到独立部署环境：%s\n' "$PYTHON" >&2
    printf '请先在项目目录创建 .venv-deploy，并安装 requirements-deploy.txt 中的依赖。\n' >&2
    exit 1
fi

cd "$ROOT"
exec "$PYTHON" "$ROOT/国内环境部署.py" "$@"
