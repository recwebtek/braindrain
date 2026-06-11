# Learning layer gap audit

**Date:** 2026-05-15  
**Scope:** L0–L3 implementation vs plans, config, hooks, runtime on host  
**Source of truth (execution):** shipped modules (`braindrain/observer.py`, `session.py`, `wiki_brain.py`, `dream.py`) + this audit; L4+ design in [learning-layer-extended.plan.md](../.cursor/plans/learning-layer-extended.plan.md)

---

## Executive summary

| Area | Verdict |
| ---- | ------- |
| **Python runtime (L0–L3 core)** | **Shipped** — `observer.py`, `session.py`, `wiki_brain.py`, `dream.py`, MCP tools, `tests/test_memory_layers.py` |
| **L0–L3 narrow plan** | Todos complete; code matches restoration plan, not every original L0–L3 design choice |
| **Extended spec (L4–L12)** | Present on disk; L0–L3 status table updated in extended plan §12 |
| **hub_config.yaml** | **Drift** — no `observer` / `sessions` / `wiki_brain` / `dreaming` / `lessons` / `provider_context` blocks; code uses hardcoded `~/.braindrain/*` defaults |
| **Observation fidelity** | **Weak** — live `events.db` has **193 `session_end` events only** (stop hook); no `tool_call` events; no MCP auto-wrap |
| **Dream ops** | Engine runs; `run_dream` + `scripts/run_dream_cron.sh` exist; cron install not verified in this audit |

**Conclusion:** Research should shift from “build L0–L3” to **operationalize and close gaps** (config, observer wrap, docs sync, extended-spec §12), then **prioritize L4+** from [learning-layer-extended.plan.md](../.cursor/plans/learning-layer-extended.plan.md).

---

## 1. Plan artifact matrix

| Plan | `_master` (before audit) | Actual status | Recommendation |
| ---- | ------------------------ | ------------- | -------------- |
| [learning-layer-L0-L3-implementation.plan.md](../.cursor/plans/learning-layer-L0-L3-implementation.plan.md) | research-needed | All todos `completed`; body says historical | **implemented** |
| [braindrain_agent_restoration_plan_23207476.plan.md](../.cursor/plans/braindrain_agent_restoration_plan_23207476.plan.md) | active | Phase-one complete per plan | **active** (SoT) |
| [learning-layer-extended.plan.md](../.cursor/plans/learning-layer-extended.plan.md) | research-needed | L0–L3 landed; L4–L12 deferred; **§12 wrong** | **research-needed** (L4+ only) |
| [memory_lessons_hardening_77a0462a.plan.md](../.cursor/plans/memory_lessons_hardening_77a0462a.plan.md) | replan-needed | Todos completed; merged into restoration | **implemented** |

---

## 2. Code vs original L0–L3 design

### L0 — Observer

| Item | Planned | As-built |
| ---- | ------- | -------- |
| `BrainEvent` + ring buffer | Yes | [`braindrain/observer.py`](../braindrain/observer.py) — default max **10,000** events (plan cited 500k in extended TOML example) |
| Wrap every `@mcp.tool()` | Yes | **No** — **47** `@mcp.tool()` handlers in `server.py`, none auto-instrumented |
| Capture path | MCP boundary | **Stop hook** [`.cursor/hooks/on-stop-observe.sh`](../.cursor/hooks/on-stop-observe.sh) + opt-in `record_observer_event` |
| `learning.enabled` gate | Yes | **No** — stores init on first use |
| Args privacy (hash only) | Yes | **Partial** — hook logs git file lists; MCP accepts free-form `metadata` |

**Live data (this host):** `~/.braindrain/events.db` — **193 events**, all `session_end`, latest ts `1778844646`.

### L1 — Sessions

| Item | Planned | As-built |
| ---- | ------- | -------- |
| `SessionSummary` | Yes | [`braindrain/session.py`](../braindrain/session.py) |
| `session_start` / `session_end` | Yes | API + `touch_session`; **no auto session_start** on MCP connect |
| Activity guard | Yes | `SessionStore.should_dream()` → `DreamEngine.run()` |
| Episode bridge (L1.5) | Out of narrow L0–L3 | **Shipped** — `EpisodeRecord`, `record_episode`, lesson promotion |

### L2 — Wiki-Brain

| Item | Planned | As-built |
| ---- | ------- | -------- |
| Single `wiki.db` with counters | Yes | **Three DBs:** `events.db`, `sessions.db`, `wiki-brain/brain.db` |
| `workflow_frequency_counters` | L3 lite | **Not found** in codebase (grep) |
| FTS + cognitive recall | Minimal | **Full** WikiBrain with supersession, decay, metrics |

**Live data:** `get_memory_metrics()` → empty `record_counts` (no promoted facts on this host yet).

### L3 — Dream

