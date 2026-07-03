#!/usr/bin/env bash
# macos_dream_watch.sh — launchd-friendly wrapper for host-idle dream evaluation.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${REPO_ROOT}/.venv/bin/python"

if [ ! -x "${PYTHON_BIN}" ]; then
  echo "[macos_dream_watch] Missing project python at ${PYTHON_BIN}" >&2
  exit 1
fi

cd "${REPO_ROOT}"
export BRAINDRAIN_CONFIG="${BRAINDRAIN_CONFIG:-${REPO_ROOT}/config/hub_config.yaml}"
exec "${PYTHON_BIN}" "${REPO_ROOT}/scripts/macos_dream_watch.py"
