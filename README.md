# braindrain

**Version:** V1.0.3  
**Last Updated:** 2026-04-16

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

## LivingDash storage boundary

LivingDash uses a split layout so scaffold code can be versioned while runtime state stays local-only:

- `.ldash/` contains dashboard scaffold and UI source/build files.
- `.braindrain/ldash/data/` contains runtime and sensitive state (`auth.json`, `status.json`, `snapshot.json`, `livingdash.pid`).

This keeps passwords/session secrets out of shareable dashboard scaffold paths and aligns with the project rule that `.braindrain/` is machine-local.

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


### Output routing


| Tool                                 | When to use                                                                                                                                                  |
| ------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `route_output(text, source, intent)` | When a tool returns a large blob. Indexes it into a local FTS5 store and returns a handle + suggested queries. The raw text never enters the context window. |
| `search_index(query, limit=5)`       | Retrieve relevant chunks from a previously routed output. Use the suggested queries from `route_output` as a starting point.                                 |


### Workflows


| Tool                                                     | When to use                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| -------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `list_workflows()`                                       | See what multi-step workflows are available.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| `prime_workspace(...)`                                   | Prime a project for AI agent use. **Parameters** include `sync_subagents`, `sync_templates`, `bundle` (`core` default), `codex_agent_targets`, `patch_user_cursor_mcp`, `compact_mcp_response`. **First run**: auto-detects current IDE/CLI (`CURSOR_*` → `TERM_PROGRAM` → dotfolders → fallback `cursor`); response includes `**detect_method`**. Uses `**config/bundles/<bundle>.yaml**` for bundle metadata. Always rewrites **minimal `.ruler/ruler.toml`** when targeting specific agents. Deploys Cursor/Codex subagent files from templates (`**subagents**`) and manages Codex `**BRAINDRAIN SUBAGENTS**` in `.codex/config.toml` when allowed (`**codex_subagent_config**`). After apply, syncs `**.cursor/rules/braindrain.mdc**` and `**project-rules.mdc**` from `.ruler/RULES.md` — see `**cursor_rules**`. When Cursor is in scope, copies `**config/templates/cursor/**` → `**.cursor/hooks.json**` and `**.cursor/hooks/*.sh**` — see `**cursor_hooks**` (create-only; `**sync_templates=true**` refreshes Ruler sources and hook templates). `**sync_subagents=true**` updates existing subagent files and managed Codex blocks (backup-first). Set `**all_agents=True**` for the full template. |
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


`list_workflows()` now includes `init_project_memory`, so agents can discover memory bootstrap as a first-class onboarding workflow.

### Telemetry


| Tool                    | When to use                                                      |
| ----------------------- | ---------------------------------------------------------------- |
| `get_token_dashboard()` | Quick snapshot of estimated tokens saved vs raw in this session. |
| `get_token_stats()`     | Full breakdown: per-tool savings, cache hits, cost avoided.      |


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

Use `.braindrain/token-metrics.jsonl` as an optional machine-local checkpoint stream for checkpoint records. Required fields per line:

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
- On Linux CPU-only machines, prefers PyTorch CPU wheels to avoid accidental CUDA downloads
- Runs fresh `get_env_context()` probe and regenerates `AGENTS.md`
- Creates `.braindrain/` (gitignored, machine-local — never committed)
- Runs an interactive MCP target checklist (Cursor, Windsurf, Zed, OpenCode, Antigravity, Codex, etc.), previews diffs, creates backups, then applies on confirmation
- Runs `ruler apply --local-only --no-gitignore --agents cursor,codex` (project-scoped; `.gitignore` policy is **not** owned by Ruler — use `prime_workspace` for the BRAINDRAIN block)
- Performs MCP handshake self-test and prints a structured final status summary + next steps

### Manual setup (if you prefer)

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
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

On Arch/rolling-release distros (e.g. EndeavourOS) where `python3` often points at Python 3.14:

- The installer supports Python 3.11–3.14 and prefers `python3.14` when available.
- Make sure system `python`/`python3` and `pip` are installed via your package manager (e.g. `pacman -S python python-pip`).
- For first-time runs, a simple:

```bash
git clone https://github.com/recwebtek/braindrain.git
cd braindrain
./install.sh
```

is expected to succeed; if it doesn’t, capture the full log from `.braindrain/install-logs/` and append a new section to `QA-Logs/bdqadebug.md` (Lenovo/Arch debug log) before iterating.

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

To pull updates:

```bash
cd braindrain && git pull && .venv/bin/pip install -r requirements.txt
```

---

## Configuration

Main config: `config/hub_config.yaml`

Environment variables (copy `.env.example` to `.env.dev` to start):


| Variable                            | Purpose                                                                                                                                       |
| ----------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| `BRAINDRAIN_CONFIG`                 | Override config file path                                                                                                                     |
| `BRAINDRAIN_LAUNCHER_PATH`          | Absolute path to the `config/braindrain` launcher. Set automatically by `install.sh`. Required by `prime_workspace()` and `configure_mcp.py`. |
| `GITHUB_TOKEN`                      | Enables the deferred GitHub MCP tool                                                                                                          |
| `LMSTUDIO_BASE_URL`                 | LM Studio endpoint (default: `http://localhost:1234/v1`)                                                                                      |
| `OLLAMA_HOST`                       | Ollama endpoint (default: `http://localhost:11434`)                                                                                           |
| `OPENAI_API_KEY`                    | Optional — cloud embeddings / semantic search                                                                                                 |
| `BRAINDRAIN_DISABLE_DOCKER_SANDBOX` | Set to `1` to skip the Docker workflow sandbox                                                                                                |


