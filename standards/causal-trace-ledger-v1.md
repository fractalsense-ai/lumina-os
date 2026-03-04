# Causal Trace Ledger (CTL) — V1 Specification

**Version:** 1.0.0  
**Status:** Active  
**Last updated:** 2026-03-02

---

## Overview

The **Causal Trace Ledger (CTL)** is the append-only accountability layer for all Project Lumina sessions. It records what happened and what the system decided — not what was said.

**Core constraint:** The CTL does not store transcripts. It stores structured decision telemetry, hashes of content, and pointers to external (encrypted, ephemeral) stores.

The CTL exists for diagnosis, not accusation. Its purpose is to enable:
- Post-hoc audit of system decisions
- Escalation packet assembly
- Domain Authority review of session outcomes
- Compliance verification

---

## Design Principles

1. **Append-only**: Records are never modified or deleted. Corrections are new records that reference the prior record.
2. **Hash-chained**: Each record includes the SHA-256 hash of the previous record in the ledger, enabling tamper detection.
3. **No transcripts at rest**: Raw conversation content is never written to the CTL. Content-bearing fields store hashes + pointers only.
4. **Pseudonymous**: Actor identifiers are pseudonymous tokens. Real-identity mapping is held by the institution in a separate, access-controlled system.
5. **Structured telemetry only**: All values in CTL records are machine-parseable structured fields.

---

## Record Types

### 1. CommitmentRecord

Records a deliberate commitment by a Domain Authority (human or system acting under explicit authorization).

```json
{
  "record_type": "CommitmentRecord",
  "record_id": "<uuid>",
  "prev_record_hash": "<sha256-hex>",
  "timestamp_utc": "<ISO-8601>",
  "actor_id": "<pseudonymous-token>",
  "actor_role": "domain_authority | meta_authority | orchestrator",
  "commitment_type": "domain_pack_activation | policy_change | escalation_resolution | session_open | session_close",
  "subject_id": "<uuid-of-subject-domain-pack-or-session>",
  "subject_version": "<semver>",
  "subject_hash": "<sha256-hex-of-subject-content>",
  "summary": "<human-readable one-line description>",
  "metadata": {}
}
```

**When to emit:**
- Domain pack activated (first use after version change)
- Policy change committed by Meta Authority
- Escalation resolved by Meta Authority
- Session opened or closed

---

### 2. TraceEvent

Records a single decision or observation during an active session.

```json
{
  "record_type": "TraceEvent",
  "record_id": "<uuid>",
  "prev_record_hash": "<sha256-hex>",
  "timestamp_utc": "<ISO-8601>",
  "session_id": "<uuid>",
  "actor_id": "<pseudonymous-token>",
  "event_type": "invariant_check | standing_order_applied | zpd_drift_detected | probe_issued | state_update | tool_call | outcome_recorded",
  "invariant_id": "<string | null>",
  "standing_order_id": "<string | null>",
  "decision": "<string>",
  "evidence_summary": {
    "correctness": "<correct | incorrect | partial | null>",
    "hint_used": "<boolean | null>",
    "response_latency_sec": "<float | null>",
    "frustration_marker_count": "<int | null>",
    "repeated_error": "<boolean | null>",
    "off_task_ratio": "<float | null>"
  },
  "state_snapshot_hash": "<sha256-hex-of-compressed-state>",
  "metadata": {}
}
```

**When to emit:**
- Invariant check result (pass or fail)
- Standing order applied
- ZPD drift detected
- Probe issued to learner
- State update committed
- Tool called and returned
- Outcome recorded (task completed)

---

### 3. ToolCallRecord

Records a single external tool invocation.

