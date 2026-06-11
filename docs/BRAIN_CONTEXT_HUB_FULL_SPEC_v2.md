---
title: BRAIN_CONTEXT_HUB_FULL_SPEC_v2
version: "2.1-sanitized"
sanitized: true
sanitized_at: "2026-06-11"
source: ".devdocs/BRAIN_CONTEXT_HUB_FULL_SPEC_v2.md (gitignored; machine-local)"
note: >
  Public clone copy. Hostnames, absolute paths, tokens, and per-user install
  paths are redacted or generalized. Architecture content is preserved.
  See §13 for modules superseded by shipped braindrain v1.0.x.
---

# BRAIN: Intelligent MCP Context Hub
## Specification · PRD · Architecture · Build Guide
**Version:** 2.0 | **Platform:** Python 3.11+ · optional Docker for workflow sandbox  
**Public sanitized copy** — see README for current install paths.

---

## EXECUTIVE SUMMARY

**braindrain** is a modular, plug-and-play MCP server that acts as an intelligent context orchestration hub between any AI coding client and the ecosystem of downstream MCP tools, local models, and cloud APIs.

**Core thesis:** Every token that enters a model's context window costs money and degrades quality. braindrain intercepts context at every layer — tool definitions coming in, tool results going out, memory across sessions, and workflow data mid-execution — and ensures only the minimum relevant tokens ever reach the frontier model.

**What it is NOT:** A monolith. braindrain does not reimplement what open-source tools already do well. It is a thin, intelligent routing and compression layer that connects modular components via configuration. Adding a new capability = adding lines to `hub_config.yaml`. Zero code changes to braindrain server itself.

**Target reduction:** 90–97% token spend on long-running agentic coding sessions vs naive implementations.

---

## 1. THE PROBLEM — FOUR TOKEN FLOOD SOURCES

Long agentic coding sessions fail catastrophically on cost and quality because of four independent token flood sources that no single existing tool addresses together:

```
FLOOD SOURCE 1 — DEFINITIONS IN
  58 MCP tools loaded upfront = 55K tokens before first message
  134K tokens in real Anthropic production cases
  → Model can't fit real work; accuracy degrades; cost spikes immediately

FLOOD SOURCE 2 — RESULTS OUT  
  One Playwright snapshot: 56 KB
  20 GitHub issues: 59 KB  
  One access log: 45 KB
  After 30 minutes: 40% of 200K context consumed by raw tool outputs

FLOOD SOURCE 3 — WORKFLOW INTERMEDIATE DATA
  "Check which team members exceeded budget" → 2,000+ expense line items
  in context even though only the 3 names matter
  Each sub-step result accumulates whether relevant or not
  5-step workflow = 5 inference passes + all intermediate data in window

FLOOD SOURCE 4 — CROSS-SESSION ENTROPY
  Every new session reloads the entire codebase, all tool descriptions,
  all past decisions — as if nothing was ever learned
  No progressive loading, no memory tiering, no self-improvement
```

**braindrain solves all four simultaneously via four modular layers.**

---

## 2. THE SOLUTION — MODULAR PLUG-AND-PLAY ARCHITECTURE

Each flood source has a dedicated module. Modules are independently replaceable. You use only what you need.

```
┌─────────────────────────────────────────────────────────────────────┐
│                    BRAIN CONTEXT HUB v2.0                          │
│           "MCP is the protocol. braindrain is the context OS."          │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  MODULE A — TOOL GATE          solves FLOOD SOURCE 1               │
│  Anthropic defer_loading beta  definitions never pre-loaded         │
│  braindrain exposes ~500 token shell; tools discovered JIT               │
│                                                                     │
│  MODULE B — OUTPUT SANDBOX     solves FLOOD SOURCE 2               │
│  context-mode MCP              all tool outputs → FTS5 index        │
│  315 KB raw output → 5.4 KB    98% output token reduction           │
│                                                                     │
│  MODULE C — WORKFLOW ENGINE    solves FLOOD SOURCE 3               │
│  llm-sandbox + PTC             intermediate data in Docker sandbox  │
│  Only final summary returned   never touches context window         │
│                                                                     │
│  MODULE D — CONTEXT DATABASE   solves FLOOD SOURCE 4               │
│  OpenViking L0/L1/L2           memory, resources, skills tiered     │
│  L0=100 tokens always loaded   L2=full content only when needed     │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### 2.1 Modular Opt-In Design

Every module is independently toggled in `hub_config.yaml`:

```yaml
modules:
  tool_gate:       { enabled: true }   # Module A — always recommended
  output_sandbox:  { enabled: true }   # Module B — context-mode
  workflow_engine: { enabled: true }   # Module C — llm-sandbox PTC
  context_database:{ enabled: true }   # Module D — OpenViking
