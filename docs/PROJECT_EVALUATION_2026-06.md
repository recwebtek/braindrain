---
name: Braindrain Project Evaluation — June 2026
created_by_model: claude-fable-5
created_at: 2026-06-10
last_modified_by_model: claude-fable-5
last_modified_at: 2026-06-10
cursor_mode: agent
scope: full-project audit (code, plans, deps, infra, MCP ecosystem currency)
---

# Braindrain MCP Hub — Full Project Evaluation (2026-06-10)

An honest, all-areas assessment of `BRAIN_MCP_HUB` v1.0.3: codebase, plans/roadmap,
dependencies, infrastructure, and how it measures against the cutting edge of the
MCP ecosystem as of June 2026.

> Working tree audited on branch `meta-plan-workflow`. LivingDash source lives on
> feature branches (`codex/livingdash`, `bugfix/livingdash-audit-fixes-ui-polish`,
> `ld-3-variant-cockpit`), not in this checkout.

---

## 1. Executive summary

Braindrain is a genuinely differentiated project: a token-economy MCP hub with a
layered memory system (L0 observer → L1 sessions → L2 WikiBrain → L3 dreaming),
BM25 tool gating, FTS5 output routing, workspace priming, a script library, a
planning auditor, and a 4-tier multi-agent system. The *ideas* are ahead of most
of the ecosystem. The *engineering hygiene* is behind them.

**Scorecard**

| Area | Grade | One-liner |
|---|---|---|
| Concept / product vision | A | Token-saving hub + layered memory is still a rare, valuable combination |
| Feature breadth | A− | 49 native tools, workflows, scriptlib, auditor, priming, multi-agent |
| Code architecture | C+ | Three mega-files carry most of the weight; mixed sync/async handlers |
| Protocol currency (MCP) | C | stdio fine; SSE fallback is legacy; no Streamable HTTP, no Tasks, no Apps |
| Dependencies / packaging | C− | Dual manifests, no lockfile, ~GB of unused torch via sentence-transformers |
| CI / QA infrastructure | D | 28 test files but **zero CI, zero lint, zero type-checking, no pre-commit** |
| Test coverage | B− | Strong on auditor/memory/primer; weak on the MCP server surface itself |
| Documentation | C+ | Rich but drifting: ROADMAP contradicts README, spec is gitignored, LivingDash docs reference missing code |
| Plan hygiene | C | 15 active plans, several shipped-but-marked-pending, 4 overlapping LivingDash plans |

**The three highest-leverage moves**

1. **Ship CI + lint + lockfile** (1–2 days of work, transforms credibility and safety).
2. **Adopt the MCP 2026-07-28 stateless model** — final spec ships **July 28, 2026**;
   you are inside the 10-week migration window right now.
3. **Reconcile LivingDash** — one plan of record, source merged to main, `livingdash:`
   config block added; consider rebuilding it as an **MCP Apps** extension UI.

---

## 2. What is genuinely strong

- **Token-economy design is coherent end-to-end**: BM25 `search_tools` gate (~300
  tokens vs full schemas), `route_output()` → context-mode FTS5, cached env probe,
  auto-route threshold at 4096 chars, telemetry with cost attribution.
- **Layered memory (L0–L3) actually shipped**: observer ring buffer, session
  episodes, WikiBrain FTS5 with decay/contradiction handling, dream consolidation
  with promotion guardrails (`require_grounded_evidence`). Most "agent memory"
  projects in 2026 are still a single vector store; this is more principled.
- **Workspace priming is a real product**: Ruler integration, bundle manifests,
  create-only memory protection, rollback manifests in `primed.json`, Cursor/Codex
  subagent + hook deployment.
- **Planning auditor** (`scripts/daily_plan_audit.py`, 4.7K lines) with 1.3K lines
  of tests is the best-tested subsystem in the repo — frontmatter contracts,
  dispositions, overlap detection, task board generation.
- **Test discipline where it exists is good**: schema-contract test
  (`test_mcp_tool_schemas.py`) enforcing docstring `Args:` for every tool param is
  a smart guard for Cursor tooltips.
