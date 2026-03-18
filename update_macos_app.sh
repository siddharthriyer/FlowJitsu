#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo "Usage: $0 /path/to/FlowJitsu.app [/Applications|~/Applications]"
  exit 1
fi

APP_SOURCE="$1"
APP_TARGET_DIR="${2:-/Applications}"
APP_NAME="FlowJitsu.app"

if [[ ! -d "${APP_SOURCE}" ]]; then
  echo "App bundle not found: ${APP_SOURCE}"
  exit 1
fi

if [[ "$(basename "${APP_SOURCE}")" != "${APP_NAME}" ]]; then
  echo "Expected an app bundle named ${APP_NAME}"
  exit 1
fi

APP_TARGET_DIR="${APP_TARGET_DIR/#\~/$HOME}"
mkdir -p "${APP_TARGET_DIR}"

APP_TARGET_PATH="${APP_TARGET_DIR}/${APP_NAME}"

echo "Installing ${APP_NAME} into ${APP_TARGET_DIR}"

if [[ -d "${APP_TARGET_PATH}" ]]; then
  rm -rf "${APP_TARGET_PATH}"
fi

cp -R "${APP_SOURCE}" "${APP_TARGET_PATH}"

echo
echo "Updated app bundle:"
echo "  ${APP_TARGET_PATH}"
echo
echo "User data remains in:"
echo "  ~/Library/Application Support/FlowJitsu"
