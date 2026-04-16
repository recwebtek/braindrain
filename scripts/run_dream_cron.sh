#!/usr/bin/env bash
# run_dream_cron.sh
# Repo-local helper for external cron/launchd/systemd scheduling.
# Uses the project venv and the installed braindrain server code directly.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${REPO_ROOT}/.venv/bin/python"

if [ ! -x "${PYTHON_BIN}" ]; then
  echo "[run_dream_cron] Missing project python at ${PYTHON_BIN}" >&2
  exit 1
fi

cd "${REPO_ROOT}"

MODE="${BRAINDRAIN_DREAM_MODE:-full}"
FORCE="${BRAINDRAIN_DREAM_FORCE:-0}"

export BRAINDRAIN_DREAM_MODE="${MODE}"
export BRAINDRAIN_DREAM_FORCE="${FORCE}"

exec "${PYTHON_BIN}" - <<'PY'
import json
import os
import sys

from braindrain.server import run_dream

mode = os.environ.get("BRAINDRAIN_DREAM_MODE", "full")
force = os.environ.get("BRAINDRAIN_DREAM_FORCE", "0").lower() in {"1", "true", "yes"}

result = run_dream(mode=mode, force=force)
json.dump(result, sys.stdout, ensure_ascii=False)
sys.stdout.write("\n")
PY
