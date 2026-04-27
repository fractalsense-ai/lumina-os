---
version: "1.2.0"
last_updated: "2026-03-08"
---

# Evaluation Harness — V1

**Version:** 1.2.0  
**Status:** Active  
**Last updated:** 2026-03-08

---

## Overview

The **evaluation harness** is the test suite that enforces Project Lumina's core constraint: **measurement, not surveillance**. It verifies that implementations handle data correctly, that the System Logs is append-only and transcript-free, and that standing orders and escalation behave within their defined bounds.

---

## Test Categories

### Category 1: Transcript Non-Storage

These tests verify that no conversation content is written to any persistent store.

**TC-TNS-001: System Log write contains no transcript**
- Trigger: Simulate a 10-turn session with varied responses
- Assert: No System Log record contains a field with value longer than 512 chars outside of hash fields
- Assert: No System Log record contains any field that matches any of the simulated response strings
- Pass criterion: All assertions pass

**TC-TNS-002: Entity profile update contains no conversation**
- Trigger: Run a session, update the entity profile
- Assert: The updated profile YAML/JSON contains no fields whose values are conversation strings
- Pass criterion: All assertions pass

**TC-TNS-003: Evidence summary is structured only**
- Trigger: Generate evidence for a turn
- Assert: Turn-data/evidence summary contains only fields defined by the active domain pack for that runtime
- Assert: No additional freeform transcript or unconstrained text fields
- Pass criterion: All assertions pass

---

### Category 2: System Log Integrity

**TC-System Log-001: Append-only enforcement**
- Trigger: Attempt to modify or delete a System Log record
- Assert: Modification raises an error (at the implementation layer)
- Assert: The System Logs record remains unchanged after the attempt
- Pass criterion: Error raised, record unchanged

**TC-System Log-002: Hash chain validity**
- Trigger: Write 20 records to the System Logs
- Assert: `verify_chain(records)` returns True
- Pass criterion: Chain verified

**TC-System Log-003: Hash chain tamper detection**
- Trigger: Write 20 records, then modify one record's `decision` field
- Assert: `verify_chain(records)` returns False
- Assert: The broken record is identified by `record_id`
- Pass criterion: Tamper detected

**TC-System Log-004: Pseudonymous IDs only**
- Trigger: Write a session with a known real-name entity/subject
- Assert: No field in any System Log record contains the real name
- Assert: All actor/entity ID fields are pseudonymous tokens (format: `[a-f0-9]{32}`)
- Pass criterion: All assertions pass

**TC-System Log-005: Module policy commitment required**
- Trigger: Start a session with a module `domain-physics.json` whose hash is not committed in System Log
- Assert: Session is blocked/frozen before autonomous action
- Assert: A discrepancy or policy-mismatch event is recorded
- Pass criterion: Session does not proceed with uncommitted policy

**TC-System Log-006: Policy update requires new commitment**
- Trigger: Change module policy JSON content and version, then attempt a session without a new commitment
- Assert: Session is blocked/frozen
- Assert: Session proceeds only after updated hash commitment exists
- Pass criterion: Updated policy cannot run without updated System Log commitment

**TC-System Log-007: Turn trace includes provenance lineage hashes**
- Trigger: Run one deterministic turn in an active committed module
- Assert: At least one `TraceEvent` metadata object includes runtime provenance keys: `domain_pack_id`, `domain_pack_version`, `domain_physics_hash`, `global_prompt_hash`, `domain_prompt_hash`, `turn_interpretation_prompt_hash`, `system_prompt_hash`
- Assert: The same turn lineage includes `turn_data_hash` and `prompt_contract_hash`
- Pass criterion: Required provenance keys are present and each hash value matches SHA-256 hex format

**TC-System Log-008: Post-payload provenance hashes recorded**
- Trigger: Run one deterministic turn end-to-end through prompt contract, tool policy, and response generation
- Assert: At least one `TraceEvent` metadata object includes `tool_results_hash`, `llm_payload_hash`, and `response_hash`
- Assert: Hash values match SHA-256 hex format
- Pass criterion: Post-payload hash lineage is present and valid

---

### Category 3: Invariant and Standing Order Bounds

**TC-INV-001: Critical invariant halts autonomous action**
- Trigger: Inject a critical invariant violation
- Assert: No further autonomous actions are taken after the violation
- Assert: A standing order is invoked (if one is defined) or an escalation is created
- Pass criterion: Session frozen or standing order applied