```

Disabling any module degrades gracefully — braindrain still functions, just without that layer's savings. A developer starting fresh can enable Module A only, prove the token savings, then layer in B/C/D iteratively.

---

## 3. COMPONENT ANALYSIS — WHAT WE USE FROM EACH REPO

### 3.1 Anthropic Advanced Tool Use Beta (Module A — TOOL GATE)
**Source:** https://www.anthropic.com/engineering/advanced-tool-use  
**Beta header:** `anthropic-beta: advanced-tool-use-2025-11-20`  
**What we use:** All three primitives  
**What we ignore:** Nothing — all three are essential

**Tool Search Tool**
- Register all downstream tools with `defer_loading: true`
- braindrain exposes only `tool_search_tool_regex` (~500 tokens) at session start
- Claude searches for tools on-demand; only matched definitions enter context
- 85% reduction on tool definition tokens
- Accuracy: Opus 4 MCP evals 49% → 74% with this alone
- Prompt caching unaffected (deferred tools never in initial prompt)

**Programmatic Tool Calling (PTC)**
- Claude writes Python orchestration code instead of natural language tool calls
- Code runs in Code Execution sandboxed environment
- `allowed_callers: ["code_execution"]` on tools restricts access appropriately
- Intermediate results process in sandbox — only final output reaches Claude
- 80–95% reduction on workflow execution tokens

**Tool Use Examples**
- `input_examples` field on every braindrain tool definition
- Teaches Claude correct parameter usage without verbose descriptions
- More reliable than schema-only — captures conventions JSON Schema cannot express

**Reference cookbooks (Opus MUST read before planning Phase 1):**
- PTC: https://github.com/anthropics/claude-cookbooks/blob/main/tool_use/programmatic_tool_calling_ptc.ipynb
- Tool Search with Embeddings: https://github.com/anthropics/claude-cookbooks/blob/main/tool_use/tool_search_with_embeddings.ipynb
- Memory + Context Editing: https://github.com/anthropics/claude-cookbooks/blob/main/tool_use/memory_cookbook.ipynb
- All tool_use cookbooks: https://github.com/anthropics/claude-cookbooks/tree/main/tool_use
- ep5 reference implementation: https://github.com/theaiautomators/claude-code-agentic-rag-series/tree/main/ep5-advanced-tool-use

**Context Editing betas (companion features):**
- `clear_tool_uses_20250919` — clears stale tool results when context grows
- `clear_thinking_20251015` — manages extended thinking blocks
- Configurable triggers and retention policies — see memory_cookbook.ipynb

---

### 3.2 context-mode (Module B — OUTPUT SANDBOX)
**Repo:** https://github.com/mksglu/context-mode  
**Licence:** ELv2 (free to use, modify, share)  
**What we use:** Installed as a HOT (non-deferred) downstream MCP tool  
**What we ignore:** Nothing — all six tools are valuable

**The problem it solves:** Tool definitions side is solved by defer_loading. But every tool *result* (Playwright DOM, log files, GitHub issues, API responses) still dumps raw bytes into context. context-mode intercepts the output side.

**Key tools we expose through Brain:**
- `ctx_batch_execute` — runs all commands + auto-indexes output; returns only search results. One call replaces 30+ individual raw calls
- `ctx_execute` — runs code in 10 languages; only stdout enters context
- `ctx_fetch_and_index` — fetches URL, converts HTML→markdown, chunks, indexes; raw HTML never enters context
- `ctx_search` — BM25 FTS5 search over indexed knowledge base (Porter stemming)

**PreToolUse hooks (critical):**
- Intercepts `curl`/`wget` commands → forces `ctx_fetch_and_index` instead
- Denies raw WebFetch calls
- Redirects HTTP calls in Python/JavaScript to sandbox
- These hooks prevent Claude from bypassing routing by going direct
- **When braindrain spawns workflow subagents, hooks auto-inject into subagent prompts** — no manual wiring needed

**Session continuity (SQLite):**
- Tracks files edited/read, tasks created/completed, git operations, errors, decisions, MCP tool call counts, subagent work
- On context compaction: data stays indexed in FTS5, not dumped back into window
- Retrieves via BM25 only what's relevant to current query

**Validated reduction:** 315 KB raw output → 5.4 KB (98% reduction) across 11 real-world scenarios

**Install:** `npx -y context-mode` — already has Claude Code and OpenCode configs

---

### 3.3 llm-sandbox (Module C — WORKFLOW ENGINE)
**Repo:** https://github.com/vndee/llm-sandbox  
**Licence:** MIT  
**What we use:** `InteractiveSandboxSession` with Docker backend + MCP server mode  
**What we ignore:** Kubernetes backend (overkill for local dev machine)

**The problem it solves:** Workflow intermediate data — all the rows, files, logs that Claude processes mid-task — must never enter context. llm-sandbox provides the execution environment for PTC.

**Key capability:** `InteractiveSandboxSession` keeps Python interpreter state alive across multiple `run()` calls (like notebook cells). Variables, imports, data structures persist within the session. This enables multi-step workflows where step N builds on step N-1, all inside the sandbox, with only the final result surfaced.

```python
with InteractiveSandboxSession(backend="docker") as session:
    session.run("symbols = repo_mapper.generate('./src', budget=2000)")
    session.run("indexed = jcodemunch.index(symbols)")
    session.run("summary = compress(indexed, max_tokens=500)")
    result = session.run("print(json.dumps(summary))")
# Only result.output (500 tokens max) returned to Claude
# All intermediate data (potentially MB of symbol data) never touched context
```

**Security on local dev machine:**
- Docker container isolation
- Configurable memory/CPU/time limits
- Network controls
- Pre-execution code scanning for dangerous patterns
- Runs natively on Apple Silicon via Docker Desktop

**MCP server mode:** `pip install 'llm-sandbox[mcp-docker]'` — exposes sandbox as MCP tool

---

### 3.4 OpenViking (Module D — CONTEXT DATABASE)
**Repo:** https://github.com/volcengine/OpenViking  
**Licence:** Apache 2.0  
**What we use:** L0/L1/L2 tiered context store for Brain's memory, resources, and skills  
**What we ignore:** Cloud-specific features; VLM image processing (not needed for coding)

**The problem it solves:** Every new session reloads everything from scratch — codebase summaries, tool descriptions, past decisions, known patterns. OpenViking provides persistent, tiered, progressively-loaded context that gets smarter over time.

**The L0/L1/L2 hierarchy (Brain's Skills mapped to this):**

```
viking://brain/
├── skills/
│   ├── ingest_codebase/
│   │   ├── .abstract.md      L0: "Index a codebase. Returns repo map + symbol index." (80 tokens — ALWAYS loaded)
│   │   ├── SKILL.md          L1: Full workflow description, params, examples (400 tokens — loaded on task match)
│   │   └── scripts/          L2: Full implementation details (on demand only)
│   ├── refactor_prep/
│   ├── compress_history/
│   └── get_context_for_task/
├── memory/
│   ├── user/                 What braindrain knows about this developer's patterns
│   └── agent/                What braindrain has learned about this codebase
└── resources/
    └── {project_name}/       Cached repo maps, symbol indexes, compressed summaries
