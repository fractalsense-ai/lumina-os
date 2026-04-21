---
version: 1.1.0
last_updated: 2026-04-16
---

# Prompt Packet Assembly

**Version:** 1.1.0
**Status:** Active
**Last updated:** 2026-04-16

---

This document describes how a Lumina prompt contract is assembled from layered components before it is sent to the LLM. It covers the full input-to-output pipeline, the role of each layer, how telemetry and sensor signals become part of the packet, how domain library tools supply verified information the LLM can reason over, and what the LLM sees versus what is deliberately hidden from it.

---

## A. The Packet Model

TCP/IP assembles network packets from layered protocols — each layer adds its header, the payload travels through, and checksums verify integrity at the destination. Project Lumina applies the same principle to LLM interactions.

The **assembled prompt contract** is the "packet." It is built by stacking headers from layers that each know only their own concern. The LLM is the processing unit at the end of the assembly line. It receives a fully-formed, context-complete packet and produces a response. The packet assembly process is deterministic and auditable. The LLM response is probabilistic and always verified.

```
┌─────────────────────────────────────────────┐
│  Input Interface                            │  ← raw signal enters here
├─────────────────────────────────────────────┤
│  Domain Adapter — Input Normalization (A)   │  ← NLP classification + anchor extraction
├─────────────────────────────────────────────┤
│  RAG Retrieval (MiniLM embeddings)          │  ← per-domain vector search (pre-interp)
├─────────────────────────────────────────────┤
│  SLM Context Compression (optional)         │  ← physics interpretation + signal digest
├─────────────────────────────────────────────┤
│  Turn Interpretation (SLM-preferred)        │  ← structured evidence extraction
├─────────────────────────────────────────────┤
│  Global Base Prompt                         │  ← universal rules  (the "IP header")
├─────────────────────────────────────────────┤
│  Domain Physics                             │  ← domain policy layer header
├─────────────────────────────────────────────┤
│  Module State + Turn Data / NLP Anchors     │  ← session-specific context header
├═════════════════════════════════════════════╡
│  Assembled Prompt Contract                  │  ← the "packet" sent to the LLM
├─────────────────────────────────────────────┤
│  LLM (Processing Unit)                      │  ← probabilistic; never trusted alone
├─────────────────────────────────────────────┤
│  Tool-Adapter Verification                  │  ← deterministic output checking
├─────────────────────────────────────────────┤
│  Domain Adapter — Signal Synthesis (B)      │  ← computes engine contract fields
├─────────────────────────────────────────────┤
│  System Log (System Logs)                   │  ← structured event + decision logging
└─────────────────────────────────────────────┘
```

> Both Domain Adapter rows are owned entirely by the domain pack. Zero domain-specific names appear in the core engine.
> See [`domain-adapter-pattern(7)`](domain-adapter-pattern.md) for the authoring contract.

The key design property is this: **the LLM does not have to guess about context.** Everything the LLM needs to reason correctly is assembled into the packet before the LLM sees any of it. The LLM is constrained to the packet. It cannot expand scope beyond what Domain Physics authorizes, because the packet itself is the boundary.

---

## B. Layer Reference Table

Each layer in the assembly pipeline has a distinct role, a distinct owner, and a distinct mutability profile.

