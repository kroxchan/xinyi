#!/usr/bin/env bash
# ============================================================
# xinyi 一键安装脚本  |  macOS / Linux
# 用法: bash <(curl -fsSL https://raw.githubusercontent.com/kroxchan/xinyi/main/scripts/install.sh)
#   或下载后本地运行: bash install.sh
# ============================================================
set -e

XINYI_DIR="${HOME}/xinyi"
REPO_URL="https://github.com/kroxchan/xinyi.git"
MIN_PYTHON="3.10"

# ── 颜色输出 ───────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

info()    { echo -e "${CYAN}[xinyi]${RESET} $1"; }
ok()      { echo -e "${GREEN}[✓]${RESET} $1"; }
warn()    { echo -e "${YELLOW}[!]${RESET} $1"; }
abort()   { echo -e "${RED}[✗]${RESET} $1" >&2; exit 1; }

# ── Banner ────────────────────────────────────────────────
cat << 'BANNER'
   __  ____  ____  ____  __  ____
  / / / / / / __/ / __ \/ / / __/__ ____
 / /_/ / _\ \/ _/ / /_/ / /_\ \/ -_) __/
 \___/_/\__/_\__/  \____/_/\__/\___/\__/
  你的 AI 分身  ·  一键安装脚本
BANNER
echo ""

# ── 0. 检查 Python 版本 ────────────────────────────────────
info "检查 Python 版本..."
PYTHON_CMD=""
for cmd in python3 python python; do
    if $cmd -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" 2>/dev/null; then
        PYTHON_CMD=$cmd
        break
    fi
done
if [[ -z "$PYTHON_CMD" ]]; then
    abort "需要 Python ${MIN_PYTHON}+，未找到。请先安装: https://www.python.org/downloads/"
fi
PY_VERSION=$($PYTHON_CMD -c "import sys; print('.'.join(map(str, sys.version_info[:3])))")
ok "Python ${PY_VERSION}"

# ── 1. 克隆 / 更新仓库 ────────────────────────────────────
if [[ -d "${XINYI_DIR}/.git" ]]; then
    info "检测到已有 xinyi，正在更新..."
    cd "${XINYI_DIR}"
    git pull origin main
else
    info "正在克隆 xinyi 到 ${XINYI_DIR}..."
    mkdir -p "$(dirname "${XINYI_DIR}")"
    git clone "${REPO_URL}" "${XINYI_DIR}"
fi
cd "${XINYI_DIR}"
ok "代码就绪"

# ── 2. 创建虚拟环境 ───────────────────────────────────────
VENV="${XINYI_DIR}/venv"
if [[ ! -d "${VENV}/bin" ]]; then
    info "创建虚拟环境..."
    $PYTHON_CMD -m venv "${VENV}"
    ok "虚拟环境已创建"
fi
source "${VENV}/bin/activate"

# ── 3. 安装依赖 ───────────────────────────────────────────
info "安装 Python 依赖（首次约需 3-5 分钟）..."
pip install --upgrade pip -q
pip install -r requirements.txt -q
ok "依赖安装完成"

# ── 4. 配置 .env ─────────────────────────────────────────
ENV_FILE="${XINYI_DIR}/.env"
if [[ ! -f "${ENV_FILE}" ]]; then
    if [[ -f "${XINYI_DIR}/.env.example" ]]; then
        cp "${XINYI_DIR}/.env.example" "${ENV_FILE}"
        ok "已从示例创建 .env 配置文件"
    fi
fi

# ── 5. 下载模型 ──────────────────────────────────────────
info "首次启动将自动下载 AI 模型（约 500MB），可随时 Ctrl+C 跳过..."
ok "模型将在首次运行时按需下载"

# ── 6. 完成 ──────────────────────────────────────────────
echo ""
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo -e "  ${GREEN}安装完成！${RESET}"
echo ""
echo -e "  启动 xinyi："
echo -e "    ${CYAN}cd ${XINYI_DIR}${RESET}"
echo -e "    ${CYAN}./run.sh${RESET}"
echo ""
echo -e "  或者双击 Finder 中 xinyi 文件夹里的 ${BOLD}run.sh${RESET}"
echo ""
echo -e "  首次使用请在界面中填写你的 API Key（支持 OpenAI / Anthropic / 兼容接口）"
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
