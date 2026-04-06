# braindrain

**Version:** V1.0.2  
**Last Updated:** 2026-03-23

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
| `prime_workspace(path, agents, dry_run, sync_templates, all_agents, local_only)` | Prime a project for AI agent use. **First run**: auto-detects current IDE/CLI (`CURSOR_*` → `TERM_PROGRAM` → dotfolders → fallback `cursor`); response includes **`detect_method`**. Always rewrites **minimal `.ruler/ruler.toml`** when targeting specific agents (even if `.ruler/` already existed) so Ruler’s `.gitignore` and config match the agent list. After apply, syncs **`.cursor/rules/braindrain.mdc`** and **`project-rules.mdc`** (managed fenced region) from `.ruler/RULES.md` — see **`cursor_rules`** in the result. Set `all_agents=True` for the full template. Set `sync_templates=True` to force-refresh all `.ruler/*` sources. |
| `init_project_memory(path, dry_run)` | Initialize project memory artifacts only (`.braindrain/AGENT_MEMORY.md` and `.cursor/hooks/state/continual-learning-index.json`). Migrates legacy `.devdocs/` on first call. Idempotent. |
| `plan_workflow(name, args)` | Generate a markdown execution plan and review it before committing to a run. Use before any destructive or long-running workflow. |
| `run_workflow(name, args)` | Execute a workflow. Intermediate output is routed through the sandbox — only the final summary returns to the agent. |

`list_workflows()` now includes `init_project_memory`, so agents can discover memory bootstrap as a first-class onboarding workflow.

### Telemetry

| Tool | When to use |
|---|---|
| `get_token_dashboard()` | Quick snapshot of estimated tokens saved vs raw in this session. |
| `get_token_stats()` | Full breakdown: per-tool savings, cache hits, cost avoided. |

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
- Installs full dependencies with visible progress, retries, and install logging to `.gstack/install-logs/`
- On Linux CPU-only machines, prefers PyTorch CPU wheels to avoid accidental CUDA downloads
- Runs fresh `get_env_context()` probe and regenerates `AGENTS.md`
- Creates `.braindrain/` (gitignored, machine-local — never committed)
- Runs an interactive MCP target checklist (Cursor, Windsurf, Zed, OpenCode, Antigravity, Codex, etc.), previews diffs, creates backups, then applies on confirmation
- Runs `ruler apply --local-only --no-gitignore --agents cursor,claude` (project-scoped; `.gitignore` policy is **not** owned by Ruler — use `prime_workspace` for the BRAINDRAIN block)
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

Install logs are written to `.gstack/install-logs/install-<timestamp>.log`.

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

is expected to succeed; if it doesn’t, capture the full log from `.gstack/install-logs/` and append a new section to `QA-Logs/bdqadebug.md` (Lenovo/Arch debug log) before iterating.

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

The server auto-loads `.env.dev` → `.env.prod` → `.env` (first found, non-overriding of existing env vars).

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
- **Project memory artifacts**: initialized by `prime_workspace()` (or `init_project_memory()`) and kept separate from generated protocol files:
  - `.devdocs/AGENT_MEMORY.md` for high-signal durable memory
  - `.cursor/hooks/state/continual-learning-index.json` for incremental transcript indexing
  - `AGENTS.md` remains generator-owned protocol text and should not be used as memory storage.

---

## License

MIT