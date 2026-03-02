# Project Lumina

**Bounded, accountable AI orchestration — architecture specifications and reference implementations.**

---

## Vision

Project Lumina builds AI orchestration systems that are **domain-bounded**, **consent-first**, and **accountable without being surveillance**. Every interaction is governed by an explicit Domain Physics ruleset, every decision is traceable via the Casual Trace Ledger, and every authority level is clearly defined.

---

## The D.S.A. Framework

All Project Lumina systems are structured around three pillars:

| Pillar | Name | Description |
|--------|------|-------------|
| **D** | **Domain** | Immutable ruleset — invariants, standing orders, artifacts, escalation triggers |
| **S** | **State** | Mutable learner/actor profile — affect (SVA), mastery, ZPD band, cognitive load |
| **A** | **Action** | Orchestrator — drift detection, minimal probes, grounded responses, escalation |

The Domain is authored by the **Domain Authority** (the human expert: teacher, doctor, coach). The State is updated incrementally from structured evidence. The Action layer is bounded: it may only do what the Domain authorizes.

See [`specs/dsa-framework-v1.md`](specs/dsa-framework-v1.md) for the full specification.

---

## Governance Model

Project Lumina uses a **fractal authority structure**: every level is a Domain Authority for its own scope, and a Meta Authority for levels below.

```
Administration          (Domain Authority for "school policy")
    ↓ Meta Authority for ↓
Department Head         (Domain Authority for "curriculum")
    ↓ Meta Authority for ↓
Teacher                 (Domain Authority for "what's correct in algebra")
    ↓ Meta Authority for ↓
Student                 (Domain Authority for "their own learning state")
```

Each level:
- Authors its own **Domain Physics** (YAML → JSON, version-controlled)
- Retrieves context from the level above via **RAG contracts**
- Is held accountable via the **Casual Trace Ledger (CTL)**
- Can escalate upward when the system cannot stabilize

See [`GOVERNANCE.md`](GOVERNANCE.md) for governance policies and [`governance/`](governance/) for templates and role definitions.

---

## Casual Trace Ledger (CTL)

The CTL is the append-only accountability layer:

- **No transcripts at rest** — stores hashes and structured decision telemetry, not conversation content
- **Diagnosis, not accusation** — records what happened and what the system decided, not raw PII
- Record types: `CommitmentRecord`, `TraceEvent`, `ToolCallRecord`, `OutcomeRecord`, `EscalationRecord`
- Ledger entries are hash-chained; tampering is detectable

See [`standards/casual-trace-ledger-v1.md`](standards/casual-trace-ledger-v1.md) and [`ledger/`](ledger/) for schemas.

---

## Key Principles

1. **Consent and boundaries first** — the magic circle must be established before any session begins
2. **Measurement, not surveillance** — structured telemetry only; no transcript storage
3. **Domain-bounded operation** — the AI may not act outside what the Domain Physics authorizes
4. **Minimal probing** — one probe per drift detection; do not interrogate learners
5. **Domain Authority is the authority** — AI assists, it does not replace the human expert
6. **Append-only accountability** — the ledger is never modified, only extended
7. **Fade support as self-correction grows** — scaffolding reduces as mastery increases
8. **Do not expand scope without drift justification** — scope creep is a violation

See [`specs/principles-v1.md`](specs/principles-v1.md) for the full non-negotiables specification.

---

## Repository Structure

```
project-lumina/
├── README.md                          ← this file
├── GOVERNANCE.md                      ← fractal authority + nested governance policy
├── LICENSE
├── standards/                         ← meta-specs all domains must conform to
│   ├── lumina-core-v1.md
│   ├── casual-trace-ledger-v1.md
│   ├── domain-physics-schema-v1.json
│   ├── student-profile-schema-v1.json
│   ├── compressed-state-schema-v1.json
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
│   └── evaluation-harness-v1.md
├── governance/                        ← policy templates and role definitions
│   ├── meta-authority-policy-template.yaml
│   ├── domain-authority-roles.md
│   └── audit-and-rollback.md
├── retrieval/                         ← RAG layer contracts and schemas
│   ├── rag-contracts.md
│   └── retrieval-index-schema-v1.json
├── state-management/                  ← compressed state, ZPD, fatigue specs
│   ├── compressed-state-estimators.md
│   ├── zpd-monitor-spec-v1.md
│   └── fatigue-estimation-spec-v1.md
├── ledger/                            ← CTL JSON schemas
│   ├── casual-trace-ledger-schema-v1.json
│   ├── commitment-record-schema.json
│   ├── trace-event-schema.json
│   └── escalation-record-schema.json
├── domain-packs/                      ← authored domain packs (YAML → JSON)
│   ├── README.md
│   ├── education/
│   │   └── algebra-level-1/
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
├── reference-implementations/         ← Python reference code
│   ├── README.md
│   ├── zpd-monitor-v0.2.py
│   ├── zpd-monitor-demo.py
│   ├── yaml-to-json-converter.py
│   └── ctl-commitment-validator.py
└── examples/                          ← worked interaction examples
    ├── README.md
    ├── casual-learning-trace-example.json
    └── escalation-example-packet.yaml
```

---

## Quick Start

1. Read [`specs/principles-v1.md`](specs/principles-v1.md) — understand the non-negotiables
2. Read [`specs/dsa-framework-v1.md`](specs/dsa-framework-v1.md) — understand the framework
3. Browse [`domain-packs/education/algebra-level-1/`](domain-packs/education/algebra-level-1/) — a complete worked domain
4. Run [`reference-implementations/zpd-monitor-demo.py`](reference-implementations/zpd-monitor-demo.py) — see the ZPD monitor in action
5. Read [`examples/README.md`](examples/README.md) — walk through a full interaction loop

---

## Standards Conformance

All domain packs and implementations must conform to:
- [`standards/lumina-core-v1.md`](standards/lumina-core-v1.md) — top-level conformance spec
- [`standards/domain-physics-schema-v1.json`](standards/domain-physics-schema-v1.json) — domain pack schema
- [`standards/casual-trace-ledger-v1.md`](standards/casual-trace-ledger-v1.md) — CTL protocol

---

*Last updated: 2026-03-02*
