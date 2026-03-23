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
