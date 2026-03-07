# Project Lumina

**Bounded, accountable AI orchestration — architecture specifications, modular runtime, and reference implementations.**

---

## Vision

Project Lumina builds AI orchestration systems that are **domain-bounded**, **measurement-not-surveillance**, and **accountable at every level**. Every interaction is governed by an explicit Domain Physics ruleset, every decision is traceable via the Causal Trace Ledger, and every authority level is clearly defined.

The core engine is **fully domain-agnostic**. All domain-specific behavior — prompts, state models, evidence extraction, tool adapters, and deterministic templates — lives in self-contained **domain packs** that are loaded at runtime via a single config file. No server code changes are needed to switch domains.

---

## The D.S.A. Engine & Traceable Accountability

Project Lumina operates on **Dynamic Prompt Contracts**. Each turn follows a strict, auditable sequence:

1. **Domain knowledge**
2. **Context (state)**
3. **Intent (action)**
4. **Proposal (LLM)**
5. **Verification (tools + invariants)**
6. **Commit / escalate**
7. **Trace (CTL)**

The D.S.A. model is the contract materialization of this sequence:

- **D (Domain)**: domain rules, invariants, standing orders, escalation triggers, and artifacts authored by a Domain Authority.
- **S (State)**: compact, mutable session state updated from structured evidence.
- **A (Action)**: bounded intended action produced by the orchestrator from Domain + State.

The orchestrator assembles a dynamic prompt contract from these components. The LLM is constrained to that contract, verification checks are applied, and the resulting decision is committed or escalated and written to CTL.

See [`specs/dsa-framework-v1.md`](specs/dsa-framework-v1.md) for the full specification.

### Tracing and Diagnosing AI Deviations via the Causal Trace Ledger (CTL)

Because the AI is handed a strict D.S.A. contract rather than a generic prompt, deviations become **structurally traceable**. The contract defines exactly what the AI was authorized to do — any output outside those bounds is an identifiable violation, not an ambiguous mistake.

This does not prevent hallucinations from occurring — it makes them **diagnosable**. The D.S.A. stack and the CTL together create the audit trail needed to identify what went wrong, trace the causal chain of events that led to a deviation, and improve the system so the same failure is less likely to recur.

The **CTL** is the append-only, cryptographic accountability layer that makes this traceability permanent:

- **Diagnosis, Not Surveillance** — the ledger never stores raw chat transcripts or PII at rest. It stores only hashes and structured decision telemetry.
- **Trace Events** — every decision is logged as a `TraceEvent` capturing the exact `event_type`, the structured `evidence_summary`, and the specific `decision`.
- **Hard Escalations** — if the AI violates a critical invariant or cannot stabilize the session, it halts and generates an `EscalationRecord` with the exact `trigger` and `decision_trail_hashes`.

See [`standards/causal-trace-ledger-v1.md`](standards/causal-trace-ledger-v1.md) and [`ledger/`](ledger/) for schemas.

---

## Modular Runtime Architecture

The core engine (`lumina-api-server.py`) is a **generic runtime host** that contains zero domain-specific logic. All domain behavior is loaded dynamically at startup from a **runtime config** owned by each domain pack.

### How it works

```
                  ┌────────────────────────────────────┐
                  │     lumina-api-server.py            │
                  │     (domain-agnostic host)          │
                  │                                     │
                  │  ┌─────────────┐  ┌──────────────┐ │
  LUMINA_RUNTIME  │  │  runtime    │  │  dsa-        │ │
  _CONFIG_PATH ──►│  │  _loader.py │─►│  orchestrator│ │
                  │  └──────┬──────┘  └──────────────┘ │
                  └─────────┼──────────────────────────┘
                            │ loads at startup
              ┌─────────────┼──────────────────────┐
              ▼             ▼                      ▼
     ┌─────────────┐ ┌─────────────┐     ┌──────────────┐
     │ prompts/    │ │ runtime-    │     │ tool-        │
     │ system +    │ │ adapters.py │     │ adapters.py  │
     │ evidence    │ │ state_build │     │ calculator   │
     │ extraction  │ │ domain_step │     │ sub_checker  │
     └─────────────┘ │ extract_ev  │     └──────────────┘
                     └─────────────┘
                     domain-packs/<domain>/
```

