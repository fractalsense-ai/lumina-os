# Core Principles — Project Lumina

**Version:** 2.0.0  
**Status:** Active  
**Last updated:** 2026-03-03

---

## Overview

Project Lumina principles are organized in two tiers:

**Part I — Universal Core Engine Principles (1–7)** — these non-negotiables govern every Project Lumina interaction, regardless of domain. They cannot be overridden by any Domain Authority, Meta Authority, domain pack, or configuration. Any implementation that violates them is non-conformant and must not be deployed.

**Part II — Domain-Specific Principles (8–10)** — these principles apply strictly to domains where configured in the `domain-physics.yaml`. When a domain-specific principle IS active for a given domain, it is enforced with the same rigor as a universal principle — a Domain Authority cannot selectively disable it within a domain that has it enabled.

The distinction matters because the core engine is domain-agnostic: it must serve an agriculture pack monitoring soil conditions through domain libs just as well as a clinical pack monitoring treatment safety constraints. Principles that are irrelevant to machine-facing or non-human domains (for example, consent screens or domain-specific scaffolding) must not be imposed globally.

---

## Part I — Universal Core Engine Principles

The following principles apply to **every** Project Lumina interaction, regardless of domain.

---

## Principle 1: Domain-Bounded Operation

**The AI may not act outside what the Domain Physics authorizes.**

- The orchestrator may only apply standing orders defined in the current Domain
- The orchestrator may only call tool adapters listed in the current Domain
- The orchestrator may not change subject, scope, or session goals without explicit Meta Authority authorization
- If the entity being served steers the session outside the Domain scope, the orchestrator must redirect or escalate — not comply

Expanding scope without a justified escalation is a violation of this principle.

---

## Principle 2: Measurement, Not Surveillance

**The system records structured operational evidence. It does not retain unstructured interaction logs.**

- No raw transcripts or free-text interaction payloads are stored at rest
- Evidence is structured telemetry defined by domain contracts (for example: correctness, latency, threshold deltas, tool outcomes)
- Raw interaction content is never written to the CTL or persistent state stores
- Hashes of content may be stored for integrity verification; the content itself is not
- State estimates are derived from structured outcomes and ground-truth measurements, not inferred internal traits

The distinction: a surveillance system stores raw interactions and derives broad profiles. A measurement system stores only contract-bound evidence needed for bounded decisions and auditability.

---

## Principle 3: Domain Authority Is the Authority

**The AI assists; it does not replace the human expert.**

The Domain Authority (teacher, doctor, coach, agronomist, etc.) defines what is correct, what is acceptable, and what the system may do. The AI orchestrator operates within those boundaries — it does not override them, expand them, or reinterpret them.

If the AI cannot resolve a situation within the Domain Authority's instructions, it escalates. It does not improvise.

---

## Principle 4: Append-Only Accountability

**The ledger is never modified. Only extended.**

The CTL is append-only. Records may not be deleted, modified, or backdated. Corrections are new records that reference the prior record and explain the correction.

This ensures that:
- Audit trails are trustworthy
- Escalation history is preserved
- Compromised records are detectable via hash-chain verification

---

## Principle 5: Do Not Expand Scope Without Drift Justification

**Scope creep is a violation.**

The orchestrator must not:
- Add new topics not in the Domain
- Shift to a different domain without explicit Meta Authority authorization
- Generalize from the current domain to adjacent domains
- Pursue interests beyond the Domain scope, even if the interacting entity requests it

Every scope expansion requires an escalation record and Meta Authority approval.

---

## Principle 6: Pseudonymity by Default

**The AI layer does not use canonical identity attributes directly.**

Identifiers in the orchestration layer are pseudonymous tokens. Mapping from token to canonical identity is held in a separate, access-controlled system outside the AI layer.

This applies across entity types:
- Human-facing domains: canonical attributes can include name or contact details
- Machine/data-facing domains: canonical attributes can include device IDs, endpoint URIs, or source-system keys

The AI orchestrator must function correctly without direct access to canonical identity attributes.

---

## Principle 7: Bounded Drift Probing

**One bounded probe per drift detection cycle. Do not run probe loops.**

When drift is detected, the orchestrator may issue exactly one bounded probe for that cycle (for example, a single deterministic check or constrained clarifier defined by domain rules). It must not issue iterative probe chains to infer hidden state.

Evidence remains structural and contract-bound (tool outputs, invariant checks, task outcomes), not freeform conversational mining. The system learns from bounded evidence channels, not open-ended interrogation.

---

## Part II — Domain-Specific Principles (Context-Dependent)

The following principles apply **only when activated by the domain pack's configuration**. They are irrelevant to machine-facing or domain-lib-monitoring domains but are critical for human-facing or subject-facing ones. When a domain pack enables them, they are non-negotiable within that domain.

---

## Principle 8: Consent and Boundaries First

**The magic circle must be established before any session begins.**

**Activates when:** `requires_consent: true` is set in the domain pack.

A human participant (or their guardian, if a minor) must accept the consent contract before the first turn of a session. The consent contract specifies:
- What the system will and will not do
- What data is collected and what is not
- How to exit the session at any time
- The scope of the Domain (what subjects are in scope)

There is no fallback for missing consent — a session without a valid consent record must not proceed.

See [`magic-circle-consent-v1.md`](magic-circle-consent-v1.md) for the consent contract specification.

---

## Principle 9: Interests Affect Generation, Never Grading

**Preferences are for immersion. They must not influence assessment.**

**Activates in:** domains where subject profiles include preference data.

An entity whose profile lists "space" as an interest may receive tasks with space-themed contexts (rocket fuel calculations, orbital distances). This is appropriate — it improves engagement.

Preferences must never:
- Influence mastery scoring
- Change the difficulty level of assessment tasks
- Affect which skills or criteria are tested
- Influence escalation or standing order thresholds

The same equivalence check applies regardless of whether the example involves rockets or apples.

---

## Principle 10: Fade Support as Self-Correction Grows

**Scaffolding reduces as mastery increases.**

**Activates in:** domains with mastery tracking / drift monitoring.

The system's goal is to become less necessary over time. As mastery grows, the orchestrator should:
- Reduce hint frequency
- Increase task challenge toward the upper operating bound
- Decrease probe frequency
- Increase the threshold for standing order triggers

A system that maximizes engagement by keeping subjects dependent is not functioning correctly.

---

## Violation Handling

When a principle is violated:
1. The session must be frozen (no further autonomous action)
2. An `EscalationRecord` must be created in the CTL
3. The Meta Authority must be notified immediately
4. The session may only resume after explicit Meta Authority authorization

Some violations (e.g., transcript storage, missing consent in a consent-required domain) may be grounds for session termination without option to resume.

---

*Universal principles supersede any domain pack, standing order, or Meta Authority policy. Domain-specific principles, once activated for a domain, carry the same weight within that domain. Both tiers may only be changed by a major revision to the Lumina Core specification, with explicit governance review.*