```

**Self-evolving memory:** At session end, OpenViking asynchronously analyses task execution results and user feedback, then automatically updates User and Agent memory directories. braindrain learns your codebase patterns without any manual curation.

**LiteLLM native support:** OpenViking's provider config speaks LiteLLM directly — it routes embedding and summary calls through Brain's LiteLLM proxy (Ollama/LM Studio) at zero additional cost.

**Already has OpenCode plugin** — plug in as MCP server, available immediately.

---

### 3.5 RepoMapper (Downstream Tool — Code Graph)
**Repo:** https://github.com/pdavis68/RepoMapper  
**Licence:** MIT  
**What we use:** MCP server mode via `uvx repomap-mcp`  
**What we ignore:** Nothing — use as-is, deferred via defer_loading

- Tree-sitter AST + PageRank relevance ranking
- Binary search to fit most important symbols within token budget
- Structural overview layer (the map)
- 4.3–6.5% context utilisation vs 54–70% for naive file-dump agents
- Complement to jCodeMunch: RepoMapper = map, jCodeMunch = scalpel

---

### 3.6 jCodeMunch (Downstream Tool — Symbol Retrieval)
**Licence:** Non-commercial — use as installed MCP only, do NOT fork  
**What we use:** `uvx jcodemunch-mcp` as downstream MCP tool  
**What we ignore:** Source code (licence constraint)

- Symbol-level surgical retrieval (function, class, method)
- `token_budget` parameter on `assemble_context()`
- Returns `_meta.tokens_saved` and `_meta.cost_avoided` per call → feed into braindrain cost tracker
- Always deferred via `defer_loading: true`

---

### 3.7 crit (Downstream Tool — Plan Review Gate)
**Repo:** https://github.com/tomasz-tomczyk/crit  
**Licence:** MIT  
**What we use:** As an optional quality gate before destructive workflows  
**What we ignore:** Nothing — use as-is

- LLM agent emits markdown plan → crit opens it with GitHub PR-style inline comments
- You review, leave comments, click "Finish Review"
- Structured feedback JSON returned to agent for plan refinement
- Works with Windsurf, Cursor, OpenCode, Claude Code, Cline
- Prevents wasted tokens on plans that need revision before execution
- Triggered by `plan_before_run: true` in workflow config

---

### 3.8 base76 token-compressor (Downstream Tool — History Compression)
**Repo:** https://github.com/base76-research-lab/token-compressor  
**What we use:** As downstream MCP tool for history compression  

- llama3.2:1b → compress → nomic-embed-text validates cosine ≥ 0.85
- Falls back to original if validation fails — no silent corruption
- 62–75% compression on structured content >80 tokens
- Skips short content (<80 tokens) — zero overhead
- Runs entirely locally via Ollama — zero API cost

---

### 3.9 LiteLLM Proxy (Model Gateway)
**Repo:** https://github.com/BerriAI/litellm  
**Docs:** https://docs.litellm.ai  
**What we use:** All of it — this is the model routing backbone

- Native LM Studio: `model=lm_studio/<model-name>`, `api_base: http://localhost:1234/v1`
- Native Ollama: `model=ollama/<model-name>`
- AnythingLLM: custom OpenAI-compatible provider entry
- `async_pre_call_hook` for braindrain pre-call middleware
- Built-in `complexity_router` with tunable weights
- `experimental_mcp_client` — MCP tools in OpenAI format
- 8ms P95 latency at 1k RPS
- All clients: `<BASE_URL>=<litellm-proxy-url>`

---

### 3.10 mcp-agent (Workflow Pattern Library)
**Repo:** https://github.com/lastmile-ai/mcp-agent  
**Licence:** MIT  
**What we use:** Orchestrator, router, evaluator-optimizer patterns internally  
**What we ignore:** Its own CLI interface — braindrain wraps these patterns as MCP tools

- Implements all Anthropic "Building Effective Agents" patterns in composable Python
- Full MCP lifecycle management built in
- Used internally in `workflow_engine.py` for multi-step pipeline patterns

---

## 4. FULL ARCHITECTURE DIAGRAM

```
╔═══════════════════════════════════════════════════════════════════╗
║                    AI CODING CLIENTS                              ║
║  Windsurf · Cursor · OpenCode CLI · Claude Code · Codex · Zed   ║
║  Config: <BASE_URL>=<litellm-proxy-url>                ║
║          MCP server: brain (STDIO or SSE)                        ║
╚═══════════════════════════════════════╤═══════════════════════════╝
                                        │ single MCP connection
╔═══════════════════════════════════════▼═══════════════════════════╗
║             BRAIN CONTEXT HUB  (FastMCP · Python 3.11)           ║
║             braindrain/server.py (via config/braindrain launcher)   ← hot-reloads hub_config.yaml      ║
║                                                                   ║
║  ┌─────────────────── MODULE A: TOOL GATE ──────────────────┐    ║
║  │  Beta: advanced-tool-use-2025-11-20                      │    ║
║  │  Exposed HOT tools (~500 tokens total):                  │    ║
║  │    search_tools(query)      → JIT tool discovery         │    ║
║  │    list_workflows()         → workflow catalog           │    ║
║  │    run_workflow(name, args) → PTC + sandbox              │    ║
║  │    plan_workflow(name, args)→ markdown plan + crit       │    ║
║  │    get_token_stats()        → session cost tracking      │    ║
║  │  All downstream tools: defer_loading=True                │    ║
║  └──────────────────────────────────────────────────────────┘    ║
║                                                                   ║
║  ┌─────────────────── MODULE B: OUTPUT SANDBOX ─────────────┐    ║
║  │  context-mode MCP (HOT — never deferred)                 │    ║
║  │  PreToolUse hooks: intercept curl/wget/WebFetch           │    ║
║  │  ctx_batch_execute → auto-indexes all output             │    ║
║  │  FTS5 SQLite → BM25 search returns only relevant chunks  │    ║
║  │  Session continuity: all events indexed, not reloaded    │    ║
║  │  315KB raw output → 5.4KB (98% reduction)                │    ║
║  └──────────────────────────────────────────────────────────┘    ║
║                                                                   ║
║  ┌─────────────────── MIDDLEWARE STACK ─────────────────────┐    ║
║  │  async_pre_call_hook:                                    │    ║
║  │    1. token counter                                      │    ║
║  │    2. cache_control injection on stable prefixes         │    ║
║  │    3. complexity router → model tier assignment          │    ║
║  │    4. local compress if history >500 tokens              │    ║
║  │    5. semantic cache lookup (skip API on hit)            │    ║
║  └──────────────────────────────────────────────────────────┘    ║
╚══════╤══════════════════════════════════════╤═════════════════════╝
       │ workflow execution (Module C)        │ model calls
╔══════▼──────────────────────┐   ╔──────────▼─────────────────────╗
║  MODULE C: WORKFLOW ENGINE  ║   ║  LiteLLM Proxy  :4000          ║
║  llm-sandbox (Docker)       ║   ║  ├─ lm_studio/*  LM Studio     ║
║  InteractiveSandboxSession  ║   ║  ├─ ollama/*     Ollama        ║
║  Persistent state per step  ║   ║  ├─ anthropic/*  Anthropic     ║
║  Only final summary exits   ║   ║  └─ gemini/*     Google        ║
║  mcp-agent patterns inside  ║   ╚────────────────────────────────╝
╚══════╤──────────────────────╝
       │ sandbox calls downstream tools
╔══════▼──────────────────────────────────────────────────────────╗
║  DOWNSTREAM MCP TOOLS  (all defer_loading=True except context-  ║
║  mode which is HOT)                                             ║
║                                                                  ║
║  context-mode   npx -y context-mode          [HOT · ELv2]      ║
║  repo_mapper    uvx repomap-mcp              [deferred · MIT]   ║
║  jcodemunch     uvx jcodemunch-mcp           [deferred · nc]    ║
║  compressor     python3 token-compressor/... [deferred · MIT]   ║
║  github         npx @mcp/server-github       [deferred · MIT]   ║
║  crit           npx crit-mcp                 [on-demand · MIT]  ║
║  [future tool]  add to hub_config.yaml       [zero code change] ║
╚══════╤──────────────────────────────────────────────────────────╝
       │ persistent context
╔══════▼──────────────────────────────────────────────────────────╗
║  MODULE D: CONTEXT DATABASE  (OpenViking · Apache 2.0)          ║
║  viking://brain/skills/{name}/.abstract.md   L0  always loaded  ║
║  viking://brain/skills/{name}/SKILL.md       L1  on task match  ║
║  viking://brain/skills/{name}/scripts/       L2  on demand      ║
║  viking://brain/memory/user/                     session learn  ║
║  viking://brain/memory/agent/                    codebase learn ║
║  viking://brain/resources/{project}/             cached maps    ║
║  Self-evolving: auto-updates memory at session end              ║
║  LiteLLM provider: routes embeddings through Ollama locally     ║
╚─────────────────────────────────────────────────────────────────╝
```