```json
{
  "record_type": "ToolCallRecord",
  "record_id": "<uuid>",
  "prev_record_hash": "<sha256-hex>",
  "timestamp_utc": "<ISO-8601>",
  "session_id": "<uuid>",
  "tool_adapter_id": "<string>",
  "tool_adapter_version": "<semver>",
  "call_type": "<string>",
  "input_hash": "<sha256-hex-of-structured-input>",
  "output_hash": "<sha256-hex-of-structured-output>",
  "success": "<boolean>",
  "latency_ms": "<int>",
  "metadata": {}
}
```

**When to emit:**
- Any call to an external tool adapter

---

### 4. OutcomeRecord

Records the outcome of a task or artifact attempt.

```json
{
  "record_type": "OutcomeRecord",
  "record_id": "<uuid>",
  "prev_record_hash": "<sha256-hex>",
  "timestamp_utc": "<ISO-8601>",
  "session_id": "<uuid>",
  "student_id": "<pseudonymous-token>",
  "task_id": "<string>",
  "task_version": "<semver>",
  "outcome": "pass | partial | fail | abandoned",
  "mastery_delta": {"<skill_id>": "<float>"},
  "artifact_earned": "<artifact_id | null>",
  "evidence_summary_hash": "<sha256-hex>",
  "metadata": {}
}
```

**When to emit:**
- Task or artifact attempt concluded

---

### 5. EscalationRecord

Records an escalation event — when the orchestrator could not stabilize and passed control upward.

```json
{
  "record_type": "EscalationRecord",
  "record_id": "<uuid>",
  "prev_record_hash": "<sha256-hex>",
  "timestamp_utc": "<ISO-8601>",
  "session_id": "<uuid>",
  "escalating_actor_id": "<pseudonymous-token>",
  "target_meta_authority_id": "<pseudonymous-token>",
  "trigger": "<string>",
  "trigger_standing_order_id": "<string | null>",
  "evidence_summary": {},
  "decision_trail_hashes": ["<sha256>"],
  "proposed_action": "<string | null>",
  "resolution_commitment_id": "<uuid | null>",
  "status": "pending | resolved | timed_out",
  "metadata": {}
}
```

**When to emit:**
- Orchestrator exhausts all standing orders without stabilization
- Critical invariant is violated and no standing order covers it
- ZPD drift is major and unresolved

---

## Hash Chaining

The first record in a ledger uses `"prev_record_hash": "genesis"`. Each subsequent record sets `prev_record_hash` to the SHA-256 hex digest of the full JSON serialization of the previous record (canonical JSON: keys sorted, no whitespace).

To verify the chain:

```python
import hashlib, json

def canonical(record: dict) -> bytes:
    return json.dumps(record, sort_keys=True, separators=(',', ':')).encode('utf-8')

def verify_chain(records: list) -> bool:
    for i, record in enumerate(records):
        if i == 0:
            assert record['prev_record_hash'] == 'genesis'
        else:
            expected = hashlib.sha256(canonical(records[i-1])).hexdigest()
            if record['prev_record_hash'] != expected:
                return False
    return True
```

---

## Privacy Requirements

- **No raw text**: Content fields must use hashes + external pointers, not inline text
- **Pseudonymous IDs only**: `actor_id`, `student_id` are pseudonymous tokens
- **Evidence summary only**: `evidence_summary` uses structured fields (correctness, latency, etc.) — not quotes from the learner
- **Mastery deltas only**: `mastery_delta` records how mastery changed, not what was said

---

## Retention Policy

CTL records are retained for the duration of the institution's data retention policy, as set by the Meta Authority. Minimum retention is 90 days for audit purposes. The CTL may be archived but not deleted during the retention window.

---

## Related Schemas

- [`../ledger/causal-trace-ledger-schema-v1.json`](../ledger/causal-trace-ledger-schema-v1.json)
- [`../ledger/commitment-record-schema.json`](../ledger/commitment-record-schema.json)
- [`../ledger/trace-event-schema.json`](../ledger/trace-event-schema.json)
- [`../ledger/escalation-record-schema.json`](../ledger/escalation-record-schema.json)
