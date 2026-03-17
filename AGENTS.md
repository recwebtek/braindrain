# AGENTS.md — BRAINDRAIN minimal protocol

## Rules (always)

1) **Discover first**: call `search_tools(query, top_k=...)` before repo-wide search/reading.
2) **Route big outputs**: use `route_output(text, source, intent=...)`; then retrieve via `search_index(query, limit=...)` (or `ctx_search`).
3) **Measure**: call `get_token_dashboard()` (or `get_token_stats()`) at milestones.
4) **Keep docs current**: if behavior/run paths/tools change, update `docs/SESSION_PROGRESS.md`, `docs/OPS.md`, and `README.md`.

## BRAINDRAIN hot tools (current)

- `search_tools`, `route_output`, `search_index`, `get_token_dashboard`, `get_token_stats`, `get_available_tools`, `ping`
