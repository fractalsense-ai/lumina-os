# Education Domain Index

This directory owns education-domain policy and semantics.

Core engine docs do not define education principles, education state semantics, or education standing-order meanings. Those are defined here.

---

## Domain Principles

Education-specific principles are declared and versioned by education domain packs. They can extend universal behavior for education contexts (for example, consent requirements or scaffolding behavior), but they are not root-level universal rules.

Primary implementation reference:
- [`modules/algebra-level-1/domain-physics.yaml`](modules/algebra-level-1/domain-physics.yaml)

---

## Domain Rules and Invariants

Education invariants and standing-order bindings are authored in domain physics and interpreted by the orchestrator as domain data:
- [`modules/algebra-level-1/domain-physics.yaml`](modules/algebra-level-1/domain-physics.yaml)
- [`modules/algebra-level-1/domain-physics.json`](modules/algebra-level-1/domain-physics.json)

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

`runtime-config.yaml` is the education domain pack runtime configuration surface for:
- domain conversational override prompt
- domain turn interpretation prompt and default turn-input fields
- deterministic response templates for local validation mode
- manifest-style adapter bindings (state builder, domain step, turn interpreter)

Reference implementation:
- [`reference-implementations/README.md`](reference-implementations/README.md)
- [`reference-implementations/zpd-monitor-v0.2.py`](reference-implementations/zpd-monitor-v0.2.py)
- [`evaluation-tests.md`](evaluation-tests.md)
- [`artifact-and-mastery-examples.md`](artifact-and-mastery-examples.md)

---

## Turn Interpretation Subsystem

Student messages pass through a three-stage pipeline before the orchestrator evaluates domain invariants:

1. **Glossary detection intercept** — the raw message is scanned against domain-defined vocabulary terms. A match short-circuits D.S.A. and returns an inline definition without entering the orchestrator loop.

2. **NLP pre-interpreter** (`nlp-pre-interpreter.py`) — deterministic extractors (<1 ms, stdlib only) annotate the message with structured anchors before the LLM sees it:
   - `answer_match` — regex-based answer extraction with confidence score (0.95 for `x=N` form, 0.90 for prose)
   - `frustration_markers` — keyword list, ALL_CAPS, excessive punctuation, short frustrated utterances
   - `hint_request` — explicit hint-seeking patterns
   - `off_task_ratio` — math-vocabulary token ratio for off-topic detection
   Anchors are injected into the LLM context hint as `_nlp_anchors`; the LLM turn interpreter always runs (world-sim dependency).

3. **Algebra parser override** (`runtime-adapters.py`) — post-LLM deterministic override for `solution_value`, `step_count`, and `equivalence_preserved` using the algebra parser tool adapter. Ground-truth values replace LLM estimates for these fields.

Function references:
- [`../../docs/3-functions/nlp-pre-interpreter.md`](../../docs/3-functions/nlp-pre-interpreter.md)
- [`../../docs/3-functions/fluency-monitor.md`](../../docs/3-functions/fluency-monitor.md)
- [`../../docs/3-functions/problem-generator.md`](../../docs/3-functions/problem-generator.md)

---

## Fluency Monitor and Problem Generator

The education domain implements a tier-advancement system for algebra practice:

- **Fluency monitor** (`fluency_monitor.py`) — tracks consecutive correct answers with solve times. After 3 consecutive correct answers each under 45 s the student advances to the next tier. A correct answer that exceeds the threshold triggers a targeted hint rather than advancement.

- **Problem generator** (`problem_generator.py`) — generates tier-appropriate `ProblemSpec` dicts:
  - Tier 1: `x + a = b` (one-step, add/subtract)
  - Tier 2: `ax = b` (one-step, multiply/divide)
  - Tier 3: `ax ± b = c` (two-step)
  All solutions are positive integers; uses stdlib `random` only.

---

## Vocabulary Growth Tracker

The education domain includes a passive vocabulary complexity monitor for Student Commons and all student profiles:

