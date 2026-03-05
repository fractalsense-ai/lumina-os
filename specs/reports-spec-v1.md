# Reports Specification — V1

**Version:** 1.1.0  
**Status:** Active  
**Last updated:** 2026-03-05

---

## Overview

This document specifies the reporting layer for Project Lumina: daily logs, progress reports, discrepancy resolution, and Domain Authority review reports.

---

## Report Types

### 1. Daily Session Log

Generated once per day per Domain Authority. Summarizes all sessions in their domain for the prior day.

**Contents:**
- Number of sessions completed
- Number of sessions escalated
- Number of artifacts awarded
- Aggregate mastery deltas per skill (average across entities)
- Number of standing order triggers per invariant
- Number of sensor drift events (minor and major)
- Any escalations pending resolution

**Format:** Structured JSON, rendered as human-readable summary on request.

**Audience:** Domain Authority (teacher), available to Meta Authority on request.

**Privacy:** All entity identifiers are pseudonymous. No individual entity data is surfaced in the daily log — only aggregates.

### 2. Entity Progress Report

Generated on demand for a specific entity, by a Domain Authority or Meta Authority with appropriate scope.

**Contents:**
- Current mastery per skill (0..1)
- Artifacts earned (with date)
- Operating band (current)
- Session count and total turns
- Trend: mastery trajectory over last N sessions (direction only: improving, stable, declining)
- Standing order trigger count (how often scaffolding was needed)

**Format:** Structured summary, suitable for parent/guardian review.

**Privacy:** Pseudonymous ID only. No conversation content. No behavioral inference.

### 3. Escalation Status Report

Generated on demand for a Meta Authority. Lists all pending and resolved escalations within their scope.

**Contents per escalation:**
- Escalation ID and timestamp
- Session ID and domain pack
- Trigger condition
- Current status: pending / resolved / timed_out
- Resolution (if resolved): action taken, CommitmentRecord ID
- SLA breach flag (if timed_out)

### 4. Domain Pack Health Report

Generated on demand for a Domain Authority. Reviews how their domain pack is performing across sessions.

**Contents:**
- Invariant trigger rate per invariant (critical and warning)
- Standing order exhaustion rate (how often max_attempts was reached)
- Escalation rate
- Average session sensor drift rate
- Artifact unlock rate
- Recommendations flagged (e.g., "invariant `show_work_minimum` triggers in >50% of sessions — consider reviewing its threshold")

---

## Discrepancy Resolution Workflow

A discrepancy is any situation where:
- A CTL record hash chain is broken
- An entity profile hash does not match the CTL commitment
- An escalation outcome does not match the CommitmentRecord
- A domain pack hash at session time does not match the committed hash

### Resolution Steps

1. **Detection**: The discrepancy is detected (during audit, session open, or chain verification)
2. **Record**: A `TraceEvent` with `event_type: discrepancy_detected` is appended to the CTL, including:
   - What was expected
   - What was found
   - The affected record IDs
3. **Freeze**: The affected session or domain pack is frozen (no new sessions using it)
4. **Escalate**: An `EscalationRecord` is created and sent to the Meta Authority
5. **Review**: The Meta Authority reviews the CTL records and external evidence
6. **Resolve**: The Meta Authority commits a `CommitmentRecord` with:
   - Resolution decision
   - Whether the discrepancy was a system error, misconfiguration, or security event
   - Whether sessions during the affected period are considered valid
7. **Unfreeze**: The domain pack or session scope is unfrozen if the resolution permits

### Resolution Outcomes

| Outcome | Action |
|---------|--------|
| System error (e.g., clock skew, race condition) | Mark affected records as error-context; continue operations |
| Misconfiguration (e.g., wrong pack version used) | Re-validate and re-commit the correct pack; flag sessions for review |
| Security event (e.g., record tampering) | Immediate escalation to institution security; sessions invalidated |

---

## Report Scheduling

| Report | Frequency | Triggered By |
|--------|-----------|-------------|
| Daily Session Log | Daily, automated | Session close events |
| Student Progress Report | On demand | Domain Authority or Meta Authority request |
| Escalation Status Report | On demand | Meta Authority request |
| Domain Pack Health Report | Weekly or on demand | Domain Authority request |

---

## Report Retention

Reports are derived views of the CTL — they are not independently stored. The CTL is the record of truth. Reports may be cached for performance but the cache is advisory. If a cached report and the CTL disagree, the CTL is authoritative.

---

## References

- [`audit-log-spec-v1.md`](audit-log-spec-v1.md) — audit log format
- [`../standards/causal-trace-ledger-v1.md`](../standards/causal-trace-ledger-v1.md) — CTL specification
- [`../governance/audit-and-rollback.md`](../governance/audit-and-rollback.md) — rollback procedures
