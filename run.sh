#!/usr/bin/env bash
# ============================================================
# xinyi 启动脚本  |  macOS / Linux
# ============================================================
set -e

XINYI_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="${XINYI_DIR}/venv"

if [[ ! -d "${VENV}/bin" ]]; then
    echo "[xinyi] 未找到虚拟环境，请先运行 install.sh"
    exit 1
fi

source "${VENV}/bin/activate"
cd "${XINYI_DIR}"

echo "[xinyi] 启动中..."
echo "[xinyi] 浏览器打开: http://localhost:7872"

python -m src
