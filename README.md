# Lumina OS

**A zero-trust, deterministic orchestration layer that secures AI reasoning behind immutable Domain Physics — giving the LLM exactly one job: high-weight reasoning.**

> **Full reference documentation** — UNIX man-page style, sections 1–8: [`docs/`](docs/README.md)
---

## What Is Lumina OS?

TCP/IP assembles packets from layered protocols — each layer adds its headers, the payload travels through, and checksums verify integrity. Lumina OS does the same thing for LLMs.

The **PPA (Prompt Packet Assembly) engine** assembles a **dynamic prompt contract** from layered components — global rules, domain policy, module state, and turn context. Only what is needed is added at each layer. The LLM processes this contract. Tool-adapters verify the output. The System Logs logs the decision.

The LLM is the **processing unit**, not the authority. The input interface is the **surface**, not the system — it can be a chat session, a sensor feed, a lab instrument stream, or any structured event source. Everything surrounding the probabilistic LLM is **deterministic and verifiable**.

```
┌──────────────────────────────────────────────────────────────────────┐
│  Input Interface                                                     │  ← chat session, sensor feed, event stream, or API call
├──────────────────────────────────────────────────────────────────────┤
│  Domain Adapter — Input Normalization (A)                            │  ← domain-owned; normalizes inputs to structured signals
├───────────────────────────────┬──────────────────────────────────────┤
│  NLP Classifier               │  Glossary Intercept                  │  ← Tier 1 domain routing | known-term early detection
│                               ├──────────────────────────────────────┤
│                               │  SLM Librarian                       │  ← renders fluent definition; LLM never invoked for glossary
│                               │  (early exit ──► response returned)  │
├───────────────────────────────┴──────────────────────────────────────┤
│  SLM Physics Interpreter                                             │  ← pre-digests domain physics → _slm_context injected into turn_data
├──────────────────────────────────────────────────────────────────────┤
│  Global Base Prompt                                                  │  ← universal rules (like IP headers)
├──────────────────────────────────────────────────────────────────────┤
│  Domain Physics                                                      │  ← immutable domain-specific policy layer
├──────────────────────────────────────────────────────────────────────┤
│  Module State + Turn Data                                            │  ← session context + NLP anchors + _slm_context
├══════════════════════════════════════════════════════════════════════╡
│  Assembled Prompt Contract                                           │  ← the "packet" ready for dispatch
├──────────────────────────────────────────────────────────────────────┤
│  Task Weight Classifier                                              │  ← LOW → SLM tier  |  HIGH → LLM tier
├──────────────────────────┬───────────────────────────────────────────┤
│  SLM — Low-weight tasks  │  LLM — Reasoning Engine                   │  ← definitions, physics interp, admin cmds | instructions, synthesis
│  (structured extraction) │  (high-weight; probabilistic; never       │
│                          │   trusted alone)                          │
├──────────────────────────┴───────────────────────────────────────────┤
│  Tool-Adapter Verification                                           │  ← deterministic output checking + novel synthesis detection
├──────────────────────────────────────────────────────────────────────┤
│  Domain Adapter — Signal Synthesis (B)                               │  ← computes engine contract fields
├──────────────────────────────────────────────────────────────────────┤
│  System Log                                                         │  ← append-only: trace events, escalations, novel synthesis events
└──────────────────────────────────────────────────────────────────────┘
```

> Both Domain Adapter rows are **domain-owned** and live entirely in the domain pack — zero domain-specific names appear in the core engine. See [`docs/7-concepts/domain-adapter-pattern.md`](docs/7-concepts/domain-adapter-pattern.md) for the authoring pattern.

The Lumina OS core engine is **fully domain-agnostic**. All domain-specific behavior — prompts, state models, turn interpretation, tool adapters, and deterministic templates — lives in self-contained **domain packs** loaded at runtime. No server code changes are needed to switch domains.

> **Full reference documentation** — UNIX man-page style, sections 1–8: [`docs/`](docs/README.md)
>
> | Section | Covers |
> |---------|--------|
> | [1 — Commands](docs/1-commands/README.md) | CLI tools and utilities |
> | [2 — Syscalls](docs/2-syscalls/README.md) | API endpoint reference |
> | [3 — Functions](docs/3-functions/README.md) | Library interfaces |
> | [4 — Formats](docs/4-formats/README.md) | JSON schemas |
> | [5 — Standards](docs/5-standards/README.md) | Core specifications |
> | [6 — Examples](docs/6-examples/README.md) | Worked interaction traces |
> | [7 — Concepts](docs/7-concepts/README.md) | Architecture and design |
> | [8 — Admin](docs/8-admin/README.md) | Governance, RBAC, operations |

