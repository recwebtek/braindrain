# BRAINDRAIN — Protocol

## Rules (Core)

1. **Environment first**: call `get_env_context()` at start.
2. **Discover before loading**: call `search_tools()`.
3. **Route big outputs**: use `route_output()`.
4. **Measure**: call `get_token_dashboard()`.
5. **Keep docs current**: update progress/ops logs.
6. **No self-probing**: use the cached context.

| Tool | Purpose |
|---|---|
| `get_env_context()` | Cached OS fingerprint |
| `prime_workspace()` | Deploy rules to project |
| `search_tools()` | Discover deferred tools |
| `route_output()` | Index large text |
| `search_index()` | Retrieve from index |
| `get_token_dashboard()` | Savings snapshot |

---

## BRAINDRAIN token-saving workflow (most important)

Use this sequence to avoid wasting context tokens on environment probing and large dumps:

1. **Start**: `get_env_context()` before any shell commands, installs, or tool assumptions.
2. **Find tools before reading/searching**: `search_tools()` to discover the right capability.
3. **Don’t paste big blobs into chat**: `route_output()` for large text; retrieve later with `search_index()`.
4. **Checkpoint**: `get_token_dashboard()` at milestones to track savings.

### Chat vs Agent mode (cost)

- **Chat**: best for short Q&A and review; avoid pasting full plans, audit reports, or large tool dumps into the thread.
- **Agent**: multi-step implementation; use `search_tools()` and the MCP catalog before loading deferred servers.
- **Reset chat after plan stages**: when architect/coordinator planning finishes, start a **new chat** for build work. Carry state via `*.plan.md`, `_master.plan.md`, `get_session_summary()`, and `.braindrain/` memory — not the full planning transcript.

### Output routing (enforced)

- When `cost_tracking.auto_route_output` is enabled, payloads **>4096 chars** are indexed unless `force_inline=true`.
- Always pair `route_output()` → `search_index()` using the returned `handle`, `index_id`, or `retrieval_hint` — never re-paste the raw blob into chat.

### MCP catalog (folder discovery)

- Run `export_mcp_catalog()` (or read `.braindrain/mcp-catalog/` after priming) before attaching heavy deferred MCP servers.
- Discover capabilities with `rg` on catalog markdown (mirrors Cursor per-server tool folders).
- Native braindrain tools are listed under `.braindrain/mcp-catalog/braindrain/tools/`.

### Search and embeddings (no cloud required by default)

- **`search_index`** → context-mode FTS5 only. **No** embedding API and **no** Mixedbread unless you opt in.
- **`search_tools`** → BM25 over the hub tool registry.
- **Optional rerank** (`modules.tool_gate.rerank_on_search`, default `false`):
  - `rerank_provider: none | lexical | mixedbread | auto`
  - `lexical` = offline; `auto` = Mixedbread when `MIXEDBREAD_API_KEY` is set, else lexical.
- **Embeddings** (`embeddings` in `hub_config.yaml`) are for future semantic workflows — local-first: `lmstudio_local`, `ollama_local`, then cloud. Not used by default `search_index`.
- Token-light workflows: `ingest_codebase` (conditional `ai_distiller`), `refactor_prep_token_light` (filescope + editor before heavy map when budget is low).

### Session compaction

- During work: `touch_session(session_id, tool_name=..., files_modified=..., key_decision=...)`.
- On stage end: `touch_session(..., end_session=true)` — emits a **≤2 KB** package (`decisions`, `files_touched`, `failures`, `open_todos`).
- Retrieve via `get_session_summary(session_id)` or `search_index` when a `context_index_handle` is returned.
- Pair with context-mode **SessionStart** / **PreCompact** hooks when configured.

### Rule bulk cap (post-`prime_workspace` audit)

Keep generated agent rules lean after priming:

- One always-apply protocol surface (`braindrain.mdc` / `RULES.md`) — do **not** duplicate the full token table in every agent file.
- Project-only facts stay in `project-rules.mdc` (from `.braindrain/AGENT_MEMORY.md`, `OPS.md`).
- Deferred MCP tool definitions belong in `.braindrain/mcp-catalog/`, not inlined into rules.
- Checklist: no duplicate checkpoint tables; link to this section instead of copying.

### Subagent token budget (coordinator / Task tool)

- **Parallel cap:** max **3** concurrent Task/subagent dispatches (use **2** under token pressure).
- **Before a subagent batch:** `get_token_dashboard()` + `record_token_checkpoint(phase="pre_high_cost", context_tags=["subagent"])`.
- **After a subagent batch:** `get_token_dashboard()` + `record_token_checkpoint(phase="post_high_cost", context_tags=["subagent"])`.
- **Cheaper models:** `testops` → flash/fast tier; `toolcall` / `research` / `embedding` → `fast`; reserve heavier models for `[BUILD]` and architect/coordinator planning.
- **`models.tier_local`** in `config/hub_config.yaml` is for routing/extraction/simple tasks (local LM Studio), not primary implementation agents.
- Route large subagent output via `route_output()` → `search_index()`; do not inline into coordinator chat.

