#!/usr/bin/env bash
# on-stop-gitops-plans.sh
# Cursor stop hook: detects recently updated *.plan.md under IDE plans/ trees
# and queues branch-setup with planSource linkage for the gitops agent.
#
# Idempotent: uses plan file content hash. Does not checkout branches.

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
QUEUE_FILE="${REPO_ROOT}/.cursor/.gitops-queue.json"
PLANS_ROOT="${REPO_ROOT}/.cursor/plans"
NOW=$(date +%s)
MAX_AGE=120

[ -d "$PLANS_ROOT" ] || exit 0

BASE_BRANCH="main"
if ! git -C "$REPO_ROOT" show-ref --verify --quiet refs/heads/main 2>/dev/null; then
  BASE_BRANCH=$(git -C "$REPO_ROOT" symbolic-ref refs/remotes/origin/HEAD 2>/dev/null \
    | sed 's@^refs/remotes/origin/@@' || echo "main")
fi

DETECTED_AT=$(date -u +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || date -u +"%Y-%m-%dT%H:%M:%SZ")

_plan_type_from_file() {
  local f="$1"
  local head
  head=$(head -20 "$f" | tr '[:upper:]' '[:lower:]')
  if echo "$head" | grep -qE '\bbugfix\b|\bbug\b|\bfix\b'; then
    echo "bugfix"
  elif echo "$head" | grep -qE '\bhotfix\b|\bhot\b'; then
    echo "hotfix"
  elif echo "$head" | grep -qE '\bchore\b|\bmaintenance\b|\bdependenc'; then
    echo "chore"
  elif echo "$head" | grep -qE '\brefactor\b'; then
    echo "refactor"
  elif echo "$head" | grep -qE '\bdocs\b|\bdocumentation\b'; then
    echo "docs"
  else
    echo "feature"
  fi
}

_slug_from_plan() {
  local f="$1"
  local raw
  raw=$(grep -m1 '^#' "$f" 2>/dev/null | sed 's/^# *//' || basename "$f" .plan.md)
  echo "$raw" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]/-/g' | sed 's/--*/-/g' | sed 's/^-//' | sed 's/-$//' | cut -c1-40
}

_append_queue_entry() {
  local entry="$1"
  if [ -f "$QUEUE_FILE" ] && grep -q '\[' "$QUEUE_FILE" 2>/dev/null; then
    local tmp="${QUEUE_FILE}.tmp.$$"
    local existing trimmed
    existing=$(cat "$QUEUE_FILE")
    trimmed=$(echo "$existing" | sed -e 's/[[:space:]]*\]$//' -e 's/[[:space:]]*$//')
    printf '%s,\n  %s\n]\n' "$trimmed" "$entry" > "$tmp"
    mv "$tmp" "$QUEUE_FILE"
  else
    mkdir -p "$(dirname "$QUEUE_FILE")"
    printf '[\n  %s\n]\n' "$entry" > "$QUEUE_FILE"
  fi
}

queued=0
while IFS= read -r -d '' plan_file; do
  base=$(basename "$plan_file")
  [ "$base" = "_master.plan.md" ] && continue
  case "$base" in *.plan.md) ;; *) continue ;; esac

  mtime=$(stat -f "%m" "$plan_file" 2>/dev/null || stat -c "%Y" "$plan_file" 2>/dev/null || echo 0)
  age=$(( NOW - mtime ))
  [ "$age" -le "$MAX_AGE" ] || continue

  plan_hash=$(sha256sum "$plan_file" 2>/dev/null | cut -c1-8 \
    || shasum -a 256 "$plan_file" 2>/dev/null | cut -c1-8 \
    || echo "00000000")
  if [ -f "$QUEUE_FILE" ] && grep -q "\"planHash\": \"${plan_hash}\"" "$QUEUE_FILE" 2>/dev/null; then
    continue
  fi

  plan_type=$(_plan_type_from_file "$plan_file")
  slug=$(_slug_from_plan "$plan_file")
  [ -z "$slug" ] && slug="plan"
  branch_name="${plan_type}/${slug}"
  rel_plan=".cursor/plans/${base}"

  new_entry=$(cat <<EOF
{
    "action": "branch-setup",
    "planType": "${plan_type}",
    "branchName": "${branch_name}",
    "baseBranch": "${BASE_BRANCH}",
    "planSource": "${rel_plan}",
    "planHash": "${plan_hash}",
    "detectedAt": "${DETECTED_AT}",
    "status": "pending"
  }
EOF
)
  _append_queue_entry "$new_entry"
  queued=$((queued + 1))
  echo "[gitops-plans-hook] Queued branch-setup for ${rel_plan}: ${branch_name} (hash: ${plan_hash})"
done < <(find "$PLANS_ROOT" -maxdepth 1 -name '*.plan.md' -type f -print0 2>/dev/null)

[ "$queued" -eq 0 ] && exit 0
exit 0
