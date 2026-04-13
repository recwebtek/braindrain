# braindrain

**Version:** V1.0.3  
**Last Updated:** 2026-04-10

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

## Tools

### Environment

| Tool | When to use |
|---|---|
| `get_env_context()` | **Call this first** in any session. Returns a cached snapshot of the machine: Python interpreters, package managers, installed IDEs and their MCP configs, running LLM servers, browsers, VM tools, GUI tools, CLI tools, and agent behaviour hints. Zero cost after the first probe. |
| `refresh_env_context()` | After installing new tools, switching machines, or any time the cached data feels stale. Re-runs the full probe (~5s) and updates the cache. |

### Tool discovery

| Tool | When to use |
|---|---|
| `search_tools(query, top_k=5)` | Before loading any external MCP tool. Searches the configured tool registry by capability. Returns lightweight references — not full definitions. Prevents loading 26K-token tool schemas unnecessarily. |
| `get_available_tools()` | Lists all configured tools and whether they are HOT (always loaded) or deferred (loaded on demand). |

### Output routing

| Tool | When to use |
|---|---|
| `route_output(text, source, intent)` | When a tool returns a large blob. Indexes it into a local FTS5 store and returns a handle + suggested queries. The raw text never enters the context window. |
| `search_index(query, limit=5)` | Retrieve relevant chunks from a previously routed output. Use the suggested queries from `route_output` as a starting point. |

### Workflows

| Tool | When to use |
|---|---|
| `list_workflows()` | See what multi-step workflows are available. |
| `prime_workspace(path, agents, dry_run, sync_templates, sync_subagents, all_agents, local_only, codex_agent_targets)` | Prime a project for AI agent use. **First run**: auto-detects current IDE/CLI (`CURSOR_*` → `TERM_PROGRAM` → dotfolders → fallback `cursor`); response includes **`detect_method`**. Always rewrites **minimal `.ruler/ruler.toml`** when targeting specific agents (even if `.ruler/` already existed) so Ruler’s `.gitignore` and config match the agent list. Also deploys Cursor/Codex subagent files from templates and reports summary in **`subagents`**. Codex config policy: create `.codex/config.toml` if missing; if present, only update managed `BRAINDRAIN SUBAGENTS` block when `sync_subagents=true` (backup-first). After apply, syncs **`.cursor/rules/braindrain.mdc`** and **`project-rules.mdc`** (managed fenced region) from `.ruler/RULES.md` — see **`cursor_rules`** in the result. Set `all_agents=True` for the full template. Set `sync_templates=True` to force-refresh `.ruler/*`; set `sync_subagents=True` to refresh existing subagent files/config blocks. |
| `init_project_memory(path, dry_run)` | Initialize project memory artifacts only (`.braindrain/AGENT_MEMORY.md` and `.cursor/hooks/state/continual-learning-index.json`). Migrates legacy `.devdocs/` on first call. Idempotent. |
| `scriptlib_enable(path, scope, harvest, dry_run)` | Hard-opt-in project or global scriptlib. Project enable can immediately harvest reusable workspace scripts into `.scriptlib/`. |
| `scriptlib_harvest_workspace(path, dry_run)` | Copy scripts from `tests/`, `scripts/`, and supported locations into scriptlib metadata entries and catalog. |
| `scriptlib_search(query, ...)` | Search scriptlib before writing a new reusable helper script. |
| `scriptlib_describe(script_id, ...)` | Inspect metadata, score, and run mode for one scriptlib entry. |
| `scriptlib_run(script_id, ...)` | Execute a script through scriptlib with restored source context when paths are sensitive. |
| `scriptlib_fork(script_id, new_variant_or_version, ...)` | Fork an existing scriptlib entry into a new version for safe edits. |
| `scriptlib_record_result(script_id, outcome, ...)` | Update success score, mistakes, and validation state. |
| `scriptlib_refresh_index(path, scope, dry_run)` | Rebuild project/global scriptlib indexes and generated catalogs. |
| `plan_workflow(name, args)` | Generate a markdown execution plan and review it before committing to a run. Use before any destructive or long-running workflow. |
| `run_workflow(name, args)` | Execute a workflow. Intermediate output is routed through the sandbox — only the final summary returns to the agent. |

`list_workflows()` now includes `init_project_memory`, so agents can discover memory bootstrap as a first-class onboarding workflow.

### Telemetry

| Tool | When to use |
|---|---|
| `get_token_dashboard()` | Quick snapshot of estimated tokens saved vs raw in this session. |
| `get_token_stats()` | Full breakdown: per-tool savings, cache hits, cost avoided. |

