---
description: End-of-chat memory capture — session compaction, L2 promotion, dream guidance, project markdown
---

# brainlog

Run this **only when the chat task is largely complete** and you want to persist what mattered for the next session.

Do **not** run at session start or mid-task unless the user explicitly asks to close out early.

## Prerequisites

- BRAINDRAIN MCP connected (`ping()` ok).
- `init_project_memory(path=".")` already run once in this workspace (creates `.braindrain/` templates).
- Memory tunables live in `config/hub_config.yaml` (`sessions`, `wiki_brain`, `lessons`, `dreaming`, `memory_learning`).

## Session identity

Pick a stable `session_id` for this chat:

1. Reuse the same id if you already called `touch_session` in this thread.
2. Else use env `CURSOR_TRACE_ID` when set.
3. Else generate a short UUID and reuse it for all steps below.

## Step 1 — Finalize L1 session (required)

From this conversation, collect:

- `files_modified`: paths touched (repo-relative)
- `key_decision`: 1–3 durable decisions (not transient debug notes)
- `error`: failures worth remembering (or omit)
- `open_todos`: carry-forward items (or omit)

Call:

```
touch_session(
  session_id="<session_id>",
  files_modified=[...],
  key_decision="...",
  error="...",              # optional
  open_todos=[...],         # optional
  end_session=true,
  index_in_context_mode=true,
)
```

Save from the response: `compact_package`, `context_index_handle`, `retrieval_hint`.

## Step 2 — Token close checkpoint (required)

```
get_token_dashboard()
record_token_checkpoint(
  phase="end",
  task="brainlog",
  note="end-of-chat session close",
  context_tags=["session", "brainlog"],
  path=".",
)
get_token_stats()
```

## Step 3 — Verify compact package (required)

```
get_session_summary(session_id="<session_id>")
```

Confirm `compact_package` exists. If `retrieval_hint` is present, note it for the user (next chat can use `search_index` with that handle — do not paste the full package into chat).

## Step 4 — L2 promotion gate (when something is worth keeping)

For each **candidate** durable fact or lesson (preferences, run paths, architecture invariants, repeated corrections):

1. `evaluate_memory_candidate(candidate="<one sentence>")`
2. If promotion is allowed:
   - **Semantic fact:** `store_fact(content="...", record_class="semantic", evidence_refs=[...])`
   - **Lesson-shaped work:** `record_episode(session_id="...", problem="...", context="...", action="...", outcome="...", evidence_refs=[...])` then `evaluate_lesson_candidate_tool(...)`; promote only when grounded.

Skip L2 writes for secrets, one-off debug, or transient state (today-only notes).

## Step 5 — L3 dream guidance (conditional)

```
get_dream_status()
```

- If the user wants consolidation **now** and quiet-window policy allows: `run_dream(mode="full", force=false)` (use `force=true` only when the user explicitly requests it).
- Otherwise: tell the user dream runs after `dreaming.quiet_minutes` (default 30) of session inactivity, via `scripts/run_dream_cron.sh`, or on macOS after host HID idle when `dreaming.triggers.macos_host_idle.enabled: true` **and** `./scripts/install_dream_watch_launchd.sh` was run for this workspace — do not block on dream completion.

## Step 6 — Project markdown (manual, required when ops facts changed)

Update machine-local files under `.braindrain/` (never commit):

| File | When to update |
|------|----------------|
| `SESSION_PROGRESS.md` | What shipped this session, blockers, next steps (dated block) |
| `AGENT_MEMORY.md` | Only **stable** Learned User Preferences / Learned Workspace Facts |
| `OPS.md` | Run paths, ports, tooling, env boundaries that changed |

If any of the above changed, run `prime_workspace(path=".", agents=["cursor"])` **or** note that the user should re-prime so `project-rules.mdc` picks up `.braindrain/` excerpts.

## Step 7 — Planning overlap (only if applicable)

If this session edited `*.plan.md` under a `plans/` tree, also run `/masterplan` (or `python3 scripts/daily_plan_audit.py --repo-root . --trigger "brainlog-closeout"`) — brainlog does **not** replace planning close-out.

## Report back

Provide a short structured summary:

1. **session_id** and whether L1 end succeeded
2. **retrieval_hint** / handle for next chat (one line)
3. **L2:** candidates evaluated, facts/episodes stored (or "none promoted")
4. **L3:** dream run result or scheduled guidance
5. **Markdown:** which `.braindrain/*.md` files were updated (or "unchanged")
6. **Token:** dashboard snapshot headline (saved vs raw if available)
7. **Next chat:** one sentence on how to resume (`get_session_summary` / `search_index`)

If nothing durable was learned, say so explicitly — do not invent memory writes.
