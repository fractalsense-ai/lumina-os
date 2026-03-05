# Education Domain — Reference Implementations

This directory contains Python reference implementations for the **education domain** sensors and utilities. These are education-specific and are separate from the core D.S.A. engine implementations in [`../../../reference-implementations/`](../../../reference-implementations/).

---

## Contents

| File | Description |
|------|-------------|
| `zpd-monitor-v0.2.py` | ZPD monitor: compressed learner state + affect + ZPD drift detection |
| `zpd-monitor-demo.py` | Worked demo of the ZPD monitor running a simulated algebra session |

---

## Requirements

Python 3.10+ is required. No external dependencies beyond the standard library.

---

## Quick Start

### Run the ZPD monitor demo

```bash
python domain-packs/education/reference-implementations/zpd-monitor-demo.py
```

---

## Relationship to Specs

| Implementation | Spec |
|---------------|------|
| `zpd-monitor-v0.2.py` | [`../sensors/zpd-monitor-spec-v1.md`](../sensors/zpd-monitor-spec-v1.md) |
| `zpd-monitor-v0.2.py` | [`../sensors/compressed-state-estimators.md`](../sensors/compressed-state-estimators.md) |
| `zpd-monitor-v0.2.py` | [`../schemas/compressed-state-schema-v1.json`](../schemas/compressed-state-schema-v1.json) |