- **Honest config**: `hub_config.yaml` is well-commented, local-first (LM Studio /
  Ollama before cloud), and explicit about what's off (`context_database: false`).

---

## 3. Protocol currency — the big 2026 story

### 3.1 MCP spec 2026-07-28 (RC locked 2026-05-21, final 2026-07-28)

This is the **largest protocol revision since launch** and it directly affects
braindrain's roadmap. Key changes:

| Spec change | Impact on braindrain |
|---|---|
| **Stateless core** (SEP-2567): protocol sessions and `Mcp-Session-Id` removed; capabilities travel in `_meta` on every request | Braindrain's per-process singletons (telemetry session, env cache) are process-state, not protocol-state — mostly fine for stdio, but any HTTP deployment must be rebuilt around this |
| **Streamable HTTP mandatory headers** (`Mcp-Method`, `Mcp-Name`, `MCP-Protocol-Version`) | Braindrain's only non-stdio transport is **legacy SSE** — deprecated since 2025-03-26 and now two generations behind. Must move to Streamable HTTP |
| **MRTR** (SEP-2322): elicitation/sampling embedded as `InputRequiredResult`, no SSE side-channel | Future interactive flows (admin-ops draft pipeline, intake questionnaires) should be designed against MRTR, not held streams |
| **Tasks extension** (SEP-2663): `tools/call` can return a task handle; client drives `tasks/get/update/cancel` | **Perfect fit** for `run_dream`, `run_workflow`, `prime_workspace`, `scriptlib_run_maintenance` — all long-running tools that currently block. The old experimental Tasks API is removed; only the new extension survives |
| **MCP Apps extension**: servers return sandboxed HTML UIs rendered by the host (Cursor, Claude Desktop, ChatGPT, VS Code all support it) | **This is the strategic answer to LivingDash.** Instead of a FastAPI+React sidecar with port management, ship the dashboard (token panel, plan board, memory browser) as `ui://` resources rendered inside the IDE |
| **Formal extensions framework** with reverse-DNS IDs and versioning | Braindrain's "hot vs deferred" catalog idea could be formalized as capability negotiation rather than YAML convention |
| **OAuth/OIDC alignment + CIMD** (successor to Dynamic Client Registration) | Only matters if braindrain is ever served remotely (e.g., LAN hub for multiple machines) — but it's now realistic to do safely |

**Timing**: the RC is locked, final spec lands July 28, 2026. Tier-1 SDKs ship
support within the validation window. The active plan
`bugfix/braindrain-mcp-enhancement-plan-2026-ble` already lists "Streamable HTTP"
— it should be re-scoped against the 2026-07-28 RC (stateless + headers + MRTR),
not the 2025-era transport.

### 3.2 FastMCP currency

- Pinned `fastmcp>=3.1.1`, resolved **3.3.1** locally; latest is **3.4.2**.
- FastMCP 3.x capabilities braindrain is **not using yet**:
  - **Background tasks** (Docket integration, SQLite/Postgres queues) — maps to the Tasks extension.
  - **Providers/transforms**: `FileSystemProvider` (hot-reload tool discovery — natural fit for scriptlib), `ProxyProvider` (proxy deferred external MCP servers through braindrain itself — would make the hub a *real* gateway instead of a YAML catalog), `SkillsProvider`, component versioning (`@tool(version="2.0")`).
  - **Visibility system** (`mcp.enable()/disable()`) — this is the *native* way to implement hot/deferred for the 49 in-process tools, which today are all always-registered despite the deferred-loading narrative.
  - **MCP Apps support** (`ui://` scheme, `AppConfig`) — shipped in 3.1.
  - **OpenTelemetry tracing** with MCP semantic conventions — complements your homegrown telemetry.
  - **Per-component authorization** — relevant for admin-ops draft pipeline.
- Note FastMCP 3 breaking changes when upgrading past your current floor:
  decorators return functions, async state methods, auth providers explicit.
  Worth a pinned-version bump + smoke run.

