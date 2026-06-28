# MCP Apps — SIGINT Map UI

Operational topology graph for the active agent/MCP session — vanilla SVG force layout fed by braindrain-native observability (observer events, MCP catalog, plans, hooks). Inspired by relationship-map UIs but scoped to runtime intelligence, not external news signals.

## Quick start

1. **Restart** the braindrain MCP connection after code changes (`braindrain/mcp_apps/` or server registration).
2. In chat, invoke **`show_sigint_map`** (or ask the agent to open the SIGINT map).
3. Use a few braindrain tools and end a Cursor turn (stop hook) so `~/.braindrain/events.db` has `tool_call` / `session_end` rows.
4. The graph auto-polls every **8 seconds** via app-only **`poll_sigint_map`**.

Default project root is the braindrain server workspace unless you pass `path`.

## Architecture

| Piece | Role |
| ----- | ---- |
| `show_sigint_map` | Opens the inline MCP App; returns graph payload + UI resource |
| `poll_sigint_map` | **App-only** refresh for the iframe (not for the model) |
| `braindrain/mcp_apps/sigint_data.py` | `build_sigint_map_payload()` — nodes, edges, event log |
| `braindrain/mcp_apps/sigint_html.py` | SVG orbital tree graph, type filters, inspector panel, poll loop |
| `braindrain/observer.py` | SQLite event store (`~/.braindrain/events.db`) |
| `config/templates/cursor/hooks/on-stop-observe.sh` | `session_end` rows with hook branch/repo metadata |

## Node types (v1)

| type | Source |
| ---- | ------ |
| `session` | `BRAINDRAIN_SESSION_ID`, arg, or latest observer session |
| `braindrain_hub` | Singleton anchor for the braindrain MCP server |
| `braindrain_tool` | Distinct `tool_name` from `tool_call` events |
| `external_mcp` | `.cursor/mcp.json` + `.braindrain/mcp-catalog/` (excluding braindrain) |
| `subagent` | `metadata.subagent` / `metadata.agent_type` when present |
| `plan` | Active plans from plan-board loaders (not archived) |
| `hook` | `metadata.hook` on `session_end` (e.g. Cursor stop hook) |

## Edge types (v1)

| type | Meaning |
| ---- | ------- |
| `tool_call` | Hub or session → braindrain tool |
| `downstream_mcp` | Hub → configured external MCP (**dashed** until live calls observed) |
| `hook_fire` | Session → hook on `session_end` |
| `plan_active` | Session → plan when hook branch matches plan `branch:` |
| `subagent_dispatch` | Session → subagent when metadata recorded |

No LLM-inferred edges — deterministic from stored events + config only.

## UI behavior

- **Orbital tree layout** on a larger canvas (960×520): session at center, type-specific rings with **even sibling spread** per branch (Plans / External MCP arcs). Sector labels mark each branch.
- **Pan & zoom**: scroll wheel, drag background, **+ / − / Fit / 1:1** controls; viewport persists across polls. Double-click a node to focus.
- **Type filters**: toggle chips above the graph show/hide node types and their edges; filter state persists across 8s polls.
- **Inspector** (right panel): selected node metadata + last related events.
- **Log strip**: last 20 observer events (AI Signal Engine–style agent log).
- **Empty state**: “No session events yet — run a braindrain tool or end a Cursor turn (stop hook).”

## Session ID heuristics

Cursor may omit `CURSOR_TRACE_ID`; stop-hook fallback IDs (`hook-YYYYMMDD-*`) may not match MCP `mcp-default`. The payload builder:

1. Uses explicit `session_id` arg, then `BRAINDRAIN_SESSION_ID`, then latest events for the project.
2. When no rows match the resolved session, unions events within a **~2 hour** window.

## Known gaps (v1)

- **Subagent visibility**: Task/subagent dispatches in Cursor do not pass through braindrain MCP unless explicitly recorded (`record_observer_event` with `subagent` metadata).
- **External MCP live edges**: Configured servers appear as nodes; dashed edges until phase-2 IDE hooks ship.
- **Read-only**: No write actions from the graph (handoff, archive) in v1.

## Observer enrichment

`tool_call` events now include `metadata.project_root` from the server workspace when instrumentation runs through `make_observe_mcp_tool`. This improves plan/session linking in multi-root workflows.

## Deferred (phase 2)

- Cursor pre/post MCP hooks for IDE-originated external MCP edges
- Codebase tech layer (file clusters, stack nodes)
- Day rail / multi-session timeline
- Write actions from graph
- SSE push stream
