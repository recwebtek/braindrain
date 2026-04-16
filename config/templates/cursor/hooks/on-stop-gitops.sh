#!/usr/bin/env bash
# on-stop-gitops.sh
# Cursor stop hook: detects when TASK-GRAPH.md is newly written/updated
# and queues a branch-setup action for the gitops agent.
#
# Idempotent: uses content hash to avoid re-queuing the same plan version.
# The gitops agent reads .cursor/.gitops-queue.json on startup and processes
# pending entries without switching the user's active branch.
#
# Location: .cursor/hooks/on-stop-gitops.sh
# Configured in: .cursor/hooks.json (stop hook)

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
TASK_GRAPH="${REPO_ROOT}/.cursor/TASK-GRAPH.md"
QUEUE_FILE="${REPO_ROOT}/.cursor/.gitops-queue.json"

# Only proceed if TASK-GRAPH.md exists
[ -f "$TASK_GRAPH" ] || exit 0

# Only proceed if TASK-GRAPH.md was modified in the last 120 seconds
MTIME=$(stat -f "%m" "$TASK_GRAPH" 2>/dev/null || stat -c "%Y" "$TASK_GRAPH" 2>/dev/null || echo 0)
NOW=$(date +%s)
AGE=$(( NOW - MTIME ))
if [ "$AGE" -gt 120 ]; then
  exit 0
fi

# Compute content hash (first 8 chars of sha256)
PLAN_HASH=$(sha256sum "$TASK_GRAPH" 2>/dev/null | cut -c1-8 \
  || shasum -a 256 "$TASK_GRAPH" 2>/dev/null | cut -c1-8 \
  || echo "00000000")

# Check if this hash already exists in the queue (idempotent)
if [ -f "$QUEUE_FILE" ]; then
  if grep -q "\"planHash\": \"${PLAN_HASH}\"" "$QUEUE_FILE" 2>/dev/null; then
    # Same plan version already queued — skip
    exit 0
  fi
fi

# Parse plan type from TASK-GRAPH.md
# Look for keywords in the first 20 lines: feature, bugfix, hotfix, chore, refactor, docs
PLAN_TYPE="feature"  # default
HEAD_CONTENT=$(head -20 "$TASK_GRAPH" | tr '[:upper:]' '[:lower:]')
if echo "$HEAD_CONTENT" | grep -qE '\bbugfix\b|\bbug\b|\bfix\b'; then
  PLAN_TYPE="bugfix"
elif echo "$HEAD_CONTENT" | grep -qE '\bhotfix\b|\bhot\b'; then
  PLAN_TYPE="hotfix"
elif echo "$HEAD_CONTENT" | grep -qE '\bchore\b|\bmaintenance\b|\bdependenc'; then
  PLAN_TYPE="chore"
elif echo "$HEAD_CONTENT" | grep -qE '\brefactor\b'; then
  PLAN_TYPE="refactor"
elif echo "$HEAD_CONTENT" | grep -qE '\bdocs\b|\bdocumentation\b'; then
  PLAN_TYPE="docs"
fi

# Derive slug from TASK-GRAPH.md title (first # heading or filename hint)
RAW_TITLE=$(grep -m1 '^#' "$TASK_GRAPH" 2>/dev/null | sed 's/^# *//' || echo "")
if [ -z "$RAW_TITLE" ]; then
  RAW_TITLE=$(head -3 "$TASK_GRAPH" | tr '\n' ' ' | sed 's/[^a-zA-Z0-9 ]/ /g')
fi
# Lowercase, replace spaces/special chars with hyphens, trim to 40 chars
SLUG=$(echo "$RAW_TITLE" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]/-/g' | sed 's/--*/-/g' | sed 's/^-//' | sed 's/-$//' | cut -c1-40)
[ -z "$SLUG" ] && SLUG="plan"

BRANCH_NAME="${PLAN_TYPE}/${SLUG}"
BASE_BRANCH="main"

# Detect default branch if main doesn't exist
if ! git -C "$REPO_ROOT" show-ref --verify --quiet refs/heads/main 2>/dev/null; then
  BASE_BRANCH=$(git -C "$REPO_ROOT" symbolic-ref refs/remotes/origin/HEAD 2>/dev/null \
    | sed 's@^refs/remotes/origin/@@' || echo "main")
fi

DETECTED_AT=$(date -u +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || date -u +"%Y-%m-%dT%H:%M:%SZ")

# Build the new queue entry
NEW_ENTRY=$(cat <<EOF
{
    "action": "branch-setup",
    "planType": "${PLAN_TYPE}",
    "branchName": "${BRANCH_NAME}",
    "baseBranch": "${BASE_BRANCH}",
    "planHash": "${PLAN_HASH}",
    "detectedAt": "${DETECTED_AT}",
    "status": "pending"
  }
EOF
)

# Append to queue file (or create it)
if [ -f "$QUEUE_FILE" ] && grep -q '\[' "$QUEUE_FILE" 2>/dev/null; then
  # Queue exists with array — insert before the closing ]
  # Use a temp file for safe write
  TMP_FILE="${QUEUE_FILE}.tmp.$$"
  # Remove trailing ] and any trailing whitespace/newlines, add comma, append new entry
  # Result: clean JSON array with consistent formatting
  EXISTING=$(cat "$QUEUE_FILE")
  # Strip the closing ] and any whitespace after the last }
  TRIMMED=$(echo "$EXISTING" | sed -e 's/[[:space:]]*\]$//' -e 's/[[:space:]]*$//')
  printf '%s,\n  %s\n]\n' "$TRIMMED" "$NEW_ENTRY" > "$TMP_FILE"
  mv "$TMP_FILE" "$QUEUE_FILE"
else
  # Create new queue file
  cat > "$QUEUE_FILE" <<QEOF
[
  ${NEW_ENTRY}
]
QEOF
fi

echo "[gitops-hook] Queued branch-setup: ${BRANCH_NAME} (hash: ${PLAN_HASH})"
exit 0