---

## 4. Codebase findings (honest)

### 4.1 Structure

~11.7K LOC across 30 modules, but weight concentrates badly:

| File | Lines | Problem |
|---|---|---|
| `braindrain/workspace_primer.py` | 2,242 | Ruler, gitignore, MCP patching, hooks, skills, rollback, memory — one module |
| `braindrain/server.py` | 1,762 | Entrypoint + all 49 tool handlers + wiring + monkey-patched decorator |
| `braindrain/scriptlib.py` | 1,530 | Entire script catalog subsystem |
| `scripts/daily_plan_audit.py` | 4,751 | The auditor is bigger than half the package |

**Recommendation**: split `server.py` into tool-group modules (FastMCP 3's
provider architecture supports composing them); split primer into
`primer/{ruler,hooks,memory,mcp_wiring,rollback}.py`.

### 4.2 Concrete debt items

1. **Mixed sync/async handlers** — sync `def` tools doing SQLite/file I/O can
   block the event loop (FastMCP 3's automatic threadpool mitigates, but be
   deliberate about it).
2. **Hot/deferred mismatch** — README and `get_available_tools` describe deferred
   loading, but all 49 native tools register at startup; only *external* YAML
   servers are deferred. `refresh_env_context` is "deferred" in config yet always
   exposed natively. Fix with FastMCP visibility or correct the docs.
3. **Stale API docs** — `plan_workflow` docstring still says "stub (Phase 3)"
   while partially implemented.
