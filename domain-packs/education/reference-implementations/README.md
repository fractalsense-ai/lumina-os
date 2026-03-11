# Education Domain — Reference Implementations

This directory contains Python reference implementations for the **education domain** state-lib components and utilities. These are education-specific and are separate from the core D.S.A. engine implementations in [`../../../reference-implementations/`](../../../reference-implementations/).

---

## Contents

| File | Description |
|------|-------------|
| `zpd-monitor-v0.2.py` | ZPD monitor: compressed learner state + affect + ZPD drift detection |
| `zpd-monitor-demo.py` | Worked demo of the ZPD monitor running a simulated algebra session |
| `nlp-pre-interpreter.py` | Deterministic NLP pre-interpreter: extracts answer-match, frustration, hint-request, and off-task anchors from raw student messages (<1 ms, stdlib only) |
| `fluency_monitor.py` | Fluency monitor: consecutive-correct gate that advances students through problem tiers (default: 3 correct under 45 s → next tier) |
| `problem_generator.py` | Tier-based algebra problem generator: produces `ProblemSpec` dicts for 3 difficulty tiers of single-variable linear equations |
| `runtime-adapters.py` | Education domain turn-interpreter adapter: NLP anchor injection, algebra-parser override, glossary detection intercept, wired into `runtime-config.yaml` |
| `tool-adapters.py` | Algebra tool adapters: parser, substitution-checker, and calculator entry points used by the orchestrator and turn interpreter |

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
| `zpd-monitor-v0.2.py` | [`../domain-lib/zpd-monitor-spec-v1.md`](../domain-lib/zpd-monitor-spec-v1.md) |
| `zpd-monitor-v0.2.py` | [`../domain-lib/compressed-state-estimators.md`](../domain-lib/compressed-state-estimators.md) |
| `zpd-monitor-v0.2.py` | [`../schemas/compressed-state-schema-v1.json`](../schemas/compressed-state-schema-v1.json) |
| `nlp-pre-interpreter.py` | [`../../../docs/3-functions/nlp-pre-interpreter.md`](../../../docs/3-functions/nlp-pre-interpreter.md) |
| `fluency_monitor.py` | [`../../../docs/3-functions/fluency-monitor.md`](../../../docs/3-functions/fluency-monitor.md) |
| `problem_generator.py` | [`../../../docs/3-functions/problem-generator.md`](../../../docs/3-functions/problem-generator.md) |
| `runtime-adapters.py` | [`../runtime-config.yaml`](../runtime-config.yaml) |
| `tool-adapters.py` | [`../modules/algebra-level-1/tool-adapters/`](../modules/algebra-level-1/tool-adapters/) |
