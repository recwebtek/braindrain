# Roadmap

Last aligned with **v1.0.3** (2026-04-10).

Public planning for this repo. For **local-only** scratch notes, use **`.devdocs/`** (gitignored, never commit).

## Shipped in v1.0.3

- Scriptlib (opt-in): harvest, search, describe, run, fork, record_result, refresh_index; integration in `braindrain/server.py` and workspace primer guidance.
- Subagent template deployment in `prime_workspace()` (Cursor + Codex templates, managed Codex config block).
- Token metrics checkpoint documentation (schema `1.0`) and installer/log path hygiene.

## Next (prioritized)

1. **L1 — Memory hardening**: retention and cleanup guidelines for `.braindrain/` and continual-learning index; document in this file and `README.md` when finalized.
2. **LLM wiki / context hub**: execute plans under `.cursor/plans/` (e.g. LLM wiki integration) with clear MCP surfaces and security boundaries.
3. **Admin / ops tools**: draft flows for operator-facing tools (see plan docs); keep `config/hub_config.yaml` and launcher paths in sync with `README.md` and `TODOS.md`.
4. **L2 / L3 memory tiers**: explicit semantics and optional `~/.braindrain/memory/` — design only until L1 is stable.

## Out of scope for this file

- Secrets, hostnames, tokens, or per-user MCP paths. Use `.env.example` and `README.md` for patterns, not live values.