4. **Deprecated remnants** — `session_stats` global ("deprecated: use telemetry
   snapshot"), `.devdocs/` legacy path reads in primer, disabled
   `modules.context_database`, `estimate_claude_tokens()` char/4 shim.
5. **Broad `except Exception` → `{"error": str(e)}`** in workflow runs and
   `prime_workspace` — no structured error types, hard to triage from a client.
6. **`tool_registry._infer_schema()` infers every param as `"string"`** —
   weakens `search_tools` results quality.
7. **Mixed typing era** — `typing.Optional` in older modules vs `X | None` in
   newer ones; no type-checker to enforce either.
8. **LivingDash source absent from mainline** — `braindrain/livingdash*.py`,
   `braindrain/ldash/`, `.ldash/` exist only on feature branches, while deployed
   commands (`/livingdash`) and `.ldash/SIDECAR.md` reference them. Anyone
   cloning main gets broken commands.

### 4.3 Test coverage

Strong: plan auditor, primer hooks/rollback, WikiBrain, dream engine, scriptlib,
telemetry sanitization, MCP schema contract.

Weak/missing: end-to-end MCP server paths (`route_output`, `touch_session`,
`run_dream` via actual tool invocation), `context_mode_client` against a mock
server, `prime_workspace` E2E, embeddings HTTP paths, SSE/HTTP transport, full
`env_probe`. No coverage reporting, no `conftest.py`/`pytest.ini`.

---

## 5. Dependencies & packaging (needs real work)

| Issue | Detail | Fix |
|---|---|---|
| **Dual manifests drift** | `pyproject.toml` lacks `sentence-transformers`, `llm-sandbox`, `tomli-w`, `pytest` that `requirements.txt` installs | Make `pyproject.toml` canonical; generate constraints from it |
| **No lockfile** | Installs vary by date; no reproducibility | Adopt **uv** (`uv lock` / `uv sync`) — the 2026 default for Python projects, and already in your XDG config dirs |
| **~GB of dead weight** | `sentence-transformers` (→ torch 2.12, transformers 5.9, scipy) installed but **never imported** anywhere | Move to an optional extra: `pip install braindrain[embeddings]`; default install drops torch entirely. Better: use local LM Studio/Ollama embedding endpoints you already support, or `sqlite-vec` + a small ONNX model |
| **Unpinned everything** | pyyaml, pydantic, anthropic, rank-bm25 all floating | Pin floors at minimum; lock exact via uv |
| **Unpinned external MCP tools** | `npx -y context-mode`, `uvx jcodemunch-mcp`, etc. — upstream can break you any day | Pin versions in `hub_config.yaml` (`npx -y context-mode@x.y.z`) |
| **`anthropic` SDK floating at 0.104.x** | Fine, but unused-looking in core paths — verify it's needed in default install | Audit; move to extra if only used by deferred features |
| **BSD-only `sed -i ''` in `install.sh`** | Breaks GNU/Linux installs — contradicts the stated Arch/Linux reliability goal | Use a portable `sed` invocation or Python |
| **pytest 9 / FastMCP 3.3.1 floors** | Healthy and current; keep them moving | Renovate/Dependabot once CI exists |

Python floor `>=3.11`, install targets 3.11–3.14: **current and correct** for
mid-2026 (3.14 is stable). No change needed besides eventually testing 3.14 in CI.

---

## 6. Missing infrastructure (the D grade)

For a project that *other workspaces depend on via priming*, this is the most
important gap. None of this exists today:

1. **CI** — no `.github/` at all. Minimum viable: GitHub Actions matrix
   (3.11/3.12/3.14, macOS + ubuntu) running `pytest`, `ruff check`,
   `ruff format --check`. The MCP-enhancement plan already calls for this (P0).
2. **Lint/format** — adopt **ruff** (lint + format, replaces black/isort/flake8).
   `.gitignore` already mentions `.ruff_cache/` — the intent existed, the config never landed.
3. **Type checking** — **mypy or pyright** in non-strict mode first; the codebase
   has partial hints already. Pydantic 2 models for `hub_config.yaml` validation
   (also already on the enhancement plan) would catch config drift like the
   missing `livingdash:` block.
4. **Pre-commit** — ruff + ruff-format + trailing-whitespace + a secrets scanner
   (you've already hit GitHub push protection on test fixtures; `gitleaks` or
   `detect-secrets` in pre-commit prevents the next one).
5. **Coverage** — `pytest-cov` with a published threshold; you can't claim the
   memory layer is solid without a number.
6. **Release automation** — version is hand-rolled at 1.0.3 across
   `pyproject.toml`/config; a tag-driven release workflow + CHANGELOG discipline
   would close the "CHANGELOG newer than ROADMAP" class of drift.
7. **Evals** (cutting-edge, 2026): the core *claim* of braindrain is token
   savings (the spec targets "90–97% stacked reduction"). There is no automated
   benchmark proving it. Build a small eval harness: fixed agent transcript
   replays through hub-on vs hub-off, assert savings %, run in CI nightly. This
   turns your headline feature from anecdote into regression-protected fact.

---

## 7. Plans & documentation — drift inventory

### 7.1 Disposition debt (shipped but marked pending)

| Plan | Reality | Action |
|---|---|---|
| Plan auditor (0/11 todos) | Largely shipped — reports generated 2026-06-09 | Mark todos, archive or close out |
| Scriptlib Phase 1 (`implemented`, 0/6 todos) | Shipped | Fix todo states |
| Token cost (87%, PR #64 closed, still `active`) | P0–P2 shipped | Close P3 into the MCP-enhancement plan |
| Claude claurst research (9/9 done, `research-needed`) | Research complete | Archive or spawn implementation plan |

Run `python3 scripts/daily_plan_audit.py --apply-disposition-sync` (human + CLI
per policy) after fixing frontmatter.

### 7.2 LivingDash: four conflicting active plans

`livingdash.plan.md` (old `braindrain/dashboard/` arch), `LivingDash-v1-refined`
(`.ldash/` sidecar), `codex-ldash-restyle` (purple MVP), `ldash_style+feature`
(references non-existent `braindrain/livingdash.py` paths). Plus PR #44 open.

**Pick one source of truth, supersede the rest in `_master.plan.md`, merge the
source to main, add the `livingdash:` block to `hub_config.yaml`** — and
seriously evaluate MCP Apps (§3.1) before investing more in the sidecar: an
in-IDE `ui://` dashboard removes the port/process/venv management that the
sidecar plans spend most of their complexity on.

### 7.3 Documentation contradictions

- `ROADMAP.md` says L2/L3 are "design only" — README correctly says they shipped. Update ROADMAP.
- Full spec (`BRAIN_CONTEXT_HUB_FULL_SPEC_v2.md`) lives in **gitignored** `.devdocs/` — the project's defining document is invisible to a fresh clone. Move a sanitized copy to `docs/`.
- `learning-layer-extended.plan.md` points to an **archived** plan as its source of truth.
- Template/deployed drift: `metaplan-closeout.md` ships in templates but isn't deployed; `/livingdash` command imports a missing module.
- Protocol text quadruplicated (`AGENTS.md`, `CLAUDE.md`, `braindrain.mdc`, `RULES.md`) — by Ruler design, but consider slimming the per-file payload; it's a large always-on context tax in every chat, which is ironic for a token-saving project. Measure it with your own dashboard.
- `TODOS.md` (4 bullets) doesn't reflect 9 active implementation plans — either generate it from the auditor or delete it.

### 7.4 Spec vision vs reality (unbuilt items worth a decision)

| Spec item | Status | Honest recommendation |
|---|---|---|
| OpenViking L0/L1/L2 (Module D) | Replaced by native L0–L3 | **Formally retire it** in the spec; native path won |
| LiteLLM proxy + semantic cache | Not built | Re-evaluate: in 2026, IDE-side routing (Cursor models, LM Studio) covers most of this; likely **drop** |
| token-compressor integration | Not built | Low value vs route_output; **drop or backlog** |
| Docker + Redis stack | Not built | Only needed if hub goes multi-machine HTTP; defer until stateless HTTP work (§3) |
| LLM Wiki layer | Backlogged | WikiBrain L2 covers 70%; merge the plan into a WikiBrain extension rather than a new subsystem |
| Admin-ops draft-tool pipeline | Backlogged | Good idea; design against MRTR elicitation + per-component auth when picked up |
| AI Shell plugin | `replan-needed` | Confirm it's still wanted before rewrite; overlaps with what Cursor/Codex shells already provide in 2026 |

---

## 8. What's missing for "cutting-edge June 2026"

Beyond spec migration (§3) and infra (§6), the gaps vs the 2026 frontier:

1. **Hybrid retrieval.** `search_index` is FTS5-only. The 2026 baseline for
   local-first search is **FTS5 + vectors in one SQLite file via `sqlite-vec`**,
   with reciprocal-rank fusion. You already have local embedding providers
   configured (LM Studio/Ollama) — wire them in behind a flag. This is already on
   the enhancement plan ("hybrid memory"); it's the right call.
2. **MCP gateway, not just catalog.** Today "deferred" external servers are YAML
   metadata; the agent still has to attach them separately. With FastMCP
   `ProxyProvider`, braindrain could *be* the single attached server that lazily
   proxies repo_mapper/jcodemunch/github/etc., applying your telemetry, output
   routing, and token accounting to every downstream call. That's the strongest
   version of the hub concept and nobody-else's-tooling does it well yet.
3. **MCP Apps for all dashboards.** Token dashboard, plan task board, memory
   browser, dream status — these are all naturally `ui://` app surfaces rendered
   in Cursor. LivingDash becomes the flagship app instead of a sidecar.
4. **Tasks for long-running tools.** `run_dream`, `run_workflow`,
   `prime_workspace`, scriptlib maintenance → task handles with progress, via
   FastMCP background tasks now, spec Tasks extension after July 28.
5. **Structured tool outputs.** Define Pydantic output models for the high-traffic
   tools (`get_token_dashboard`, `search_tools`, `get_session_summary`) so hosts
   get typed `structuredContent` instead of JSON-in-text. Already on the
   enhancement plan — prioritize it.
6. **OpenTelemetry export.** Your telemetry JSONL is good; emitting OTel spans
   with MCP semantic conventions (FastMCP 3 built-in) makes it interoperable
   with any 2026 observability stack for free.
7. **Token-savings eval harness** (§6.7) — the single most persuasive artifact
   the project could have, and it doesn't exist.
8. **MCP Registry presence.** The official MCP registry ecosystem matured through
   2025–26; publishing braindrain (with `server.json` metadata) is cheap
   distribution once CI exists.
9. **Security posture for tool execution.** `scriptlib_run` and `run_workflow`
   execute code; sandbox guarantees are Docker-optional and fail-soft. Document a
   threat model; require explicit opt-in config for non-sandboxed execution;
   pre-commit secrets scanning (§6.4).

---

## 9. Deprecated / retire list (quick reference)

| Item | Where | Action |
|---|---|---|
| SSE transport fallback | `server.py` `main()` | Replace with Streamable HTTP (stateless, 2026-07-28 headers) |
| `session_stats` global | `server.py` | Delete after one release |
| `.devdocs/` legacy reads | `workspace_primer.py` | Remove migration path; `.braindrain/` is canonical |
| `modules.context_database` | `hub_config.yaml` | Delete the dead flag + any code behind it |
| `plan_workflow` "stub" docstring | `server.py` | Rewrite to match implementation |
| `estimate_claude_tokens()` char/4 shim | `telemetry.py` | Fold into estimator selection |
| OpenViking / LiteLLM / token-compressor spec modules | `.devdocs/` spec v2 | Mark superseded in a spec v3 §12 update |
| `sentence-transformers` dependency | `requirements.txt` | Remove from default install (unused) |
| Old `braindrain/dashboard/` LivingDash plan | `.cursor/plans/livingdash.plan.md` | Supersede |
| `typing.Optional` style in older modules | `types.py` etc. | Sweep when ruff lands (`UP` rules) |

---

## 10. Prioritized action plan

### P0 — this month (before MCP final spec lands July 28)
1. **CI + ruff + lockfile (uv) + pre-commit + secrets scan.** Foundation for everything else.
2. **Unify packaging**: `pyproject.toml` canonical, `sentence-transformers` → optional extra, pin external `npx`/`uvx` versions.
3. **LivingDash reconciliation**: one plan, merge source to main, `livingdash:` config block, fix `/livingdash` command.
4. **Plan disposition sync** + ROADMAP/spec §12 truth-up (cheap, removes the contradictions a new contributor hits first).

### P1 — next 4–8 weeks
5. **Streamable HTTP (stateless) transport** replacing SSE; validate against the 2026-07-28 RC during the official window.
6. **Pydantic config schema** for `hub_config.yaml` with validation errors at startup.
7. **Structured outputs** on the top-10 tools; fix `_infer_schema` string-typing.
8. **Split `server.py` / `workspace_primer.py`** into modules (do alongside #7 while touching every handler).
9. **Token-savings eval harness** in CI (nightly).

### P2 — quarter
10. **Tasks extension** for long-running tools (FastMCP background tasks).
11. **Hybrid retrieval** (`sqlite-vec` + FTS5 fusion) behind config flag, local-first embeddings.
12. **ProxyProvider gateway mode** — braindrain as the single attached MCP server proxying the deferred catalog with telemetry on every hop.
13. **MCP Apps**: token dashboard + plan board as `ui://` apps; fold LivingDash direction into this.

### P3 — strategic
14. OpenTelemetry export; MCP Registry publication; per-component auth + remote (LAN) deployment using the new OAuth/CIMD model; revisit admin-ops pipeline on MRTR; spec v3 rewrite retiring superseded modules.

---

## 11. Bottom line

Braindrain's vision — *the token-economy layer every coding agent should sit
behind* — is more relevant in June 2026 than when the spec was written, because
context costs and multi-agent orchestration both grew. The memory stack and
auditor are real, working differentiators. What holds the project back is not
ideas or features; it is the absence of the boring layer (CI, pinning, lint,
typing, evals) and protocol drift (SSE-era transport, sidecar-era dashboard) at
the exact moment the MCP ecosystem is re-architecting around stateless HTTP,
Tasks, and Apps. The P0 list is roughly one focused week of work and would move
the project from "impressive personal infrastructure" to "credible
open-source platform."
