#!/usr/bin/env bash
# on-stop-observe.sh
# Cursor stop hook: records a lightweight BrainEvent into ~/.braindrain/events.db.
# This hook is intentionally cheap: no network, no dream processing, no model calls.

set -euo pipefail

command -v sqlite3 >/dev/null 2>&1 || exit 0
command -v jq >/dev/null 2>&1 || exit 0
command -v git >/dev/null 2>&1 || exit 0

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
BRAINDRAIN_DIR="${HOME}/.braindrain"
DB_PATH="${BRAINDRAIN_DIR}/events.db"

mkdir -p "${BRAINDRAIN_DIR}"

HOOK_INPUT="$(cat || true)"
HOOK_INPUT="${HOOK_INPUT:-{}}"

SESSION_ID="${CURSOR_TRACE_ID:-}"
if [ -z "${SESSION_ID}" ]; then
  SESSION_ID="$(printf '%s' "${HOOK_INPUT}" | jq -r '.session_id // .sessionId // .conversation_id // .conversationId // .trace_id // .traceId // empty' 2>/dev/null || true)"
fi
if [ -z "${SESSION_ID}" ]; then
  SESSION_ID="hook-$(date +%Y%m%d)-${PPID:-$$}"
fi

BRANCH_NAME="$(git -C "${REPO_ROOT}" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")"
MODIFIED_FILES="$(git -C "${REPO_ROOT}" diff --name-only --relative HEAD 2>/dev/null || true)"
UNTRACKED_FILES="$(git -C "${REPO_ROOT}" ls-files --others --exclude-standard 2>/dev/null || true)"

FILES_JSON="$(
  printf '%s\n%s\n' "${MODIFIED_FILES}" "${UNTRACKED_FILES}" \
    | jq -R . \
    | jq -s 'map(select(length > 0)) | unique'
)"

METADATA_JSON="$(
  jq -cn \
    --arg hook "stop" \
    --arg branch "${BRANCH_NAME}" \
    --arg repo_root "${REPO_ROOT}" \
    --arg trace_id "${CURSOR_TRACE_ID:-}" \
    --argjson files "${FILES_JSON}" \
    '{hook:$hook, branch:$branch, repo_root:$repo_root, trace_id:$trace_id, observed_files:$files}'
)"

sql_escape() {
  printf "%s" "$1" | sed "s/'/''/g"
}

FILES_SQL="$(sql_escape "${FILES_JSON}")"
METADATA_SQL="$(sql_escape "${METADATA_JSON}")"
SESSION_SQL="$(sql_escape "${SESSION_ID}")"
TIMESTAMP="$(date +%s)"

sqlite3 "${DB_PATH}" <<SQL
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS brain_events (
  event_id INTEGER PRIMARY KEY AUTOINCREMENT,
  timestamp REAL NOT NULL,
  session_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  tool_name TEXT,
  files_touched TEXT NOT NULL,
  token_cost INTEGER NOT NULL DEFAULT 0,
  duration_ms INTEGER NOT NULL DEFAULT 0,
  metadata TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_brain_events_session_time
ON brain_events(session_id, timestamp DESC);
INSERT INTO brain_events (
  timestamp,
  session_id,
  event_type,
  tool_name,
  files_touched,
  token_cost,
  duration_ms,
  metadata
) VALUES (
  ${TIMESTAMP},
  '${SESSION_SQL}',
  'session_end',
  'cursor_stop_hook',
  '${FILES_SQL}',
  0,
  0,
  '${METADATA_SQL}'
);
SQL

echo "[observe-hook] Recorded stop event for ${SESSION_ID}"
exit 0
