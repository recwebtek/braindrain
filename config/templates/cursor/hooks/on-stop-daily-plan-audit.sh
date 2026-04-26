#!/usr/bin/env bash
# on-stop-daily-plan-audit.sh
# Cursor stop hook: run planning audit at most once per day.

set -euo pipefail

command -v git >/dev/null 2>&1 || exit 0
command -v python3 >/dev/null 2>&1 || exit 0

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
AUDIT_SCRIPT="${REPO_ROOT}/scripts/daily_plan_audit.py"
STATE_DIR="${REPO_ROOT}/.cursor/hooks/state"
STATE_FILE="${STATE_DIR}/daily-plan-audit.json"
OUT_DIR="${REPO_ROOT}/create-subagent"
TODAY="$(date +%Y-%m-%d)"

[ -f "${AUDIT_SCRIPT}" ] || exit 0

mkdir -p "${STATE_DIR}"
mkdir -p "${OUT_DIR}"

LAST_RUN_DATE=""
if [ -f "${STATE_FILE}" ]; then
  LAST_RUN_DATE="$(
    python3 -c 'import json,sys; p=sys.argv[1]; 
try:
  d=json.load(open(p, "r", encoding="utf-8"))
  print(d.get("last_run_date",""))
except Exception:
  print("")' "${STATE_FILE}" 2>/dev/null || true
  )"
fi

if [ "${LAST_RUN_DATE}" = "${TODAY}" ]; then
  exit 0
fi

if python3 "${AUDIT_SCRIPT}" \
  --repo-root "${REPO_ROOT}" \
  --report-date "${TODAY}" \
  --trigger "cursor-stop-daily-gated" \
  --output-dir "${OUT_DIR}" >/dev/null 2>&1; then
  TMP_FILE="${STATE_FILE}.tmp.$$"
  printf '{\n  "last_run_date": "%s",\n  "trigger": "cursor-stop-daily-gated"\n}\n' "${TODAY}" > "${TMP_FILE}"
  mv "${TMP_FILE}" "${STATE_FILE}"
fi

exit 0