---

## 5. DATA FLOW — WHAT HAPPENS ON A SINGLE REQUEST

**Example:** Developer in Cursor types "refactor the auth module to use JWT"

```
1. CURSOR → BRAIN: "refactor auth module to use JWT"

2. BRAIN MODULE A (Tool Gate):
   Only search_tools in context (~500 tokens)
   No tool definitions pre-loaded
   
3. BRAIN MODULE D (Context Database):
   Loads L0 abstracts for all skills (~100 tokens total)
   Matches "refactor" → loads L1 of refactor_prep skill (~400 tokens)
   Loads L1 of ingest_codebase if first session (~400 tokens)
   Total context so far: ~1,400 tokens

4. CLAUDE (Sonnet) decides:
   search_tools("codebase refactor symbols") 
   → braindrain returns: repo_mapper, jcodemunch refs (~300 tokens)
   Now in context: ~1,700 tokens

5. CLAUDE calls: run_workflow("refactor_prep", {files: ["auth/"], change: "JWT"})

6. BRAIN MODULE C (Workflow Engine):
   Opens InteractiveSandboxSession (Docker)
   Inside sandbox (NEVER enters context):
     → repo_mapper.generate("./auth", budget=3000) → dependency graph
     → jcodemunch.get_affected_symbols(graph) → 47 affected symbols
     → compress(symbols, max_tokens=800) → ranked summary
   Returns to Claude: 800-token summary of exactly what matters

7. BRAIN MODULE B (Output Sandbox):
   context-mode FTS5 indexes the sandbox output
   Any subsequent tool calls on same data → ctx_search, not re-execution

8. CLAUDE has full picture in ~2,500 tokens total
   Proceeds with refactor with surgical precision

9. SESSION END:
   OpenViking asynchronously extracts:
     → "Developer uses JWT in auth patterns"
     → "Project: auth module at ./auth/, 47 symbols, dependencies mapped"
   Updates viking://brain/memory/ for next session
   Next session starts with this knowledge pre-loaded at L0

TOTAL TOKENS USED: ~2,500
WITHOUT BRAIN: 55K+ (definitions) + 56KB+ (outputs) + full file dumps = 150K+
REDUCTION: ~98%
```

---

## 6. HUB CONFIGURATION — COMPLETE SCHEMA

