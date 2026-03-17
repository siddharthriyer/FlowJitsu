#!/usr/bin/env bash
set -euo pipefail

ENV_NAME="${1:-biocompute-vscode-min}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! command -v conda >/dev/null 2>&1; then
  echo "conda not found on PATH"
  exit 1
fi

eval "$(conda shell.bash hook)"

if ! conda env list | awk '{print $1}' | grep -qx "${ENV_NAME}"; then
  echo "Conda environment not found: ${ENV_NAME}"
  exit 1
fi

conda activate "${ENV_NAME}"
python -m pip install --upgrade pip
python -m pip install -e "${SCRIPT_DIR}"

echo
echo "Installed flow-gate-app into conda environment: ${ENV_NAME}"
echo "Launch with:"
echo "  conda activate ${ENV_NAME}"
echo "  flow-gate-desktop"

