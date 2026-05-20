# Jules Bolt PR #69 close-out — WikiBrain `detect_contradiction`

**Date:** 2026-05-19  
**Merged PR:** [#69](https://github.com/recwebtek/braindrain/pull/69) — optimize `WikiBrain.detect_contradiction`  
**Supersedes (closed as duplicate):** [#59](https://github.com/recwebtek/braindrain/pull/59), [#61](https://github.com/recwebtek/braindrain/pull/61), [#66](https://github.com/recwebtek/braindrain/pull/66)

## What shipped

- `SELECT record_id, title, content` instead of `SELECT *` (skips JSON hydration for unused columns).
- Direct row access instead of `_row_to_record` in the hot loop.
- Short-circuit: content similarity only when title similarity ≥ `0.78`.
- `tests/test_wiki_brain_contradiction.py` — regression + legacy parity probes.

## Related (already on `main`)

- [#50](https://github.com/recwebtek/braindrain/pull/50) — `_similarity()` fast-path (complementary; merged earlier).

## Duplicate PR rationale

| PR | Why closed |
|----|------------|
| #59 | Same optimization as #69 (older Jules run). |
| #61 | Partial fix (column select only; no title short-circuit). |
| #66 | Same optimization as #69 (older Jules run). |

## Ops note

After merge, restart the braindrain MCP connection if the server is running so tool hosts pick up the updated module.
