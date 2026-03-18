#!/usr/bin/env bash
set -euo pipefail

ENV_NAME="${1:-biocompute-vscode-min}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIST_DIR="${SCRIPT_DIR}/dist"
APP_NAME="FlowJitsu.app"
APP_ZIP="${DIST_DIR}/FlowJitsu-macos.zip"

rm -rf "${DIST_DIR}"

"${SCRIPT_DIR}/build_wheel.sh"
"${SCRIPT_DIR}/build_macos_app.sh" "${ENV_NAME}"

if [[ -d "${DIST_DIR}/${APP_NAME}" ]]; then
  ditto -c -k --sequesterRsrc --keepParent "${DIST_DIR}/${APP_NAME}" "${APP_ZIP}"
fi

cd "${DIST_DIR}"
shasum -a 256 ./* > SHA256SUMS.txt

echo
echo "Release assets ready in:"
echo "  ${DIST_DIR}"
