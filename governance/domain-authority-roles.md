# Domain Authority Roles — Project Lumina

**Version:** 1.0.0  
**Status:** Active  
**Last updated:** 2026-03-02

---

## Overview

This document defines the **Domain Authority** role in Project Lumina: what it means, who holds it, what rights it grants, what obligations it creates, and how it is assigned and revoked.

---

## What Is a Domain Authority?

A **Domain Authority** is a human participant who has been granted authoring rights over a Domain Physics document within a defined scope. In educational contexts, the Domain Authority is typically a subject-matter expert — a teacher, curriculum designer, or department head.

The Domain Authority is not an administrator or manager. Their authority is specifically about **what is correct and acceptable within their subject domain**. A teacher is the Domain Authority for "what is correct in algebra" — not for "school IT policy."

---

## Domain Authority Rights

A Domain Authority may:

1. **Author Domain Packs** — write and version the `domain-physics.yaml` for their scope
2. **Define Invariants** — specify what is and is not acceptable (critical and warning severity)
3. **Define Standing Orders** — specify the bounded automated responses within their domain
4. **Define Escalation Triggers** — specify when the system must escalate to them or above
5. **Define Artifacts** — specify mastery milestones and boss challenge structures
6. **Set ZPD Parameters** — configure the Zone of Proximal Development band and drift thresholds
7. **Review CTL Records** — access audit logs for sessions in their domain
8. **Receive Escalations** — receive and resolve escalation packets from their sessions
9. **Authorize Tool Adapters** — approve which external tools may be used in their sessions

---

## Domain Authority Obligations

A Domain Authority must:

1. **Maintain Domain Pack Versions** — keep a CHANGELOG and commit domain pack hashes to the CTL before use
2. **Respond to Escalations Within SLA** — acknowledge escalation packets within the SLA defined in their domain pack
3. **Not Override Higher-Level Invariants** — their domain pack may not relax invariants set by their Meta Authority
4. **Maintain Pseudonymity** — not map pseudonymous student IDs to real identities within the AI system
5. **Respect Consent Boundaries** — not instruct the AI to act outside the magic circle consent contract
6. **Not Store Transcripts** — any system they operate must comply with the no-transcript constraint
7. **Report Discrepancies** — if they observe unexpected system behavior, create a discrepancy report

---

## Domain Authority Levels

In a fractal governance structure, each level is a Domain Authority for its own scope and a Meta Authority for the level below:

| Level | Title | Domain Scope | Meta Authority For |
|-------|-------|-------------|-------------------|
| 1 | Administration | Institutional policy | Department Heads |
| 2 | Department Head | Curriculum standards | Teachers |
| 3 | Teacher | Subject matter | Students (in session) |
| 4 | Student | Own learning state | (none below) |

A student is the Domain Authority for their own learning state — they can set preferences, exit sessions, and consent or withdraw consent. They are not the Domain Authority for "what is correct in algebra."

---

## Onboarding a Domain Authority

To onboard a new Domain Authority:

1. **Scope assignment** — the Meta Authority defines the scope of the new Domain Authority's domain
2. **Pseudonymous ID issuance** — a pseudonymous token is assigned; real-identity mapping held by institution
3. **Policy review** — the new Domain Authority reviews and signs the governance policy and the Meta Authority policy template
4. **Domain pack training** — review of domain pack authoring process and invariant design guidelines
5. **Commitment record** — a `CommitmentRecord` is appended to the CTL recording the onboarding
6. **First domain pack** — the new Domain Authority authors their first domain pack under Meta Authority review

---

## Domain Authority Scope Conflicts

If two Domain Authorities have overlapping scope:
- The higher-level Meta Authority resolves the conflict
- Until resolved, the more restrictive invariant set applies
- The resolution is recorded as a `CommitmentRecord` in the CTL

---

## Domain Authority Revocation

A Domain Authority's rights may be revoked by their Meta Authority. Revocation:
- Is recorded as a `CommitmentRecord` in the CTL
- Takes effect immediately for new sessions
- Does not retroactively invalidate past sessions
- Requires the domain pack to be reassigned or deactivated

---

## Student as Domain Authority

Students have a limited form of Domain Authority over their own learning state:

**Students may:**
- Set and update their preferences (interests, dislikes, explanation style)
- Accept or withdraw consent (magic circle)
- Request a summary of their own CTL records
- Exit sessions at any time

**Students may not:**
- Modify their mastery estimates directly
- Override standing orders or escalation triggers
- Author domain packs (unless they are themselves a teacher or higher)

---

## References

- [`GOVERNANCE.md`](../GOVERNANCE.md) — fractal authority structure
- [`meta-authority-policy-template.yaml`](meta-authority-policy-template.yaml) — Meta Authority policy
- [`../specs/magic-circle-consent-v1.md`](../specs/magic-circle-consent-v1.md) — consent contract
- [`../standards/lumina-core-v1.md`](../standards/lumina-core-v1.md) — conformance requirements
