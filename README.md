# Lumina OS

**A zero-trust, deterministic orchestration layer that secures AI reasoning behind immutable Domain Physics — giving the LLM exactly one job: high-weight reasoning.**

---

## What Is Lumina OS?

TCP/IP assembles packets from layered protocols — each layer adds its headers, the payload travels through, and checksums verify integrity. Lumina OS does the same thing for LLMs.

The **PPA (Prompt Packet Assembly) engine** assembles a **dynamic prompt contract** from layered components — global rules, domain policy, module state, and turn context. Only what is needed is added at each layer. The LLM processes this contract. Tool-adapters verify the output. The Causal Trace Ledger logs the decision.

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
│  CTL (Causal Trace Ledger)                                           │  ← append-only: trace events, escalations, novel synthesis events
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
3. **Intent (action)** — bounded action determined by Domain + State
4. **Proposal (LLM)** — the LLM processes the assembled prompt contract
5. **Verification (tools + invariants)** — tool-adapters check the LLM's reasoning; unrecognized patterns are flagged as novel synthesis signals
6. **Commit / escalate** — verified decisions are committed; violations escalate to a human; novel synthesis events require a two-key gate (LLM flags → Domain Authority confirms or rejects)
7. **Trace (CTL)** — the decision is logged to the append-only ledger

The **D.S.A. structural schema** is the contract model behind PPA. Three pillars define every session contract:

| Pillar | Name | Role | Mutability |
|--------|------|------|------------|
| **D**  | Domain | Rules, invariants, standing orders, escalation triggers | Immutable per session |
| **S**  | State | Compact entity profile updated from structured evidence | Mutable |
| **A**  | Action | Bounded response produced by the orchestrator | Constrained by Domain |

The PPA orchestrator assembles a dynamic prompt contract from these D.S.A. components. The LLM is constrained to that contract, tool-adapters verify its output, and the resulting decision is committed or escalated and written to CTL.

See [`specs/dsa-framework-v1.md`](specs/dsa-framework-v1.md) for the full D.S.A. structural specification and [`standards/causal-trace-ledger-v1.md`](standards/causal-trace-ledger-v1.md) for CTL protocol.

---

## Modular Runtime

The core engine (`src/lumina/api/server.py`) is a **generic runtime host** with zero domain-specific logic. Domain behavior is loaded at startup from a domain pack's `cfg/runtime-config.yaml`, which declares prompt files, state adapters, tool policies, and deterministic templates.

At startup, the runtime computes policy/prompt hashes and enforces a **policy commitment gate** — the active domain-physics hash must match a committed CTL `CommitmentRecord` before any session can execute. During each turn, provenance lineage hashes are carried in CTL metadata for packet-level auditability without storing transcript content.

### Swapping domains

No server code changes required. Set one environment variable:

```bash
export LUMINA_RUNTIME_CONFIG_PATH="domain-packs/education/cfg/runtime-config.yaml"   # Education
export LUMINA_RUNTIME_CONFIG_PATH="domain-packs/agriculture/cfg/runtime-config.yaml"  # Agriculture
```

### Tool mediation

Tool calls are **policy-driven**, not hardcoded. Each domain's config maps resolved actions to tool-adapter calls with template-interpolated payloads — the engine resolves variables from interpreted turn-data, calls the tool adapter, and passes verified results back through the pipeline.

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

The CTL records `model_id`, `model_version`, and the verdict for every gate event. This builds a **cross-domain model performance heatmap** — distinguishing models that parrott known answers from those that generate genuine insight. The domain knowledge base is never updated until Key 2 turns.

See [`docs/7-concepts/novel-synthesis-framework.md`](docs/7-concepts/novel-synthesis-framework.md) for the full lifecycle diagram and CTL telemetry schema.

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

Each level authors its own Domain Physics, retrieves context from the level above via RAG contracts, is held accountable via the CTL, and can escalate upward when the system cannot stabilize.

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
project-lumina/
├── src/
│   ├── lumina/                 ← core D.S.A. engine (FastAPI, domain-agnostic)
│   │   ├── api/                ← FastAPI server and route handlers
│   │   ├── auth/               ← authentication and token management
│   │   ├── cli/                ← command-line interface
│   │   ├── core/               ← orchestrator, PPA engine, prompt assembly
│   │   ├── ctl/                ← Causal Trace Ledger writer
│   │   ├── orchestrator/       ← turn pipeline and commitment gating
│   │   ├── persistence/        ← storage adapters (SQLite, filesystem)
│   │   └── systools/           ← repo integrity verifier and admin utilities
│   └── web/                    ← Vite + React reference UI
├── cfg/                        ← runtime registry (domain-registry.yaml)
├── scripts/                    ← PowerShell verification and maintenance scripts
├── domain-packs/               ← domain-specific everything (education, agriculture, ...)
│   └── <domain>/
│       ├── cfg/                ← runtime-config.yaml for this domain
│       ├── docs/               ← domain-scoped reference documentation
│       ├── modules/            ← worked module packs
│       ├── prompts/            ← domain physics and prompt templates
│       └── systools/           ← domain-specific tool adapters
├── specs/                      ← architecture specifications (PPA framework, principles, prompts)
├── standards/                  ← universal engine schemas and contracts
├── ledger/                     ← CTL JSON schemas (trace events, commitments, escalations)
├── governance/                 ← policy templates and role definitions
├── retrieval/                  ← RAG layer contracts and schemas
├── docs/                       ← UNIX man-page reference (sections 1–8)
├── tests/                      ← pytest unit + integration tests
└── examples/                   ← worked interaction traces
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
2. [`specs/dsa-framework-v1.md`](specs/dsa-framework-v1.md) — the D.S.A. structural schema (Domain, State, Action) underlying PPA
3. [`domain-packs/education/cfg/runtime-config.yaml`](domain-packs/education/cfg/runtime-config.yaml) — how a domain owns its runtime behavior
4. [`domain-packs/education/modules/algebra-level-1/`](domain-packs/education/modules/algebra-level-1/) — a complete worked domain pack (education)
5. [`domain-packs/agriculture/modules/operations-level-1/`](domain-packs/agriculture/modules/operations-level-1/) — a sensor/field operations domain pack
6. [`examples/README.md`](examples/README.md) — full interaction traces
7. [`docs/7-concepts/slm-compute-distribution.md`](docs/7-concepts/slm-compute-distribution.md) — SLM three-role architecture, weight routing, provider backends, fallback guarantees
8. [`docs/7-concepts/novel-synthesis-framework.md`](docs/7-concepts/novel-synthesis-framework.md) — two-key verification gate, model benchmarking via CTL telemetry

---

## Conformance

All domain packs and implementations must conform to [`standards/lumina-core-v1.md`](standards/lumina-core-v1.md). See [`docs/5-standards/`](docs/5-standards/README.md) for the full specification index.

---

## Disclaimer

Lumina OS is research/experimental software provided AS-IS under Apache 2.0 with NO WARRANTIES. No part of this project is certified for safety-critical, high-stakes, or regulated use (including with minors) without thorough independent validation.

The engine provides structural accountability (D.S.A. contracts, CTL traces) but does **not** replace human oversight, professional judgment, or legal compliance. Ultimate accountability for any deployment sits with the human Domain Authority at each level, never the AI or the engine.

Domain packs that involve vulnerable populations (children, patients, etc.) include additional warnings and must be independently reviewed before any real-world deployment. See individual domain pack READMEs for domain-specific disclaimers.

---

*Last updated: 2026-03-13*
