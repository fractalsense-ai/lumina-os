# Audit and Rollback Policy — Project Lumina

**Version:** 1.0.0  
**Status:** Active  
**Last updated:** 2026-03-02

---

## Overview

This document specifies audit procedures and rollback policy for Project Lumina. It governs how System Log records are reviewed, how discrepancies are handled, and what rollback means in an append-only system.

---

## Audit Procedures

### Who May Audit

| Role | May Audit |
|------|----------|
| Subject/Target | Their own sessions only |
| Domain Authority | All sessions in their governed domains |
| Meta Authority | All sessions governed by their subordinate Domain Authorities |
| Administration | All sessions institution-wide |
| External Auditor | As defined by Meta Authority policy; scope-limited |

### Audit Request Process

1. **Request**: The auditor submits an audit request specifying the scope (session ID, date range, domain pack, or subject ID)
2. **Authorization check**: The system verifies the requestor's scope against their role
3. **Generation**: The audit log generator reads from the System Logs and produces the report
4. **System Log record**: A `TraceEvent` with `event_type: audit_requested` is appended to the System Logs
5. **Delivery**: The report is delivered to the auditor via the authorized channel

### What Audits Produce

Audit reports contain structured telemetry only:
- Decision summaries
- Invariant check results
- Standing order invocations
- State drift detections
- Mastery deltas
- Escalation records
- Chain integrity check result

Audits do not produce:
- Conversation transcripts
- Raw subject responses
- PII beyond pseudonymous identifiers

### Audit Frequency

| Report Type | Minimum Frequency |
|-------------|------------------|
| Domain Pack Health Report | Weekly |
| Escalation Status Review | After each escalation resolution |
| Full Session Audit | Triggered by discrepancy or on request |
| Chain Integrity Scan | Monthly (automated) |

---

## Hash Chain Integrity Verification

The System Logs hash chain must be verified periodically to detect tampering.

### Automated Scan

An automated scan should run monthly (minimum) against the full System Log:

```bash
python reference-implementations/system-log-validator.py \
  --verify-chain path/to/ledger.jsonl \
  --report path/to/integrity-report.json
```

### Manual Verification

For spot-checking individual sessions:

```bash
python reference-implementations/system-log-validator.py \
  --verify-session <session-id> \
  --ledger path/to/ledger.jsonl
```

### Handling a Broken Chain

If the chain integrity check fails:

1. **Freeze**: Immediately freeze the affected domain(s) — no new sessions
2. **Record**: Append a `TraceEvent` with `event_type: chain_integrity_failure` to the System Logs
3. **Escalate**: Create an `EscalationRecord` to the highest available Meta Authority
4. **Preserve**: Do not modify the System Logs — preserve it exactly as found
5. **Investigate**: Determine the cause (system error, misconfiguration, or tampering)
6. **Resolve**: Meta Authority commits a `CommitmentRecord` with resolution decision

---

## Rollback Policy

### What Rollback Means in an Append-Only System

The System Logs is **append-only**. Rollback does not mean deleting records. It means:
- Appending a new `CommitmentRecord` that declares the prior version to be superseded
- Marking the relevant records as part of a superseded context
- Resuming operations under the corrected context

### Domain Pack Rollback

If a domain pack version has a defect:

1. The Domain Authority authors a corrected version (new semver)
2. A `CommitmentRecord` is appended: `commitment_type: domain_pack_rollback`, referencing the prior version's record and the new version
3. Sessions started after this CommitmentRecord use the new version
4. Sessions started before this CommitmentRecord retain their original domain pack hash in their System Log records

Domain pack rollback does **not** retroactively change the outcome of prior sessions. Those sessions operated under the prior version — that is the correct historical record.

### Subject Profile Rollback

In rare cases, a subject profile may need to be rolled back (e.g., a bug caused incorrect state updates):

1. The Domain Authority (or Meta Authority) identifies the correct prior state
2. The corrected state is written to the profile
3. A `CommitmentRecord` is appended: `commitment_type: profile_correction`, referencing the affected session(s) and explaining the correction
4. The correction is noted in the session audit log for the affected sessions

Profile rollback requires Meta Authority approval and is recorded in the System Logs.

### What Cannot Be Rolled Back

- System Log records themselves cannot be deleted or modified
- A session that occurred cannot be declared to not have occurred
- An artifact earned during a valid session cannot be revoked (though it can be noted as "awarded during corrected period" in a subsequent CommitmentRecord)

---

## Security Events

A security event is any situation where the System Logs integrity is intentionally compromised, PII is exposed, or the system is operated outside its consent boundaries.

Security event response:

1. **Immediate freeze**: All sessions institution-wide
2. **Preserve**: System Log is preserved exactly as found (no modifications)
3. **Notify**: Institution security team and Meta Authority are notified immediately
4. **Forensics**: The integrity scan is run and the full scope of the compromise is determined
5. **Remediation**: The compromised layer is rebuilt from trusted state
6. **Re-verification**: Chain integrity is re-verified end-to-end before sessions resume
7. **Post-incident record**: A `CommitmentRecord` is appended summarizing the incident and remediation

---

## References

- [`../standards/system-log-v1.md`](../standards/system-log-v1.md) — System Log specification
- [`../specs/audit-log-spec-v1.md`](../specs/audit-log-spec-v1.md) — audit log format
- [`../specs/reports-spec-v1.md`](../specs/reports-spec-v1.md) — report types and discrepancy workflow
- [`../reference-implementations/system-log-validator.py`](../reference-implementations/system-log-validator.py) — chain verification tool
