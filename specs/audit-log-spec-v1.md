# Audit Log Specification — V1

**Version:** 1.1.0  
**Status:** Active  
**Last updated:** 2026-03-05

---

## Overview

The **audit log** is the human-readable view of the Causal Trace Ledger (CTL). While the CTL is a machine-readable append-only record store, the audit log is the structured report produced for governance review, compliance audits, and discrepancy resolution.

This document specifies what the audit log contains, who may request it, and how it is generated.

---

## Relationship to the CTL

The audit log is not a separate store. It is a **view** generated from CTL records on demand. The CTL is the authoritative source; the audit log is derived.

```
CTL (append-only, machine-readable)
    ↓ audit log generator
Audit Log (human-readable structured report)
```

The audit log may be generated at any time by a party with appropriate audit rights. Generating an audit log does not modify the CTL.

---

## Audit Log Contents

An audit log report for a session contains:

```
Session Audit Log
=================
Session ID:     <uuid>
Entity ID:      <pseudonymous-token>
Domain Pack:    algebra-level-1 v0.2.0
Domain Authority: <pseudonymous-token>
Session Open:   2026-03-05T10:00:00Z
Session Close:  2026-03-05T10:45:22Z
Total Turns:    18

Consent Record
--------------
Consent Accepted:      true
Consent Version:       1.0.0
Consent Timestamp:     2026-03-02T09:59:43Z

Domain Pack Commitment
----------------------
CommitmentRecord ID: <uuid>
Domain Pack Hash:    <sha256>
Committed At:        2026-03-01T08:00:00Z

Invariant Check Log
-------------------
Turn  4: equivalence_preserved — PASS
Turn  7: equivalence_preserved — FAIL → standing_order: request_more_steps (attempt 1/3)
Turn  8: equivalence_preserved — PASS

Standing Order Log
------------------
Turn  7: request_more_steps applied (attempt 1/3)

State Drift Log *(domain-defined signal names)*
-------------
Turn 11: challenge=0.78, challenge_band=[0.3, 0.7] → OUTSIDE (above)
Turn 12: challenge=0.75, challenge_band=[0.3, 0.7] → OUTSIDE (above)
Turn 13: challenge=0.72, challenge_band=[0.3, 0.7] → OUTSIDE (above)
Turn 13: Minor drift detected (3/10 turns outside) → domain standing order applied

Outcome Records
---------------
Task: linear_equations_one_variable_set_1 → partial (score: 0.65)
Task: linear_equations_one_variable_set_2 → pass (score: 0.88)

Mastery Deltas
--------------
solve_one_variable:    0.52 → 0.61
check_equivalence:     0.45 → 0.50
show_work_steps:       0.60 → 0.63

Escalations
-----------
None

Chain Integrity
---------------
Records verified: 23
Chain intact: YES
```

### What the Audit Log Does NOT Contain

- Conversation content
- Verbatim entity/subject responses
- Any information beyond structured telemetry

---

## Audit Rights

| Role | Scope |
|------|-------|
| Subject/Target (e.g., student, patient, operator) | Their own sessions only; structured summary format |
| Micro Authority / Domain Authority (e.g., teacher, clinician) | All sessions in their domain |
| Meta Authority (e.g., department head, supervising officer) | All sessions in their scope |
| Administration | All sessions institution-wide |

Audit requests outside the requestor's scope must be rejected and the rejection recorded as a `TraceEvent` in the CTL.

---

## Audit Log Generation

The audit log generator reads from the CTL and:
1. Verifies the hash chain for the requested session's records
2. Extracts the structured fields from each record
3. Formats them as a human-readable report
4. Appends a `TraceEvent` to the CTL noting that an audit was generated (who requested it, for which session)

The audit log itself is not stored — it is generated fresh each time from the CTL.

---

## Chain Integrity Check

Every audit log generation includes a chain integrity check:
- Walk all records for the session in order
- Verify `prev_record_hash` for each record
- Report `Chain intact: YES` or `Chain BROKEN at record <uuid>`

A broken chain is a reportable event requiring immediate escalation to the Meta Authority.

---

## Audit Trail of Audits

Every audit request is itself recorded as a `TraceEvent`:

```json
{
  "record_type": "TraceEvent",
  "event_type": "audit_requested",
  "session_id": "<session-being-audited>",
  "actor_id": "<pseudonymous-id-of-auditor>",
  "decision": "audit_log_generated",
  "metadata": {
    "requested_session": "<uuid>",
    "requested_by_role": "teacher"
  }
}
```

This ensures that even audits are themselves auditable.

---

## Discrepancy Resolution

If an audit reveals a discrepancy (e.g., a record that doesn't match expected behavior, a broken chain, or a missing record), the resolution process is:

1. Document the discrepancy in a `TraceEvent` with `event_type: discrepancy_detected`
2. Escalate to the Meta Authority via an `EscalationRecord`
3. Do not modify the CTL
4. The Meta Authority reviews and commits a resolution `CommitmentRecord`

See [`../specs/reports-spec-v1.md`](reports-spec-v1.md) for the full discrepancy resolution workflow.
