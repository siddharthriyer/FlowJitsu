#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

python -m pip install --upgrade pip build
python -m build

echo
echo "Built distribution files in:"
echo "  ${SCRIPT_DIR}/dist"

