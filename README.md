# Project Lumina

**Deterministic orchestration around a probabilistic LLM — dynamic prompt contracts, verified outputs, and traceable accountability.**

---

## What Is Project Lumina?

TCP/IP assembles packets from layered protocols — each layer adds its headers, the payload travels through, and checksums verify integrity. Project Lumina does the same thing for LLMs.

The **D.S.A. engine** assembles a **dynamic prompt contract** from layered components — global rules, domain policy, module state, and turn context. Only what is needed is added at each layer. The LLM processes this contract. Tool-adapters verify the output. The Causal Trace Ledger logs the decision.

The LLM is the **processing unit**, not the authority. The chat interface is the **GUI**, not the system. Everything surrounding the probabilistic LLM is **deterministic and verifiable**.

```
┌─────────────────────────────────────────────┐
│  Chat Interface                             │  ← the GUI (human-facing surface)
├─────────────────────────────────────────────┤
│  Global Base Prompt                         │  ← universal rules (like IP headers)
├─────────────────────────────────────────────┤
│  Domain Physics                             │  ← domain-specific policy layer
├─────────────────────────────────────────────┤
│  Module State + Turn Data                   │  ← session-specific context
├─────────────═══════════════════─────────────┤
│  Assembled Prompt Contract                  │  ← the "packet" sent to the LLM
├─────────────────────────────────────────────┤
│  LLM (Processing Unit)                      │  ← probabilistic; never trusted alone
├─────────────────────────────────────────────┤
│  Tool-Adapter Verification                  │  ← deterministic output checking
├─────────────────────────────────────────────┤
│  CTL (Causal Trace Ledger)                  │  ← structured event/error logging
└─────────────────────────────────────────────┘
```

The core engine is **fully domain-agnostic**. All domain-specific behavior — prompts, state models, turn interpretation, tool adapters, and deterministic templates — lives in self-contained **domain packs** loaded at runtime. No server code changes are needed to switch domains.

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

## The D.S.A. Engine

Every turn follows a strict, auditable sequence:

1. **Domain knowledge** — immutable rules authored by the Domain Authority
2. **Context (state)** — mutable session state updated from structured evidence
3. **Intent (action)** — bounded action determined by Domain + State
4. **Proposal (LLM)** — the LLM processes the assembled prompt contract
5. **Verification (tools + invariants)** — tool-adapters check the LLM's reasoning
6. **Commit / escalate** — verified decisions are committed; violations escalate to a human
7. **Trace (CTL)** — the decision is logged to the append-only ledger

The D.S.A. model is the contract materialization of this sequence:

| Pillar | Name | Role | Mutability |
|--------|------|------|------------|
| **D**  | Domain | Rules, invariants, standing orders, escalation triggers | Immutable per session |
| **S**  | State | Compact entity profile updated from structured evidence | Mutable |
| **A**  | Action | Bounded response produced by the orchestrator | Constrained by Domain |

The orchestrator assembles a dynamic prompt contract from these components. The LLM is constrained to that contract, tool-adapters verify its output, and the resulting decision is committed or escalated and written to CTL.

See [`specs/dsa-framework-v1.md`](specs/dsa-framework-v1.md) for the full specification and [`standards/causal-trace-ledger-v1.md`](standards/causal-trace-ledger-v1.md) for CTL protocol.

---

## Modular Runtime

The core engine (`lumina-api-server.py`) is a **generic runtime host** with zero domain-specific logic. Domain behavior is loaded at startup from a domain pack's `runtime-config.yaml`, which declares prompt files, state adapters, tool policies, and deterministic templates.

At startup, the runtime computes policy/prompt hashes and enforces a **policy commitment gate** — the active domain-physics hash must match a committed CTL `CommitmentRecord` before any session can execute. During each turn, provenance lineage hashes are carried in CTL metadata for packet-level auditability without storing transcript content.

### Swapping domains

No server code changes required. Set one environment variable:

```bash
export LUMINA_RUNTIME_CONFIG_PATH="domain-packs/education/runtime-config.yaml"   # Education
export LUMINA_RUNTIME_CONFIG_PATH="domain-packs/agriculture/runtime-config.yaml"  # Agriculture
```

### Tool mediation

Tool calls are **policy-driven**, not hardcoded. Each domain's config maps resolved actions to tool-adapter calls with template-interpolated payloads — the engine resolves variables from interpreted turn-data, calls the tool adapter, and passes verified results back through the pipeline.

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

These seven universal principles apply to every Project Lumina interaction, regardless of domain. They cannot be overridden by any authority level. Domain-specific principles are owned by each domain pack under [`domain-packs/`](domain-packs/).

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
├── front-end/                  ← Vite + React reference UI
├── reference-implementations/  ← core D.S.A. engine (FastAPI, domain-agnostic)
├── domain-packs/               ← domain-specific everything (education, agriculture, ...)
├── specs/                      ← architecture specifications (DSA, principles, prompts)
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

### Run the deterministic demo (no API key needed)

```bash
# 1. Create a virtual environment
python -m venv .venv
source .venv/bin/activate  # or .\.venv\Scripts\activate on Windows

# 2. Install the server dependency
pip install fastapi uvicorn

# 3. Set the runtime config (required — no silent defaults)
export LUMINA_RUNTIME_CONFIG_PATH="domain-packs/education/runtime-config.yaml"

# 4. Start the server
python reference-implementations/lumina-api-server.py

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
python reference-implementations/verify-repo-integrity.py

# Backend unit + integration tests
pip install -r requirements-dev.txt
python -m pytest tests -q

# Full verification flow (integrity + orchestrator + optional API/FE)
# PowerShell:  .\reference-implementations\run-full-verification.ps1
```

See [`docs/1-commands/`](docs/1-commands/README.md) for detailed command references and [`docs/2-syscalls/`](docs/2-syscalls/README.md) for API endpoint documentation.

### Explore the architecture

1. [`specs/principles-v1.md`](specs/principles-v1.md) — the non-negotiables
2. [`specs/dsa-framework-v1.md`](specs/dsa-framework-v1.md) — the D.S.A. framework specification
3. [`domain-packs/education/runtime-config.yaml`](domain-packs/education/runtime-config.yaml) — how a domain owns its runtime behavior
4. [`domain-packs/education/modules/algebra-level-1/`](domain-packs/education/modules/algebra-level-1/) — a complete worked domain pack
5. [`examples/README.md`](examples/README.md) — full interaction traces

---

## Conformance

All domain packs and implementations must conform to [`standards/lumina-core-v1.md`](standards/lumina-core-v1.md). See [`docs/5-standards/`](docs/5-standards/README.md) for the full specification index.

---

## Disclaimer

Project Lumina is research/experimental software provided AS-IS under Apache 2.0 with NO WARRANTIES. No part of this project is certified for safety-critical, high-stakes, or regulated use (including with minors) without thorough independent validation.

The engine provides structural accountability (D.S.A. contracts, CTL traces) but does **not** replace human oversight, professional judgment, or legal compliance. Ultimate accountability for any deployment sits with the human Domain Authority at each level, never the AI or the engine.

Domain packs that involve vulnerable populations (children, patients, etc.) include additional warnings and must be independently reviewed before any real-world deployment. See individual domain pack READMEs for domain-specific disclaimers.

---

*Last updated: 2026-03-10*
