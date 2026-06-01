#!/usr/bin/env bash
# install_dream_watch_launchd.sh — explicit opt-in launchd install for this workspace.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${REPO_ROOT}/.venv/bin/python"

if [ ! -x "${PYTHON_BIN}" ]; then
  echo "[install_dream_watch] Missing project python at ${PYTHON_BIN}" >&2
  exit 1
fi

POLL_INTERVAL="$(
  REPO_ROOT="${REPO_ROOT}" "${PYTHON_BIN}" - <<'PY'
import os
import sys
from pathlib import Path

repo = Path(os.environ["REPO_ROOT"])
sys.path.insert(0, str(repo))
from braindrain.config import Config

cfg_path = Path(os.environ.get("BRAINDRAIN_CONFIG", repo / "config" / "hub_config.yaml"))
dreaming = Config(cfg_path).get("dreaming", {}) or {}
triggers = dreaming.get("triggers") if isinstance(dreaming.get("triggers"), dict) else {}
host_idle = triggers.get("macos_host_idle") if isinstance(triggers.get("macos_host_idle"), dict) else {}
print(int(host_idle.get("poll_interval_seconds", 120) or 120))
PY
)"

WS_HASH="$(
  REPO_ROOT="${REPO_ROOT}" "${PYTHON_BIN}" - <<'PY'
import os
import sys
from pathlib import Path

repo = Path(os.environ["REPO_ROOT"])
sys.path.insert(0, str(repo))
from braindrain.dream_trigger import workspace_hash

print(workspace_hash(repo))
PY
)"

LABEL="com.braindrain.dream-watch.${WS_HASH}"
PLIST_SRC="${REPO_ROOT}/config/com.braindrain.dream-watch.plist"
PLIST_DST="${HOME}/Library/LaunchAgents/${LABEL}.plist"
LOG_DIR="${HOME}/.braindrain/logs"
mkdir -p "${LOG_DIR}"

sed \
  -e "s|__REPO_ROOT__|${REPO_ROOT}|g" \
  -e "s|__LABEL__|${LABEL}|g" \
  -e "s|__POLL_INTERVAL__|${POLL_INTERVAL}|g" \
  -e "s|__STDOUT_LOG__|${LOG_DIR}/dream-watch-${WS_HASH}.out.log|g" \
  -e "s|__STDERR_LOG__|${LOG_DIR}/dream-watch-${WS_HASH}.err.log|g" \
  "${PLIST_SRC}" > "${PLIST_DST}"

launchctl bootout "gui/$(id -u)/${LABEL}" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "${PLIST_DST}"
launchctl enable "gui/$(id -u)/${LABEL}" 2>/dev/null || true

echo "Installed ${PLIST_DST}"
echo "Label: ${LABEL}"
echo "Poll interval: ${POLL_INTERVAL}s"
echo "Remember: set dreaming.triggers.macos_host_idle.enabled: true in this workspace hub_config.yaml"
