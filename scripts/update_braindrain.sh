#!/usr/bin/env bash
# BRAINDRAIN — update_braindrain.sh
# Non-interactive check/apply for repo-clone installs.
#
# Exit codes:
#   0  — up to date (check) or update applied / already current (apply)
#   10 — update available (check mode only)
#   1  — error (dirty tree, network, non-ff, missing venv, etc.)

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

MODE="${1:-check}"
VENV_PYTHON="$REPO/.venv/bin/python"

if [[ "$MODE" != "check" && "$MODE" != "apply" ]]; then
  echo "Usage: $0 [check|apply]" >&2
  exit 1
fi

if [[ ! -x "$VENV_PYTHON" ]]; then
  echo "[braindrain] Missing venv at $VENV_PYTHON; run ./install.sh first." >&2
  exit 1
fi

exec "$VENV_PYTHON" -m braindrain.updater "$MODE" --repo-root "$REPO"