The server auto-loads `.env.dev` → `.env.prod` → `.env` (first found, non-overriding of existing env vars).

---

## Repo structure

```
braindrain/
├── braindrain/
│   ├── server.py               # FastMCP server — all MCP tools registered here
│   ├── workspace_primer.py     # prime_workspace: Ruler templates, subagents, Cursor hooks
│   ├── env_probe.py            # OS fingerprint probe, synthesis, and cache
│   ├── config.py               # YAML config loader
│   ├── context_mode_client.py  # context-mode stdio client (output routing)
│   ├── mcp_stdio_client.py     # generic stdio MCP client (workflow engine)
│   ├── output_router.py        # route large outputs → FTS5 index
│   ├── scriptlib.py            # opt-in script library, harvesting, indexing, run wrapper
│   ├── telemetry.py            # token telemetry + JSONL logging
│   ├── workflow_engine.py      # multi-step workflow execution + sandbox
│   ├── tool_registry.py        # BM25 search + defer_loading
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
│   └── com.braindrain.mcp.plist  # macOS launchd service template
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
- **Cursor hooks (not Ruler)**: when the resolved agent set includes Cursor, `prime_workspace()` copies `config/templates/cursor/hooks.json` and `config/templates/cursor/hooks/*.sh` into `.cursor/` (create-only by default; `sync_templates=true` overwrites with timestamped backups). Hook templates currently include:
  - `.cursor/hooks/on-stop-observe.sh` (lightweight stop-event observation)
  - `.cursor/hooks/on-stop-gitops.sh` (TASK-GRAPH branch queueing)
  - `.cursor/hooks/on-stop-daily-plan-audit.sh` (daily-gated planning audit report)
  Edit templates under `config/templates/cursor/` in this repo, then re-prime consumer projects to roll out hook changes.
- **Subagent templates**: canonical source is `config/templates/agents/*.md`. `prime_workspace()` copies that tree to:
  - `.cursor/agents/` when Cursor is in the resolved agent set, and
  - `.codex/agents/` when Codex is in the resolved agent set (same files; IDE-specific layout only).
  Skills still deploy from `config/templates/cursor-skills/` -> `.cursor/skills/` (e.g. scriptlib-librarian).
  Existing files are create-only by default; set `sync_subagents=true` to update with backups. `.cursor/` is gitignored at repo root; do not commit generated agent/skill files—edit templates and re-run `prime_workspace`.
- **Codex config merge**: `prime_workspace()` appends/updates a managed `BRAINDRAIN SUBAGENTS` block in `.codex/config.toml` only when allowed by policy (`sync_subagents=true` for existing files). Existing MCP server entries remain intact.
- **Project memory artifacts**: initialized by `prime_workspace()` (or `init_project_memory()`) and kept separate from generated protocol files:
  - `.braindrain/AGENT_MEMORY.md` for high-signal durable memory (legacy `.devdocs/` / `.devdocs/AGENT_MEMORY.md` may be migrated on first run)
  - `.cursor/hooks/state/continual-learning-index.json` for incremental transcript indexing
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

**Roadmap and release TODOs** ship from the repo root as `**ROADMAP.md`** and `**TODOS.md**`. Use `**.devdocs/**` only on your machine for private drafts (that path is gitignored and must not be committed).

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
    - `scripts/run_dream_cron.sh`

Memory artifacts and paths:

- Durable project memory path: `.braindrain/AGENT_MEMORY.md` (machine-local, gitignored).
- Incremental transcript index path: `.cursor/hooks/state/continual-learning-index.json`.
- Daily planning audit hook state path: `.cursor/hooks/state/daily-plan-audit.json`.
- Daily planning audit reports path:
  - `.braindrain/plan-reports/plan-audit-YYYY-MM-DD.md` (full report, now plan-centric cards grouped by IDE -> disposition)
  - `.braindrain/plan-reports/latest.md` (latest mirror)
  - `.braindrain/plan-reports/plan-task-board.md` (active item board with IDE + inherited owner)
  - `.braindrain/plan-reports/master-plan.md` (generated master mirror + drift detection)
  - `.braindrain/plan-reports/next-actions.md` (verb queue: `MERGE`, `FIX`, `REPLAN`, `RESEARCH`, `IMPLEMENT`, `BACKLOG`)
  - Primary plan discovery now scans known IDE plan dirs (`.cursor/plans`, `.codex/plans`, `.kiro/plans`, `.windsurf/plans`, etc.), and each plan/action is tagged with its IDE source.
  - Ownership defaults to `@<current username>` from `get_env_context()` when `owner:`/`dri:` are absent. Explicit item-level owner markers (`@name`, `owner:`, `assignee:`, `dri:`) still work and override inherited ownership.
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