- **Vocabulary growth monitor** (`domain-lib/vocabulary_growth_monitor_v0_1.py`) — receives pre-computed complexity scores from the client-side analyzer, maintains a rolling baseline, and produces a non-negative growth delta. No transcript content is processed server-side.

- **Client-side analyzer** (`domain-packs/education/web/services/vocabularyAnalyzer.ts`) — buffers student messages, computes lexical diversity, average word length, embedding spread, and domain-term detection. Posts structured metrics via the domain-declared API route.

- **API route handlers** (`controllers/api_handlers.py`) — domain-owned HTTP endpoints for vocabulary metric submission (`POST /api/user/{user_id}/vocabulary-metric`) and dashboard data (`GET /api/dashboard/education/vocabulary-growth`). Declared in `cfg/runtime-config.yaml` under `adapters.api_routes` and mounted by the core server at startup.

Function references:
- [`docs/3-functions/vocabulary-growth-monitor.md`](docs/3-functions/vocabulary-growth-monitor.md)
- [`../../docs/7-concepts/learning-profile.md`](../../docs/7-concepts/learning-profile.md) — `vocabulary_tracking` schema

---

## Domain Physics and Prompt Contracts

Education packs declare their own prompt-contract extensions and domain vocabulary:
- [`modules/algebra-level-1/prompt-contract-schema.json`](modules/algebra-level-1/prompt-contract-schema.json)
- [`modules/algebra-level-1/tool-adapters/`](modules/algebra-level-1/tool-adapters/)

---

## Domain-Lib vs Tool-Adapters

The education domain separates its components into two categories:

- **`domain-lib/`** — Passive specification documents (ZPD monitor spec, fatigue estimation spec, compressed-state estimators). These are read as context by the orchestrator and LLM. They define *what* the domain measures but have no callable entry point.

- **`modules/algebra-level-1/tool-adapters/`** — Active deterministic tools (algebra parser, substitution checker, calculator). These are invoked by the orchestrator or turn interpreter, accept structured input, and return structured output. They provide ground-truth data that the LLM validates against.

See [`../README.md`](../README.md#domain-lib-vs-tool-adapters) for the full architectural distinction.

---

## Boundary With Core

Universal engine contracts live in:
- [`../../README.md`](../../README.md)
- [`../../docs/7-concepts/dsa-framework.md`](../../docs/7-concepts/dsa-framework.md) (D.S.A. structural schema underlying PPA)
- [`../../docs/7-concepts/principles.md`](../../docs/7-concepts/principles.md)

Education-specific principles, rules, states, and physics stay in this directory and its packs.

---

## World Simulation and Consent Boundary

The education domain pack includes a **world simulation** layer and a consent-boundary instantiation named **magic circle consent** under [`world-sim/`](world-sim/):

- [`world-sim/magic-circle-consent-v1.md`](world-sim/magic-circle-consent-v1.md) — consent contract for entering personalized learning simulation environments (the "magic circle")
- [`world-sim/world-sim-spec-v1.md`](world-sim/world-sim-spec-v1.md) — how to present learning material within a narrative context adapted to the student's likes/dislikes
- [`world-sim/artifact-and-mastery-spec-v1.md`](world-sim/artifact-and-mastery-spec-v1.md) — artifact award process, boss challenges, and proficiency estimation for the education domain

The consent boundary (implemented here as the magic circle) establishes explicit, informed consent before entering any simulated / immersive / world-sim learning mode. This creates a bounded environment where:
- Special pedagogical rules apply (failure is safe, experimentation encouraged)
- Real-world consequences are suspended within bounds
- The system and Domain Authority are protected from liability claims related to simulation content

Consent is **measurement + accountability**, not surveillance: only a pseudonymous token and scope hash are stored in System Log; no PII/transcript at rest.

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
> The engine provides structural accountability (D.S.A. contracts, System Log traces) but does **NOT** replace human oversight, professional judgment, or legal compliance.
>
> The education-domain magic-circle consent specification is a structural template implementing the universal consent-boundary principle. It is **not legal advice**. Consult education lawyers and ethics boards before production use.