```yaml
# hub_config.yaml — THE ONLY FILE YOU EDIT TO ADD CAPABILITIES
# braindrain server hot-reloads on change. Zero code changes needed.

version: "2.0"
project_name: "my_project"

# ─── MODULES (opt-in, degrade gracefully if disabled) ──────────────
modules:
  tool_gate:
    enabled: true
    beta_features:
      advanced_tool_use: true          # anthropic-beta: advanced-tool-use-2025-11-20
      context_editing: true            # clear_tool_uses_20250919
      clear_thinking: true             # clear_thinking_20251015
      prompt_caching: true

  output_sandbox:
    enabled: true
    backend: context_mode              # context-mode MCP
    enforce_hooks: true                # block direct curl/wget/WebFetch

  workflow_engine:
    enabled: true
    backend: llm_sandbox               # Docker on local dev machine
    sandbox_limits:
      memory_mb: 2048
      cpu_cores: 2
      timeout_seconds: 120

  context_database:
    enabled: true
    backend: openviking
    workspace: ~/.brain/openviking
    litellm_provider: true             # routes embeddings through local Ollama
    memory_extraction: true            # auto-update at session end
    tiers:
      L0_always_load: true
      L1_on_task_match: true
      L2_on_demand: true

# ─── MODEL TIERS ───────────────────────────────────────────────────
models:
  tier_micro:
    provider: ollama
    model: llama3.2:1b
    api_base: http://localhost:11434
    use_for: [history_compression, classification, summarization]
    cost_per_1k: 0.0
    max_tokens: 2048

  tier_local:
    provider: lmstudio
    model: qwen3:4b
    api_base: http://localhost:1234/v1
    use_for: [routing, extraction, simple_tasks, embeddings]
    cost_per_1k: 0.0
    max_tokens: 8192

  tier_standard:
    provider: anthropic
    model: claude-sonnet-4-6
    use_for: [complex_coding, multi_file_edit, reasoning, planning]
    cost_per_1k_input: 0.003
    cost_per_1k_output: 0.015

  tier_architect:
    provider: anthropic
    model: claude-opus-4-6
    use_for: [architecture, critical_planning, cross_repo_analysis]
    cost_per_1k_input: 0.015
    cost_per_1k_output: 0.075

complexity_router:
  thresholds:
    micro: 0.2       # tier_micro  (local, free)
    local: 0.4       # tier_local  (local, free)
    standard: 0.75   # tier_standard
    architect: 1.0   # tier_architect
  weights:
    token_count: 0.10
    code_presence: 0.30
    reasoning_markers: 0.25   # "step by step", "explain why", "compare"
    technical_terms: 0.25
    simple_indicators: 0.05   # "what is", "list", "show me"
    multi_step_patterns: 0.05 # "then", "after", "finally"

# ─── DOWNSTREAM MCP TOOLS ──────────────────────────────────────────
mcp_tools:

  # HOT: never deferred — intercepts ALL tool outputs
  - name: context_mode
    transport: stdio
    command: "npx -y context-mode"
    hot: true                        # defer_loading: false
    defer_loading: false
    tags: [sandbox, output, compression, fts5, session]
    description: "Output sandbox. Routes all tool outputs through FTS5 index. 98% output token reduction."

  # DEFERRED: discovered on-demand via search_tools()
  - name: repo_mapper
    transport: stdio
    command: "uvx repomap-mcp"
    defer_loading: true
    tags: [codebase, symbols, graph, map, pagerank, tree-sitter]
    token_weight: low
    description: "PageRank dependency graph + token-budgeted repo map."
    input_examples:
      - {path: "./src", token_budget: 2000}
      - {path: "./src", token_budget: 1000, include_tests: false}

  - name: jcodemunch
    transport: stdio
    command: "uvx jcodemunch-mcp"
    defer_loading: true
    tags: [codebase, symbols, retrieval, search, function, class]
    token_weight: low
    description: "Surgical symbol-level retrieval. Respects token_budget."
    input_examples:
      - {query: "auth functions", token_budget: 1500}
      - {symbol: "UserModel", include_dependencies: true}

  - name: token_compressor
    transport: stdio
    command: "python3 ~/.braindrain/tools/token-compressor/mcp_server.py"
    defer_loading: true
    tags: [compression, history, context, summarization]
    token_weight: negligible
    description: "llama3.2:1b compression with cosine similarity validation. 62-75% reduction on content >80 tokens."

  - name: crit
    transport: stdio
    command: "npx crit-mcp"
    defer_loading: true
    tags: [review, plan, quality_gate, human_in_loop, markdown]
    token_weight: negligible
    description: "GitHub PR-style plan review. Emits markdown → human reviews inline → structured feedback returned."

  - name: github
    transport: stdio
    command: "npx @modelcontextprotocol/server-github"
    defer_loading: true
    hot_tools: [create_pull_request]  # keep one tool hot
    tags: [git, pr, issues, commits, review]
    token_weight: high                # 26K tokens if loaded — ALWAYS defer
    description: "GitHub operations: PR creation, issue management, code review."
    env:
      GITHUB_PERSONAL_ACCESS_TOKEN: "${GITHUB_TOKEN}"

  # ── ADD NEW TOOLS HERE — ZERO CODE CHANGES TO BRAIN SERVER ──────
  # - name: new_tool
  #   transport: sse | stdio
  #   url: "http://localhost:PORT/mcp"   # SSE
  #   command: "command args"            # STDIO
  #   defer_loading: true
  #   tags: [relevant, tags]
  #   description: "One sentence. What it does and when to use it."

# ─── WORKFLOWS ─────────────────────────────────────────────────────
workflows:

  ingest_codebase:
    description: "Full codebase indexing. Run once per project, then use incremental."
    steps:
      - repo_mapper.generate
      - jcodemunch.index
      - compress_history
    executes_in: sandbox              # llm-sandbox — intermediate data never in context
    model: tier_micro
    token_budget: 2000
    cache_ttl_seconds: 3600
    plan_before_run: false
    stores_to: "viking://brain/resources/{project}/"
    input_examples:
      - {path: "./src", mode: "new_project"}
      - {path: "./src", mode: "incremental", since_commit: "HEAD~10"}

  refactor_prep:
    description: "Blast radius analysis. What files/symbols are affected by a proposed change."
    steps:
      - repo_mapper.dependency_graph
      - jcodemunch.get_affected_symbols
    executes_in: sandbox
    model: tier_local
    token_budget: 3000
    plan_before_run: true             # emits markdown plan → crit quality gate
    input_examples:
      - {files: ["./auth/"], change_description: "migrate to JWT"}
      - {symbol: "UserModel", change_type: "schema_change"}

  get_context_for_task:
    description: "Semantic search over indexed codebase. Returns ranked relevant symbols only."
    steps:
      - jcodemunch.search_symbols
    executes_in: sandbox
    model: tier_micro
    token_budget: 2000
    input_examples:
      - {task: "add rate limiting to API endpoints", budget: 1500}
      - {task: "fix the login bug", files_hint: ["./auth/"]}

  compress_history:
    description: "Rolling conversation compression. Call when history exceeds 2K tokens."
    steps:
      - token_compressor.compress
    executes_in: direct               # too fast for sandbox overhead
    model: tier_micro
    token_budget: 500
    preserve_fields: [code_decisions, file_paths, error_messages, accepted_changes]
    input_examples:
      - {messages: "...", preserve_decisions: true}

# ─── CACHE ─────────────────────────────────────────────────────────
cache:
  semantic:
    enabled: true
    backend: redis
    host: localhost
    port: 6379
    similarity_threshold: 0.92
    ttl_seconds: 3600
    # Similar queries skip API entirely — 50-73% savings on repeated work

  prompt_cache:
    enabled: true
    stable_prefix_markers:
      - system_prompt
      - tool_examples
      - openviking_L0_abstracts
    cache_ttl: ephemeral              # 5 min default; extended via cache_control

# ─── COST TRACKING ─────────────────────────────────────────────────
cost_tracking:
  enabled: true
  log_file: ~/.brain/costs/session.jsonl
  track_fields:
    - tokens_in_raw              # what would have been sent without Brain
    - tokens_in_actual           # what was actually sent
    - tokens_saved               # delta
    - cost_avoided_usd           # at current model pricing
    - cache_hits                 # times semantic cache bypassed API entirely
    - module_attribution         # which module saved what
  alert_threshold_usd_per_session: 0.50
  dashboard: true                # print stats on session end
```