A domain pack's `runtime-config.yaml` declares:
- **Prompt files** — global base prompt + domain system override + evidence extraction prompt
- **Default task spec** — domain-specific task parameters and skill targets
- **Domain step parameters** — thresholds and windows for the domain's state library
- **Evidence defaults** — fallback evidence fields for the domain
- **Deterministic templates** — per-action response templates for testing without an LLM
- **Tool call policies** — action-to-tool mappings with template-interpolated payloads
- **Adapters** — Python module paths + callable names for state builder, domain step, evidence extractor, and tool functions

### Swapping domains

No server code changes required. Set one environment variable:

```bash
# Education domain
export LUMINA_RUNTIME_CONFIG_PATH="domain-packs/education/runtime-config.yaml"

# Agriculture domain
export LUMINA_RUNTIME_CONFIG_PATH="domain-packs/agriculture/runtime-config.yaml"
```

### In-turn tool mediation

Tool calls during a turn are **policy-driven**, not hardcoded. Each domain's `runtime-config.yaml` maps resolved actions to tool adapter calls with template-interpolated payloads:

```yaml
tool_call_policies:
  request_verification_retry:
    -
      tool_id: substitution_checker
      payload:
        left_value: "{evidence.left_value}"
        right_value: "{evidence.right_value}"
```

The engine resolves `{evidence.left_value}` from the turn's evidence dict, calls the tool adapter, and passes the result to the LLM or deterministic response.

---

## Governance Model

Project Lumina uses a **fractal authority structure**: every level is a Domain Authority for its own scope, and a Meta Authority for levels below. This is a generic pattern that applies to any domain.

```
Macro Authority    (e.g., Corporate Policy / Hospital Admin / School Board)
    ↓ Meta Authority for ↓
Meso Authority     (e.g., Site Manager / Dept Head / Curriculum Director)
    ↓ Meta Authority for ↓
Micro Authority    (e.g., Operator / Lead Physician / Teacher)
    ↓ Meta Authority for ↓
Subject/Target     (e.g., Environment / Patient / Subject)
```

Education is one instantiation of this pattern (Administration → Department Head → Teacher → Student). Agriculture (Corporate Policy → Site Manager → Operator → Environment) and medical (Hospital Admin → Department Head → Physician → Patient) are others.

Each level:
- Authors its own **Domain Physics** (YAML → JSON, version-controlled)
- Retrieves context from the level above via **RAG contracts**
- Is held accountable via the **Causal Trace Ledger (CTL)**
- Can escalate upward when the system cannot stabilize

See [`GOVERNANCE.md`](GOVERNANCE.md) for governance policies and [`governance/`](governance/) for templates and role definitions.

---

## Key Principles

Root-level principles are **universal engine principles only**. Domain-specific principles, rules, state semantics, and domain physics are owned by each domain pack under [`domain-packs/`](domain-packs/).

See [`specs/principles-v1.md`](specs/principles-v1.md) for universal principles and [`domain-packs/README.md`](domain-packs/README.md) for domain-owned policy structure.

### Universal Core Engine Principles (1–7)

These apply to every Project Lumina interaction, regardless of domain:

1. **Domain-bounded operation** — the AI may not act outside what the Domain Physics authorizes
2. **Measurement, not surveillance** — structured telemetry only; no transcript storage
3. **Domain Authority is the authority** — AI assists, it does not replace the human expert
4. **Append-only accountability** — the ledger is never modified, only extended
5. **Do not expand scope without drift justification** — scope creep is a violation
6. **Pseudonymity by default** — the AI layer does not know who the entity is; pseudonymous tokens only
7. **Bounded drift probing** — one bounded probe per drift detection cycle; avoid multi-probe drift inference loops

Domain-specific principles are intentionally not defined at root. Each domain pack declares and versions its own principles in its own directory.

---

## Repository Structure

