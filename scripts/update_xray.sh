#!/usr/bin/env bash
set -euo pipefail

VERSION="${1:-}"
if [[ ! "$VERSION" =~ ^v?[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "用法：$0 <固定版本，例如 v26.7.28>" >&2
    exit 2
fi
INSTALLER="$(mktemp)"
trap 'rm -f "$INSTALLER"' EXIT
REF="${XRAY_INSTALL_SCRIPT_REF:-main}"
echo "下载官方安装脚本，目标 Xray 版本：$VERSION"
curl --fail --show-error --location --retry 2 --connect-timeout 10 --max-time 120 \
    "https://raw.githubusercontent.com/XTLS/Xray-install/$REF/install-release.sh" --output "$INSTALLER"
test -s "$INSTALLER"
bash -n "$INSTALLER"
sudo bash "$INSTALLER" install --version "$VERSION"
"${XRAY_BIN:-/usr/local/bin/xray}" version
echo "核心安装完成；请按安装时使用的服务和配置路径验证后重启。"
