# BRAIN MCP HUB

Welcome to the BRAIN MCP HUB. This repository provides custom Model Context Protocol (MCP) servers (like `braindrain`) that can be used across various AI-powered editors and agents to enhance context discovery, token efficiency, and workflows.

## What BRAINDRAIN does (Phase 2)

- **Tool discovery shell**: keeps the always-loaded tool surface tiny (Phase 1).
- **Output sandbox routing**: large outputs can be indexed into `context-mode` (FTS5) instead of being dumped into the model context.
- **Token telemetry**: `get_token_dashboard` / `get_token_stats` exposes estimated “raw vs actual” tokens saved, and writes JSONL logs to disk.

## Run paths (dev + prod)

### Dev (recommended)

- **Create venv** (Python 3.12+ recommended):

```bash
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
```

- **Run BRAINDRAIN server (stdio)**:

```bash
. .venv/bin/activate
python braindrain/server.py stdio
```

### “Prod” (stable local install)

- Use the launcher script referenced by your IDE MCP config:
  - `config/braindrain` (this repo’s wrapper/launcher)
- Keep configuration in:
  - `config/hub_config.yaml`
- Keep secrets in environment variables (see `.env.example`).

## Environment variables (devops notes)

- **BRAINDRAIN_CONFIG**: override config path (default: `config/hub_config.yaml`)
- **GITHUB_TOKEN**: used by GitHub MCP tool (deferred)
- **OPENAI_API_KEY**: optional (for Sourcerer if configured)
- **OLLAMA_HOST**: optional (for local embeddings backends)
- **FILESCOPE_MCP_SERVER_JS / FILESCOPE_BASE_DIR**: optional (for FileScopeMCP wiring)

See `.env.example` for a starting point. If you keep separate environments, use `.env.dev` / `.env.prod` and load them in your launcher script or shell profile.

## Token reduction: how to see it

- **MCP tool**: `get_token_dashboard`
  - Shows estimated: `tokens_in_raw_est`, `tokens_in_actual_est`, `tokens_saved_est`, and per-tool breakdown.
- **Logs**: JSONL events written to:
  - `~/.braindrain/costs/session.jsonl` (configured in `config/hub_config.yaml`)

## Output routing: how to test quickly

- Use the MCP tool `route_output` to index large text into `context-mode`:
  - Returns `handle` + `suggested_queries`
- Then call `search_index` (or `ctx_search` directly on the `context-mode` MCP server) to retrieve the relevant chunks.

## Installation Guide (AI Agents & IDEs)

Below are the configuration snippets to install the `braindrain` MCP server into various modern AI editors and agents. Just copy the relevant JSON snippet into the editor's configuration file as documented.

### 1. Cursor
To add the MCP server in Cursor, you can either add it via the **Cursor Settings > Features > MCP** GUI, or place the following in your `.cursor/mcp.json` file inside your workspace:

```json
{
  "mcpServers": {
    "braindrain": {
      "command": "/Volumes/devnvme/Development/BRAIN_MCP_HUB/config/braindrain",
      "args": [],
      "env": {}
    }
  }
}
```

### 2. Windsurf
Windsurf uses a global configuration file for MCP servers. Open `~/.codeium/windsurf/mcp_config.json` and add the braindrain server:

```json
{
  "mcpServers": {
    "braindrain": {
      "command": "/Volumes/devnvme/Development/BRAIN_MCP_HUB/config/braindrain",
      "args": [],
      "env": {}
    }
  }
}
```

### 3. Zed
Zed mounts custom MCP servers under the `context_servers` key in your Zed settings. Open `~/.config/zed/settings.json` and add the following configuration:

```json
{
  "context_servers": {
    "braindrain": {
      "command": "/Volumes/devnvme/Development/BRAIN_MCP_HUB/config/braindrain",
      "args": [],
      "env": {}
    }
  }
}
```

### 4. Opencode
Opencode uses a dedicated JSONC configuration file for determining MCP endpoints. Open `~/.config/opencode/opencode.jsonc` and add it to the `mcp` object. Note that Opencode uses an array for the command block:

```jsonc
{
  "mcp": {
    "braindrain": {
      "type": "local",
      "command": ["/Volumes/devnvme/Development/BRAIN_MCP_HUB/config/braindrain"]
    }
  }
}
```

### 5. Codex
Codex relies on standard Claude Desktop formatted configuration files. Place this configuration in your `.codexrules` or the corresponding `mcp.json` file used by your Codex agent environment:

```json
{
  "mcpServers": {
    "braindrain": {
      "command": "/Volumes/devnvme/Development/BRAIN_MCP_HUB/config/braindrain",
      "args": [],
      "env": {}
    }
  }
}
```

### 6. Antigravity
For Antigravity (Google DeepMind's agent), MCPs are parsed using standard definitions. Add the following to your `mcp.json` or equivalent agent settings config file (typically resolving in `~/.gemini/antigravity/mcp.json` or local `.gemini` folder):

```json
{
  "mcpServers": {
    "braindrain": {
      "command": "/Volumes/devnvme/Development/BRAIN_MCP_HUB/config/braindrain",
      "args": [],
      "env": {}
    }
  }
}
```

---

*Note: The executable path (`/Volumes/devnvme/Development/BRAIN_MCP_HUB/config/braindrain`) is absolute. Ensure this path is correctly pointing to the compiled executable on your machine.*
