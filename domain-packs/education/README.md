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

## Domain-Lib vs Tool-Adapters

The education domain separates its components into two categories:

- **`domain-lib/`** — Passive specification documents (ZPD monitor spec, fatigue estimation spec, compressed-state estimators). These are read as context by the orchestrator and LLM. They define *what* the domain measures but have no callable entry point.

- **`algebra-level-1/tool-adapters/`** — Active deterministic tools (algebra parser, substitution checker, calculator). These are invoked by the orchestrator or evidence extractor, accept structured input, and return structured output. They provide ground-truth evidence that the LLM validates against.

See [`../README.md`](../README.md#domain-lib-vs-tool-adapters) for the full architectural distinction.

---

## Boundary With Core

Universal engine contracts live in:
- [`../../README.md`](../../README.md)
- [`../../specs/dsa-framework-v1.md`](../../specs/dsa-framework-v1.md)
- [`../../specs/principles-v1.md`](../../specs/principles-v1.md)

Education-specific principles, rules, states, and physics stay in this directory and its packs.

---

## World Simulation and Consent

The education domain pack includes a **world simulation** layer and **magic circle consent** specification under [`world-sim/`](world-sim/):

- [`world-sim/magic-circle-consent-v1.md`](world-sim/magic-circle-consent-v1.md) — consent contract for entering personalized learning simulation environments (the "magic circle")
- [`world-sim/world-sim-spec-v1.md`](world-sim/world-sim-spec-v1.md) — how to present learning material within a narrative context adapted to the student's likes/dislikes
- [`world-sim/artifact-and-mastery-spec-v1.md`](world-sim/artifact-and-mastery-spec-v1.md) — artifact award process, boss challenges, and proficiency estimation for the education domain

The magic circle establishes explicit, informed consent before entering any simulated / immersive / world-sim learning mode. This creates a bounded environment where:
- Special pedagogical rules apply (failure is safe, experimentation encouraged)
- Real-world consequences are suspended within bounds
- The system and Domain Authority are protected from liability claims related to simulation content

Consent is **measurement + accountability**, not surveillance: only a pseudonymous token and scope hash are stored in CTL; no PII/transcript at rest.

The world simulation personalizes presentation based on student interests and preferences (from the student profile's `likes` / `dislikes` fields) without affecting grading or assessment. Domain invariants are enforced identically regardless of narrative theme.

These specs were relocated here from `specs/` because they are domain-specific liability + pedagogical framing, not core engine invariants. Other domain packs (e.g., agriculture for operational simulation consent, medical for scenario-based training) may adapt these patterns with domain-appropriate language and thresholds.

---

> **WARNING: Educational Domain Pack — Child Safety**
>
> This domain pack includes features for use with minors (e.g., Zone of Proximal Development monitoring, personalized world simulations, magic-circle consent flows).
>
> It is provided **AS-IS** under Apache 2.0 with **NO WARRANTIES**.
>
> Deploying this in real educational settings involving children **REQUIRES** independent review and compliance with applicable laws (COPPA, FERPA, GDPR child data rules, local education regulations).
>
> **Domain Authorities** (teachers, admins, districts) are **solely responsible** for:
> - Obtaining required parental/guardian consents
> - Ensuring psychological/developmental appropriateness
> - Protecting student privacy and data
> - Handling liability for simulation content or AI decisions
>
> The engine provides structural accountability (D.S.A. contracts, CTL traces) but does **NOT** replace human oversight, professional judgment, or legal compliance.
>
> The magic-circle consent specification is a structural template inspired by pedagogical best practices and liability framing — it is **not legal advice**. Consult education lawyers and ethics boards before production use.