### Token Checkpoint Protocol (required)

Use this protocol when capturing token observability data:

| Trigger | Required | Tooling | Notes |
|---|---|---|---|
| Task start | Yes | `get_token_dashboard()` | Baseline snapshot before meaningful work begins |
| Before high-cost operation | Yes | `get_token_dashboard()` | High-cost = broad searches, large-output reads, subagent batches, long-running commands |
| After high-cost operation | Yes | `get_token_dashboard()` | Capture immediate delta and annotate operation type |
| Milestone/phase close | Yes | `get_token_stats()` | Full attribution and per-tool breakdown |
| Task end | Yes | `get_token_dashboard()` + `get_token_stats()` | Final summary plus detailed closing stats |
| Trivial/no-op action | Optional skip | None | Skip only when no meaningful token movement is expected |

### Token Metrics Schema (versioned)

When persisting records to `.braindrain/token-metrics.jsonl`, each JSONL row must include:

- `schema_version` (string, current: `1.0`)
- `timestamp` (ISO-8601 UTC)
- `task` (short task identifier)
- `phase` (`start|pre_high_cost|post_high_cost|milestone_close|end`)
- `tool` (`get_token_dashboard|get_token_stats`)
- `totals` object with:
  - `estimated_raw_tokens` (number)
  - `actual_context_tokens` (number)
  - `saved_tokens` (number)
- `context_tags` (string array, e.g. `["search","docs","subagent"]`)
- `note` (short human-readable summary)

Example JSONL row:
`{"schema_version":"1.0","timestamp":"2026-04-06T12:00:00Z","task":"token-stats-rule-system","phase":"post_high_cost","tool":"get_token_dashboard","totals":{"estimated_raw_tokens":6400,"actual_context_tokens":2100,"saved_tokens":4300},"context_tags":["docs","search"],"note":"Captured after cross-file wording audit."}`

### Token Protocol Validation Gates

- PASS only if all policy surfaces use the same cadence semantics.
- PASS only if `get_token_dashboard()` is documented as quick snapshot and `get_token_stats()` as detailed attribution.
- PASS only if large-output handling is documented as `route_output() -> search_index()`.
- FAIL if `.braindrain/token-metrics.jsonl` is presented as a replacement for `~/.braindrain/costs/session.jsonl`.
- FAIL if `schema_version` is missing from JSONL checkpoint documentation.

### BRAINDRAIN hot tools (cheat sheet)

| Tool | Purpose |
|---|---|
| `get_env_context(refresh=False)` | Cached OS fingerprint — call this first |
| `prime_workspace(path=".", agents=None, dry_run=False, sync_templates=False, sync_subagents=False, all_agents=False, local_only=True, codex_agent_targets=None, bundle="core")` | Prime project; auto-detects IDE, applies bundle manifest, writes `.braindrain/primed.json`, deploys Cursor/Codex subagent files and Cursor hook templates |
| `search_tools(query, top_k=5)` | Discover deferred tools by capability |
| `route_output(text, source, ...)` | Index large text into context-mode |
| `search_index(query, limit=5)` | Retrieve from FTS5 index |
| `list_workflows()` | List available workflows |
| `run_workflow(name, args)` | Execute workflow in sandbox |
| `plan_workflow(name, args)` | Review plan before running |
| `init_project_memory(path, dry_run=False)` | Initialize project memory artifacts |
| `get_token_dashboard()` | Token savings snapshot |
| `get_token_stats()` | Full session cost breakdown |
| `record_token_checkpoint(phase, task, ...)` | Append schema 1.0 row to `.braindrain/token-metrics.jsonl` |
| `export_mcp_catalog(dry_run=False)` | Write `.braindrain/mcp-catalog/` for `rg` discovery |
| `touch_session(session_id, ...)` | Session telemetry; `end_session=true` for compact package |
| `get_session_summary(session_id)` | Latest ≤2 KB session summary + retrieval hint |
| `get_available_tools()` | Show hot vs deferred tools |
| `ping()` | Health check |
| `refresh_env_context()` | Re-probe OS environment (deferred) |

<!-- SCRIPTLIB_GUIDANCE -->

### Cursor Plan Build — branch guard (required)

Clicking **Build** on a Cursor plan runs the **default workspace agent**, not the coordinator subagent. Before any implementation edits when working from a `*.plan.md`:

1. Resolve the plan branch: run `python3 scripts/daily_plan_audit.py --repo-root .` (or `/masterplan`) so frontmatter `branch:` is reconciled with **git** and **gh** — do not trust a stale auto-generated slug; then read `.braindrain/plan-reports/master-plan.md` for branch/PR.
2. **First shell command:** `python3 scripts/plan_build_guard.py --plan <repo-relative-plan-path> --repo-root .`
3. Proceed only when the guard reports `"ok": true` (creates branch with `git branch` if needed; checkout uses stash + `git switch` when dirty).
4. Do not implement on an unrelated branch (e.g. a feature branch for a different plan).