```
project-lumina/
├── README.md                          ← this file
├── GOVERNANCE.md                      ← fractal authority + nested governance policy
├── LICENSE
├── standards/                         ← universal engine specs (all domains)
│   ├── lumina-core-v1.md
│   ├── causal-trace-ledger-v1.md
│   ├── domain-physics-schema-v1.json
│   ├── domain-state-lib-contract-v1.md
│   ├── prompt-contract-schema-v1.json
│   └── tool-adapter-schema-v1.json
├── specs/                             ← detailed architecture specifications
│   ├── dsa-framework-v1.md
│   ├── principles-v1.md
│   ├── global-system-prompt-v1.md     ← root prompt (domain-agnostic base)
│   ├── orchestrator-system-prompt-v1.md
│   ├── domain-profile-spec-v1.md
│   ├── memory-spec-v1.md
│   ├── audit-log-spec-v1.md
│   ├── reports-spec-v1.md
│   └── evaluation-harness-v1.md
├── governance/                        ← policy templates and role definitions
│   ├── meta-authority-policy-template.yaml
│   ├── domain-authority-roles.md
│   └── audit-and-rollback.md
├── retrieval/                         ← RAG layer contracts and schemas
│   ├── rag-contracts.md
│   └── retrieval-index-schema-v1.json
├── ledger/                            ← CTL JSON schemas
│   ├── causal-trace-ledger-schema-v1.json
│   ├── commitment-record-schema.json
│   ├── trace-event-schema.json
│   └── escalation-record-schema.json
├── domain-packs/                      ← domain-specific everything
│   ├── README.md
│   ├── education/                     ← complete education domain pack
│   │   ├── README.md
│   │   ├── runtime-config.yaml        ← runtime ownership surface
│   │   ├── prompts/                   ← domain-owned prompt files
│   │   │   ├── domain-system-override.md
│   │   │   └── evidence-extraction.md
│   │   ├── schemas/
│   │   │   ├── compressed-state-schema-v1.json
│   │   │   └── student-profile-schema-v1.json
│   │   ├── domain-lib/                ← state lib components (ZPD, affect, fatigue)
│   │   │   ├── README.md
│   │   │   ├── compressed-state-estimators.md
│   │   │   ├── zpd-monitor-spec-v1.md
│   │   │   └── fatigue-estimation-spec-v1.md
│   │   ├── world-sim/                 ← consent + world simulation (domain-specific)
│   │   │   ├── magic-circle-consent-v1.md
│   │   │   ├── world-sim-spec-v1.md
│   │   │   └── artifact-and-mastery-spec-v1.md
│   │   ├── reference-implementations/
│   │   │   ├── runtime-adapters.py    ← state builder, domain step, evidence extractor
│   │   │   ├── tool-adapters.py       ← calculator, substitution checker
│   │   │   ├── zpd-monitor-v0.2.py
│   │   │   └── zpd-monitor-demo.py
│   │   └── algebra-level-1/           ← specific domain pack instance
│   │       ├── domain-physics.yaml / .json
│   │       ├── prompt-contract-schema.json
│   │       ├── tool-adapters/
│   │       ├── student-profile-template.yaml
│   │       ├── example-student-alice.yaml
│   │       └── CHANGELOG.md
│   └── agriculture/                   ← agriculture domain pack (domain-swap proof)
│       ├── README.md
│       ├── runtime-config.yaml
│       ├── prompts/
│       │   ├── domain-system-override.md
│       │   └── evidence-extraction.md
│       ├── reference-implementations/
│       │   └── runtime-adapters.py
│       └── operations-level-1/
│           ├── domain-physics.json
│           └── example-subject.yaml
├── reference-implementations/         ← core D.S.A. engine (domain-agnostic)
│   ├── README.md
│   ├── lumina-api-server.py           ← generic runtime host (FastAPI)
│   ├── runtime_loader.py             ← config loader + adapter resolver
│   ├── dsa-orchestrator.py            ← D.S.A. orchestrator engine
│   ├── dsa-orchestrator-demo.py       ← standalone orchestrator demo
│   ├── ctl-commitment-validator.py    ← CTL hash-chain validator
│   ├── yaml-loader.py                ← minimal YAML parser (zero deps)
│   ├── yaml-to-json-converter.py
│   └── run-preintegration-scenarios.ps1 ← deterministic regression test suite
└── examples/                          ← worked interaction examples
    ├── README.md
    ├── causal-learning-trace-example.json
    └── escalation-example-packet.yaml
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
    "evidence_override": {
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

Then start the server and send requests without `deterministic_response` or `evidence_override`.

### Run the regression test suite

```powershell
# PowerShell (from repo root, with server running)
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\reference-implementations\run-preintegration-scenarios.ps1 -BaseUrl "http://localhost:8000"
```

Tests: health check, stable turn (no escalation), major drift (escalation), CTL hash-chain integrity, EscalationRecord presence.

### Explore the architecture

1. Read [`specs/principles-v1.md`](specs/principles-v1.md) — understand the non-negotiables
2. Read [`specs/dsa-framework-v1.md`](specs/dsa-framework-v1.md) — understand the framework
3. Browse [`domain-packs/education/runtime-config.yaml`](domain-packs/education/runtime-config.yaml) — see how a domain owns its runtime behavior
4. Browse [`domain-packs/education/algebra-level-1/`](domain-packs/education/algebra-level-1/) — a complete worked domain pack
5. Run [`domain-packs/education/reference-implementations/zpd-monitor-demo.py`](domain-packs/education/reference-implementations/zpd-monitor-demo.py) — see the ZPD monitor in action
6. Run [`reference-implementations/dsa-orchestrator-demo.py`](reference-implementations/dsa-orchestrator-demo.py) — see the full D.S.A. orchestrator loop
7. Read [`examples/README.md`](examples/README.md) — walk through a full interaction trace

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/health` | Health check — returns `{"status": "ok", "provider": "..."}` |
| `POST` | `/api/chat` | Process a message through the D.S.A. pipeline |
| `POST` | `/api/tool/{tool_id}` | Invoke a domain tool adapter directly |