---

## 7. FILE STRUCTURE

```
brain-mcp-hub/
│
├── braindrain/server.py (via config/braindrain launcher)              # FastMCP server — single entry point
├── hub_config.yaml              # THE config — only file edited for new tools
├── requirements.txt
├── docker-compose.yaml          # Redis + Ollama + any services
│
├── core/
│   ├── __init__.py
│   ├── config_loader.py         # Parses hub_config.yaml, watches for changes
│   ├── tool_registry.py         # defer_loading management, BM25 + embedding search
│   ├── workflow_engine.py       # mcp-agent patterns + llm-sandbox execution
│   ├── model_router.py          # Complexity scorer + LiteLLM tier assignment
│   ├── context_manager.py       # cache_control injection, context editing betas
│   ├── cost_tracker.py          # JSONL logging, savings calculation
│   └── openviking_client.py     # L0/L1/L2 load orchestration
│
├── workflows/
│   ├── __init__.py
│   ├── ingest_codebase.py       # RepoMapper → jCodeMunch → compress
│   ├── refactor_prep.py         # Dependency graph → blast radius
│   ├── get_context_for_task.py  # Semantic symbol search
│   └── compress_history.py      # llama3.2:1b rolling summary
│
├── hooks/
│   ├── pre_call.py              # LiteLLM async_pre_call_hook
│   └── post_call.py             # Cost logging, cache population
│
├── openviking/
│   ├── skills/
│   │   ├── ingest_codebase/
│   │   │   ├── .abstract.md     # L0: 80 tokens, always loaded
│   │   │   └── SKILL.md         # L1: 400 tokens, loaded on match
│   │   ├── refactor_prep/
│   │   ├── get_context_for_task/
│   │   └── compress_history/
│   └── memory/
│       ├── user/
│       └── agent/
│
├── tests/
│   ├── test_tool_search.py       # defer_loading + search accuracy
│   ├── test_ptc_sandbox.py       # PTC execution, no context leakage
│   ├── test_model_routing.py     # Complexity score → correct tier
│   ├── test_output_sandbox.py    # context-mode 98% reduction validation
│   ├── test_openviking.py        # L0/L1/L2 load behaviour
│   ├── test_workflows.py         # End-to-end workflow token budgets
│   └── test_cost_tracker.py      # Savings calculation accuracy
│
├── litellm_config.yaml           # LiteLLM proxy model routing config
├── .brain/                       # Runtime data (gitignored)
│   ├── costs/
│   └── openviking/
└── README.md
```

---

## 8. CORE IMPLEMENTATION PATTERNS

### 8.1 braindrain Server — Tool Gate with defer_loading

```python
# braindrain/server.py (via config/braindrain launcher)
import anthropic
from mcp.server.fastmcp import FastMCP
from core.config_loader import ConfigLoader
from core.tool_registry import ToolRegistry
from core.workflow_engine import WorkflowEngine
from core.context_manager import ContextManager
from core.cost_tracker import CostTracker

mcp = FastMCP("brain-context-hub")
config = ConfigLoader("hub_config.yaml")   # hot-reloads on file change
registry = ToolRegistry(config)
engine = WorkflowEngine(config, registry)
ctx_mgr = ContextManager(config)
tracker = CostTracker(config)

# HOT tools — always in context, ~500 tokens total

@mcp.tool()
async def search_tools(query: str) -> dict:
    """
    Search available tools by capability. Call this FIRST before any task.
    Returns only references (~300 tokens) not full definitions.
    Examples: "codebase symbols", "git operations", "compress context"
    """
    results = await registry.search(query, top_k=5)
    return {"tools": results, "total_available": registry.count()}

@mcp.tool()
async def run_workflow(name: str, args: dict) -> dict:
    """
    Execute a workflow in an isolated sandbox. Returns only final summary.
    Intermediate data NEVER enters your context window.
    Available: ingest_codebase, refactor_prep, get_context_for_task, compress_history
    """
    result = await engine.run(name, args)
    tracker.record(name, result["tokens_saved"])
    return result

@mcp.tool()
async def plan_workflow(name: str, args: dict) -> dict:
    """
    Generate a review plan before running a destructive workflow.
    Opens in crit for inline PR-style review. Returns approved plan path.
    Use before: refactor_prep, ingest_codebase (large projects)
    """
    return await engine.plan(name, args)

@mcp.tool()
async def list_workflows() -> dict:
    """List available workflows with L0 descriptions and token budgets."""
    return config.get_workflow_catalog()

@mcp.tool()
async def get_token_stats() -> dict:
    """Session cost tracking: tokens saved, cost avoided, cache hits by module."""
    return tracker.get_session_stats()
```

### 8.2 Tool Registry — defer_loading + Search

```python
# core/tool_registry.py
from anthropic.types.beta import BetaToolParam

class ToolRegistry:
    def build_api_tools(self) -> list[BetaToolParam]:
        """Build tool list for Anthropic API with defer_loading."""
        tools = [
            # Tool Search Tool — the only always-loaded tool besides Brain's own
            {"type": "tool_search_tool_regex_20251119", "name": "tool_search_tool_regex"},
            # Code execution for PTC
            {"type": "code_execution_20250825", "name": "code_execution"},
        ]
        for tool in self.config.mcp_tools:
            tools.append({
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.schema,
                "input_examples": tool.input_examples,
                "defer_loading": not tool.hot,  # context-mode is hot; rest deferred
            })
        return tools

    async def search(self, query: str, top_k: int = 5) -> list[dict]:
        """BM25 search over tool descriptions + tags. Returns refs, not full schemas."""
        # Uses rank_bm25 for speed; upgrade to embeddings for quality at scale
        scores = self.bm25.get_scores(query.split())
        top_indices = sorted(range(len(scores)), key=lambda i: -scores[i])[:top_k]
        return [
            {"name": self.tools[i].name, "description": self.tools[i].description}
            for i in top_indices
        ]
```

