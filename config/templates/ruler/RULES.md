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

### BRAINDRAIN hot tools (cheat sheet)

| Tool | Purpose |
|---|---|
| `get_env_context(refresh=False)` | Cached OS fingerprint — call this first |
| `prime_workspace(path=".", agents=None, dry_run=False, sync_templates=False, sync_subagents=False, all_agents=False, local_only=True, codex_agent_targets=None)` | Prime project; auto-detects IDE, writes `.braindrain/primed.json`, deploys Cursor/Codex subagent files |
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

### Ops/docs to keep current (when behaviour/run paths/tools change)

- `.braindrain/SESSION_PROGRESS.md`
- `.braindrain/OPS.md`
- `.braindrain/AGENT_MEMORY.md`
- `README.md`

### Ownership boundaries (important)

- `AGENTS.md` is generated protocol and environment context only.
- High-signal project memory belongs in `.braindrain/AGENT_MEMORY.md` (gitignored, never committed).
- Use `prime_workspace()` for full project onboarding and `init_project_memory()` for memory-only initialization.
- `.braindrain/` is **never** committed — it is machine-local and gitignored.

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
