# Domain State Lib Contract — V1

**Version:** 1.0.0  
**Status:** Active  
**Last updated:** 2026-03-03

---

## Overview

Every domain in Project Lumina defines its own **domain lib** — the set of deterministic estimators and checks that feed its compressed state. The D.S.A. engine is universal; domain libs are domain-specific.

This document defines the contract that all domain libs must conform to and explains why they are separated from the universal engine.

---

## Why Domain Libs Are Domain-Specific

The **State** pillar of the D.S.A. Framework is a compressed, mathematically structured profile of the entity being observed. Each domain pack defines its own subject state schema in its `schemas/` directory; the *domain lib that populates it* depends entirely on the domain.

| Domain | Example Domain Lib Components |
|--------|----------------|
| **Education** | ZPD monitor, affect estimator (SVA), cognitive fatigue estimator |
| **Agriculture** | Soil-health drift monitor, equipment-status estimator, weather-deviation checks |
| **Medicine** | Vital-sign trend monitor, alert-fatigue estimator, treatment-response checks |

A ZPD monitor is education's equivalent of a soil-health monitor in agriculture. They both answer the question: *"Is the entity currently operating within its optimal functioning band?"* — but the signals, thresholds, and interpretations are entirely domain-specific.

---

## Domain Lib Contract

Every domain lib must conform to the following requirements:

### 1. Structured Evidence Only

Domain-lib components must accept **structured evidence** as input — never raw conversation content or free text. Evidence is produced by tool adapters and the domain's evidence summary pipeline.

### 2. Deterministic Output

Given the same inputs, a domain lib must produce the same output. No probabilistic or ML-based estimators are permitted without explicit Domain Authority approval and documentation.

### 3. Human-Readable Logic

Domain-lib update rules must be expressible in plain arithmetic or simple conditionals that the Domain Authority can read, understand, and audit. Opacity is a governance risk.

### 4. Subject State Schema Conformance

Domain-lib outputs must map to fields defined in the domain's own subject state schema, located in the domain pack's `schemas/` directory (e.g., [`../domain-packs/education/schemas/compressed-state-schema-v1.json`](../domain-packs/education/schemas/compressed-state-schema-v1.json) for the education domain). Domains may leave fields unpopulated if they are not applicable, but must not define fields outside their schema without a schema version bump.

### 5. Domain Lib Directory

Each domain pack must include a state-estimation directory (commonly `sensors/` in legacy packs) containing:
- A `README.md` listing the domain-lib components and their purpose
- One specification file per component

---

## Universal Structure, Domain-Specific Population

The compressed state schema defines the *fields* that may be populated. Which fields are populated and what thresholds matter is domain-specific:

| Schema Field | Education | Agriculture | Medicine |
|--------------|-----------|-------------|---------|
| `salience` | Engagement/focus | Operator attention | Patient compliance |
| `valence` | Emotional tone toward task | N/A (not applicable) | Patient affect |
| `arousal` | Activation level | N/A | Physiological activation |
| `mastery` | Per-skill mastery | Per-crop/equipment proficiency | Per-protocol proficiency |
| `challenge` | Task difficulty vs. operating band | Task complexity vs. operator skill | Case complexity vs. clinician level |
| `uncertainty` | Orchestrator uncertainty | Prediction model uncertainty | Diagnostic uncertainty |

Domains that do not use a field leave it at its default value and do not configure standing orders that respond to it.

---

## Domain Lib Lifecycle

Domain-lib specifications are versioned independently of the domain pack itself:

```
Draft → Validated → Committed (CTL) → Active
                                         ↓
                                    New Version
                                         ↓
                                    Validated → Committed → Active
```

A domain-lib update that changes thresholds or update rules is a **Minor** version bump. A domain-lib update that changes the output schema is a **Major** version bump.

---

## Legacy Terminology

Earlier versions and file paths use `sensor` and `sensor array`. In this repository, those terms are legacy aliases for the domain-lib layer.

---

## References

- [`../domain-packs/education/schemas/compressed-state-schema-v1.json`](../domain-packs/education/schemas/compressed-state-schema-v1.json) — education domain subject state schema (example instantiation)
- [`../domain-packs/education/domain-lib/README.md`](../domain-packs/education/domain-lib/README.md) — education domain lib components
- [`lumina-core-v1.md`](lumina-core-v1.md) — core conformance spec (Section 3: Compressed State Conformance)
