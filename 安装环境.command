#!/bin/bash
# ============================================================
#  打包与部署 · 一键安装环境
#  双击此文件即可自动创建虚拟环境并安装依赖
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
cd "$SCRIPT_DIR"

VENV_DIR="$SCRIPT_DIR/.venv-deploy"
PYTHON="$VENV_DIR/bin/python"

echo "=================================================="
echo "  打包与部署 · 环境安装"
echo "=================================================="
echo ""

# 1. 检查系统 Python
if ! command -v python3 &>/dev/null; then
    echo "[错误] 未找到 python3，请先安装 Python 3.10+。" >&2
    echo "       macOS 安装方式： brew install python@3.12" >&2
    echo "       或访问 https://www.python.org/downloads/" >&2
    exit 1
fi

PY_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "[1/4] 检测到 Python $PY_VERSION"

# 2. 创建虚拟环境
if [[ -x "$PYTHON" ]]; then
    echo "[2/4] 虚拟环境已存在，跳过创建"
else
    echo "[2/4] 创建虚拟环境 .venv-deploy ..."
    python3 -m venv "$VENV_DIR"
    echo "      完成"
fi

# 3. 安装依赖
echo "[3/4] 安装依赖包 ..."
"$PYTHON" -m pip install --upgrade pip --quiet
"$PYTHON" -m pip install -r "$SCRIPT_DIR/requirements-deploy.txt" --quiet
echo "      完成"

# 4. 验证
echo "[4/4] 验证安装 ..."
"$PYTHON" -c "import requests; print(f'      requests {requests.__version__} OK')"
echo ""

echo "=================================================="
echo "  ✅ 安装完成！"
echo "=================================================="
echo ""
echo "  使用方式："
echo "    国内部署：双击「国内环境部署.command」"
echo "    香港部署：双击「香港环境部署.command」"
echo ""
echo "  首次使用会提示输入 Jenkins 密码，"
echo "  密码会自动保存到 macOS 钥匙串，之后无需重复输入。"
echo ""
echo "  按任意键关闭此窗口..."
read -n 1 -s