---

## Prompt Packet Assembly (PPA)

Every turn follows a strict, auditable sequence:

1. **Domain knowledge** — immutable rules authored by the Domain Authority
2. **Context (state)** — mutable session state updated from structured evidence
3. **Actor evidence** — structured signals produced by the Actor (student, sensor, operator) that update State and inform the orchestrator's action
4. **Proposal (LLM)** — the LLM processes the assembled prompt contract
5. **Verification (tools + invariants)** — tool-adapters check the LLM's reasoning; unrecognized patterns are flagged as novel synthesis signals
6. **Commit / escalate** — verified decisions are committed; violations escalate to a human; novel synthesis events require a two-key gate (LLM flags → Domain Authority confirms or rejects)
7. **Trace (System Log)** — the decision is logged to the append-only ledger

The **D.S.A. structural schema** is the contract model behind PPA. Three pillars define every session contract:

| Pillar | Name | Role | Mutability |
|--------|------|------|------------|
| **D**  | Domain | Rules, invariants, standing orders, escalation triggers | Immutable per session |
| **S**  | State | Compact entity profile updated from structured evidence | Mutable |
| **A**  | Actor | Evidence-producing entity (student, sensor, operator, device) | Identified per session |

> **Note:** The orchestrator's **action** (bounded response) is the *output* derived from all three pillars — it is not itself a pillar. See [`docs/7-concepts/dsa-actor-model.md`](docs/7-concepts/dsa-actor-model.md) for the full Actor definition and signal flow.

The PPA orchestrator assembles a dynamic prompt contract from these D.S.A. components. The LLM is constrained to that contract, tool-adapters verify its output, and the resulting decision is committed or escalated and written to System Log.

See [`specs/dsa-framework-v1.md`](specs/dsa-framework-v1.md) for the full D.S.A. structural specification and [`standards/system-log-v1.md`](standards/system-log-v1.md) for System Log protocol.

---

## Modular Runtime

The core engine is a **generic runtime host** with zero domain-specific logic. Domain behavior is loaded at startup from a domain pack's `cfg/runtime-config.yaml`, which declares prompt files, state adapters, tool policies, and deterministic templates.

At startup, the runtime computes policy/prompt hashes and enforces a **policy commitment gate** — the active domain-physics hash must match a committed System Log `CommitmentRecord` before any session can execute. During each turn, provenance lineage hashes are carried in System Log metadata for packet-level auditability without storing transcript content.

### API Server Architecture

`src/lumina/api/server.py` is a **~200-line thin factory** that creates the FastAPI application, mounts routers, and configures CORS. All feature logic lives in 22 focused sub-modules:

```
src/lumina/api/
├── server.py            ← thin factory (~200 lines); _ModProxy bridge for test monkey-patching
├── config.py            ← env-var singletons: DOMAIN_REGISTRY, PERSISTENCE, feature flags
├── session.py           ← SessionContainer, DomainContext (up to 10 domain contexts per session)
├── models.py            ← Pydantic request/response models
├── middleware.py        ← JWT bearer scheme, get_current_user, require_auth, require_role
├── llm.py               ← call_llm — provider dispatch (OpenAI / Anthropic)
├── processing.py        ← process_message — six-stage per-turn pipeline
├── runtime_helpers.py   ← render_contract_response, invoke_runtime_tool
├── utils/
│   ├── text.py          ← LaTeX regex helpers, strip_latex_delimiters
│   ├── glossary.py      ← detect_glossary_query, per-domain definition cache
│   ├── coercion.py      ← normalize_turn_data, field-type coercers
│   └── templates.py     ← template rendering for tool-call policy strings
└── routes/
    ├── chat.py          ← POST /api/chat
    ├── auth.py          ← auth and user-management endpoints
    ├── admin.py         ← escalation, audit, manifest, HITL admin-command endpoints
    ├── system_log.py    ← System Log record-browsing endpoints
    ├── domain.py        ← domain-pack lifecycle and session-close endpoints
    ├── ingestion.py     ← document ingestion pipeline endpoints
    ├── system.py        ← health, domain listing, tool adapter, System Log validate
    ├── dashboard.py     ← governance dashboard telemetry endpoints
    └── events.py        ← SSE event stream endpoints
```

The `_ModProxy` test bridge enables test-time monkey-patching of any sub-module without importing the entire monolith. No route module imports from another route module — all shared state is accessed via `lumina.api.config` singletons.