| # | Layer | Owner | Mutability | Contribution to the packet |
|---|-------|-------|------------|---------------------------|
| 1 | **Input Interface** | External (caller) | Per-turn | Raw signal: chat message, sensor value, lab event, API payload |
| 2 | **Domain Adapter A — Input Normalization** | Domain pack | Per-turn | NLP classification result; `_nlp_anchors`; structured evidence partial |
| 2½a | **RAG Retrieval** (MiniLM embeddings) | Core engine | Per-turn | Embeds the raw input via MiniLM (`all-MiniLM-L6-v2`, 384-dim) and runs cosine-similarity search against per-domain vector stores. Produces `_rag_context` (top-k document chunks with source, heading, score). Runs **before** turn interpretation so retrieved domain context is available to the interpreter. See [`slm-compute-distribution(7)`](slm-compute-distribution.md). |
| 2½b | **SLM Context Compression** (optional) | Core engine (SLM) | Per-turn | Matches incoming signals against domain physics; produces `_slm_context` (matched invariants, relevant glossary terms, context summary, suggested evidence fields). Runs after turn interpretation once structured `turn_data` is available. See [`slm-compute-distribution(7)`](slm-compute-distribution.md). |
| 2½c | **Turn Interpretation** | Domain pack (SLM-preferred) | Per-turn | Extracts structured evidence from raw input. Prefers the local SLM (`call_slm`); falls back to the LLM (`call_llm`) when the SLM is unavailable. Deterministic tools (algebra parser, NLP anchors) bracket the model call — they run before and after to constrain the output. |
| 3 | **Global Base Prompt** | Core engine / system physics | Immutable per session | Universal rules that apply regardless of domain; "never act outside authorization"; append-only accountability; scope constraints |
| 4 | **Domain Physics** | Domain Authority | Immutable per session | Domain-specific standing orders; invariants; escalation triggers; tool call policies; consent flags |
| 5 | **Module State + Turn Data** | Core engine (from adapter outputs) | Mutable per turn | Current entity profile (ZPD position, fluency score, fatigue estimate); current task; turn number; NLP anchor lines |
| ═ | **Assembled Prompt Contract** | Core engine | — | The complete packet serialized for LLM consumption |
| 6 | **LLM** | External LLM provider | — | Probabilistic response — never trusted as sole authority |
| 7 | **Tool-Adapter Verification** | Domain pack (policy-driven) | Per-turn | Deterministic override of specific LLM-produced fields (e.g., algebra parser replaces `correctness`) |
| 8 | **Domain Adapter B — Signal Synthesis** | Domain pack | Per-turn | Engine contract fields (`problem_solved`, `problem_status`); final `evidence` dict |
| 9 | **System Log** | Core engine | Append-only | Hash-chained trace event logging the decision, provenance hashes, and outcome. Events are emitted to the [System Log Micro-Router](system-log-micro-router.md) which routes them by level (AUDIT → immutable ledger, WARNING → dashboard, etc.). |

### What "immutable per session" means

Domain Physics and the Global Base Prompt are loaded once at session start and hash-committed via the policy commitment gate. They cannot be changed mid-session. If the active domain-physics hash does not match the committed System Log `CommitmentRecord`, the session does not start. This ensures the LLM's operating rules cannot be silently swapped mid-turn.

---

## C. Input Sources and Telemetry

Lumina is designed to receive any structured event stream as input — not only human text messages. The input interface abstracts over the source. What the domain adapter does with that input is the domain's concern.

| Input source | Example | Normalization by Adapter A |
|---|---|---|
| Chat / text message | Student types "I think x = 4" | NLP pre-interpreter extracts `correctness`, `extracted_answer`, `frustration_marker_count` |
| Sensor feed | Temperature sensor reads 38.7°C | Domain adapter maps value to structured signal (e.g., `temp_above_threshold: true`) |
| Lab instrument event | Mass spectrometer reports spectrum scan ID 7 | Adapter maps to `scan_complete: true`, `scan_id: "7"`, populates expected step fields |
| Agricultural telemetry | Soil moisture sensor: 12% | Adapter maps to `moisture_deficit: true`, appends to variance tracking evidence |
| API payload | `{"task_id": "pipette_fill", "volume_ul": 500}` | Adapter validates payload, sets `task_received: true`, `volume_ok: (500 == expected_volume)` |

No matter the source, by the time the payload reaches Layer 3 (Global Base Prompt assembly), it has been normalized to a structured evidence dict. The LLM never receives raw telemetry — it receives structured, labeled signals.

### Education example: the student as telemetry

In the education domain the "sensor" is the student. They are attempting to learn algebra. Everything the student says is the input signal. Everything else — the domain physics, the module state, the NLP anchors — exists to convert that raw signal into a form the LLM can reason over accurately.

The domain's job is to filter. Algebra is what is being measured. If the student sends a message about football, that is `off_task_ratio: 1.0` — noise, measured and classified, not a domain expansion. The orchestrator sees a high off-task ratio in the NLP anchors and applies the appropriate standing order (redirect, log, do not comply). The student never sees the standing order logic.

