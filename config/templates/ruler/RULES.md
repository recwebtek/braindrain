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
| `prime_workspace(path=".", agents=None, dry_run=False, sync_templates=False, all_agents=False, local_only=True)` | Prime project; auto-detects IDE, writes `.braindrain/primed.json` |
| `search_tools(query, top_k=5)` | Discover deferred tools by capability |
| `route_output(text, source, ...)` | Index large text into context-mode |
| `search_index(query, limit=5)` | Retrieve from FTS5 index |
| `list_workflows()` | List available workflows |
| `run_workflow(name, args)` | Execute workflow in sandbox |
| `plan_workflow(name, args)` | Review plan before running |
| `init_project_memory(path, dry_run=False)` | Initialize project memory artifacts |
| `get_token_dashboard()` | Token savings snapshot |
| `get_token_stats()` | Full session cost breakdown |
| `get_available_tools()` | Show hot vs deferred tools |
| `ping()` | Health check |
| `refresh_env_context()` | Re-probe OS environment (deferred) |

<!-- SCRIPTLIB_GUIDANCE -->

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
