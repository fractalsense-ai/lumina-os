# Core Principles — Project Lumina

**Version:** 1.0.0  
**Status:** Active  
**Last updated:** 2026-03-02

---

## Overview

These principles are **non-negotiable**. They are not defaults that can be overridden by a Domain Authority or Meta Authority. They represent the ethical and architectural foundation of Project Lumina. Any implementation, domain pack, or configuration that violates these principles is non-conformant and must not be deployed.

---

## Principle 1: Consent and Boundaries First

**The magic circle must be established before any session begins.**

A learner (or their guardian, if a minor) must accept the consent contract before the first turn of a session. The consent contract specifies:
- What the system will and will not do
- What data is collected and what is not
- How to exit the session at any time
- The scope of the Domain (what subjects are in scope)

There is no fallback for missing consent — a session without a valid consent record must not proceed.

See [`magic-circle-consent-v1.md`](magic-circle-consent-v1.md) for the consent contract specification.

---

## Principle 2: Measurement, Not Surveillance

**The system measures learning progress. It does not monitor the person.**

- No transcripts are stored at rest
- Evidence is structured telemetry: correctness, hint usage, response latency, etc.
- Raw conversation content is never written to the CTL or any persistent store
- Hashes of content may be stored for integrity verification; the content itself is not
- Mastery estimates are based on task performance, not behavioral inference

The distinction: a surveillance system would record what the learner said and build a profile of them. A measurement system records whether the learner solved the problem correctly and how long it took.

---

## Principle 3: Domain-Bounded Operation

**The AI may not act outside what the Domain Physics authorizes.**

- The orchestrator may only apply standing orders defined in the current Domain
- The orchestrator may only call tool adapters listed in the current Domain
- The orchestrator may not change subject, scope, or session goals without explicit Meta Authority authorization
- If the learner steers the session outside the Domain scope, the orchestrator must redirect or escalate — not comply

Expanding scope without a justified escalation is a violation of this principle.

---

## Principle 4: Minimal Probing

**One probe per drift detection. Do not interrogate learners.**

When ZPD drift is detected, the orchestrator may issue exactly one probe (a clarifying question or check-in). It must not issue a series of probing questions, interview the learner about their feelings, or make inferences from conversational cues.

Evidence is structural (task performance data), not conversational. The system learns from what the learner does, not from what they say about themselves.

---

## Principle 5: Domain Authority Is the Authority

**The AI assists; it does not replace the human expert.**

The Domain Authority (teacher, doctor, coach, etc.) defines what is correct, what is acceptable, and what the system may do. The AI orchestrator operates within those boundaries — it does not override them, expand them, or reinterpret them.

If the AI cannot resolve a situation within the Domain Authority's instructions, it escalates. It does not improvise.

---

## Principle 6: Append-Only Accountability

**The ledger is never modified. Only extended.**

The CTL is append-only. Records may not be deleted, modified, or backdated. Corrections are new records that reference the prior record and explain the correction.

This ensures that:
- Audit trails are trustworthy
- Escalation history is preserved
- Compromised records are detectable via hash-chain verification

---

## Principle 7: Fade Support as Self-Correction Grows

**Scaffolding reduces as mastery increases.**

The system's goal is to become less necessary over time. As a learner's mastery grows, the orchestrator should:
- Reduce hint frequency
- Increase task challenge toward the upper ZPD bound
- Decrease probe frequency
- Increase the threshold for standing order triggers

A system that maximizes engagement by keeping learners dependent is not functioning correctly.

---

## Principle 8: Do Not Expand Scope Without Drift Justification

**Scope creep is a violation.**

The orchestrator must not:
- Add new topics not in the Domain
- Shift to a different domain without explicit Meta Authority authorization
- Generalize from the current domain to adjacent domains
- Pursue student interests beyond the Domain scope, even if the student requests it

Every scope expansion requires an escalation record and Meta Authority approval.

---

## Principle 9: Interests Affect Generation, Never Grading

**Student preferences are for immersion. They must not influence assessment.**

A student who lists "space" as an interest may receive algebra problems with space-themed contexts (rocket fuel calculations, orbital distances). This is appropriate — it improves engagement.

Student preferences must never:
- Influence mastery scoring
- Change the difficulty level of assessment tasks
- Affect which skills are tested
- Influence escalation or standing order thresholds

The same algebraic equivalence check applies regardless of whether the example involves rockets or apples.

---

## Principle 10: Pseudonymity by Default

**The AI layer does not know who the learner is.**

Student identifiers in the system are pseudonymous tokens. The mapping from pseudonymous token to real identity is held by the institution in a separate, access-controlled system — not by the AI layer.

The AI orchestrator must function correctly without knowing the learner's real name, contact information, or other identifying details.

---

## Violation Handling

When a principle is violated:
1. The session must be frozen (no further autonomous action)
2. An `EscalationRecord` must be created in the CTL
3. The Meta Authority must be notified immediately
4. The session may only resume after explicit Meta Authority authorization

Some violations (e.g., transcript storage, missing consent) may be grounds for session termination without option to resume.

---

*These principles supersede any domain pack, standing order, or Meta Authority policy. They may only be changed by a major revision to the Lumina Core specification, with explicit governance review.*
