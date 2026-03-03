# Domain Sensor Array — V1

**Version:** 1.0.0  
**Status:** Active  
**Last updated:** 2026-03-03

---

## Overview

Every domain in Project Lumina defines its own **sensor array** — the set of estimators that feed its compressed state. The D.S.A. engine is universal; the sensors are domain-specific.

This document defines the contract that all domain sensor arrays must conform to and explains why sensor arrays are separated from the universal engine.

---

## Why Sensor Arrays Are Domain-Specific

The **State** pillar of the D.S.A. Framework is a compressed, mathematically structured profile of the entity being observed. The *structure* of that profile is universal (defined by `compressed-state-schema-v1.json`), but the *sensors that populate it* depend entirely on the domain.

| Domain | Example Sensors |
|--------|----------------|
| **Education** | ZPD monitor, affect estimator (SVA), cognitive fatigue estimator |
| **Agriculture** | Soil-health drift monitor, equipment-status estimator, weather-deviation sensor |
| **Medicine** | Vital-sign trend monitor, alert-fatigue estimator, treatment-response sensor |

A ZPD monitor is education's equivalent of a soil-health monitor in agriculture. They both answer the question: *"Is the entity currently operating within its optimal functioning band?"* — but the signals, thresholds, and interpretations are entirely domain-specific.

---

## Sensor Array Contract

Every domain sensor array must conform to the following requirements:

### 1. Structured Evidence Only

Sensors must accept **structured evidence** as input — never raw conversation content or free text. Evidence is produced by tool adapters and the domain's evidence summary pipeline.

### 2. Deterministic Output

Given the same inputs, a sensor must produce the same output. No probabilistic or ML-based sensors are permitted without explicit Domain Authority approval and documentation.

### 3. Human-Readable Logic

Sensor update rules must be expressible in plain arithmetic or simple conditionals that the Domain Authority can read, understand, and audit. Opacity is a governance risk.

### 4. Compressed State Conformance

Sensor outputs must map to fields defined in [`compressed-state-schema-v1.json`](compressed-state-schema-v1.json). Domains may leave fields unpopulated if they are not applicable, but must not define fields outside the schema without a schema version bump.

### 5. Sensor Array Directory

Each domain pack must include a `sensors/` directory containing:
- A `README.md` listing the sensors and their purpose
- One specification file per sensor

---

## Universal Structure, Domain-Specific Population

The compressed state schema defines the *fields* that may be populated. Which fields are populated and what thresholds matter is domain-specific:

| Schema Field | Education | Agriculture | Medicine |
|--------------|-----------|-------------|---------|
| `salience` | Engagement/focus | Operator attention | Patient compliance |
| `valence` | Emotional tone toward task | N/A (not applicable) | Patient affect |
| `arousal` | Activation level | N/A | Physiological activation |
| `mastery` | Per-skill mastery | Per-crop/equipment proficiency | Per-protocol proficiency |
| `challenge` | Task difficulty vs. ZPD | Task complexity vs. operator skill | Case complexity vs. clinician level |
| `uncertainty` | Orchestrator uncertainty | Prediction model uncertainty | Diagnostic uncertainty |

Domains that do not use a field leave it at its default value and do not configure standing orders that respond to it.

---

## Sensor Array Lifecycle

Sensor specifications are versioned independently of the domain pack itself:

```
Draft → Validated → Committed (CTL) → Active
                                         ↓
                                    New Version
                                         ↓
                                    Validated → Committed → Active
```

A sensor update that changes thresholds or update rules is a **Minor** version bump. A sensor update that changes the output schema is a **Major** version bump.

---

## References

- [`compressed-state-schema-v1.json`](compressed-state-schema-v1.json) — universal compressed state schema
- [`../domain-packs/education/sensors/README.md`](../domain-packs/education/sensors/README.md) — education domain sensor array
- [`lumina-core-v1.md`](lumina-core-v1.md) — core conformance spec (Section 3: Compressed State Conformance)
