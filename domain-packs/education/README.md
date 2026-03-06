# Education Domain Index

This directory owns education-domain policy and semantics.

Core engine docs do not define education principles, education state semantics, or education standing-order meanings. Those are defined here.

---

## Domain Principles

Education-specific principles are declared and versioned by education domain packs. They can extend universal behavior for education contexts (for example, consent requirements or scaffolding behavior), but they are not root-level universal rules.

Primary implementation reference:
- [`algebra-level-1/domain-physics.yaml`](algebra-level-1/domain-physics.yaml)

---

## Domain Rules and Invariants

Education invariants and standing-order bindings are authored in domain physics and interpreted by the orchestrator as domain data:
- [`algebra-level-1/domain-physics.yaml`](algebra-level-1/domain-physics.yaml)
- [`algebra-level-1/domain-physics.json`](algebra-level-1/domain-physics.json)

---

## Domain State Model and Domain Lib

Education state schema and estimators are defined under `schemas/` and `domain-lib/`:
- [`schemas/compressed-state-schema-v1.json`](schemas/compressed-state-schema-v1.json)
- [`schemas/student-profile-schema-v1.json`](schemas/student-profile-schema-v1.json)
- [`domain-lib/README.md`](domain-lib/README.md)
- [`domain-lib/zpd-monitor-spec-v1.md`](domain-lib/zpd-monitor-spec-v1.md)
- [`domain-lib/compressed-state-estimators.md`](domain-lib/compressed-state-estimators.md)
- [`domain-lib/fatigue-estimation-spec-v1.md`](domain-lib/fatigue-estimation-spec-v1.md)
- [`runtime-config.yaml`](runtime-config.yaml)

`runtime-config.yaml` is the education-root runtime ownership surface for:
- domain conversational override prompt
- domain evidence extraction prompt and defaults
- deterministic response templates for local validation mode
- manifest-style adapter bindings (state builder, domain step, evidence extractor)

Reference implementation:
- [`reference-implementations/README.md`](reference-implementations/README.md)
- [`reference-implementations/zpd-monitor-v0.2.py`](reference-implementations/zpd-monitor-v0.2.py)
- [`evaluation-tests.md`](evaluation-tests.md)
- [`artifact-and-mastery-examples.md`](artifact-and-mastery-examples.md)

---

## Domain Physics and Prompt Contracts

Education packs declare their own prompt-contract extensions and domain vocabulary:
- [`algebra-level-1/prompt-contract-schema.json`](algebra-level-1/prompt-contract-schema.json)
- [`algebra-level-1/tool-adapters/`](algebra-level-1/tool-adapters/)

---

## Boundary With Core

Universal engine contracts live in:
- [`../../README.md`](../../README.md)
- [`../../specs/dsa-framework-v1.md`](../../specs/dsa-framework-v1.md)
- [`../../specs/principles-v1.md`](../../specs/principles-v1.md)

Education-specific principles, rules, states, and physics stay in this directory and its packs.