### `POST /api/chat` request body

```json
{
  "session_id": "optional-uuid",
  "message": "user input text",
  "deterministic_response": false,
  "evidence_override": null
}
```

### `POST /api/chat` response body

```json
{
  "session_id": "uuid",
  "response": "LLM or deterministic response text",
  "action": "task_presentation",
  "prompt_type": "task_presentation",
  "escalated": false,
  "tool_results": []
}
```

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `LUMINA_RUNTIME_CONFIG_PATH` | **Yes** | — | Path to domain `runtime-config.yaml` (relative to repo root) |
| `LUMINA_LLM_PROVIDER` | No | `openai` | LLM backend: `openai` or `anthropic` |
| `LUMINA_OPENAI_MODEL` | No | `gpt-4o` | OpenAI model name |
| `LUMINA_ANTHROPIC_MODEL` | No | `claude-sonnet-4-20250514` | Anthropic model name |
| `LUMINA_PORT` | No | `8000` | Server port |
| `OPENAI_API_KEY` | For live | — | OpenAI API key |
| `ANTHROPIC_API_KEY` | For live | — | Anthropic API key |

---

## Standards Conformance

All domain packs and implementations must conform to:
- [`standards/lumina-core-v1.md`](standards/lumina-core-v1.md) — top-level conformance spec
- [`standards/domain-physics-schema-v1.json`](standards/domain-physics-schema-v1.json) — domain pack schema
- [`standards/domain-state-lib-contract-v1.md`](standards/domain-state-lib-contract-v1.md) — domain-lib adapter contract
- [`standards/causal-trace-ledger-v1.md`](standards/causal-trace-ledger-v1.md) — CTL protocol

---

## Disclaimer

Project Lumina is research/experimental software provided AS-IS under Apache 2.0 with NO WARRANTIES. No part of this project is certified for safety-critical, high-stakes, or regulated use (including with minors) without thorough independent validation.

The engine provides structural accountability (D.S.A. contracts, CTL traces) but does **not** replace human oversight, professional judgment, or legal compliance. Ultimate accountability for any deployment sits with the human Domain Authority at each level, never the AI or the engine.

Domain packs that involve vulnerable populations (children, patients, etc.) include additional warnings and must be independently reviewed before any real-world deployment. See individual domain pack READMEs for domain-specific disclaimers.

---

*Last updated: 2026-03-06*