See [`docs/7-concepts/api-server-architecture.md`](docs/7-concepts/api-server-architecture.md) for the full sub-module responsibility matrix.

### Swapping domains

No server code changes required. Set one environment variable:

```bash
export LUMINA_RUNTIME_CONFIG_PATH="domain-packs/education/cfg/runtime-config.yaml"   # Education
export LUMINA_RUNTIME_CONFIG_PATH="domain-packs/agriculture/cfg/runtime-config.yaml"  # Agriculture
```

### NLP Semantic Router

Every input passes through a **three-pass domain classifier** before the prompt contract is assembled:

| Pass | Name | Mechanism | Stops early? |
|------|------|-----------|--------------|
| **1** | Keyword matching | `hits / total_keywords` scored against each domain's keyword list | Yes — if confidence ≥ 0.6 |
| **1.5** | Vector routing | Semantic similarity via global `_global` vector store | Yes — if score ≥ 0.55 (soft dependency) |
| **2** | spaCy similarity | Doc vector cosine against domain exemplar sentences | Final fallback |

Pass 1.5 is a **soft dependency** — if the global vector store is absent the classifier falls through to Pass 2 without error. This is the entry point for edge-vectorized domain routing; see [Edge Vectorization](#edge-vectorization) below.

Source: `src/lumina/core/nlp.py` — see [`docs/7-concepts/nlp-semantic-router.md`](docs/7-concepts/nlp-semantic-router.md) for the full classification procedure.

### Tool mediation

Tool adapters now have **two subtypes**:

- **Policy-driven tool adapters** — declared as YAML under `modules/<module>/tool-adapters/`, called by `apply_tool_call_policy` in the orchestrator. Configurable without Python changes.
- **Direct tool adapters** — Python callables in `controllers/tool_adapters.py`, invoked directly by the runtime adapter for computed signals that need low-level domain logic.

Both subtypes follow the same `payload: dict → dict` contract and are deterministic. See [`docs/7-concepts/domain-adapter-pattern.md`](docs/7-concepts/domain-adapter-pattern.md) for the four-layer distinction and authoring pattern.

---

### SLM Compute Tier

Lumina OS distributes compute across two model tiers so the LLM receives only pre-digested, high-quality context. The SLM handles all **low-weight** work:

| SLM Role | What it does | LLM involvement |
|----------|--------------|-----------------|
| **Librarian** | Renders fluent glossary definitions from domain-owned term data | None — response returned before LLM is invoked |
| **Physics Interpreter** | Pre-digests domain physics against incoming signals → `_slm_context` injected into the prompt packet | Reduced — LLM receives compressed, pre-interpreted context |
| **Command Translator** | Parses natural-language admin instructions into structured operations | None — execution goes through existing RBAC-enforced admin endpoints |

A **Task Weight Classifier** evaluates the assembled prompt contract and routes `LOW` tasks (definitions, physics interpretation, state formatting, admin commands) to the SLM and `HIGH` tasks (instructions, corrections, novel synthesis, verification requests) to the LLM.

The SLM layer **always degrades gracefully** — if the SLM is unavailable, deterministic templates fill glossary responses, the prompt packet assembles without context compression, and admin commands return HTTP 503. SLM failure never blocks the system.

See [`docs/7-concepts/slm-compute-distribution.md`](docs/7-concepts/slm-compute-distribution.md) for the full three-role architecture, weight routing table, provider backends, and fallback guarantees.

---

### Novel Synthesis Tracking

When the LLM produces a response the domain's evidence extractors cannot classify using existing rules, the system enters a **two-key verification gate**:

1. **Key 1 — Domain invariant fires** — the domain physics defines a `signal_type: NOVEL_PATTERN` invariant. When the pattern-recognition check fails, the orchestrator applies a standing order (requesting justification) and, if unresolved, creates an `EscalationRecord` with `trigger_type: novel_synthesis_review`.
2. **Key 2 — Domain Authority confirms** — the human Domain Authority reviews the escalation and issues a verdict: `novel_synthesis_verified` (innovation recorded) or `novel_synthesis_rejected` (false positive flagged).

The System Logs records `model_id`, `model_version`, and the verdict for every gate event. This builds a **cross-domain model performance heatmap** — distinguishing models that parrott known answers from those that generate genuine insight. The domain knowledge base is never updated until Key 2 turns.

See [`docs/7-concepts/novel-synthesis-framework.md`](docs/7-concepts/novel-synthesis-framework.md) for the full lifecycle diagram and System Log telemetry schema.

---

## Domain Packs

### Domain Pack Anatomy

A domain pack is the **D pillar** of the D.S.A. Framework — a self-contained unit of domain knowledge, behavioural constraints, and processing tools. Every fully-realised production pack is composed of **seven components**:

| # | Component | Location | Mandatory | What it owns |
|---|-----------|----------|-----------|--------------|
| 1 | **Physics files** | `modules/<module>/domain-physics.yaml` and `.json` | Yes | Invariants, standing orders, escalation triggers, artifact definitions, `actor_types`, `group_libraries`, `group_tools` |
| 2 | **Tool adapters** | `modules/<module>/tool-adapters/*.yaml` + `controllers/tool_adapters.py` | Recommended | Active deterministic verifiers — policy-driven (YAML) or direct (Python) |
| 3 | **Runtime adapter** | `controllers/runtime_adapters.py` | Yes | Phase A (NLP pre-processing before LLM) + Phase B (signal synthesis after tools); emits engine contract fields |
| 4 | **NLP pre-interpreter** | `controllers/nlp_pre_interpreter.py` | Recommended | Information gate — extracts deterministic anchors before any LLM inference |
| 5 | **Domain library** | `domain-lib/` | Recommended | Passive state estimators (ZPD, fluency, sensor normalization) |
| 6 | **Group Libraries / Group Tools** | `domain-lib/` + `controllers/group_tool_adapters.py` | Optional | Domain-scoped shared resources used by multiple modules within the domain |
| 7 | **World-sim** | `world-sim/` | Optional | Narrative framing and persona for human-facing contexts |

Each domain pack also ships a `/docs` directory mirroring the root Unix man-page section layout (sections 1–8).

The engine (`src/lumina/`) reads only two engine contract fields: `problem_solved` and `problem_status`. Zero domain-specific names appear in the core engine — this is the **self-containment contract**.

See [`docs/7-concepts/domain-pack-anatomy.md`](docs/7-concepts/domain-pack-anatomy.md) for the full seven-component anatomy and self-containment contract.

### Group Libraries and Group Tools

Within a single domain, identical logic often recurs across modules. **Group Libraries** and **Group Tools** solve this by declaring **domain-scoped shared resources** that any module within the same domain can reference:

- **Group Libraries** — passive pure-function Python modules in `domain-lib/`. Called by the runtime adapter; never called by the core engine directly. Same inputs always produce the same outputs; no LLM involvement; no external dependencies.
- **Group Tools** — active shared verifiers in `controllers/group_tool_adapters.py`. Follow the same `payload: dict → dict` contract as regular tool adapters. Callable by policy or by the runtime adapter directly.

Both types are declared in the domain-physics JSON under `group_libraries` / `group_tools` arrays. They never cross the domain boundary — a Group Library in `agriculture/` cannot be imported by `education/`.

Reference implementation: `domain-packs/agriculture/domain-lib/environmental_sensors.py`

See [`docs/7-concepts/group-libraries-and-tools.md`](docs/7-concepts/group-libraries-and-tools.md) for the physics-file declaration schema and authoring pattern.

### Domain Role Hierarchy

Domain packs can declare domain-specific role tiers beneath the Domain Authority ceiling via a `domain_roles` block in their domain-physics JSON. This enables fine-grained access control within a domain (e.g., `teacher`, `teaching_assistant`, `student` in an education deployment) without touching system-level roles.

Key properties:

- **Additive overlay** — system roles (`root`, `domain_authority`, `it_support`, `qa`, `auditor`, `user`, `guest`) are the base layer; domain roles refine access within a domain.
- **DA is always the ceiling** — no domain role can grant more access than the Domain Authority. Domain roles start at hierarchy level 1.
- **Domain-scoped** — a user can be a `teacher` in algebra and a `student` in geometry; there is no cross-domain inheritance.
- **JWT integration** — the JWT now carries a `domain_roles` claim. The system includes `role_defaults` in `cfg/domain-registry.yaml` for routing `root`/`it_support` to the system domain automatically.

See [`docs/7-concepts/domain-role-hierarchy.md`](docs/7-concepts/domain-role-hierarchy.md) for the full declaration schema and permission-resolution sequence.

### DSA Actor Model

The **Actor** pillar of the D.S.A. Framework is fully documented. Domain physics files declare `actor_types` (typed Actor definitions with `id`, `label`, `evidence_sources`, and `groups` fields) and `actor_groups` (operational groupings of Actors that share a common context).

Key invariant: **the orchestrator is not an Actor**. It is an executor and translator — it observes incoming evidence produced by Actors, updates State, checks Domain invariants, selects a response within standing orders, and escalates when it cannot stabilise.

See [`specs/dsa-framework-v1.md`](specs/dsa-framework-v1.md) and [`docs/7-concepts/dsa-actor-model.md`](docs/7-concepts/dsa-actor-model.md) for the full constraint set.

### HMVC Heritage

Lumina's domain-pack architecture descends from **Hierarchical MVC**. Domain packs are the HMVC modules; the core engine is the framework router. The mapping:

| HMVC Concept | Lumina Equivalent | Location |
|---|---|---|
| Module (self-contained app) | Domain Pack | `domain-packs/{domain}/` |
| Model (data, rules, state) | Physics + Schemas + Evidence | `modules/{mod}/domain-physics.*`, `evidence-schema.json` |
| Controller (input→logic→output) | Controllers directory | `controllers/runtime_adapters.py`, `nlp_pre_interpreter.py`, `tool_adapters.py` |
| View (presentation layer) | Prompts + World-Sim Persona | `prompts/`, `world-sim/` |
| Service layer (shared domain logic) | Domain Library | `domain-lib/` |
| Module routes / config | Runtime Config | `cfg/runtime-config.yaml` |
| Framework router | Domain Registry | `cfg/domain-registry.yaml` + `src/lumina/core/domain_registry.py` |
| Frontend plugin (View) | Domain Web Plugin | `domain-packs/{domain}/web/plugin.ts` via `PluginRegistry` |

The `ui` section in `runtime-config.yaml` is the declarative View binding. It declares the plugin bundle path and any slash commands or dashboard tabs the domain contributes. At runtime the framework's `PluginRegistry` (`src/web/plugins/PluginRegistry.ts`) loads each domain's plugin bundle; the plugin calls `addDashboardTabs()`, `addSidebarPanels()`, `addSlashCommands()`, and `addChatHooks()` to register its UI contributions. The legacy `ui_manifest` (theme, chrome text) is still read for backward compatibility but `panels` are now plugin-owned. The `controllers/` directory naming reflects this HMVC lineage (renamed from `systools/`).

See [`docs/7-concepts/hmvc-heritage.md`](docs/7-concepts/hmvc-heritage.md) for the full mapping and design rationale.

---

## Infrastructure and Backend Services

### Inspection Middleware

Every LLM output passes through a **three-stage deterministic boundary** before tool adapters or the orchestrator act on it:

| Stage | Name | What it does |
|-------|------|--------------|
| **1** | NLP Pre-Processing | Runs domain-supplied extractor functions against raw user input; merges anchors into the payload using LLM-precedence semantics |
| **2** | Schema Validation | Validates the structured payload against the `turn_input_schema` declared in `runtime-config.yaml`; fills missing optional fields from schema defaults |
| **3** | Invariant Checking | Evaluates the domain-physics `invariants` list against the payload; fires standing orders for violations |

The middleware does not call any language model. It uses only deterministic Python stdlib operations.

Source: `src/lumina/middleware/` — see [`docs/7-concepts/inspection-middleware.md`](docs/7-concepts/inspection-middleware.md).

### Edge Vectorization

The retrieval subsystem uses **per-domain vector isolation** instead of a single monolithic vector store. Each domain pack's embedded content is stored under its own subdirectory:

```
data/retrieval-index/
├── _global/     ← routing index for NLP semantic router (Pass 1.5)
├── education/
├── agriculture/
└── system/
```

The `VectorStoreRegistry` (`src/lumina/retrieval/vector_store.py`) manages lazy per-domain `VectorStore` instances — a domain store is created and loaded on first access, never at startup. The `_global` store aggregates lightweight routing vectors from all domains and is used exclusively by the NLP semantic router's Pass 1.5.

A per-domain search **structurally cannot** return content from another domain — isolation is enforced by the storage layout, not by post-hoc filtering.

Source files: `src/lumina/retrieval/vector_store.py`, `src/lumina/retrieval/housekeeper.py`, `src/lumina/retrieval/embedder.py` — see [`docs/7-concepts/edge-vectorization.md`](docs/7-concepts/edge-vectorization.md).

### Execution Route Compilation

The **route compiler** is an ahead-of-time (AOT) compilation step that converts domain-physics pointers into flat O(1) lookup tables at startup. The orchestrator and middleware then execute dictionary lookups per turn instead of walking the reference graph at runtime — analogous to a shader cache in a graphics engine.

Four compilation phases prepare a domain pack from raw declaration to runtime-ready data:

| Phase | Analogy | Output |
|-------|---------|--------|
| Lexical Ingestion | Tokenisation | Per-domain `.npz` vector stores |
| Dependency Linking | Linking shared libraries | `RouterIndex` with group_libraries and group_tools |
| Semantic Logic Graphing | Building the AST | Invariant/standing-order/escalation declaration graph |
| **AOT Caching** | **Shader compilation** | **`CompiledRoutes` flat lookup tables** |

`compile_execution_routes()` in `src/lumina/core/route_compiler.py` produces a `CompiledRoutes` container with `InvariantRoute` and `StandingOrderRoute` frozen dataclasses.

See [`docs/7-concepts/execution-route-compilation.md`](docs/7-concepts/execution-route-compilation.md).

### Resource Monitor Daemon

A background asyncio task that periodically samples system load and dispatches batch maintenance tasks when the host is idle:

- **Load estimation** — blends event-loop latency, HTTP queue depth, and GPU VRAM usage into a single 0.0–1.0 `load_score`
- **Idle dispatch** — triggers when `load_score < 0.20` is sustained for 300 seconds; dispatches tasks from the priority list: `knowledge_graph_rebuild`, `glossary_expansion`, `rebuild_domain_vectors`, `rejection_corpus_alignment`, and others
- **Cooperative preemption** — requests graceful pause when `load_score > 0.40` spikes during a running task; resumes when load drops

The daemon runs on the same asyncio event loop as the FastAPI server — no threads, no subprocesses. Manual triggers via the `trigger_daemon_task` admin command are also supported.

Source files: `src/lumina/daemon/` — see [`docs/7-concepts/resource-monitor-daemon.md`](docs/7-concepts/resource-monitor-daemon.md).

### State-Change Commit Policy

Every API endpoint that mutates persistent state **must** write a System Log record before returning success. Enforced at two levels:

- **Runtime** — `@requires_log_commit` decorator (`lumina.system_log.commit_guard`) raises `LogCommitMissing` if the handler completes without writing a log record
- **Static** — AST-based audit scanner (`lumina.system_log.audit_scanner`) verifiable in CI

All three persistence adapters (`FilesystemPersistenceAdapter`, `SQLitePersistenceAdapter`, `NullPersistenceAdapter`) call `notify_log_commit()` automatically inside `append_log_record`, satisfying the decorator without boilerplate.

See [`docs/7-concepts/state-change-commit-policy.md`](docs/7-concepts/state-change-commit-policy.md).

### System Log Micro-Router

All Lumina subsystems emit a `LogEvent` into a central async **log bus**. The **Micro-Router** inspects each event's `level` and `category` tags and routes to the appropriate destination — no module decides where its own log output goes:

| Level | Destination |
|-------|-------------|
| DEBUG / INFO | Rolling archives |
| WARNING | Dashboard queue |
| ERROR / CRITICAL | Alert queue |
| AUDIT | Immutable audit ledger |

Source: `src/lumina/system_log/log_bus.py`, `src/lumina/system_log/log_router.py` — see [`docs/7-concepts/system-log-micro-router.md`](docs/7-concepts/system-log-micro-router.md).

### Document Ingestion Pipeline

Domain Authorities can upload external content — PDF, DOCX, Markdown, CSV, JSON, YAML — and transform it into structured domain-physics YAML via SLM-driven interpretation. The pipeline is RBAC-gated (`root`, `domain_authority`, `it_support` only):

```
Upload → Content Extraction → SLM Interpretation → DA Review → Commit
```

Daemon batch tasks run `glossary_expansion` and `rejection_corpus_alignment` after ingestion days to incorporate newly committed content into retrieval indices.

See [`docs/7-concepts/ingestion-pipeline.md`](docs/7-concepts/ingestion-pipeline.md).

---

## Governance — Fractal Authority

Every level is a Domain Authority for its own scope and a Meta Authority for levels below:

```
Macro Authority    (e.g., Corporate Policy / Hospital Admin / School Board)
    ↓ Meta Authority for ↓
Meso Authority     (e.g., Site Manager / Dept Head / Curriculum Director)
    ↓ Meta Authority for ↓
Micro Authority    (e.g., Operator / Lead Physician / Teacher)
    ↓ Meta Authority for ↓
Subject/Target     (e.g., Environment / Patient / Learner)
```

Each level authors its own Domain Physics, retrieves context from the level above via RAG contracts, is held accountable via the System Logs, and can escalate upward when the system cannot stabilize.

See [`GOVERNANCE.md`](GOVERNANCE.md) for policies and [`docs/8-admin/`](docs/8-admin/README.md) for role definitions, RBAC, and audit procedures.

---

## Core Principles

These seven universal principles apply to every Lumina OS interaction, regardless of domain. They cannot be overridden by any authority level. Domain-specific principles are owned by each domain pack under [`domain-packs/`](domain-packs/).

1. **Domain-bounded operation** — the AI may not act outside what the Domain Physics authorizes
2. **Measurement, not surveillance** — structured telemetry only; no transcript storage
3. **Domain Authority is the authority** — AI assists, it does not replace the human expert
4. **Append-only accountability** — the ledger is never modified, only extended
5. **Do not expand scope without drift justification** — scope creep is a violation
6. **Pseudonymity by default** — the AI layer does not know who the entity is; pseudonymous tokens only
7. **Bounded drift probing** — one bounded probe per drift detection cycle

See [`specs/principles-v1.md`](specs/principles-v1.md) for the full specification including domain-specific principles.

---

## Repository Structure

```
lumina-os/
├── src/
│   ├── lumina/
│   │   ├── api/                ← thin factory + 22 sub-modules (routes/, utils/, session, config, etc.)
│   │   ├── core/               ← domain registry, NLP classifier, route compiler, runtime loader, adapter indexer
│   │   ├── orchestrator/       ← PPA orchestrator, actor resolver
│   │   ├── middleware/         ← inspection pipeline (NLP pre-proc, schema validation, invariant checking)
│   │   ├── retrieval/          ← VectorStoreRegistry, DocEmbedder, housekeeper (per-domain vector stores)
│   │   ├── daemon/             ← ResourceMonitorDaemon, LoadEstimator, PreemptionToken
│   │   ├── ingestion/          ← document ingestion service, extractors, interpreter
│   │   ├── system_log/         ← SystemLogWriter, log bus, micro-router, alert/warning stores
│   │   ├── auth/               ← JWT, password hashing, token management
│   │   ├── persistence/        ← SQLite, filesystem, null adapters
│   │   └── systools/           ← repo integrity verifier, hw probes, manifest integrity
│   └── web/                    ← Vite + React reference UI
├── cfg/                        ← domain-registry.yaml, system-runtime-config.yaml, system-physics.yaml
├── data/
│   └── retrieval-index/        ← per-domain vector stores (_global/, education/, agriculture/, system/)
├── domain-packs/
│   └── <domain>/
│       ├── cfg/runtime-config.yaml       ← adapter bindings, ui_manifest, world-sim config
│       ├── modules/<module>/
│       │   ├── domain-physics.yaml/.json
│       │   ├── evidence-schema.json
│       │   └── tool-adapters/
│       ├── controllers/                   ← nlp_pre_interpreter, runtime_adapters, tool_adapters, group_tool_adapters
│       ├── domain-lib/                    ← Group Libraries + passive state estimator specs
│       ├── docs/                          ← domain-scoped man pages (sections 1–8)
│       ├── web/                           ← domain-owned frontend plugin (plugin.ts, components/, services/)
│       └── world-sim/                     ← optional narrative framing
├── specs/
├── standards/
├── ledger/
├── docs/                       ← UNIX man-page reference (sections 1–8)
├── tests/
└── scripts/
```

---

## Quick Start

### Prerequisites

- Python 3.12+ (tested on 3.14)
- An LLM API key (OpenAI or Anthropic) — only required for live (non-deterministic) responses

Install and packaging workflows are documented in [`docs/1-commands/installation-and-packaging.md`](docs/1-commands/installation-and-packaging.md). Runtime secret and production config setup is documented in [`docs/8-admin/secrets-and-runtime-config.md`](docs/8-admin/secrets-and-runtime-config.md).

### Run the deterministic demo (no API key needed)

```bash
# 1. Create a virtual environment
# Windows — use the py launcher to pin a specific version (required for the nlp extra):
#   py -3.13 -m venv .venv && .venv\Scripts\Activate.ps1
# macOS / Linux:
python3 -m venv .venv
source .venv/bin/activate

# 2. Install runtime dependencies (once venv is active, use plain pip)
pip install -r requirements.txt

# 3. Set the runtime config (required — no silent defaults)
export LUMINA_RUNTIME_CONFIG_PATH="domain-packs/education/cfg/runtime-config.yaml"

# 4. Start the server
python -m lumina.api.server

# 5. In another terminal, send a deterministic request
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "I solved it and checked by substitution.",
    "deterministic_response": true,
    "turn_data_override": {
      "correctness": "correct",
      "frustration_marker_count": 0,
      "step_count": 4,
      "hint_used": false,
      "repeated_error": false,
      "off_task_ratio": 0.0,
      "response_latency_sec": 6
    }
  }'
```

### Run with a live LLM

```bash
# OpenAI (default)
export OPENAI_API_KEY="sk-..."
pip install openai

# Or Anthropic
export LUMINA_LLM_PROVIDER="anthropic"
export ANTHROPIC_API_KEY="sk-ant-..."
pip install anthropic
```

Then start the server and send requests without `deterministic_response` or `turn_data_override`.

### Available domain packs

| Domain | Pack | Status | Notes |
|--------|------|--------|-------|
| Education — Algebra Level 1 | `education/modules/algebra-level-1` | Active | Full 7-component pack with world-sim, MUD World Builder |
| Agriculture — Operations Level 1 | `agriculture/modules/operations-level-1` | Active | Group Library reference implementation (`environmental_sensors`) |
| System | `system/` | Active | `local_only: true`, SLM-only routing, no external LLM |

### Testing and verification

```bash
# Repository integrity check (markdown links, schema linkage, version alignment)
python -m lumina.systools.verify_repo

# Backend unit + integration tests
# Install runtime + dev dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt
python -m pytest tests -q

# Full verification flow (integrity + orchestrator + optional API/FE)
# PowerShell:  .\scripts\run-full-verification.ps1
```

See [`docs/1-commands/`](docs/1-commands/README.md) for detailed command references and [`docs/2-syscalls/`](docs/2-syscalls/README.md) for API endpoint documentation.

### Explore the architecture

1. [`specs/principles-v1.md`](specs/principles-v1.md) — the non-negotiables
2. [`specs/dsa-framework-v1.md`](specs/dsa-framework-v1.md) — the D.S.A. structural schema (Domain, State, Actor) underlying PPA
3. [`domain-packs/education/cfg/runtime-config.yaml`](domain-packs/education/cfg/runtime-config.yaml) — how a domain owns its runtime behavior
4. [`domain-packs/education/modules/algebra-level-1/`](domain-packs/education/modules/algebra-level-1/) — a complete worked domain pack (education)
5. [`domain-packs/agriculture/modules/operations-level-1/`](domain-packs/agriculture/modules/operations-level-1/) — a sensor/field operations domain pack
6. [`examples/README.md`](examples/README.md) — full interaction traces
7. [`docs/7-concepts/slm-compute-distribution.md`](docs/7-concepts/slm-compute-distribution.md) — SLM three-role architecture, weight routing, provider backends, fallback guarantees
8. [`docs/7-concepts/novel-synthesis-framework.md`](docs/7-concepts/novel-synthesis-framework.md) — two-key verification gate, model benchmarking via System Log telemetry
9. [`docs/7-concepts/domain-pack-anatomy.md`](docs/7-concepts/domain-pack-anatomy.md) — seven-component anatomy, self-containment contract
10. [`docs/7-concepts/group-libraries-and-tools.md`](docs/7-concepts/group-libraries-and-tools.md) — Group Libraries and Group Tools
11. [`docs/7-concepts/edge-vectorization.md`](docs/7-concepts/edge-vectorization.md) — per-domain vector stores, Pass 1.5 routing
12. [`docs/7-concepts/execution-route-compilation.md`](docs/7-concepts/execution-route-compilation.md) — AOT route compilation
13. [`docs/7-concepts/resource-monitor-daemon.md`](docs/7-concepts/resource-monitor-daemon.md) — load-based opportunistic task scheduling
14. [`docs/7-concepts/domain-role-hierarchy.md`](docs/7-concepts/domain-role-hierarchy.md) — domain-scoped RBAC role tiers
15. [`docs/7-concepts/hmvc-heritage.md`](docs/7-concepts/hmvc-heritage.md) — architectural lineage and HMVC mapping

---

## Conformance

All domain packs and implementations must conform to [`standards/lumina-core-v1.md`](standards/lumina-core-v1.md). See [`docs/5-standards/`](docs/5-standards/README.md) for the full specification index.

---

## Disclaimer

Lumina OS is research/experimental software provided AS-IS under Apache 2.0 with NO WARRANTIES. No part of this project is certified for safety-critical, high-stakes, or regulated use (including with minors) without thorough independent validation.

The engine provides structural accountability (D.S.A. contracts, System Log traces) but does **not** replace human oversight, professional judgment, or legal compliance. Ultimate accountability for any deployment sits with the human Domain Authority at each level, never the AI or the engine.

Domain packs that involve vulnerable populations (children, patients, etc.) include additional warnings and must be independently reviewed before any real-world deployment. See individual domain pack READMEs for domain-specific disclaimers.

---

*Last updated: 2026-03-28*
