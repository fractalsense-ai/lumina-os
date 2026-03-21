---
version: 1.0.0
last_updated: 2026-03-21
---

# Command Execution Pipeline

**Version:** 1.0.0
**Status:** Active
**Last updated:** 2026-03-21

---

## Overview

The Lumina Conversational Interface (CI) never executes state changes directly.
Every operation that mutates system or domain state travels through a
deterministic three-stage pipeline:

1. **Proposal** — the CI fills in a structured JSON schema form
2. **Validation** — a domain-scoped deterministic tool checks the proposal
3. **HITL approval** — a system-level user accepts, rejects, or modifies before execution

This document explains why that pipeline exists, how physics files fit into it,
and what each stage guarantees.

---

## The SOP Model — Physics Files as Standing Orders

Physics files (`system-physics.yaml`, `domain-physics.json`) are **standing
orders** and **escalation routes**, not execution authorities.

A standing order defines:
- **When** a condition is met (invariant check, tolerance drift, escalation trigger)
- **What** the CI must route or do next (apply a standing order, escalate to
  Meta Authority)

Physics files tell the CI *how to behave*. They do not tell the CI to *write
to disk*, *modify RBAC*, or *activate new domain versions*. That distinction is
fundamental.

> **Analogy:** A hospital's Standard Operating Procedures tell staff what to
> do when a condition is detected. The SOP does not perform the procedure — the
> authorised staff member does, after review.

---

## The Form Analogy

When a state change is needed, the CI behaves like a clerk filling in a
government form:

| Step | Who | What |
|------|-----|------|
| 1 | CI | Reads the applicable admin command schema |
| 2 | CI | Populates the JSON proposal fields from context |
| 3 | Domain tool | Validates the populated form deterministically |
| 4 | System-level user | Reviews, then accepts / rejects / modifies |
| 5 | Actuator layer | Executes the approved proposal |

The CI **fills the form**. The CI does **not** submit or execute it.

---

## Pipeline Diagram

```
  User / Domain Event
        |
        v
+--------------------+
|  CI (Proposer)     |  <-- fills JSON proposal schema
+--------------------+
        |
        v  proposal JSON
+-----------------------------+
|  Domain Deterministic Tool  |  <-- validates schema + content
|  (e.g. algebra_checker,     |
|   collar-sensor-validator)  |
+-----------------------------+
        |
        v  validated proposal
+-------------------------------+
|  Admin Staging Pipeline       |  <-- Brain -> Checkpoint -> Actuator
|  (HITL Review Gate)           |
|  accept / reject / modify     |
+-------------------------------+
        |
        v  on accept
+--------------------+
|  Actuator Layer    |  <-- executes the approved change
+--------------------+
        |
        v
  System Log  (CommitmentRecord + TraceEvent appended, hash-chained)
```

---

## Physics Files vs. Executors

| Physics file concept | Role |
|----------------------|------|
| `invariants` | Conditions the CI checks on every turn |
| `standing_orders` | Bounded responses the CI is authorised to apply |
| `escalation_triggers` | Conditions that must be handed to a human Meta Authority |
| `ci_output_contract` | Rules governing what the CI may output |
| `execution_policy.deterministic_tools` | Tools that must validate proposals in this domain |

None of these grant the CI write access to the filesystem, RBAC table,
domain physics store, or any other mutable system resource.

---

## Domain-Scoped Deterministic Tools

Validation is performed by **domain-scoped deterministic tools** — not
system-wide LLM judgment. Each domain pack declares which tool(s) are
responsible:

| Domain | Deterministic tool |
|--------|--------------------|
| `education/*` | `adapter/edu/algebra-checker/v1` |
| `agriculture/operations-level-1` | `adapter/agri/collar-sensor/v1` |
| `system/*` | system admin command schema validator |

A deterministic tool returns a binary pass/fail verdict and a structured
error report. Only proposals that pass proceed to the HITL gate.

---

## HITL as the Universal Gate

The Human-in-the-Loop (HITL) review gate is **universal**. No domain, role, or
runtime condition may bypass it for state-changing operations. This is
enforced by:

- `system-physics.yaml` invariant `no_direct_execution` (severity: `critical`)
- `ci_output_contract.proposal_approval_requirement: hitl_required_before_execution`
- The admin staging pipeline (`src/lumina/api/routes/admin.py`), which holds
  proposals in a `staged_commands` store (TTL 300 s) until a system-level user
  acts via `_HITL_VALID_ACTIONS: {accept, reject, modify}`

### What HITL covers

All 16 admin operations, including but not limited to:
- Domain physics activation / deactivation
- RBAC role and permission changes
- System physics updates
- Domain pack installation and removal
- Audit log access and export

---

## Logging

Every completed pipeline run produces two append-only, hash-chained ledger
entries in the System Log:

| Record type | Written when |
|-------------|-------------|
| `CommitmentRecord` | HITL accept triggers actuator execution |
| `TraceEvent` | Each orchestrator turn that produced a proposal |

These records are write-once and form the audit trail linking every executed
change back to the validated proposal and the human who approved it.

---

## References

- [`cfg/system-physics.yaml`](../../cfg/system-physics.yaml) — invariant `no_direct_execution`; `ci_output_contract` execution policy fields
- [`standards/system-physics-schema-v1.json`](../../standards/system-physics-schema-v1.json) — JSON schema for `ci_output_contract`
- [`standards/domain-physics-schema-v1.json`](../../standards/domain-physics-schema-v1.json) — `execution_policy` property schema
- [`specs/dsa-framework-v1.md`](../../specs/dsa-framework-v1.md) — Action Constraints, "may NOT" list
- [`specs/global-system-prompt-v1.md`](../../specs/global-system-prompt-v1.md) — Layer 3 Command Execution Policy
- [`specs/orchestrator-system-prompt-v1.md`](../../specs/orchestrator-system-prompt-v1.md) — COMMAND EXECUTION DIRECTIVE
- [`docs/7-concepts/file-generation-staging.md`](file-generation-staging.md) — three-phase Brain/Checkpoint/Actuator pipeline
- [`src/lumina/api/routes/admin.py`](../../src/lumina/api/routes/admin.py) — HITL implementation
