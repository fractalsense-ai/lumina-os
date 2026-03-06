# Governance Model — Project Lumina

**Version:** 1.0.0  
**Last updated:** 2026-03-02

---

## Overview

Project Lumina governance is built on a **fractal authority structure**: every participant is a Domain Authority for their own scope, and simultaneously a Meta Authority for the level(s) beneath them. Authority flows from consent and competence, not from hierarchy for its own sake.

---

## Fractal Authority Structure

The fractal authority structure is a generic pattern applicable to any domain:

```
Macro Authority
  Role: Domain Authority for top-level policy
  Meta Authority for: Meso Authorities
  Examples: School Board / Hospital Admin / Corporate Policy
        ↓
Meso Authority
  Role: Domain Authority for operational standards
  Meta Authority for: Micro Authorities
  Examples: Curriculum Director / Department Head / Site Manager
        ↓
Micro Authority
  Role: Domain Authority for subject-matter or operational correctness
  Meta Authority for: Subjects/Targets (within their sessions)
  Examples: Teacher / Lead Physician / Operator
        ↓
Subject/Target
  Role: Domain Authority for their own state and preferences
  Meta Authority for: (no level below)
  Examples: Learner / Patient / Farm Environment
```

**Education instantiation:** Administration → Department Head → Teacher → Student  
**Medical instantiation:** Hospital Admin → Department Head → Lead Physician → Patient  
**Agriculture instantiation:** Corporate Policy → Site Manager → Operator → Environment

Each level:
1. **Authors its own Domain Physics** — YAML ruleset defining invariants, standing orders, and escalation triggers within its scope
2. **Retrieves from the level above** — via RAG contracts; cannot override a higher authority's invariants
3. **Is accountable via the CTL** — every commitment, decision, and escalation is ledger-recorded
4. **Can escalate upward** — when the system cannot stabilize within its own Domain Physics

---

## Domain Authority

A **Domain Authority** is any human participant who has been granted authoring rights over a Domain Physics document within their scope.

Rights:
- Author and version domain packs within their scope
- Define invariants (critical and warning severity)
- Define standing orders and their automated response bounds
- Define escalation triggers

Constraints:
- Cannot override invariants set by a higher-level Domain Authority
- All domain pack versions must be hash-committed to the CTL before taking effect
- Domain pack changes require explicit versioning and a CHANGELOG entry

See [`governance/domain-authority-roles.md`](governance/domain-authority-roles.md) for role definitions and onboarding.

---

## Meta Authority

A **Meta Authority** is a Domain Authority that has the additional right to set governance policy for levels below. Specifically:

- Approving or rejecting domain packs authored by subordinate Domain Authorities
- Setting the retrieval scope available to subordinate sessions
- Setting override invariants that subordinate domain packs cannot relax
- Receiving escalation packets from subordinate sessions

The Meta Authority relationship is explicit and must be declared in the domain pack of the higher level.

---

## Document Versioning

All governance documents and domain packs follow semantic versioning:

| Change Type | Version Bump | Example |
|-------------|-------------|---------|
| New invariant, changed escalation threshold | **Major** | v1.0 → v2.0 |
| New standing order, clarified constraint | **Minor** | v1.0 → v1.1 |
| Wording correction, metadata update | **Patch** | v1.0 → v1.0.1 |

Version history is maintained in Git. The current hash of every active domain pack must be committed to the CTL as a `CommitmentRecord` before the pack takes operational effect.

---

## Escalation Protocol

Escalation occurs when the AI orchestrator cannot stabilize a session within its current Domain Physics. The escalation is **always upward** — to the Meta Authority above the current session's Domain Authority.

### Escalation Steps

1. **Detection** — the orchestrator detects that state drift is major, a critical invariant is repeatedly violated, or a standing order is exhausted
2. **Freeze** — the orchestrator halts autonomous action within this session scope
3. **Packet Assembly** — an `EscalationRecord` is assembled: structured summary, evidence hashes, decision trail from CTL, proposed next action
4. **CTL Record** — the `EscalationRecord` is appended to the CTL (append-only; escalation cannot be deleted)
5. **Notification** — the Meta Authority receives the escalation packet through the designated channel
6. **Resolution** — the Meta Authority reviews, decides, and records their decision as a `CommitmentRecord`
7. **Resume or Terminate** — the session resumes under updated parameters, or is terminated cleanly

Every escalation step must be recorded. An escalation that is not acknowledged within the SLA defined in the domain pack is itself a reportable event.

---

## Audit Rights

All stakeholders have the right to audit within their authority scope:

- **Subject/Target** (e.g., Student, Patient): may request a summary of their own CTL records (structured telemetry only, never raw transcripts)
- **Micro Authority** (e.g., Teacher, Physician, Operator): may audit CTL records for sessions within their domain
- **Meso Authority** (e.g., Department Head, Site Manager): may audit Micro Authority-level CTL records
- **Macro Authority** (e.g., Administration, Hospital Admin, Corporate Policy): may audit all CTL records within their scope

Audit outputs are structured summaries. No audit may produce a transcript — the CTL does not store transcripts.

See [`governance/audit-and-rollback.md`](governance/audit-and-rollback.md) for audit procedures and rollback policy.

---

## Privacy Policy

- **No transcripts at rest** — this is a hard constraint, not a default
- **Pseudonymous only** — subject identifiers in the CTL are pseudonymous; real identity mapping is held by the institution, not the AI layer
- **Interests affect generation, never grading** — subject preference data may be used for immersion (e.g., contextualizing task presentation) but must never influence assessment or outcome scoring
- **Structured telemetry only** — the CTL records decision summaries, not conversational content

---

## Rollback Policy

Domain Physics changes may be rolled back by a Domain Authority within their scope. Rollback:
- Must be recorded as a new version (not a deletion)
- Must append a `CommitmentRecord` to the CTL explaining the reason
- Does not remove prior CTL records — the ledger is append-only

See [`governance/audit-and-rollback.md`](governance/audit-and-rollback.md).

---

*This document shall be updated when governance policy changes. All changes require a Major version bump and a CTL commitment.*