### Token Checkpoint Protocol

Use this cadence for consistent token observability:

| Trigger | Required | Call |
|---|---|---|
| Task start | Yes | `get_token_dashboard()` |
| Before high-cost operation | Yes | `get_token_dashboard()` |
| After high-cost operation | Yes | `get_token_dashboard()` |
| Milestone or phase close | Yes | `get_token_stats()` |
| Task end | Yes | `get_token_dashboard()` then `get_token_stats()` |
| Trivial/no-op action | Optional skip | none |

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

| Tool | When to use |
|---|---|
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

`.cursor/mcp.json` (project) or **`~/.cursor/mcp.json`** (global) via **Settings › Features › MCP**:

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

If the MCP log shows **`[MCP Allowlist] No serverName provided for adapter`**, either add **`"serverName": "braindrain"`** on that server object in **`~/.cursor/mcp.json`**, or run **`prime_workspace(..., patch_user_cursor_mcp=true)`** once so braindrain patches the global file. `install.sh` / `configure_mcp.py` and project-level `prime_workspace` set this for generated configs; UI-created entries may omit it.

**Large `prime_workspace` results:** the MCP tool defaults to **`compact_mcp_response=true`** (smaller JSON) to avoid **ClosedResourceError** / connection closed while returning the tool result. Set **`compact_mcp_response=false`** only if you need the full `templates.deployed` map and untruncated Ruler logs.

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

After saving, reload via the command palette: **`agent: reload context servers`**. braindrain will appear in the Agent panel's MCP section.

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

| Variable | Purpose |
|---|---|
| `BRAINDRAIN_CONFIG` | Override config file path |
| `BRAINDRAIN_LAUNCHER_PATH` | Absolute path to the `config/braindrain` launcher. Set automatically by `install.sh`. Required by `prime_workspace()` and `configure_mcp.py`. |
| `GITHUB_TOKEN` | Enables the deferred GitHub MCP tool |
| `LMSTUDIO_BASE_URL` | LM Studio endpoint (default: `http://localhost:1234/v1`) |
| `OLLAMA_HOST` | Ollama endpoint (default: `http://localhost:11434`) |
| `OPENAI_API_KEY` | Optional — cloud embeddings / semantic search |
| `BRAINDRAIN_DISABLE_DOCKER_SANDBOX` | Set to `1` to skip the Docker workflow sandbox |
| `MATTERMOST_ENDPOINT` | Mattermost server base URL for Mattermost MCP integration (example: `http://localhost:8065`) |
| `MATTERMOST_TOKEN` | Mattermost personal access token used by the Mattermost MCP server |
| `MATTERMOST_TEAM` | Team identifier/name used by the selected Mattermost MCP server |
| `COORDINATOR_MATTERMOST_ENABLED` | Set to `1` to allow coordinator subagents to auto-use Mattermost comms protocol |

The server auto-loads `.env.dev` → `.env.prod` → `.env` (first found, non-overriding of existing env vars).

---

## Mattermost coordinator comms

You can give the coordinator read+post communication via an existing Mattermost MCP server.

### 1) Add Mattermost MCP server to Cursor project config

`install.sh` now ensures a project-level Mattermost entry exists in `.cursor/mcp.json`:

```json
"mattermost": {
  "command": "npx",
  "args": ["-y", "mcp-server-mattermost"],
  "env": {
    "endpoint": "${MATTERMOST_ENDPOINT}",
    "token": "${MATTERMOST_TOKEN}",
    "team": "${MATTERMOST_TEAM}"
  },
  "type": "stdio",
  "serverName": "mattermost"
}
```

### 2) Configure env vars locally (do not commit tokens)

Recommended split:
- `.env.dev` for local testing
- `.env.prod` for stable daily-driver usage

Add:

```bash
MATTERMOST_ENDPOINT=http://localhost:8065
MATTERMOST_TOKEN=your_personal_access_token
MATTERMOST_TEAM=your_team_name_or_id
COORDINATOR_MATTERMOST_ENABLED=1
```

### 3) Verify read/post loop

After reloading MCP servers in Cursor:
- Verify Mattermost tools are visible (for example `read_channel`, `search_posts`, `create_post`)
- Read latest channel context
- Post a heartbeat message
- Run one full loop: read context -> produce status delta -> create post update

If tool visibility fails:
- Ensure `npx` is available and can resolve `mcp-server-mattermost`
- Confirm `MATTERMOST_ENDPOINT` points to the reachable Mattermost host
- Confirm PAT has permission to read and post in target channels

---

## Repo structure

