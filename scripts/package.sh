#!/usr/bin/env bash
# ============================================================
# xinyi 跨平台打包脚本
#   macOS:  bash scripts/package.sh          → xinyi-macos.zip
#   Windows (通过 Wine/交叉编译): 需在 Windows 机器上运行
#   Windows CI/CD:  github actions 自动构建
#
#   完整构建 macOS:
#     pip install pyinstaller && pyinstaller xinyi.spec --clean
#     zip -r dist/xinyi-macos.zip dist/xinyi.app
#
#   完整构建 Windows (在 Windows 机器上):
#     pip install pyinstaller && pyinstaller xinyi-windows.spec --clean
#     powershell Compress-Archive dist/xinyi dist/xinyi-windows.zip
# ============================================================
set -e

cd "$(dirname "${BASH_SOURCE[0]}")/.."
PKG_DIR="${PWD}/dist"
mkdir -p "${PKG_DIR}"

PLATFORM=$(uname -s)

echo "=========================================="
echo "  xinyi 跨平台打包脚本"
echo "  平台: ${PLATFORM}"
echo "=========================================="

pip install pyinstaller -q

if [[ "${PLATFORM}" == "Darwin" ]]; then
    echo ""
    echo "[1/2] 构建 macOS app bundle..."
    pyinstaller xinyi.spec --clean
    echo ""
    echo "[2/2] 打包 xinyi-macos.zip..."
    cd "${PKG_DIR}"
    zip -r "xinyi-macos.zip" xinyi.app
    echo ""
    echo "macOS 打包完成: ${PKG_DIR}/xinyi-macos.zip ($(du -sh xinyi-macos.zip | cut -f1))"
    echo ""
    echo "下一步（发布到 GitHub Releases）:"
    echo "  gh release create v1.0.0 --title 'xinyi v1.0.0' --notes '发布说明'"
    echo "  gh release upload v1.0.0 dist/xinyi-macos.zip"

elif [[ "${PLATFORM}" == "Linux" ]]; then
    echo ""
    echo "[1/2] 构建 Linux app bundle..."
    pyinstaller xinyi-linux.spec --clean
    echo ""
    echo "[2/2] 打包 xinyi-linux.tar.gz..."
    cd "${PKG_DIR}"
    tar -czf "xinyi-linux.tar.gz" xinyi
    echo ""
    echo "Linux 打包完成: ${PKG_DIR}/xinyi-linux.tar.gz ($(du -sh xinyi-linux.tar.gz | cut -f1))"

else
    echo ""
    echo "直接运行以下命令在 Windows 上构建:"
    echo ""
    echo "  pip install pyinstaller"
    echo "  pyinstaller xinyi-windows.spec --clean"
    echo "  powershell Compress-Archive dist\\xinyi dist\\xinyi-windows.zip"
    echo ""
    echo "Windows spec 文件: xinyi-windows.spec"
    echo "构建产物目录: dist\\xinyi\\"
fi

echo ""
echo "=========================================="
echo "  打包脚本完成！"
echo ""
echo "  发行版文件:"
ls -lh "${PKG_DIR}" 2>/dev/null | grep -E "xinyi|total" || echo "  (在 Windows 机器上运行后在 dist/ 查看)"
echo "=========================================="
