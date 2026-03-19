# BRAIN MCP HUB

A lightweight MCP server hub providing custom tools for token efficiency, output routing, workflow automation, and OS environment fingerprinting across AI-powered editors and agents.

## What BRAINDRAIN does

### Phase 1 — Tool discovery shell
- FastMCP server with tiny always-loaded surface
- BM25-powered `search_tools` for deferred tool discovery
- Config-driven `defer_loading` to avoid baseline token bloat

### Phase 2 — Output sandbox + telemetry
- Large outputs routed into `context-mode` (FTS5) instead of dumped into model context
- `route_output` + `search_index` for index/retrieve cycle
- `get_token_dashboard` / `get_token_stats` for estimated token savings + JSONL logs

### Phase 3 — Workflow engine
- `run_workflow` executes multi-step workflows with output routing
- `plan_workflow` emits a markdown execution plan for review
- Docker sandbox stage (`llm-sandbox`); falls back to deterministic local summary
- First workflows: `ingest_codebase`, `refactor_prep`

### Phase 3.5 — Environment context tool
- `get_env_context(refresh=False)` — returns a cached OS fingerprint (hostname, LAN IPs, shell, runtimes, package managers, CLI tools, agent hints) with zero token overhead after first probe
- `refresh_env_context()` — re-runs the ~35-command parallel probe and updates the cache at `~/.braindrain/env_context.json`
- Deterministic synthesis — no LLM involved, pure subprocess capture
- HOT tool — always loaded, tiny definition footprint

---

## MCP Tools

| Tool | Type | Purpose |
|---|---|---|
| `search_tools` | HOT | Discover deferred tools by capability |
| `get_env_context` | HOT | Cached OS fingerprint (shell, runtimes, tools, hints) |
| `get_available_tools` | HOT | List hot vs deferred tools |
| `get_token_dashboard` | HOT | Compact token savings snapshot |
| `get_token_stats` | HOT | Full session cost tracking |
| `ping` | HOT | Health check |
| `route_output` | HOT | Index large text into context-mode |
| `search_index` | HOT | Retrieve from context-mode FTS5 index |
| `list_workflows` | HOT | List available workflows |
| `run_workflow` | HOT | Execute a workflow in sandbox |
| `plan_workflow` | HOT | Generate markdown execution plan |
| `refresh_env_context` | deferred | Re-probe OS environment and update cache |

---

## Installation

### Prerequisites

- Python 3.12+
- A running MCP-compatible client (Cursor, Zed, Windsurf, OpenCode, etc.)

### Setup

