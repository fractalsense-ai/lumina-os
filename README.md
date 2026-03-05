# Project Lumina

**Bounded, accountable AI orchestration — architecture specifications and reference implementations.**

---

## Vision

Project Lumina builds AI orchestration systems that are **domain-bounded**, **measurement-not-surveillance**, and **accountable at every level**. Every interaction is governed by an explicit Domain Physics ruleset, every decision is traceable via the Causal Trace Ledger, and every authority level is clearly defined.

---

## The D.S.A. Engine & Traceable Accountability

Project Lumina operates on **Dynamic Prompt Contracts** — every AI interaction is strictly bound by the D.S.A. Framework. Rather than issuing a generic prompt, the orchestrator assembles a contract from three pillars, and the AI may only act within what that contract authorizes.

| Pillar | Name | Description |
|--------|------|-------------|
| **D** | **Domain (The Rules)** | The immutable ruleset authored by a human Domain Authority (e.g., a teacher, doctor, or coach). Defines strict invariants, standing orders, artifacts, and escalation triggers. |
| **S** | **State (The Context)** | The mutable, mathematically compressed snapshot of the target entity at the time of the request. It contains the real-time variables, historical telemetry, and active status required by the orchestrator to make a bounded decision. |
| **A** | **Action (The Boundary)** | The specific, highly constrained task the orchestrator is permitted to execute, based exclusively on the active Domain and State. The AI may only do what the Domain authorizes. |

The Domain is authored by the **Domain Authority** (the human expert: teacher, doctor, coach). The State is updated incrementally from structured evidence. The Action layer is bounded: it may only do what the Domain authorizes.

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

## Governance Model

Project Lumina uses a **fractal authority structure**: every level is a Domain Authority for its own scope, and a Meta Authority for levels below. This is a generic pattern that applies to any domain.

```
Macro Authority    (e.g., Corporate Policy / Hospital Admin / School Board)
    ↓ Meta Authority for ↓
Meso Authority     (e.g., Site Manager / Dept Head / Curriculum Director)
    ↓ Meta Authority for ↓
Micro Authority    (e.g., Operator / Lead Physician / Teacher)
    ↓ Meta Authority for ↓
Subject/Target     (e.g., Environment / Patient / Learner)
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

Principles are organized in two tiers. See [`specs/principles-v1.md`](specs/principles-v1.md) for the full specification.

### Universal Core Engine Principles (1–7)

These apply to every Project Lumina interaction, regardless of domain:

1. **Domain-bounded operation** — the AI may not act outside what the Domain Physics authorizes
2. **Measurement, not surveillance** — structured telemetry only; no transcript storage
3. **Domain Authority is the authority** — AI assists, it does not replace the human expert
4. **Append-only accountability** — the ledger is never modified, only extended
5. **Do not expand scope without drift justification** — scope creep is a violation
6. **Pseudonymity by default** — the AI layer does not know who the entity is; pseudonymous tokens only
7. **Minimal probing** — one probe per drift detection; do not interrogate subjects

### Domain-Specific Principles (8–10)

These principles apply only when activated by a specific domain pack's configuration (see the Education Domain Pack below for an example). Once active, the orchestrator enforces them with the exact same rigor as universal principles:

8. **Consent and boundaries first** — the magic circle must be established before any session begins *(active when `requires_consent: true` is declared in the domain pack)*
9. **Interests affect generation, never grading** — subject preferences improve immersion; they must not influence assessment *(activates in domains where subject profiles include preference data)*
10. **Fade support as self-correction grows** — scaffolding reduces as mastery increases *(applies to domains with mastery tracking / drift monitoring)*

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
│   ├── domain-sensor-array-v1.md      ← sensor array contract
│   ├── prompt-contract-schema-v1.json
│   └── tool-adapter-schema-v1.json
├── specs/                             ← detailed architecture specifications
│   ├── dsa-framework-v1.md
│   ├── principles-v1.md
│   ├── domain-profile-spec-v1.md
│   ├── magic-circle-consent-v1.md
│   ├── world-sim-spec-v1.md
│   ├── artifact-and-mastery-spec-v1.md
│   ├── memory-spec-v1.md
│   ├── audit-log-spec-v1.md
│   ├── reports-spec-v1.md
│   ├── evaluation-harness-v1.md
│   └── orchestrator-system-prompt-v1.md
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
│   ├── education/
│   │   ├── schemas/                   ← education-domain JSON schemas
│   │   │   ├── compressed-state-schema-v1.json
│   │   │   └── student-profile-schema-v1.json
│   │   ├── sensors/                   ← education-domain sensor array (ZPD, affect, fatigue)
│   │   │   ├── README.md
│   │   │   ├── compressed-state-estimators.md
│   │   │   ├── zpd-monitor-spec-v1.md
│   │   │   └── fatigue-estimation-spec-v1.md
│   │   ├── reference-implementations/ ← education-domain Python reference code
│   │   │   ├── README.md
│   │   │   ├── zpd-monitor-v0.2.py
│   │   │   └── zpd-monitor-demo.py
│   │   └── algebra-level-1/           ← specific domain pack
│   │       ├── domain-physics.yaml
│   │       ├── domain-physics.json
│   │       ├── tool-adapters/
│   │       │   ├── calculator-adapter-v1.yaml
│   │       │   └── substitution-checker-adapter-v1.yaml
│   │       ├── student-profile-template.yaml
│   │       ├── example-student-alice.yaml
│   │       ├── prompt-contract-schema.json
│   │       └── CHANGELOG.md
│   └── agriculture/
│       └── README.md
├── reference-implementations/         ← core D.S.A. engine Python reference code
│   ├── README.md
│   ├── yaml-to-json-converter.py
│   ├── ctl-commitment-validator.py
│   ├── dsa-orchestrator.py
│   └── dsa-orchestrator-demo.py
└── examples/                          ← worked interaction examples
    ├── README.md
    ├── causal-learning-trace-example.json
    └── escalation-example-packet.yaml
```

---

## Quick Start

1. Read [`specs/principles-v1.md`](specs/principles-v1.md) — understand the non-negotiables
2. Read [`specs/dsa-framework-v1.md`](specs/dsa-framework-v1.md) — understand the framework
3. Browse [`domain-packs/education/algebra-level-1/`](domain-packs/education/algebra-level-1/) — a complete worked domain
4. Run [`domain-packs/education/reference-implementations/zpd-monitor-demo.py`](domain-packs/education/reference-implementations/zpd-monitor-demo.py) — see the education domain's ZPD monitor in action
5. Run [`reference-implementations/dsa-orchestrator-demo.py`](reference-implementations/dsa-orchestrator-demo.py) — see the full D.S.A. orchestrator loop in action
6. Read [`examples/README.md`](examples/README.md) — walk through a full interaction loop

---

## Standards Conformance

All domain packs and implementations must conform to:
- [`standards/lumina-core-v1.md`](standards/lumina-core-v1.md) — top-level conformance spec
- [`standards/domain-physics-schema-v1.json`](standards/domain-physics-schema-v1.json) — domain pack schema
- [`standards/causal-trace-ledger-v1.md`](standards/causal-trace-ledger-v1.md) — CTL protocol

---

*Last updated: 2026-03-04*
