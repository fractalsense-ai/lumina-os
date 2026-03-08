# Education Domain — Domain Lib

**Version:** 1.0.0  
**Status:** Active  
**Last updated:** 2026-03-03

---

## Overview

This directory contains the education domain's **domain lib** — passive specification documents that define the estimators feeding the compressed state for education-domain sessions.

These files are **reference specifications**, not executable code. They describe data models, threshold tables, estimation algorithms, and decision criteria that the orchestrator and LLM read as context. For active, callable tools that accept input and produce deterministic output, see the [`tool-adapters/`](../algebra-level-1/tool-adapters/) directory within each subject-level pack.

Each component defines a deterministic heuristic that takes structured evidence as input and produces an updated state value. No ML models are used.

---

## Components in This Domain Lib

| Component | File | Description |
|-----------|------|-------------|
| Compressed State Estimators | [`compressed-state-estimators.md`](compressed-state-estimators.md) | Affect (SVA), mastery, challenge, uncertainty, and ZPD window estimators |
| ZPD Monitor | [`zpd-monitor-spec-v1.md`](zpd-monitor-spec-v1.md) | Zone of Proximal Development drift detection and decision tier |
| Fatigue Estimator | [`fatigue-estimation-spec-v1.md`](fatigue-estimation-spec-v1.md) | Cognitive fatigue estimation from structural signals |

---

## Why This Domain Lib Is Education-Specific

These components are tightly coupled to educational concepts:

- **ZPD (Zone of Proximal Development)** — Vygotsky's model of the optimal challenge band for learning. Meaningful only in educational contexts.
- **Affect (SVA — Salience, Valence, Arousal)** — Interpreted here in terms of learning engagement and emotional response to academic tasks.
- **Cognitive Fatigue** — Estimated from academic performance signals (hint use, error rate, response latency in a task context).

A farm domain would have entirely different domain-lib components — soil moisture drift, yield prediction deviation, equipment health status. A medical domain might use vital-sign trend monitors and alert-fatigue estimators.

---

## Domain Lib Contract

Each component in this domain lib must:

1. Accept **structured evidence** as input — never raw conversation content
2. Produce **deterministic output** given the same inputs
3. Be **readable by the Domain Authority** — no black-box logic
4. Feed its output into the **education domain subject state schema** (`domain-packs/education/schemas/compressed-state-schema-v1.json`)

---

## References

- [`../../../standards/domain-state-lib-contract-v1.md`](../../../standards/domain-state-lib-contract-v1.md) — universal domain-lib spec
- [`../schemas/compressed-state-schema-v1.json`](../schemas/compressed-state-schema-v1.json) — education domain subject state schema
- [`../reference-implementations/zpd-monitor-v0.2.py`](../reference-implementations/zpd-monitor-v0.2.py) — Python reference implementation
