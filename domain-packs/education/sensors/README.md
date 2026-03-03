# Education Domain — Sensor Array

**Version:** 1.0.0  
**Status:** Active  
**Last updated:** 2026-03-03

---

## Overview

This directory contains the education domain's **sensor array** — the set of estimators that feed the compressed state for education-domain sessions.

Each sensor is a deterministic heuristic that takes structured evidence as input and produces an updated state value. No ML models are used.

---

## Sensors in This Array

| Sensor | File | Description |
|--------|------|-------------|
| Compressed State Estimators | [`compressed-state-estimators.md`](compressed-state-estimators.md) | Affect (SVA), mastery, challenge, uncertainty, and ZPD window estimators |
| ZPD Monitor | [`zpd-monitor-spec-v1.md`](zpd-monitor-spec-v1.md) | Zone of Proximal Development drift detection and decision tier |
| Fatigue Estimator | [`fatigue-estimation-spec-v1.md`](fatigue-estimation-spec-v1.md) | Cognitive fatigue estimation from structural signals |

---

## Why These Sensors Are Education-Specific

These sensors are tightly coupled to educational concepts:

- **ZPD (Zone of Proximal Development)** — Vygotsky's model of the optimal challenge band for learning. Meaningful only in educational contexts.
- **Affect (SVA — Salience, Valence, Arousal)** — Interpreted here in terms of learning engagement and emotional response to academic tasks.
- **Cognitive Fatigue** — Estimated from academic performance signals (hint use, error rate, response latency in a task context).

A farm domain would have entirely different sensors — soil moisture drift, yield prediction deviation, equipment health status. A medical domain might use vital-sign trend monitors and alert-fatigue estimators.

---

## Sensor Array Contract

Each sensor in this array must:

1. Accept **structured evidence** as input — never raw conversation content
2. Produce **deterministic output** given the same inputs
3. Be **readable by the Domain Authority** — no black-box logic
4. Feed its output into the **compressed state schema** (`standards/compressed-state-schema-v1.json`)

---

## References

- [`../../../standards/domain-sensor-array-v1.md`](../../../standards/domain-sensor-array-v1.md) — universal sensor array spec
- [`../../../standards/compressed-state-schema-v1.json`](../../../standards/compressed-state-schema-v1.json) — compressed state schema
- [`../../../reference-implementations/zpd-monitor-v0.2.py`](../../../reference-implementations/zpd-monitor-v0.2.py) — Python reference implementation