| Item | Planned | As-built |
| ---- | ------- | -------- |
| `light_dream` only | Yes | **Light + REM + Deep** + `ConsolidationPlan` + `DREAMS.md` |
| In-process idle scheduler | Yes | **External cron** via [`scripts/run_dream_cron.sh`](../scripts/run_dream_cron.sh) (intentional per restoration) |
| Passive tier candidates | Yes | Heuristic promotion in deep phase; audit thresholds in config defaults only |

**Live data:** `get_dream_status()` returns a recent `full` plan with `session_end` source handles.

---

## 3. Configuration drift

[`config/hub_config.yaml`](../config/hub_config.yaml) ends at `provenance:` — missing blocks documented in restoration Part 5.

[`braindrain/config.py`](../braindrain/config.py) parses: `observer`, `sessions`, `wiki_brain`, `lessons`, `dreaming`, `provider_context`.

[`braindrain/server.py`](../braindrain/server.py) fallbacks:

| Key | Default path |
| --- | ------------ |
| `observer.storage_path` | `~/.braindrain/events.db` |
| `sessions.storage_path` | `~/.braindrain/sessions.db` |
| `wiki_brain.storage_path` | `~/.braindrain/wiki-brain/brain.db` |
| `dreaming.storage.base_dir` | `~/.braindrain/dreaming` |

**Naming collision:** `modules.context_database` comment “custom L0/L1/L2” is the **context DB module**, not learning-layer milestones.

---

## 4. Hooks and operations

| Surface | Status |
| ------- | ------ |
| [`.cursor/hooks.json`](../.cursor/hooks.json) | Wires `on-stop-observe.sh` (with gitops hooks) |
| Template [config/templates/cursor/hooks.json](../config/templates/cursor/hooks.json) | Also includes `on-stop-daily-plan-audit.sh` — **not** in deployed hooks.json |
| Dream cron | Helper script exists; **host cron/launchd install not verified** |
| Tests | [`tests/test_memory_layers.py`](../tests/test_memory_layers.py) — dream promotion path only |

---

## 5. Extended spec (L4–L12) — forward backlog

From [learning-layer-extended.plan.md](../.cursor/plans/learning-layer-extended.plan.md) §10 milestones (deferred):

| Milestone | Deliverable |
| --------- | ----------- |
| **L4** | Pattern Analyzer Pass A — PrefixSpan tool chains |
| **L5** | Pass B — context access graph |
| **L6** | Pass C — TierAffinityScore, OpenViking |
| **L7** | `deep_dream` + workflow fingerprints |
| **L8** | Clarification Agent |
| **L9** | Coordinator + adaptation lifecycle |
| **L10–L12** | defer_loading prefetch, PTC hints, CLI |

**Critical path to “Gate 2” (live adaptation):** L0 → L1 → L2 → L3 → **L7 → L9** (per extended spec). L0–L3 base is in place; next research slice is **L4–L7** or **operational gaps** below.

**Doc debt:** Extended spec §12 (“Repo implementation status snapshot”) states L0–L3 **not implemented** — contradicts code and restoration plan. **Update §12** on next plan edit.

---

## 6. Prioritized backlog

### P0 — Reconcile (low code, high clarity)

1. Add `observer` / `sessions` / `wiki_brain` / `lessons` / `dreaming` / `provider_context` to `hub_config.yaml` (match restoration Part 5).
2. Update `_master.plan.md` dispositions (see audit execution).
3. Fix extended spec §12 status table.
4. Align [ROADMAP.md](../ROADMAP.md) item 4 (“L2/L3 design only”) with shipped memory layer.

### P1 — Operationalize observation

1. MCP observer wrapper behind `observer.enabled` — hash args, record `tool_call` / duration / token estimates for hot tools first.
2. Emit `session_start` once per MCP connection (or document one-session-per-connection limitation).
3. Document retention: ring `max_events` (10k vs 500k), prune policy, privacy threat model.
4. Verify dream cron on host + document in README ops section.

### P2 — L4+ research / build

1. Spike **L4** tool-chain mining (or prove dream light phase already covers “good enough” counters).
2. OpenViking IPC feasibility (L6 prereq per extended §11).
3. Global vs per-project Wiki-Brain (`project_id` tagging) — extended §11 Q5.

### Non-goals (this phase)

- NATS event bus
- SQLCipher (unless threat model requires)
- Auto tier moves without confidence gates
- `modules.context_database` module

---

## 7. MCP memory surface (inventory)

Registered in `server.py` (learning-related):

- `record_observer_event`, `get_event_stats`
- `touch_session`, `get_session_summary`
- `record_episode`, `list_episodes`, `evaluate_lesson_candidate`
- `store_fact`, `query_facts`, `cognitive_recall`, `review_playbook`
- `record_memory_metric`, `get_memory_metrics`
- `get_provider_context_policy`
- `run_dream`, `get_dream_status`

---

*Audit produced per learning_layer_audit plan. Implementation work requires separate approval.*