Gitops `branch-setup` mode must **not** checkout. Checkout is allowed only for `plan-execution` / Plan Build guard flows.

### Planning session close-out (Cursor / Codex)

When you **create or finish editing** a tracked plan file under an IDE `plans/` directory (for example `.cursor/plans/*.plan.md`):

**Planning-owned agents** (for example `architect`, `coordinator`, or any agent authoring `*.plan.md` in a `plans/` tree) **must** complete this close-out **before ending the turn** when a new or materially updated plan was written:

1. Ensure `_master.plan.md` links any new active plans (markdown links under `## active`, top-to-bottom = default build order). Optional frontmatter: `execution_order:` (override list), `goalposts:` (alignment hints for overseer reports).
2. Run the planning auditor so reports stay current — either invoke the `daily-plan-auditor` subagent or run:
   `python3 scripts/daily_plan_audit.py --repo-root . --trigger "post-planning-session"`
   (The Cursor stop hook may also run the auditor, but it is daily-gated; session close-out should not rely on the hook alone.)
3. For **replan** work, prefer a **new** plan file and record supersession in the master index rather than overwriting the old file in place.
4. Mark abandoned plans `disposition: archived` (or `archived: true` / `status: archived`), or list them under `archived_plans:` / `archive:` in `_master.plan.md` frontmatter; the next auditor run moves them to `.plan.archives/` under the same `plans/` directory.

### Model provenance and footer policy

Use `provenance` settings from `config/hub_config.yaml` as the source of truth:

- `provenance.chat_footer.enabled` + `provenance.chat_footer.scope` controls chat footer inclusion.
  - `all_agents`: append footer on every completion message.
  - `planning_only`: append footer on planning/audit/coordination completions only.
  - `off`: do not append footer.
- Footer format: `model: <model_name> | date: <YYYY-MM-DD>` using `provenance.date_format`.
- When model identity is not available from the host, use `model: auto` (never invent model names).
- In `planning_only` scope, when creating or materially rewriting any `*.plan.md`, include YAML frontmatter metadata at first write (not later patch-up), including:
  - plan metadata: `name`, `owner`, `dri`, `disposition`, `priority`, `parent`, `ide`, `isProject`, `todos`
  - provenance metadata: `created_by_model`, `created_at`, `last_modified_by_model`, `last_modified_at`, `cursor_mode`
- For plan files and generated plan reports, include provenance in YAML frontmatter:
  - `created_by_model`, `created_at`, `last_modified_by_model`, `last_modified_at`, `cursor_mode`.
- For sub-agent operations, record model provenance events to
  `.braindrain/plan-reports/model-trace.jsonl` when `provenance.subagent_trace.enabled=true`.

### Ops/docs to keep current (when behaviour/run paths/tools change)

- `.braindrain/SESSION_PROGRESS.md`
- `.braindrain/OPS.md`
- `.braindrain/AGENT_MEMORY.md`
- `README.md`
- `.devdocs/SESSION_PROGRESS.md` (if repo-local collaboration logs are in use)
- `.braindrain/token-metrics.jsonl` (optional machine-local checkpoint stream)

### Ownership boundaries (important)

- `AGENTS.md` is generated protocol and environment context only.
- High-signal project memory belongs in `.braindrain/AGENT_MEMORY.md` (gitignored, never committed).
- Use `prime_workspace()` for full project onboarding and `init_project_memory()` for memory-only initialization.
- `.braindrain/` is **never** committed — it is machine-local and gitignored.
- Token telemetry source-of-truth remains machine-local (`~/.braindrain/costs/session.jsonl`); `.braindrain/token-metrics.jsonl` is an optional machine-local checkpoint artifact.

### Git / secrets (do not leak local state)

- `prime_workspace()` runs `ruler apply` with **`--no-gitignore`** so Ruler does not own `.gitignore`. Braindrain appends a **BRAINDRAIN GITIGNORE PROTOCOL** block that ignores **root-level** dotfiles (`/.*`) with explicit `!` exceptions for paths that must ship (e.g. `/.github/`, `/.gitignore`, `/.env.example`). Extend `!` lines only when your team commits another root dotdir.
- Never commit env files, MCP tokens, or IDE-only config.

## Environment Context Protocol

Before running any shell commands, installing packages, or assuming tool
availability — call `get_env_context()` first.

It tells you:
- Exact hostname, username, and LAN IPs
- Which package manager to use (`brew` vs `apt` vs `dnf` etc.)
- Which Python interpreters are in PATH and which is active via pyenv
- Active runtimes and their version managers
- Which modern CLI tools are installed (`fd`, `bat`, `rg`, `fzf` …)
- Which IDEs/agents have MCP configs and where those files live
- Which LLM servers are running locally and on what ports
- Shell type, browsers, VM tools, GUI tools
- Agent behaviour hints (what to prefer and avoid on this OS)

**Never probe the environment yourself.** If something seems missing,
call `refresh_env_context()`.