```
braindrain/
├── braindrain/
│   ├── server.py               # FastMCP server — all MCP tools registered here
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

- **`AGENTS.md`**: generated locally by `./install.sh` from `AGENTS.md.template` (and includes a machine-specific env block between `<!-- ENV_CONTEXT_START -->` / `<!-- ENV_CONTEXT_END -->`).
- **Ruler-generated dotfiles**: `./install.sh` (and the `prime_workspace()` tool) deploys `config/templates/ruler/` → `.ruler/` and runs `npx @intellectronica/ruler apply` to generate project-local agent rule files like `.cursor/rules/braindrain.mdc`, `.mcp.json`, `CLAUDE.md`, `.agent/rules/ruler.md`, etc.
  - Source-of-truth for those generated rule files is `config/templates/ruler/RULES.md` (and `.ruler/ruler.toml`).
  - **Important**: files like `CLAUDE.md` are **generated artifacts** (gitignored) and should be treated as **disposable**. Edit the templates instead, then re-run Ruler.
  - If a project already has older `.ruler/*` files, call `prime_workspace(..., sync_templates=true)` to refresh those templates safely and propagate new guidance without manual cleanup.
- **Subagent templates**: `prime_workspace()` deploys:
  - `config/templates/cursor-subagents/` -> `.cursor/agents/`
  - `config/templates/cursor-skills/` -> `.cursor/skills/` (e.g. scriptlib-librarian)
  - `config/templates/codex-subagents/` -> `.codex/agents/` (or `codex_agent_targets`)
  Existing files are create-only by default; set `sync_subagents=true` to update with backups. `.cursor/` is gitignored at repo root; do not commit generated agent/skill files—edit templates and re-run `prime_workspace`.
- **Codex config merge**: `prime_workspace()` appends/updates a managed `BRAINDRAIN SUBAGENTS` block in `.codex/config.toml` only when allowed by policy (`sync_subagents=true` for existing files). Existing MCP server entries remain intact.
- **Project memory artifacts**: initialized by `prime_workspace()` (or `init_project_memory()`) and kept separate from generated protocol files:
  - `.braindrain/AGENT_MEMORY.md` for high-signal durable memory (legacy `.devdocs/AGENT_MEMORY.md` may be migrated on first run)
  - `.cursor/hooks/state/continual-learning-index.json` for incremental transcript indexing
  - `AGENTS.md` remains generator-owned protocol text and should not be used as memory storage.
- **Scriptlib**: disabled by default. When enabled for a workspace, braindrain seeds `.scriptlib/`, harvests reusable scripts, and injects scriptlib guidance into generated agent rule surfaces for that workspace only.

### Docs ownership map (token observability)

| File/path | Ownership | Purpose |
|---|---|---|
| `config/templates/ruler/RULES.md` | Source-of-truth template | Canonical protocol language and trigger matrix |
| `AGENTS.md.template` | Source template | Generated `AGENTS.md` content for protocol distribution |
| `AGENTS.md` | Generated artifact | Do not edit directly |
| `.cursor/rules/agent-system.mdc` | Cursor local enforcement | Immediate IDE-specific guardrails |
| `~/.braindrain/costs/session.jsonl` | Machine-local telemetry | Runtime token telemetry source-of-truth |
| `.braindrain/token-metrics.jsonl` | Optional machine-local artifact | Local checkpoint stream using schema `1.0` |

---

## Memory state and roadmap TODOs

**Roadmap and release TODOs** ship from the repo root as **`ROADMAP.md`** and **`TODOS.md`**. Use **`.devdocs/`** only on your machine for private drafts (that path is gitignored and must not be committed).

Current implemented memory behavior:

- Durable project memory path is `.braindrain/AGENT_MEMORY.md` (machine-local, gitignored).
- Incremental transcript index path is `.cursor/hooks/state/continual-learning-index.json`.
- `init_project_memory(path, dry_run)` bootstraps memory artifacts and is idempotent.
- `prime_workspace()` includes memory initialization in onboarding.

L1/L2/L3 roadmap (current-state only, not yet implemented semantics):

- **L1 (project memory hardening)**: finalize retention/cleanup guidelines for project-local memory and transcript index updates.
- **L2 (tiered memory model)**: define explicit layer semantics and migration policy for tiered memory behavior.
- **L3 (cross-project memory)**: add optional global memory under `~/.braindrain/memory/` with retrieval and governance controls.

Roadmap notes:

- L1/L2/L3 are planning levels, not active runtime tier enforcement yet.
- Public telemetry source-of-truth remains `~/.braindrain/costs/session.jsonl`.
- `.braindrain/token-metrics.jsonl` remains an optional checkpoint stream only.

---

## License

MIT
