#!/usr/bin/env bash
set -euo pipefail

ENV_NAME="${1:-biocompute-vscode-min}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! command -v conda >/dev/null 2>&1; then
  echo "conda not found on PATH"
  exit 1
fi

eval "$(conda shell.bash hook)"
conda activate "${ENV_NAME}"

cd "${SCRIPT_DIR}"

python -m pip install --upgrade pip pyinstaller
python -m pip install -e .

pyinstaller \
  --noconfirm \
  --clean \
  --windowed \
  --name FlowJitsu \
  --paths "${SCRIPT_DIR}/src" \
  --hidden-import tkinter \
  --collect-submodules FlowCytometryTools \
  --collect-submodules flow_gate_app \
  "${SCRIPT_DIR}/src/flow_gate_app/__main__.py"

echo
echo "Built macOS app bundle:"
echo "  ${SCRIPT_DIR}/dist/FlowJitsu.app"