### 8.3 Workflow Engine — PTC + llm-sandbox

```python
# core/workflow_engine.py
from llm_sandbox import InteractiveSandboxSession

class WorkflowEngine:
    async def run(self, workflow_name: str, args: dict) -> dict:
        wf = self.config.get_workflow(workflow_name)
        tokens_before = len(str(args)) // 4  # rough estimate

        with InteractiveSandboxSession(backend="docker") as session:
            session.run(f"import json; args = {json.dumps(args)}")

            for step in wf.steps:
                tool = self.registry.get_tool(step.split(".")[0])
                method = step.split(".")[1]
                # Each step builds on previous — state persists in sandbox
                session.run(f"result = mcp_call('{tool.command}', '{method}', result if 'result' in dir() else args)")

            # Compress to token budget INSIDE sandbox — only summary exits
            final = session.run(f"""
                compressed = compress_to_budget(result, budget={wf.token_budget})
                print(json.dumps({{"result": compressed, "steps_completed": {len(wf.steps)}}}))
            """)

        tokens_after = len(final.output) // 4
        return {
            "result": json.loads(final.output),
            "tokens_saved": tokens_before - tokens_after,
            "workflow": workflow_name
        }
```

### 8.4 LiteLLM Config

```yaml
# litellm_config.yaml
model_list:
  - model_name: claude-sonnet-4-6
    litellm_params:
      model: anthropic/claude-sonnet-4-6
      api_key: os.environ/<API_KEY_REDACTED>

  - model_name: claude-opus-4-6
    litellm_params:
      model: anthropic/claude-opus-4-6
      api_key: os.environ/<API_KEY_REDACTED>

  - model_name: qwen3-local
    litellm_params:
      model: lm_studio/qwen3-4b
      api_base: http://localhost:1234/v1
      api_key: lm-studio

  - model_name: llama-micro
    litellm_params:
      model: ollama/llama3.2:1b
      api_base: http://localhost:11434

litellm_settings:
  callbacks: ["brain_pre_call_hook"]

router_settings:
  routing_strategy: latency-based-routing
  num_retries: 2

general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY
  port: 4000
```

---

## 9. MAC MINI M1 SETUP — COMPLETE

```bash
# ── 1. System Prerequisites ────────────────────────────────────────
brew install python@3.11 redis node
brew install --cask lm-studio docker

# Verify Docker Desktop is running (needed for llm-sandbox)
docker ps

# ── 2. Local Models ────────────────────────────────────────────────
brew install ollama
ollama serve &                          # start daemon

ollama pull llama3.2:1b                 # ~1GB  — history compression
ollama pull nomic-embed-text            # ~270MB — cosine validation
ollama pull qwen3:4b                    # ~2.5GB — routing + local tasks

# LM Studio: download app, pull qwen3:4b or any preferred model
# Start server: LM Studio → Local Server → Start (port 1234)

# ── 3. Python Environment ──────────────────────────────────────────
python3.11 -m venv ~/.brain/env
source ~/.brain/env/bin/activate

pip install fastmcp litellm anthropic
pip install 'llm-sandbox[mcp-docker]'
pip install rank-bm25 sentence-transformers redis
pip install watchfiles pyyaml rich

# ── 4. Downstream MCP Tools ────────────────────────────────────────
npm install -g context-mode             # or: npx -y context-mode (auto)
pip install uvx                         # for repomap-mcp + jcodemunch-mcp
# uvx tools install on first use — no manual install needed

# ── 5. Token Compressor ────────────────────────────────────────────
git clone https://github.com/base76-research-lab/token-compressor \
    ~/.brain/tools/token-compressor
pip install -r ~/.brain/tools/token-compressor/requirements.txt

# ── 6. OpenViking ──────────────────────────────────────────────────
pip install openviking
openviking init ~/.brain/openviking

# ── 7. LiteLLM Proxy ──────────────────────────────────────────────
pip install 'litellm[proxy]'
litellm --config litellm_config.yaml --port 4000 &

# ── 8. Docker Services ────────────────────────────────────────────
docker-compose up -d                    # Redis

# ── 9. braindrain Server ───────────────────────────────────────────────
python braindrain/server.py (via config/braindrain launcher)                  # STDIO mode for IDE MCP config

# ── 10. Client MCP Config (add to each IDE) ───────────────────────
# Windsurf / Cursor / Claude Code / OpenCode:
# {
#   "mcpServers": {
#     "braindrain": {
#       "command": "python3",
#       "args": ["~/.braindrain/brain-mcp-hub/braindrain/server.py (via config/braindrain launcher)"],
#       "env": {
#         "<API_KEY_REDACTED>": "${<API_KEY_REDACTED>}",
#         "<BASE_URL>": "<litellm-proxy-url>"
#       }
#     }
#   }
# }
```

---

## 10. TOKEN REDUCTION SUMMARY

| Module | Mechanism | Token Source | Reduction |
|--------|-----------|-------------|-----------|
| A — Tool Gate | `defer_loading: true` | Definitions in | **85%** |
| B — Output Sandbox | context-mode FTS5 | Results out | **98%** |
| C — Workflow Engine | llm-sandbox PTC | Intermediate data | **80–95%** |
| D — Context DB | OpenViking L0/L1/L2 | Cross-session reload | **90%** |
| Middleware | Prompt caching | Stable prefix | **90% on cache hits** |
| Middleware | Semantic cache | Repeated queries | **100% (skip API)** |
| Middleware | Local model routing | Simple tasks | **100% (zero cost)** |

**Realistic stacked reduction vs naive: 90–97%**  
**Validated by:** Anthropic internal testing (85% Tool Gate alone), context-mode benchmarks (98% output), RepoMapper research (10x vs file-dump)

---

## 11. COMPLETE REFERENCE LINKS

