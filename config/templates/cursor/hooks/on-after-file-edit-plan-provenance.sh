#!/usr/bin/env bash
# on-after-file-edit-plan-provenance.sh
# Cursor afterFileEdit hook: stamp *.plan.md frontmatter with model provenance.

set -euo pipefail

command -v git >/dev/null 2>&1 || exit 0
command -v python3 >/dev/null 2>&1 || exit 0
command -v jq >/dev/null 2>&1 || exit 0

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
PRIMED_JSON="${REPO_ROOT}/.braindrain/primed.json"

_resolve_stamp_script() {
  local local_script="${REPO_ROOT}/scripts/plan_provenance_stamp.py"
  if [ -f "${local_script}" ]; then
    echo "${local_script}"
    return 0
  fi
  if [ -f "${PRIMED_JSON}" ]; then
    local hub
    hub="$(
      python3 -c 'import json,sys; p=sys.argv[1];
try:
  d=json.load(open(p,"r",encoding="utf-8"))
  print((d.get("braindrain_hub_root") or "").strip())
except Exception:
  print("")' "${PRIMED_JSON}" 2>/dev/null || true
    )"
    if [ -n "${hub}" ] && [ -f "${hub}/scripts/plan_provenance_stamp.py" ]; then
      echo "${hub}/scripts/plan_provenance_stamp.py"
      return 0
    fi
  fi
  if [ -n "${BRAINDRAIN_LAUNCHER_PATH:-}" ]; then
    local launcher_root
    launcher_root="$(cd "$(dirname "${BRAINDRAIN_LAUNCHER_PATH}")/.." && pwd 2>/dev/null || true)"
    if [ -n "${launcher_root}" ] && [ -f "${launcher_root}/scripts/plan_provenance_stamp.py" ]; then
      echo "${launcher_root}/scripts/plan_provenance_stamp.py"
      return 0
    fi
  fi
  return 1
}

STAMP_SCRIPT="$(_resolve_stamp_script)" || exit 0

HOOK_INPUT="$(cat || true)"
HOOK_INPUT="${HOOK_INPUT:-{}}"

FILE_PATH="$(printf '%s' "${HOOK_INPUT}" | jq -r '.file_path // .path // empty' 2>/dev/null || true)"
if [ -z "${FILE_PATH}" ]; then
  exit 0
fi

case "${FILE_PATH}" in
  */plans/*.plan.md|*/.cursor/plans/*.plan.md)
    printf '%s' "${HOOK_INPUT}" | python3 "${STAMP_SCRIPT}" \
      --repo-root "${REPO_ROOT}" \
      --plan-path "${FILE_PATH}" || true
    ;;
esac

exit 0
