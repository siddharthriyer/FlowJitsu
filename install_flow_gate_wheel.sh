#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo "Usage: $0 /path/to/flow_gate_app-<version>-py3-none-any.whl [conda-env-name]"
  exit 1
fi

WHEEL_PATH="$1"
ENV_NAME="${2:-biocompute-vscode-min}"

if [[ ! -f "${WHEEL_PATH}" ]]; then
  echo "Wheel not found: ${WHEEL_PATH}"
  exit 1
fi

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
python -m pip install --upgrade "${WHEEL_PATH}"

echo
echo "Installed wheel into conda environment: ${ENV_NAME}"
echo "Launch with:"
echo "  conda activate ${ENV_NAME}"
echo "  flow-gate-desktop"