```bash
git clone https://github.com/youruser/BRAIN_MCP_HUB.git
cd BRAIN_MCP_HUB

python3.12 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

### Run manually (stdio)

```bash
. .venv/bin/activate
python braindrain/server.py stdio
```

The `config/braindrain` launcher script is the preferred entry point for IDE configs — it handles the venv Python automatically:

```bash
# Launcher (used by all IDE configs below)
/Volumes/devnvme/Development/BRAIN_MCP_HUB/config/braindrain
```

> **Important:** The launcher calls `.venv/bin/python` directly. Do not replace this with a bare `python3` call — if pyenv or system Python is a different version (e.g. 3.8), it will have none of the project's dependencies and the server will crash silently on startup.

---

## IDE / Agent Configuration

Update the paths below to match your local repo location.

### Cursor

Add to `.cursor/mcp.json` (workspace) or via **Settings > Features > MCP**:

```json
{
  "mcpServers": {
    "braindrain": {
      "command": "/path/to/BRAIN_MCP_HUB/config/braindrain",
      "args": [],
      "env": {}
    }
  }
}
```

### Windsurf

Add to `~/.codeium/windsurf/mcp_config.json`:

```json
{
  "mcpServers": {
    "braindrain": {
      "command": "/path/to/BRAIN_MCP_HUB/config/braindrain",
      "args": [],
      "env": {}
    }
  }
}
```

### Zed

Add to `~/.config/zed/settings.json` under the **`context_servers`** key.
This is the correct key for custom MCP servers in Zed — not `mcp_servers`.

```json
{
  "context_servers": {
    "braindrain": {
      "command": "/path/to/BRAIN_MCP_HUB/config/braindrain",
      "args": [],
      "env": {}
    }
  }
}
```

After adding or editing the entry, reload via command palette: **`agent: reload context servers`** (or restart Zed). The server will appear in the Agent panel's MCP section once the handshake succeeds.

### OpenCode

Add to `~/.config/opencode/opencode.jsonc` (note: OpenCode uses an array for the command):

```jsonc
{
  "mcp": {
    "braindrain": {
      "type": "local",
      "command": ["/path/to/BRAIN_MCP_HUB/config/braindrain"]
    }
  }
}
```

### Codex / Claude Desktop format

```json
{
  "mcpServers": {
    "braindrain": {
      "command": "/path/to/BRAIN_MCP_HUB/config/braindrain",
      "args": [],
      "env": {}
    }
  }
}
```

### Antigravity (Google)

```json
{
  "mcpServers": {
    "braindrain": {
      "command": "/path/to/BRAIN_MCP_HUB/config/braindrain",
      "args": [],
      "env": {}
    }
  }
}
```

---

## Environment Variables

| Variable | Purpose |
|---|---|
| `BRAINDRAIN_CONFIG` | Override config path (default: `config/hub_config.yaml`) |
| `GITHUB_TOKEN` | GitHub MCP tool (deferred) |
| `OPENAI_API_KEY` | Optional — Sourcerer semantic search |
| `OLLAMA_HOST` | Optional — local embeddings backend |
| `FILESCOPE_MCP_SERVER_JS` | Optional — FileScopeMCP wiring |
| `BRAINDRAIN_DISABLE_DOCKER_SANDBOX` | Set to `1` to disable Docker sandbox stage |

Start from `.env.example`. Use `.env.dev` / `.env.prod` for environment separation. The server auto-loads the first file it finds (`.env.dev` → `.env.prod` → `.env`) without overriding existing env vars.

---

## Token reduction: how to validate

```python
# Call via any connected MCP client:
get_token_dashboard()    # quick snapshot
get_token_stats()        # full breakdown with module attribution
```

On-disk JSONL log: `~/.braindrain/costs/session.jsonl`

---

## Output routing: quick test

```python
# Index a large blob — returns handle + suggested_queries
route_output(text="...", source="my_tool", intent="summarise")

# Retrieve only the relevant section
search_index(query="the thing I need", limit=5)
```

---

## Workflows

```python
list_workflows()                          # see what's available
plan_workflow("refactor_prep", {...})     # review before running
run_workflow("ingest_codebase", {...})    # execute in sandbox
```

Docker Desktop must be running for the Docker sandbox stage. Set `BRAINDRAIN_DISABLE_DOCKER_SANDBOX=1` to skip it.

---

## Environment context

```python
# First call runs the probe and caches to ~/.braindrain/env_context.json
get_env_context()

# Subsequent calls return instantly from cache
get_env_context()

# After installing new tools or switching machines:
refresh_env_context()
```

The probe fires ~35 read-only shell commands in parallel (5s timeout each), synthesises them deterministically, and renders a ready-to-paste AGENTS.md block.

---

## Repo structure

```
BRAIN_MCP_HUB/
├── braindrain/
│   ├── server.py               # FastMCP server + all MCP tools
│   ├── config.py               # YAML config loader
│   ├── env_probe.py            # OS fingerprint probe + cache (Phase 3.5)
│   ├── context_mode_client.py  # context-mode stdio client
│   ├── mcp_stdio_client.py     # generic stdio MCP client
│   ├── output_router.py        # large output → context-mode index
│   ├── telemetry.py            # token telemetry + JSONL logging
│   ├── embeddings_router.py    # local-first embeddings scaffold
│   ├── workflow_engine.py      # workflow engine + sandbox
│   ├── tool_registry.py        # defer_loading + BM25
│   └── types.py
├── config/
│   ├── hub_config.yaml         # main config
│   ├── braindrain              # launcher script (uses .venv/bin/python)
│   ├── zed_mcp.json            # Zed reference config
│   ├── opencode_mcp.jsonc      # OpenCode reference config
│   └── com.braindrain.mcp.plist
├── tests/
│   ├── test_core.py
│   ├── test_workflow_engine.py
│   └── fake_mcp_tool_server.py
├── AGENTS.md                   # agent protocol (minimal, always-on)
├── requirements.txt
└── pyproject.toml
```

---

## Phase 4 (upcoming)

- Custom memory system L0/L1/L2 (`~/.braindrain/memory/`)
- `refresh_env_context()` auto-updates the `<!-- ENV_CONTEXT_START -->` block in `AGENTS.md`
- Session-level memory with lightweight local model for compression