The same model applies to any domain. In a lab automation domain the pipette fill procedure is the domain. Sensor readings outside the expected value ranges are noise, classified deterministically by the domain adapter and escalated if thresholds are violated. The LLM reasons over labeled signals, not raw instrument output.

---

## D. Domain Library Tools

The LLM does not have to reason about everything from scratch. The domain library provides tools — deterministic verifiers, calculators, device adapters — whose outputs are injected into the packet so the LLM receives pre-verified facts alongside the question.

Domain library tools come in two kinds:

### Tool Adapters (active, policy-driven)

Tool adapters are called by the orchestrator's policy system when a specific resolved action is triggered. They are declared in YAML and backed by Python functions. The LLM never dispatches them directly — the orchestrator resolves the action, calls the adapter, and the result is returned as a verified field in the evidence dict.

| Domain | Tool | What it does |
|--------|------|-------------|
| Education | Algebra parser | Parses the student's expression and validates structural form |
| Education | Substitution checker | Substitutes the student's answer into the original equation and confirms equality |
| Lab automation | Pipette volume verifier | Checks commanded volume against protocol spec; returns `volume_ok: bool` |
| Agriculture | Soil moisture comparator | Compares sensor reading to domain threshold; returns `deficit_severity: str` |
| Robotics | Arm position validator | Confirms end-effector position is within tolerance for current step; returns `position_valid: bool` |

The LLM sees the result (`substitution_check: true`, `volume_ok: true`) in the evidence presented in its prompt context. It never sees the tool call itself, its parameters, or its dispatch logic.

### Domain Library Functions (passive, state-estimation)

Domain library functions track entity state across turns. They are called by the runtime adapter (not the orchestrator) and produce state estimates that become part of Module State for the next turn.

| Domain | Library function | What it tracks |
|--------|-----------------|---------------|
| Education | ZPD monitor | Whether the current task is inside, above, or below the learning zone |
| Education | Fluency tracker | Vocabulary and problem-type fluency across the session |
| Education | Fatigue estimator | Engagement and response-quality degradation signal |
| Agriculture | Variance tracker | Rolling deviation from expected yield or moisture baselines |

These produce fields like `zpd_zone: "within"`, `fluency_advanced: true`, `fatigue_signal: 0.3` that flow into Module State. The LLM sees them as session context when they are relevant to the current action.

### Embedding / Retrieval Infrastructure (passive, pre-interpretation)

The core engine provides a MiniLM-based embedding and retrieval layer that runs before turn interpretation. This is not a domain library function — it is core infrastructure available to all domains.

| Component | Model / Implementation | What it does |
|-----------|----------------------|-------------|
| `DocEmbedder` | `all-MiniLM-L6-v2` (384-dim) via Ollama or `sentence-transformers` | Embeds document chunks and query text into dense vectors |
| `VectorStore` | Flat-file `.npz` with brute-force cosine similarity | Per-domain vector index storing embedded chunks from domain docs, physics files, and standards |
| `search_domain()` | Cosine similarity, top-k retrieval | Finds the most relevant domain document chunks for the current input; results are filtered by active module to exclude sibling-module content |

The retrieval step produces `_rag_context` — a list of `{text, source, heading, score}` dicts injected into `turn_data`. The LLM sees these as grounding context in the assembled prompt. The embedding model, vector store internals, and similarity scores are hidden from the LLM.

---

## E. What the LLM Sees vs. What It Doesn't

The packet is carefully bounded. Some information is structurally hidden from the LLM — either because the LLM does not need it to do its job, or because exposing it would violate a design property (pseudonymity, separation of concerns, or security).

### What the LLM sees

| Component | Example content |
|-----------|----------------|
| Global Base Prompt | "You are operating within the Project Lumina framework. You may only take actions authorized by the current Domain Physics..." |
| Domain Physics | Standing orders, invariants, escalation conditions, task templates — authored by the Domain Authority |
| Module State | Current entity profile: `{zpd_zone: "within", fluency_level: 2, current_problem: {id: "alg-003", ...}}` |
| Turn Data / NLP Anchors | "NLP pre-analysis (deterministic): correctness: correct (confidence: 0.95)..." |
| Tool adapter results | `substitution_check: true`, `algebra_parse: "valid"` — returned as labeled fields in evidence |