**TC-INV-002: Standing order max_attempts enforced**
- Trigger: Trigger the same invariant violation `max_attempts + 1` times
- Assert: After `max_attempts` standing order invocations, the system escalates
- Assert: The standing order is not applied on the `max_attempts + 1`th violation
- Pass criterion: Escalation created on exhaustion

**TC-INV-003: Escalation record created on exhaust**
- Trigger: Exhaust a standing order
- Assert: An `EscalationRecord` is appended to the System Logs
- Assert: The `EscalationRecord`'s `trigger` field matches the standing order ID
- Assert: The `status` is `pending`
- Pass criterion: All assertions pass

---

### Category 4: Preferences Isolation

**TC-PREF-001: Preferences do not affect mastery update**
- Trigger: Run two otherwise-identical sessions with different preferences (interests: ["space"] vs interests: ["sports"])
- Assert: Mastery deltas are identical for identical task performance
- Pass criterion: Deltas are equal (within floating point tolerance)

**TC-PREF-002: Preferences do not affect operating band**
- Trigger: Run two otherwise-identical sessions with different preferences
- Assert: Operating band calculations are identical
- Pass criterion: Operating bands are equal

**TC-PREF-003: Preferences do not affect standing order thresholds**
- Trigger: Configure an entity/subject with preferences, trigger standing orders
- Assert: Standing order trigger thresholds are the same as for an entity with no preferences
- Pass criterion: Thresholds are equal

---

### Category 5: Domain Lib Correctness

> **Note:** This category defines universal domain-lib test patterns. Concrete domain cases (education, agriculture, clinical, etc.) belong in each domain pack's evaluation docs.

**TC-SENS-001: Minor drift detection**
- Trigger: Inject drift signals that exceed `minor_drift_threshold` inside the configured drift window
- Assert: Decision tier is `minor`
- Pass criterion: Correct tier

**TC-SENS-002: Major drift detection**
- Trigger: Inject drift signals that exceed `major_drift_threshold` inside the configured drift window
- Assert: Decision tier is `major`
- Pass criterion: Correct tier

**TC-SENS-003: No false drift inside operating band**
- Trigger: Keep operating values within the configured domain band for the full drift window
- Assert: No drift detected; decision tier is `ok`
- Pass criterion: Decision is `ok`

**TC-SENS-004: Derived instability flag from domain evidence**
- Trigger: Inject domain-specific evidence signals that should trigger instability according to active domain rules
- Assert: Domain lib's instability estimator returns `True`
- Pass criterion: Correct flag

Education example signals:
- `consecutive_incorrect: 3`, `hint_count: 3`, `frustration_marker_count: 2`

Domain-specific worked examples:
- [`../model-packs/education/evaluation-tests.md`](../model-packs/education/evaluation-tests.md)

---

### Category 6: Consent Enforcement

**TC-CON-001: Session blocked without consent**
- Trigger: Attempt to open a session with no consent record in the subject profile
- Assert: Session open fails
- Assert: An error record is created (no `CommitmentRecord` for session open)
- Pass criterion: Session blocked

**TC-CON-002: Session blocked with expired consent**
- Trigger: Attempt to open a session with a consent record older than the institution's consent expiry policy
- Assert: Session open fails or prompts re-consent
- Pass criterion: Fresh consent required

---

## Running the Harness

```bash
# Run all evaluation harness tests
python -m pytest reference-implementations/ -k "test_harness" -v

# Run a specific category
python -m pytest reference-implementations/ -k "test_harness_transcript" -v
```

The reference implementation includes test stubs that implement these test cases against domain-lib references and `reference-implementations/system-log-validator.py`. For education-specific examples, see `model-packs/education/evaluation-tests.md`.

---

## Conformance Certification

A Project Lumina implementation is considered conformant with respect to measurement-not-surveillance when all Category 1, 2, and 4 tests pass. Categories 3, 5, and 6 are domain-specific and depend on the domain pack configuration.

Conformance must be re-verified after:
- Any change to the System Logs write path
- Any change to the state update functions/domain-lib runtime logic
- Any change to the turn-interpretation or tool-adapter pipeline
- Any change to the entity profile update logic
- Any material module `domain-physics` policy update (version/hash change)