| Resource | URL | Priority |
|----------|-----|----------|
| Anthropic Advanced Tool Use | https://www.anthropic.com/engineering/advanced-tool-use | **READ FIRST** |
| PTC Cookbook | https://github.com/anthropics/claude-cookbooks/blob/main/tool_use/programmatic_tool_calling_ptc.ipynb | **READ FIRST** |
| Tool Search Embeddings Cookbook | https://github.com/anthropics/claude-cookbooks/blob/main/tool_use/tool_search_with_embeddings.ipynb | **READ FIRST** |
| Memory + Context Editing Cookbook | https://github.com/anthropics/claude-cookbooks/blob/main/tool_use/memory_cookbook.ipynb | Read |
| All Tool Use Cookbooks | https://github.com/anthropics/claude-cookbooks/tree/main/tool_use | Reference |
| ep5 Reference Implementation | https://github.com/theaiautomators/claude-code-agentic-rag-series/tree/main/ep5-advanced-tool-use | Reference |
| context-mode | https://github.com/mksglu/context-mode | **READ FIRST** |
| OpenViking | https://github.com/volcengine/OpenViking | Read |
| llm-sandbox | https://github.com/vndee/llm-sandbox | Read |
| crit | https://github.com/tomasz-tomczyk/crit | Reference |
| RepoMapper | https://github.com/pdavis68/RepoMapper | Reference |
| FastMCP | https://github.com/jlowin/fastmcp | Reference |
| mcp-agent | https://github.com/lastmile-ai/mcp-agent | Reference |
| LiteLLM | https://github.com/BerriAI/litellm | Reference |
| base76 token-compressor | https://github.com/base76-research-lab/token-compressor | Reference |
| Anthropic Building Effective Agents | https://www.anthropic.com/research/building-effective-agents | Background |

---

## 12. INSTRUCTIONS FOR CLAUDE OPUS (PLANNING AGENT)

You are the planning agent for the braindrain MCP hub. Your job is to produce a detailed, phase-by-phase task plan that Claude Sonnet will execute one task at a time.

### Before planning, you MUST read these in order:
1. `programmatic_tool_calling_ptc.ipynb` — defines exact PTC API patterns
2. `tool_search_with_embeddings.ipynb` — defines Tool Search implementation
3. `context-mode` README — understand the six tools and hook system
4. `memory_cookbook.ipynb` — understand context editing betas

### Planning rules:

**Phases must be strictly ordered** — each phase produces a working, testable state. Never plan a phase that cannot be independently verified.

**Each task must specify:**
- Exact file to create or modify (full path)
- Function signatures (name, params, return type)
- Dependencies: what must exist before this task starts
- Test: exact shell command or Python assertion to verify done-state
- Token impact: how this task contributes to the reduction goal
- Estimated lines of code

**Module A (Tool Gate) is Phase 1.** It provides the highest single-step ROI and validates the entire architecture. Do not plan Modules B/C/D until Module A plan is reviewed and approved.

**local dev machine constraints (non-negotiable):**
- STDIO transport preferred for all MCP servers (no port conflicts)
- Docker available — use for llm-sandbox and Redis only
- All local models must run on CPU/MPS (no CUDA)
- LM Studio and Ollama run natively on Apple Silicon — use both

**Non-negotiable architectural rules:**
- All downstream tools: `defer_loading: true` except context-mode
- context-mode: always hot, never deferred
- All workflow execution: via llm-sandbox (intermediate data never in context)
- `hub_config.yaml`: only file changed to add new tools — zero code changes to braindrain server
- Beta header `anthropic-beta: advanced-tool-use-2025-11-20` on every Anthropic API call
- OpenViking replaces all naive SQLite/Redis session storage
- Every braindrain tool must have `input_examples` in its definition

**When handing tasks to Sonnet:**
- One task at a time, never batched
- Each task: full context, clear done-state, test command
- If a task fails: Sonnet reports exact error, you re-plan that task only
- Never skip testing — a passing test is the only definition of done

**Phase structure to plan:**
- Phase 1: braindrain server shell + Module A (Tool Gate) + config loader + BM25 search
- Phase 2: Module B (context-mode integration + hooks)
- Phase 3: Module C (llm-sandbox + PTC + workflow engine)
- Phase 4: Module D (OpenViking L0/L1/L2 integration)
- Phase 5: LiteLLM proxy + model routing middleware
- Phase 6: Workflow implementations (ingest_codebase, refactor_prep, etc.)
- Phase 7: Cost tracking + session stats
- Phase 8: End-to-end integration tests + token reduction validation

### Success criteria for the complete system:
A 30-minute agentic coding session that would consume 150K+ tokens naive must consume <10K tokens through Brain. Measure and log this for every workflow execution.


---

## 13. v2.1 Addendum — Superseded modules (June 2026)

This addendum records what **shipped braindrain v1.0.x** replaced from the v2.0
spec. Do not plan new work against the retired modules below.

| Spec module (v2.0) | Status | Replacement in braindrain |
| --- | --- | --- |
| **Module D — OpenViking L0/L1/L2** (`context_database`) | **Retired** | Native **L0–L3 memory stack**: `observer.py`, `session.py`, `wiki_brain.py`, `dream.py` — see `README.md` Memory layer and `docs/learning-layer-gap-audit.md` |
| **LiteLLM proxy** (model gateway on :4000) | **Dropped** | Direct provider config in `hub_config.yaml` + local LM Studio / Ollama; no proxy layer in the hub |
| **base76 token-compressor** (deferred MCP) | **Dropped** | `route_output()` → context-mode FTS5 + token telemetry; no separate compressor service |
| **Docker + Redis** (compose stack) | **Deferred** | Optional Docker for `llm-sandbox` workflow sandbox only; **no Redis** in default install. Full container orchestration deferred to **stateless HTTP / MCP 2026-07-28** transport work (see `docs/PROJECT_EVALUATION_2026-06.md` P1) |
| **OpenViking tier promotions from Dream** | **Retired** | WikiBrain tier/heuristic promotion in `dream.py`; no OpenViking IPC |

**Still accurate from v2.0:** Module A (BM25 `search_tools` gate), Module B
(`route_output` / `search_index` via context-mode FTS5), Module C (workflow
engine with optional Docker sandbox), workspace priming, scriptlib, planning
auditor.

**Learning layer:** L0–L3 milestones in
[`docs/learning-layer-gap-audit.md`](learning-layer-gap-audit.md) are **shipped**.
L4–L12 (Pattern Analyzer, Clarification Agent, NATS bus, etc.) remain design-only
in [`.cursor/plans/learning-layer-extended.plan.md`](../.cursor/plans/learning-layer-extended.plan.md)
(machine-local).

**Historical note:** §12 below is the original v2.0 planning-agent brief. Treat it
as archival context, not the execution backlog.