### What the LLM does not see

| Hidden component | Why it's hidden |
|-----------------|----------------|
| Tool call dispatch parameters | Tool calls are policy mechanisms, not LLM decisions. The LLM should not know what tools were checked or what parameters they used — it confuses the separation between reasoning and verification. |
| Domain physics enforcement logic | Whether the domain hash matched, whether a CommitmentRecord was found — these are infrastructure concerns. Exposing them would add noise without adding reasoning value. |
| Glossary intercept matching | If the message was a known glossary term, the LLM never received the turn. The intercept returned a definition directly (via SLM Librarian or deterministic template). |
| SLM processing details | Which invariants the SLM matched, what context it compressed, its raw JSON output — the LLM sees only the final `_slm_context` summary, not the SLM's internal reasoning. See [`slm-compute-distribution(7)`](slm-compute-distribution.md). |
| System Log write operations | Ledger writes happen after the LLM turn, as audit infrastructure. They are not inputs to reasoning. |
| System-physics hash injection | The system-physics hash in System Log metadata (`system_physics_hash`) is a provenance record for the auditor, not reasoning context for the LLM. |
| Caller identity and RBAC result | The LLM operates on pseudonymous session IDs only. Canonical identity, role, and permission check outcomes are resolved at the API layer before the prompt is assembled. |
| Raw telemetry before normalization | Sensor readings, raw event payloads, and protocol frames are normalized by Domain Adapter A before the Global Base Prompt layer. The LLM receives structured signals, not raw instrument data. |
| Conversation transcripts | No raw transcript is stored or re-injected. The LLM receives structured state and signals, not a replay of prior turns in free text. |
| RAG retrieval internals | The embedding model (MiniLM), vector store implementation, similarity scores, and source-path filtering logic are hidden. The LLM sees only the final `_rag_context` chunks (truncated text + heading), not the retrieval mechanism. |
| Turn interpretation routing | Whether the SLM or LLM handled turn interpretation, which weight class was assigned, and the fallback logic are infrastructure concerns. The LLM sees structured `turn_data`, not the model that produced it. |

This boundary is not an accident. The domain authority does not want the student to see the standing order that says "if off-task ratio exceeds 0.6, issue a single redirect and log a drift event." The lab operator does not need the LLM to know that the pipette verifier was invoked via a policy trigger — only that the volume check passed. Hiding these layers makes the LLM simpler to constrain, debug, and verify.

---

## SEE ALSO

- [`context-is-not-conversation(7)`](context-is-not-conversation.md) — foundational thesis for structured context assembly
- [`ai-governance-principles(7)`](ai-governance-principles.md) — governance constraints implemented by the packet pipeline
- [`README.md`](../../README.md) — top-level packet assembly diagram and TCP/IP metaphor
- [`specs/dsa-framework-v1.md`](../../specs/dsa-framework-v1.md) — D.S.A. structural schema (Domain, State, Actor pillars) and turn sequence that PPA assembles into each prompt packet
- [`docs/7-concepts/domain-adapter-pattern.md`](domain-adapter-pattern.md) — Phase A/ Phase B authoring contract; engine contract field reference
- [`docs/7-concepts/nlp-semantic-router.md`](nlp-semantic-router.md) — Tier 1 domain classification and Tier 2 anchor extraction
- [`docs/7-concepts/slm-compute-distribution.md`](slm-compute-distribution.md) — SLM compute distribution: Librarian, Physics Interpreter, Command Translator
- [`standards/prompt-contract-schema-v1.json`](../../standards/prompt-contract-schema-v1.json) — JSON schema for the assembled prompt contract
- [`specs/global-system-prompt-v1.md`](../../specs/global-system-prompt-v1.md) — Global Base Prompt specification (rendered view; source of truth is `cfg/system-physics.yaml`)
- [`cfg/system-physics.yaml`](../../cfg/system-physics.yaml) — system physics: source of truth for global-layer rules and hash
- [`standards/lumina-core-v1.md`](../../standards/lumina-core-v1.md) — provenance metadata fields in System Log TraceEvents; system physics hash injection
