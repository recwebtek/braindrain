# braindrain

[![CI](https://github.com/recwebtek/braindrain/actions/workflows/ci.yml/badge.svg)](https://github.com/recwebtek/braindrain/actions/workflows/ci.yml)

**Version:** V1.0.3  
**Last Updated:** 2026-06-11

An MCP server that keeps AI agents lean. It stops context windows bloating with redundant tool definitions, large raw outputs, and repeated environment discovery — and gives agents the right information at the right time instead.

Built on [FastMCP](https://gofastmcp.com). Works with Cursor, Zed, Windsurf, OpenCode, Antigravity, Codex, and any MCP-compatible client.

---

## The problem it solves

Every AI session starts with the same waste:

- The agent loads tool definitions it will never use — each one costs tokens before a single line of code is written
- Large tool outputs get dumped raw into context — a 10,000-token blob when you needed 200 words
- The agent probes the environment from scratch — `which python3`, `uname`, `ls ~/.config` — questions it has asked a hundred times before

braindrain eliminates all three.

---

## How it works

braindrain runs as a local MCP server alongside your AI client. It exposes a small set of always-loaded (HOT) tools and a larger set of deferred tools that are only described to the agent when it searches for them. The agent stays lean by default and pulls in capability on demand.

Large outputs are routed through a local FTS5 index ([context-mode](https://github.com/zcaceres/context-mode)) instead of being dumped into the context window. The agent gets a handle and a set of suggested queries — it retrieves only the relevant chunks.

OS environment data is probed once, cached locally, and served instantly on every subsequent call. The agent never has to discover Python versions, IDE configs, or running services again.

---

---

## Tools

### Environment


| Tool                    | When to use                                                                                                                                                                                                                                                                           |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `get_env_context()`     | **Call this first** in any session. Returns a cached snapshot of the machine: Python interpreters, package managers, installed IDEs and their MCP configs, running LLM servers, browsers, VM tools, GUI tools, CLI tools, and agent behaviour hints. Zero cost after the first probe. |
| `refresh_env_context()` | After installing new tools, switching machines, or any time the cached data feels stale. Re-runs the full probe (~5s) and updates the cache.                                                                                                                                          |


### Tool discovery


| Tool                           | When to use                                                                                                                                                                                              |
| ------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `search_tools(query, top_k=5)` | Before loading any external MCP tool. Searches the configured tool registry by capability. Returns lightweight references — not full definitions. Prevents loading 26K-token tool schemas unnecessarily. |
| `get_available_tools()`        | Lists all configured tools and whether they are HOT (always loaded) or deferred (loaded on demand).                                                                                                      |
| `export_mcp_catalog(path=".")` | Writes `.braindrain/mcp-catalog/<server>/tools/*.md` for folder-discovery. Run after `hub_config.yaml` changes; use `rg` on the catalog before loading heavy deferred MCP servers.                      |


### Output routing


| Tool                                 | When to use                                                                                                                                                  |
| ------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `route_output(text, source, intent)` | When a tool returns a large blob. Indexes it into a local FTS5 store and returns a handle + suggested queries. The raw text never enters the context window. |
| `search_index(query, limit=5)`       | Retrieve relevant chunks from a previously routed output. Uses **context-mode FTS5** — no embedding API required. Optional `rerank=true` only when rerank is enabled in config (see below). |


### Search, embeddings, and rerank (P2)

**No Mixedbread or cloud API is required** for normal search:

| Path | Engine | API keys |
| ---- | ------ | -------- |
| `search_index` | context-mode `ctx_search` (FTS5) | None |
| `search_tools` | BM25 over `hub_config` tools | None |
| Optional rerank on `search_index` | Off by default (`rerank_on_search: false`) | Only if you enable cloud or `auto` rerank |

**Optional rerank** (`config/hub_config.yaml` → `modules.tool_gate`):

| `rerank_provider` | Behavior |
| ----------------- | -------- |
| `none` (default) | No rerank pass |
| `lexical` | Offline token overlap — no network |
| `mixedbread` | Cloud `/reranking` API (`MIXEDBREAD_API_KEY`) |
| `auto` | Mixedbread when key is set, else `lexical` |

Enable only after benchmarking: set `rerank_on_search: true` and choose a provider. Per-call override: `search_index(query, rerank=True)`.

**Embeddings** (`embeddings` in `hub_config.yaml`) are for future semantic workflows — **not** used by default `search_index`. Local-first providers (priority order):

| Provider | Kind | Endpoint |
| -------- | ---- | -------- |
| `lmstudio_local` | `openai_compat` | `POST {LMSTUDIO_BASE_URL}/embeddings` |
| `ollama_local` | `ollama` | `POST {OLLAMA_HOST}/api/embed` |
| Cloud fallbacks | `openai_compat` / `hf_inference` | Google AI Studio, Hugging Face, Mixedbread |

Set `embeddings.default_provider` (default: `lmstudio_local`). Programmatic helper: `braindrain.embeddings_client.embed_texts()`.

**Token-efficient workflows** (also in `hub_config.yaml`):

- `ingest_codebase` — runs `ai_distiller` first only when repo file count exceeds `options.distiller_when_file_count_gt` (default 200).
- `refactor_prep_token_light` — `filescope` + `text_editor` before `repo_mapper` / `jcodemunch` when `token_budget` &lt; 2000.

**Benchmark harness** (machine-local report under `.braindrain/plan-reports/`):

```bash
# Tracked CLI (also mirrored in .scriptlib/ when scriptlib is enabled)
python3 scripts/benchmark_token_savings_brain_mcp_hub_v1.py --repo-root . --fail-on-regression

# Pytest marker (used by nightly token-benchmark workflow)
uv run pytest -m token_benchmark
```

Replays deterministic fixtures in `tests/fixtures/token_benchmark/` through **hub-on** paths (`route_output`, `search_tools`, cached `get_env_context`, session compaction) vs a **hub-off** naive full-context baseline. Metrics align with `braindrain/telemetry.py` (`estimated_raw_tokens` / `actual_context_tokens` / `saved_tokens`). Minimum savings floor defaults to **25%** (`TOKEN_BENCHMARK_MIN_SAVINGS_PCT`). Nightly CI uploads the markdown report as a workflow artifact (not committed).


### Workflows


| Tool                                                     | When to use                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| -------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `list_workflows()`                                       | See what multi-step workflows are available.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| `prime_workspace(...)`                                   | Prime a project for AI agent use. **Parameters** include `sync_subagents`, `sync_templates`, `bundle` (`core` default), `codex_agent_targets`, `patch_user_cursor_mcp`, `compact_mcp_response`. **First run**: auto-detects current IDE/CLI (`CURSOR_*` → `TERM_PROGRAM` → dotfolders → fallback `cursor`); response includes `**detect_method`**. Uses `**config/bundles/<bundle>.yaml`** for bundle metadata. Always rewrites **minimal `.ruler/ruler.toml`** when targeting specific agents. Deploys Cursor/Codex subagent files from templates (`**subagents**`) and manages Codex `**BRAINDRAIN SUBAGENTS**` in `.codex/config.toml` when allowed (`**codex_subagent_config**`). After apply, syncs `**.cursor/rules/braindrain.mdc**` and `**project-rules.mdc**` from `.ruler/RULES.md` — see `**cursor_rules**`. When Cursor is in scope, copies `**config/templates/cursor/**` → `**.cursor/hooks.json**` and `**.cursor/hooks/*.sh**` — see `**cursor_hooks**` (create-only; `**sync_templates=true**` refreshes Ruler sources and hook templates). `**sync_subagents=true**` updates existing subagent files and managed Codex blocks (backup-first). Set `**all_agents=True**` for the full template. |
| `init_project_memory(path, dry_run)`                     | Initialize project memory artifacts only (`.braindrain/AGENT_MEMORY.md` and `.cursor/hooks/state/continual-learning-index.json`). Migrates legacy `.devdocs/` on first call. Idempotent.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| `scriptlib_enable(path, scope, harvest, dry_run)`        | Hard-opt-in project or global scriptlib. Project enable can immediately harvest reusable workspace scripts into `.scriptlib/`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| `scriptlib_harvest_workspace(path, dry_run)`             | Recursively copy script-like files from the workspace into the local project scriptlib catalog, honoring ignore rules.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| `scriptlib_search(query, ...)`                           | Search local and shared scriptlib entries before writing a new reusable helper script. Returns a `reuse                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| `scriptlib_describe(script_id, ...)`                     | Inspect metadata, scope, score, run mode, provenance, and pin/update status for one scriptlib entry.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| `scriptlib_run(script_id, ...)`                          | Execute a script through scriptlib with restored source context when paths are sensitive.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| `scriptlib_fork(script_id, new_variant_or_version, ...)` | Fork an existing scriptlib entry into a new version for safe edits.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| `scriptlib_promote(script_id, ...)`                      | Promote a validated project-local script into the shared personal scriptlib catalog. Requires approval.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| `scriptlib_list_updates(path)`                           | List pinned shared script artifacts with available updates for the current workspace.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| `scriptlib_apply_update(script_id, ...)`                 | Pin or upgrade a shared script artifact for the current workspace. Requires approval.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| `scriptlib_run_maintenance(path, scope, ...)`            | Refresh indexes, surface duplicates/promotions/updates, and optionally persist new ignore dirs.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| `scriptlib_catalog_status(path, ...)`                    | Summarize project/shared roots, shared pins, promotion candidates, and update state.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| `scriptlib_record_result(script_id, outcome, ...)`       | Update success score, mistakes, and validation state.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| `scriptlib_refresh_index(path, scope, dry_run)`          | Rebuild project/global scriptlib indexes and generated catalogs.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| `plan_workflow(name, args)`                              | Generate a markdown execution plan and review it before committing to a run. Use before any destructive or long-running workflow.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| `run_workflow(name, args)`                               | Execute a workflow. Intermediate output is routed through the sandbox — only the final summary returns to the agent.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |


`list_workflows()` includes `init_project_memory` and **`prime_cursor_orchestration`** (calls `prime_workspace` with `bundle=cursor-orchestration` — deploys agents, hooks, skills, `scripts/daily_plan_audit.py`, and `scripts/plan_build_guard.py`). Consumer slash commands (from `config/templates/cursor/commands/`, installed by `prime_workspace` into `.cursor/commands/`):

| Command | When to use |
| ------- | ----------- |
| `/prime-braindrain` | Onboard or refresh Cursor orchestration (rules, hooks, skills, auditor scripts). |
| `/brainlog` | **End of chat** — finalize L1 session compaction, token checkpoint, optional L2 wiki-brain promotion, L3 dream guidance, and reminders to update `.braindrain/AGENT_MEMORY.md` / `OPS.md` / `SESSION_PROGRESS.md`. |
| `/masterplan` | Manual planning close-out (`daily_plan_audit.py`); use after editing `*.plan.md`, not as a substitute for `/brainlog`. See cadence table in `config/templates/cursor/commands/masterplan.md`. |
| `/metaplan-closeout` | Split a `disposition: meta` umbrella plan into child `*.plan.md` files + `_master` links (`plan_meta_closeout.py`). |

Plan Build: run `python3 scripts/plan_build_guard.py --plan <path>` before edits (see Ruler `RULES.md`). Meta plans are blocked (`meta_plan_no_build`) — close out with `/metaplan-closeout` first.

### Telemetry


| Tool                    | When to use                                                      |
| ----------------------- | ---------------------------------------------------------------- |
| `get_token_dashboard()` | Quick snapshot of estimated tokens saved vs raw in this session. |
| `get_token_stats()`     | Full breakdown: per-tool savings, cache hits, cost avoided.      |
| `record_token_checkpoint(phase, task, note, context_tags, path=".")` | Append schema `1.0` rows to `<path>/.braindrain/token-metrics.jsonl`. Use the **workspace root** for `path` (same as `export_mcp_catalog`), not the JSONL file path. |

Async MCP tools record observer `tool_call` rows via `asyncio.to_thread` so SQLite writes do not block the event loop.

### MCP Apps (inline dashboards)

Cursor and other MCP App hosts can render interactive `ui://` HTML from braindrain without loading a separate frontend stack.

| Tool | When to use |
| ---- | ----------- |
| `show_token_dashboard()` | Inline token savings snapshot (JSON via `get_token_dashboard` stays separate). |
| `show_plan_board(path="")` | Interactive plan task board from `.braindrain/plan-reports/`. |
| `show_sigint_map(path="", session_id="")` | Operational topology graph (session, tools, hooks, plans, external MCP peers). |
| `poll_plan_board(...)` | **App-only** — refresh board and all plan-board write actions from the iframe (audit, sync, archive, disposition, masterplan). |
| `poll_sigint_map(...)` | **App-only** — refresh SIGINT map graph from the iframe (8s auto-poll). |

**Plan board UI:** filters, per-plan disposition dropdown, Recheck/Apply sync, archive/cancel, timestamp tags, and open-in-editor flow. Full reference: [`braindrain/mcp_apps/PLAN_BOARD_UI.md`](braindrain/mcp_apps/PLAN_BOARD_UI.md).

**SIGINT map UI:** SVG force graph of active-session ops intelligence from observer events + project config. Full reference: [`braindrain/mcp_apps/SIGINT_MAP_UI.md`](braindrain/mcp_apps/SIGINT_MAP_UI.md).

Restart the braindrain MCP server after `braindrain/mcp_apps/` or registration changes.


### Token Checkpoint Protocol

Use this cadence for consistent token observability:


| Trigger                    | Required      | Call                                             |
| -------------------------- | ------------- | ------------------------------------------------ |
| Task start                 | Yes           | `get_token_dashboard()`                          |
| Before high-cost operation | Yes           | `get_token_dashboard()`                          |
| After high-cost operation  | Yes           | `get_token_dashboard()`                          |
| Milestone or phase close   | Yes           | `get_token_stats()`                              |
| Task end                   | Yes           | `get_token_dashboard()` then `get_token_stats()` |
| Trivial/no-op action       | Optional skip | none                                             |


High-cost operations include broad searches, large-output reads, subagent batches, and long-running commands.

For large outputs, always use:
`route_output() -> search_index()`

Bad vs good large-output handling:

- Bad: paste a long tool dump directly into chat and then ask for analysis.
- Good: call `route_output()` on the dump, then query targeted chunks with `search_index()`.

### Token Metrics Contract (schema `1.0`)

Use `<workspace>/.braindrain/token-metrics.jsonl` as an optional machine-local checkpoint stream for checkpoint records (pass workspace root via `record_token_checkpoint(..., path=".")` or `export_mcp_catalog(path=".")`). Required fields per line:

- `schema_version` (`1.0`)
- `timestamp` (ISO-8601 UTC)
- `task`
- `phase` (`start|pre_high_cost|post_high_cost|milestone_close|end`)
- `tool` (`get_token_dashboard|get_token_stats`)
- `totals.estimated_raw_tokens`
- `totals.actual_context_tokens`
- `totals.saved_tokens`
- `context_tags` (string array)
- `note`

Example line:
`{"schema_version":"1.0","timestamp":"2026-04-06T12:00:00Z","task":"token-stats-rule-system","phase":"post_high_cost","tool":"get_token_dashboard","totals":{"estimated_raw_tokens":6400,"actual_context_tokens":2100,"saved_tokens":4300},"context_tags":["docs","search"],"note":"Captured after cross-file wording audit."}`

Validation gates:

- PASS only if checkpoint cadence is consistent across `RULES.md`, `AGENTS.md.template`, and `.cursor/rules/agent-system.mdc`.
- PASS only if `route_output() -> search_index()` appears as the large-output path.
- FAIL if `schema_version` is omitted in JSONL examples.
- FAIL if `.braindrain/token-metrics.jsonl` is treated as runtime telemetry source-of-truth.

### Utility


| Tool     | When to use                                                   |
| -------- | ------------------------------------------------------------- |
| `ping()` | Health check — confirms the server is running and responding. |


---

## Installation

### Quickstart (one command)

```bash
git clone https://github.com/recwebtek/braindrain.git
cd braindrain
./install.sh
```

`install.sh` now does a full guided setup:

- Validates Python **3.11-3.14** (fails fast on unsupported runtimes like 3.15+)
- Creates `.env.dev` early (before dependency steps) so env setup never gets skipped
- Installs full dependencies with visible progress, retries, and install logging to `.braindrain/install-logs/`
- Default install is **torch-free** (`pyproject.toml` is canonical); optional in-process embeddings via `pip install -e ".[embeddings]"`
- Runs fresh `get_env_context()` probe and regenerates `AGENTS.md`
- Creates `.braindrain/` (gitignored, machine-local — never committed)
- Runs an interactive MCP target checklist (Cursor, Windsurf, Zed, OpenCode, Antigravity, Codex, etc.), previews diffs, creates backups, then applies on confirmation
- Runs `ruler apply --local-only --no-gitignore --agents cursor,codex` (project-scoped; `.gitignore` policy is **not** owned by Ruler — use `prime_workspace` for the BRAINDRAIN block)
- Performs MCP handshake self-test and prints a structured final status summary + next steps

### Manual setup (if you prefer)

**With [uv](https://docs.astral.sh/uv/) (recommended for contributors — lockfile-backed):**

```bash
uv sync --group dev
uv run pytest
```

**Classic pip (still supported):**

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
# optional in-process embeddings (pulls torch):
pip install -e ".[embeddings]"
```

`requirements.txt` is a thin compat shim (`-e .`) pointing at `pyproject.toml`.

### Contributing (lint + hooks)

```bash
uv sync --group dev
uv run ruff check
uv run ruff format --check
uv run pytest -m "not local_only"

pre-commit install   # once per clone
pre-commit run --all-files
```

CI runs the same checks on Python 3.11 / 3.12 / 3.14 across Ubuntu and macOS. Tests marked `local_only` (machine-local services, launchd, LM Studio, etc.) are skipped in CI. The **token benchmark** suite (`pytest -m token_benchmark`) runs on a separate nightly schedule via `.github/workflows/token-benchmark.yml`.

**MCP tool schema snapshot** (`tests/test_mcp_tool_schemas.py`): CI fails if native tool definitions drift from `tests/fixtures/mcp_tool_schemas_snapshot.json`. After you intentionally change `@mcp.tool()` signatures, descriptions, or `outputSchema`, regenerate and commit the fixture:

```bash
uv run python scripts/regenerate_mcp_tool_schemas_snapshot.py
uv run pytest tests/test_mcp_tool_schemas.py -q
```

### Installer options

```bash
PYTHON=python3.14 ./install.sh   # force interpreter
SKIP_TEST=1 ./install.sh         # skip MCP initialize handshake
```

Install logs are written to `.braindrain/install-logs/install-<timestamp>.log`.

### Requirements

- Python 3.11–3.14
- Node.js (for `context-mode` output routing)
- An MCP-compatible AI client

### Arch / Linux dev machines

On Arch/rolling-release distros where `python3` often points at Python 3.14:

- The installer supports Python 3.11–3.14 and prefers `python3.14` when available.
- Make sure system `python`/`python3` and `pip` are installed via your package manager (e.g. `pacman -S python python-pip`).
- For first-time runs, a simple:

```bash
git clone https://github.com/recwebtek/braindrain.git
cd braindrain
./install.sh
```

is expected to succeed; if it doesn’t, capture the full log from `.braindrain/install-logs/` and append a new section to `QA-Logs/bdqadebug.md` (debug log) before iterating.

---

## IDE / Agent configuration

Replace `/path/to/braindrain` with the absolute path to your clone. `install.sh` prints this for you.

> **Important:** Always point your IDE config at `config/braindrain` directly — not at `python3`. If pyenv or system Python resolves to a different version than your venv (a common trap on macOS), the server crashes silently before producing any output.

### Cursor

`.cursor/mcp.json` (project) or `**~/.cursor/mcp.json`** (global) via **Settings › Features › MCP**:

```json
{
  "mcpServers": {
    "braindrain": {
      "command": "/path/to/braindrain/config/braindrain",
      "args": [],
      "env": {},
      "serverName": "braindrain"
    }
  }
}
```

If the MCP log shows `**[MCP Allowlist] No serverName provided for adapter**`, either add `**"serverName": "braindrain"**` on that server object in `**~/.cursor/mcp.json**`, or run `**prime_workspace(..., patch_user_cursor_mcp=true)**` once so braindrain patches the global file. `install.sh` / `configure_mcp.py` and project-level `prime_workspace` set this for generated configs; UI-created entries may omit it.

### Remote transport (non-stdio)

- braindrain now uses FastMCP `streamable-http` for remote mode with `stateless_http=true`.
- Legacy SSE remote transport has been removed.
- MCP protocol headers (including `MCP-Protocol-Version`) are validated by FastMCP's Streamable HTTP transport stack.

**Large `prime_workspace` results:** the MCP tool defaults to `**compact_mcp_response=true`** (smaller JSON) to avoid **ClosedResourceError** / connection closed while returning the tool result. Set `**compact_mcp_response=false`** only if you need the full `templates.deployed` map and untruncated Ruler logs.

#### Multi-agent loop (Cursor)

This repo includes a 4-tier multi-agent system under `.cursor/`. Run:

- `/intake` (once per project) to generate `project-context.json`
- `/architect` to generate `PRD.md`, `TASK-GRAPH.md`, and `COORDINATOR-BRIEF.md`
- `/coordinate` to execute stages (Tier 3 `coordinator` uses `composer-2`)

### Windsurf

`~/.codeium/windsurf/mcp_config.json`:

```json
{
  "mcpServers": {
    "braindrain": {
      "command": "/path/to/braindrain/config/braindrain",
      "args": [],
      "env": {}
    }
  }
}
```

### Zed

`~/.config/zed/settings.json` — use the `context_servers` key (not `mcp_servers`):

```json
{
  "context_servers": {
    "braindrain": {
      "command": "/path/to/braindrain/config/braindrain",
      "args": [],
      "env": {}
    }
  }
}
```

After saving, reload via the command palette: `**agent: reload context servers**`. braindrain will appear in the Agent panel's MCP section.

### OpenCode

`~/.config/opencode/opencode.jsonc`:

```jsonc
{
  "mcp": {
    "braindrain": {
      "type": "local",
      "command": ["/path/to/braindrain/config/braindrain"]
    }
  }
}
```

### Antigravity

`~/.gemini/antigravity/mcp_config.json`:

```json
{
  "mcpServers": {
    "braindrain": {
      "command": "/path/to/braindrain/config/braindrain",
      "args": [],
      "env": {},
      "disabledTools": []
    }
  }
}
```

### Claude Desktop / Codex and others

Any client that uses the standard `mcpServers` format:

```json
{
  "mcpServers": {
    "braindrain": {
      "command": "/path/to/braindrain/config/braindrain",
      "args": [],
      "env": {}
    }
  }
}
```

---

## New device setup

```bash
git clone https://github.com/recwebtek/braindrain.git
cd braindrain
./install.sh
```

Each device runs its own environment probe and gets its own `env_context` — correct Python paths, correct IDE config locations, correct installed tools for that machine. No shared state between devices.

### Updating

Repo-clone installs can check and apply updates without hosting braindrain online:

```bash
# Check only (exit 10 when updates are available)
./scripts/update_braindrain.sh check

# Fast-forward pull when the clone is clean (ff-only)
./scripts/update_braindrain.sh apply
```

From an agent session you can also call `check_hub_update()` (notify-only fetch) or `apply_hub_update()` (pull + dependency sync). **After `apply`, reconnect or restart the braindrain MCP connection** in your IDE so the host loads new code and tool schemas.

The launcher (`config/braindrain`) runs a throttled background check at most once per 24h and prints a stderr nudge when `.braindrain/update-state.json` shows commits behind `origin/main`. Automatic paths never pull without an explicit `apply`.

Manual fallback:

```bash
cd braindrain && git pull --ff-only && (command -v uv >/dev/null && uv sync || .venv/bin/pip install -r requirements.txt)
```

---

## Configuration

Main config: `config/hub_config.yaml`

**Startup validation (Pydantic v2)** — `braindrain/config_schema.py` validates the YAML at server load via `braindrain/config.py`:

- Invalid types or missing required fields (e.g. `mcp_tools[].name`) **fail fast** with dotted field paths.
- Unknown **top-level** keys log a warning and are ignored (forward-compat).
- The legacy `livingdash:` block is **not** validated; if present it is ignored (superseded by MCP Apps dashboard work).
- Restart the braindrain MCP server after config or schema changes.

**Memory stack (L0–L3)** — explicit sections in `hub_config.yaml` (defaults match server fallbacks):

- `observer` — episodic tool-call ring buffer (`~/.braindrain/events.db`)
- `sessions` — session store + inactivity compaction (`~/.braindrain/sessions.db`)
- `wiki_brain` — durable recall/forgetting weights (`~/.braindrain/wiki-brain/brain.db`)
- `lessons` / `memory_learning` — promotion guardrails for facts and playbooks
- `dreaming` — consolidation policy (`quiet_minutes`, scan limits, `storage.base_dir`, `weights`, `triggers.macos_host_idle`)
- `provider_context` — strategy for vendor-native vs Braindrain durable memory (`provider-native-first`)

Restart the braindrain MCP server after changing these blocks. Machine-local ops detail: `.braindrain/OPS.md` (memory stack table).

### Host-idle dream (macOS, manual opt-in)

Two-step enablement (config alone does **not** install or start a watcher):

1. **Install watcher for this workspace** (once per repo): `./scripts/install_dream_watch_launchd.sh`
2. **Enable in this workspace config**: `dreaming.triggers.macos_host_idle.enabled: true` in `config/hub_config.yaml`

The watcher polls HID keyboard/mouse idle time (`IOHIDSystem`). When idle exceeds `idle_threshold_seconds`, it runs consolidation using `mode` (default `full`). Shared memory DBs stay under `~/.braindrain/`; per-workspace state lives under `~/.braindrain/dreaming/workspaces/<workspace_hash>/`.

| Knob | Default | Purpose |
| --- | --- | --- |
| `idle_threshold_seconds` | 300 | Host idle before dream is considered |
| `poll_interval_seconds` | 120 | launchd poll interval (install script reads this) |
| `cooldown_minutes` | 60 | Minimum gap between host-idle dream runs |
| `bypass_session_quiet` | true | When true, host idle can dream even if a Cursor session was active recently |
| `mode` | full | Dream mode passed to `DreamEngine.run` |

Manual one-shot (no launchd): `./scripts/macos_dream_watch.sh`  
Legacy cron path still works: `scripts/run_dream_cron.sh`

Environment variables (copy `.env.example` to `.env.dev` to start):


| Variable                            | Purpose                                                                                                                                       |
| ----------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| `BRAINDRAIN_CONFIG`                 | Override config file path                                                                                                                     |
| `BRAINDRAIN_LAUNCHER_PATH`          | Absolute path to the `config/braindrain` launcher. Set automatically by `install.sh`. Required by `prime_workspace()` and `configure_mcp.py`. |
| `GITHUB_TOKEN`                      | Enables the deferred GitHub MCP tool                                                                                                          |
| `LMSTUDIO_BASE_URL`                 | LM Studio OpenAI-compatible API (default: `http://localhost:1234/v1`)                                                                         |
| `LMSTUDIO_EMBED_MODEL`              | Embedding model name for LM Studio (see `embeddings.providers.lmstudio_local`)                                                                |
| `OLLAMA_HOST`                       | Ollama API base (default: `http://localhost:11434`)                                                                                           |
| `OLLAMA_EMBED_MODEL`              | Ollama embed model (default: `nomic-embed-text`)                                                                                                |
| `MIXEDBREAD_API_KEY`                | Optional — cloud rerank/embeddings only when explicitly enabled in config                                                                     |
| `OPENAI_API_KEY`                    | Optional — cloud embeddings / semantic search                                                                                                 |
| `BRAINDRAIN_DISABLE_DOCKER_SANDBOX` | Set to `1` to skip the Docker workflow sandbox                                                                                                |


The server auto-loads `.env.dev` → `.env.prod` → `.env` (first found, non-overriding of existing env vars).

### Model provenance toggles

`config/hub_config.yaml` now includes a `provenance` block used by planning/report tooling:

- `provenance.chat_footer.enabled` and `provenance.chat_footer.scope` (`all_agents`, `planning_only`, `off`)
- `provenance.plan_metadata.enabled`
- `provenance.subagent_trace.enabled`
- `provenance.subagent_trace.path` (default: `.braindrain/plan-reports/model-trace.jsonl`)
- `provenance.date_format` (default: `%Y-%m-%d`)

The planning auditor writes model metadata into report frontmatter:
`created_by_model`, `created_at`, `last_modified_by_model`, `last_modified_at`, `cursor_mode`, and `subagent_models_used`.

To force explicit provenance values during audit runs:

```bash
python3 scripts/daily_plan_audit.py \
  --repo-root . \
  --report-date "$(date +%Y-%m-%d)" \
  --model-name "Codex 5.3" \
  --cursor-mode auto
```

---

## Repo structure

```
braindrain/
├── braindrain/
│   ├── server.py               # FastMCP server entrypoint + tool registration
│   ├── tools/                  # Tool-domain implementations (tokens, memory, workflows, etc.)
│   ├── primer/                 # Workspace primer submodules (detect/deploy/apply/memory/prime)
│   ├── workspace_primer.py     # compatibility exports for legacy primer imports
│   ├── env_probe.py            # OS fingerprint probe, synthesis, and cache
│   ├── config.py               # YAML config loader
│   ├── context_mode_client.py  # context-mode stdio client (output routing)
│   ├── mcp_stdio_client.py     # generic stdio MCP client (workflow engine)
│   ├── output_router.py        # route large outputs → FTS5 index
│   ├── scriptlib.py            # opt-in script library, harvesting, indexing, run wrapper
│   ├── telemetry.py            # token telemetry + JSONL logging
│   ├── workflow_engine.py      # multi-step workflow execution + sandbox
│   ├── tool_registry.py        # BM25 search + defer_loading
│   ├── rerank.py               # optional search_index rerank (lexical / mixedbread / auto)
│   ├── embeddings_client.py    # local-first embeddings (LM Studio, Ollama, cloud)
│   ├── embeddings_router.py    # provider priority + quota backoff
│   ├── mcp_apps/               # MCP Apps ui:// dashboards (token, plan board, SIGINT map)
│   ├── repo_stats.py           # file-count gating for workflows
│   └── types.py
├── config/
│   ├── bundles/                # bundle manifests (`core`, `comms`, …) for prime_workspace
│   ├── templates/
│   │   ├── ruler/              # Ruler sources (RULES.md, ruler.toml) for prime_workspace
│   │   ├── agents/             # `.cursor/agents/*.md` subagent templates
│   │   └── cursor/             # Cursor hooks: `hooks.json`, `hooks/*.sh`
│   ├── hub_config.yaml         # tools, workflows, model tiers, embeddings
│   ├── braindrain              # launcher script (self-detecting, venv-pinned)
│   ├── opencode_mcp.jsonc      # OpenCode reference config
│   ├── com.braindrain.mcp.plist  # macOS launchd service template
│   └── com.braindrain.dream-watch.plist  # macOS host-idle dream watcher template
├── AGENTS.md                   # agent protocol — generated per device by install.sh
├── AGENTS.md.template          # template used to generate AGENTS.md
├── VERSION                     # semver for releases (kept in sync with this README)
├── CHANGELOG.md                # release history
├── ROADMAP.md                  # public product direction (local scratch: `.devdocs/`, gitignored)
├── TODOS.md                    # public release-aligned checklist (never commit `.devdocs/`)
├── install.sh                  # new device setup script
├── requirements.txt
└── pyproject.toml
```

### Rule generation (AGENTS.md vs Ruler)

- `**AGENTS.md**`: generated locally by `./install.sh` from `AGENTS.md.template` (and includes a machine-specific env block between `<!-- ENV_CONTEXT_START -->` / `<!-- ENV_CONTEXT_END -->`).
- **Ruler-generated dotfiles**: `./install.sh` (and the `prime_workspace()` tool) deploys `config/templates/ruler/` → `.ruler/` and runs `npx @intellectronica/ruler apply` to generate project-local agent rule files like `.cursor/rules/braindrain.mdc`, `.mcp.json`, `CLAUDE.md`, `.agent/rules/ruler.md`, etc.
  - Source-of-truth for those generated rule files is `config/templates/ruler/RULES.md` (and `.ruler/ruler.toml`).
  - **Important**: files like `CLAUDE.md` are **generated artifacts** (gitignored) and should be treated as **disposable**. Edit the templates instead, then re-run Ruler.
  - If a project already has older `.ruler/*` files, call `prime_workspace(..., sync_templates=true)` to refresh those templates safely and propagate new guidance without manual cleanup.
- **Cursor slash commands**: when Cursor is in scope, `prime_workspace()` copies `config/templates/cursor/commands/*.md` → `.cursor/commands/` (create-only by default; `sync_templates=true` refreshes with backups). Shipped commands include `/prime-braindrain`, `/brainlog`, and `/build-plan` (see table under Workflows).
- **Cursor hooks (not Ruler)**: when the resolved agent set includes Cursor, `prime_workspace()` copies `config/templates/cursor/hooks.json` and `config/templates/cursor/hooks/*.sh` into `.cursor/` (create-only by default; `sync_templates=true` overwrites with timestamped backups). Hook templates currently include:
  - `.cursor/hooks/on-stop-observe.sh` (lightweight stop-event observation)
  - `.cursor/hooks/on-stop-gitops.sh` (TASK-GRAPH branch queueing)
  - `.cursor/hooks/on-stop-daily-plan-audit.sh` (daily-gated planning audit report)
  - `.cursor/hooks/on-after-file-edit-plan-provenance.sh` (stamps `*.plan.md` frontmatter with model provenance from hook payload)
  - `.cursor/hooks/on-stop-plan-provenance.sh` (refreshes `.braindrain/active-model.json` for audit/report pickup)
  - Hook output contract: stop-hook scripts should be silent unless they intentionally emit valid JSON. Plain text output can cause Cursor hook-response JSON parse failures.
  Edit templates under `config/templates/cursor/` in this repo, then re-prime consumer projects to roll out hook changes.
- **Subagent templates**: canonical source is `config/templates/agents/*.md`. `prime_workspace()` copies that tree to:
  - `.cursor/agents/` when Cursor is in the resolved agent set, and
  - `.codex/agents/` when Codex is in the resolved agent set (same files; IDE-specific layout only).
  Skills deploy from `config/templates/cursor-skills/<id>/` → `.cursor/skills/<id>/` for each id in the active bundle `skills:` list (e.g. `cursor-orchestration`: coordinator, gitops, scriptlib-librarian). See `docs/skill-braindrain-hub-pr.md`.
  Operational scripts (`daily_plan_audit`, `plan_build_guard`, `plan_provenance_stamp`, `plan_branch_utils`) copy from hub `scripts/` → project `scripts/` per bundle `operational_scripts`. Re-prime upgrades them when the hub revision changes (content-hash marker), so plan branch/PR reconciliation reaches consumer workspaces without tracking `*.plan.md` in git.
  Existing files are create-only by default; set `sync_subagents=true` to update with backups. `.cursor/` is gitignored at repo root; do not commit generated agent/skill files—edit templates and re-run `prime_workspace`.
- **Codex config merge**: `prime_workspace()` appends/updates a managed `BRAINDRAIN SUBAGENTS` block in `.codex/config.toml` only when allowed by policy (`sync_subagents=true` for existing files). Existing MCP server entries remain intact.
- **Project memory artifacts**: initialized by `prime_workspace()` (or `init_project_memory()`) and kept separate from generated protocol files:
  - `.braindrain/AGENT_MEMORY.md`, `.braindrain/OPS.md`, and `.braindrain/SESSION_PROGRESS.md` are **create-only** on prime/re-prime (existing content is preserved)
  - `.cursor/hooks/state/continual-learning-index.json` for incremental transcript indexing
  - prime now snapshots protected memory files into `.braindrain/rollback/<ts>/memory/` and records metadata in `.braindrain/primed.json` (`schema_version: 2.0`) plus `.braindrain/primed-history.jsonl`
  - use `list_prime_snapshots(path=".")` and `restore_prime_snapshot(path=".", snapshot_id=None, restore_memory=true, restore_cursor=true)` to recover from rollback snapshots
  - `AGENTS.md` remains generator-owned protocol text and should not be used as memory storage
- **Scriptlib**: disabled by default. When enabled for a workspace, braindrain seeds project-local `.scriptlib/`, harvests reusable scripts recursively, and injects librarian-first guidance into generated agent rule surfaces for that workspace only.
- **Shared personal scriptlib**: promoted scripts can also live in `~/.braindrain/scriptlib` as a curated machine-level catalog. Project-local harvest never auto-publishes into the shared catalog.
- **Pins and updates**: workspaces can pin approved shared artifacts and receive upgrade suggestions later without silent mutation.

### Docs ownership map (token observability)


| File/path                           | Ownership                       | Purpose                                                 |
| ----------------------------------- | ------------------------------- | ------------------------------------------------------- |
| `config/templates/ruler/RULES.md`   | Source-of-truth template        | Canonical protocol language and trigger matrix          |
| `AGENTS.md.template`                | Source template                 | Generated `AGENTS.md` content for protocol distribution |
| `AGENTS.md`                         | Generated artifact              | Do not edit directly                                    |
| `.cursor/rules/agent-system.mdc`    | Cursor local enforcement        | Immediate IDE-specific guardrails                       |
| `~/.braindrain/costs/session.jsonl` | Machine-local telemetry         | Runtime token telemetry source-of-truth                 |
| `.braindrain/token-metrics.jsonl`   | Optional machine-local artifact | Local checkpoint stream using schema `1.0`              |


---

## Memory layer status and roadmap

**Roadmap and release TODOs** ship from the repo root as `**ROADMAP.md`** and `**TODOS.md`**. Use `**.devdocs/**` only on your machine for private drafts (that path is gitignored and must not be committed).

Implemented now (runtime behavior in this repo):

- **L1 (session and episodic grounding)**:
  - `ObserverStore` (`braindrain/observer.py`) captures bounded event traces.
  - `SessionStore` + `EpisodeRecord` (`braindrain/session.py`) track lifecycle, grounded evidence, and promotion-ready episode units.
- **L2 (durable memory store)**:
  - `WikiBrain` (`braindrain/wiki_brain.py`) stores semantic/procedural/lesson records with FTS recall, supersession, decay/forgetting, and metrics.
- **L3/L4 (dream consolidation and operational automation)**:
  - `DreamEngine` (`braindrain/dream.py`) runs Light/REM/Deep consolidation and writes `ConsolidationPlan` artifacts plus `DREAMS.md`.
  - MCP tools include `run_dream`, `get_dream_status`, and related memory/episode/recall endpoints in `braindrain/server.py`.
  - Automation hooks and scheduler helpers are wired:
    - `.cursor/hooks/on-stop-observe.sh`
    - `.cursor/hooks/on-stop-gitops.sh`
    - `.cursor/hooks/on-stop-daily-plan-audit.sh`
    - `.cursor/hooks/on-after-file-edit-plan-provenance.sh`
    - `.cursor/hooks/on-stop-plan-provenance.sh`
    - `scripts/run_dream_cron.sh`
    - `scripts/macos_dream_watch.sh` + `scripts/install_dream_watch_launchd.sh` (macOS host-idle, opt-in)

Memory artifacts and paths:

- Durable project memory path: `.braindrain/AGENT_MEMORY.md` (machine-local, gitignored).
- Incremental transcript index path: `.cursor/hooks/state/continual-learning-index.json`.
- Daily planning audit hook state path: `.cursor/hooks/state/daily-plan-audit.json`.
- Daily planning audit reports path:
  - `.braindrain/plan-reports/plan-audit-YYYY-MM-DD.md` (full report, now plan-centric cards grouped by IDE -> disposition)
  - `.braindrain/plan-reports/latest.md` (latest mirror)
  - `.braindrain/plan-reports/plan-task-board.md` (active item board with **Seq** / **Plan** columns, sorted by `_master.plan.md` execution order then item status)
  - `.braindrain/plan-reports/master-plan.md` (generated master mirror + **Implementation sequence** build queue + drift detection + **Branch** and **PR** columns)
  - `.braindrain/plan-reports/overlap-relations.md` (plan-level overlap pairs and clusters snapshot)
  - `.braindrain/plan-reports/next-actions.md` (verb queue: `MERGE`, `FIX`, `REPLAN`, `RESEARCH`, `IMPLEMENT`, `BACKLOG`, **READY_TO_ARCHIVE**)

### Planning overseer (`/masterplan`)

The daily auditor (`scripts/daily_plan_audit.py`, Cursor `/masterplan`) treats **frontmatter `todos`** as the status source when present, orders the build queue from `_master.plan.md` (`execution_order:` or `## active` link order), and adds overseer sections to `master-plan.md`:

- **Implementation sequence** — numbered build queue (excludes archived / implemented / merge-ready)
- **Overlap clusters** — shared paths, token Jaccard, identical branches, declared `supersedes`
- **Goal alignment** — scores active plans against goals from `.cursor/PRD.md`, `.cursor/TASK-GRAPH.md`, `.cursor/project-context.json`, and `_master.plan.md` `goalposts:`

Run read-only by default. Human-confirmed write-back uses explicit CLI flags (never the daily-gated stop hook):

```bash
python3 scripts/daily_plan_audit.py --repo-root . --trigger "manual-masterplan-command"
python3 scripts/daily_plan_audit.py --repo-root . --trigger "manual-masterplan-command" \
  --apply-disposition-sync --apply-archive
python3 scripts/daily_plan_audit.py --repo-root . --trigger "manual-masterplan-command" \
  --apply-overlap-relations
python3 scripts/daily_plan_audit.py --repo-root . --trigger "manual-masterplan-command" \
  --apply-goal-tags
```

Optional defaults in `config/hub_config.yaml` under `planning_auditor:` (`overlap_jaccard_threshold`, `apply_overlap_relations`, `apply_goal_tags`, `goal_alignment_min_score`). CLI threshold and `--apply-*` flags override YAML for one-off runs. Machine-local run paths: `.braindrain/OPS.md`.
  - Primary plan discovery now scans known IDE plan dirs (`.cursor/plans`, `.codex/plans`, `.kiro/plans`, `.windsurf/plans`, etc.), and each plan/action is tagged with its IDE source.
  - Branch resolution for each plan is hybrid by precedence: frontmatter `branch:` -> `.cursor/.gitops-queue.json` (`planSource` exact match, then fuzzy) -> `.cursor/.gitops-memory.jsonl` -> local git branch slug match (`git_local`) -> `—`.
  - PR column: `gh pr list --head <branch> --state all` when `gh` is available (`none` if no PR; `—` if gh unavailable).
  - When a branch is resolved from gitops queue/history and the plan lacks `branch:`, the auditor writes `branch:` into that plan's frontmatter during the audit run.
  - Optional `--bootstrap-branches` persists high-confidence `git_local` matches into `branch:` for `active` / `merge-ready` plans only.
  - Ownership defaults to `@<current username>` from `get_env_context()` when `owner:`/`dri:` are absent. Explicit item-level owner markers (`@name`, `owner:`, `assignee:`, `dri:`) still work and override inherited ownership.

Plan execution branch invariant (coordinator/gitops contract):

- For every plan execution/build path, enforce: `check branch -> checkout correct branch -> proceed`.
- If a selected plan has no associated branch, run `branch-setup` first, then continue execution on that branch.
- Cursor Plan **Build** runs in the current workspace on the current git HEAD unless agents follow the plan implementation guardrail in Ruler `RULES.md` / `.cursor/rules/braindrain.mdc`.
- Stop hook `.cursor/hooks/on-stop-gitops-plans.sh` queues `branch-setup` for recently edited `*.plan.md` files with `planSource` linkage.
- Dream artifacts path: `~/.braindrain/dreaming/` (`plans/`, `daily/`, `DREAMS.md`, `last_status.json`).
- `init_project_memory(path, dry_run)` bootstraps memory artifacts and is idempotent.
- `prime_workspace()` includes memory initialization in onboarding.

Next-phase roadmap (optional expansion, not missing core restoration):

- Cross-project memory governance and retrieval policy for optional global memory.
- Additional lesson-quality scoring and promotion analytics dashboards.
- Extended provider-boundary metrics for long-run token ROI tracking.

Operational notes:

- Public telemetry source-of-truth remains `~/.braindrain/costs/session.jsonl`.
- `.braindrain/token-metrics.jsonl` remains an optional checkpoint stream only.

---

## License

This project is licensed under the **GNU Affero General Public License v3.0 (AGPL-3.0)**.

Braindrain is a community-first, research-driven orchestration layer focused on **token-usage reduction** and practical MCP workflows. Contributions and forks are welcome under the AGPL terms.

### What this means in practice

- You can use, study, modify, and redistribute this project.
- If you run a modified version for users over a network, you must make the corresponding source code available under AGPL-3.0.
- Derivative works must keep the same license terms.

### Commercial use and naming

Commercial use is permitted under AGPL-3.0.
However, the **Braindrain** name, branding, and project identity are governed separately by project trademark policy. Forks, research reuse, and community improvements are welcome; just avoid presenting modified or hosted versions as the official Braindrain project unless explicitly authorized.

For full terms, see the `[LICENSE](LICENSE)` file and naming guidance in `[TRADEMARKS.md](TRADEMARKS.md)`.