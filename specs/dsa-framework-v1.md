# D.S.A. Framework — V1 Specification

**Version:** 1.0.0  
**Status:** Active  
**Last updated:** 2026-03-02

---

## Overview

The **D.S.A. Framework** is the structural foundation of all Project Lumina orchestration systems. Every Lumina session is governed by exactly three components:

| Pillar | Name | Mutability | Owner |
|--------|------|------------|-------|
| **D** | **Domain** | Immutable per session | Domain Authority (human) |
| **S** | **State** | Mutable, updated from evidence | Orchestrator + Entity |
| **A** | **Action** | Bounded by Domain | Orchestrator |

---

## D — Domain

The Domain is the **immutable ruleset** for a session. It is authored by the Domain Authority (a human expert: teacher, coach, doctor, etc.) before the session begins. The orchestrator may not modify the Domain during a session.

### Domain Components

**Invariants** — conditions that must always hold:
- `critical` severity: violation halts autonomous action immediately
- `warning` severity: violation triggers a standing order
- Each invariant has an explicit check description and a designated response

**Standing Orders** — bounded automated responses the orchestrator may take:
- Defined in advance by the Domain Authority
- Have explicit `max_attempts` limits
- Must escalate when exhausted (`escalation_on_exhaust: true`)
- Examples (education domain): `zpd_scaffold`, `request_more_steps`, `zpd_intervene_or_escalate`

**Escalation Triggers** — conditions causing the system to pass control to the Meta Authority:
- Named conditions (e.g., `major_zpd_drift_unresolved` in the education domain)
- Target role (who receives the escalation)
- SLA for acknowledgement

**Artifacts** — mastery items that can be earned:
- Defined by unlock conditions and mastery thresholds
- Used for assessment, not surveillance

**Subsystem Configuration** — domain-specific sensor parameters, keyed by subsystem ID in `subsystem_configs`:
- Parameters are defined per-domain (e.g., `min_challenge`, `max_challenge`, `drift_window_turns` for the education domain's ZPD monitor; equivalent fields for other domain sensors)
- `minor_drift_threshold`, `major_drift_threshold` — fraction of window triggering minor/major drift
- The engine treats subsystem configuration as opaque; each domain sensor interprets its own parameters

### Domain Pack Format

Domains are authored in YAML (human-readable) and converted to JSON (machine-queryable) using the `yaml-to-json-converter.py` reference tool. Both files are committed to Git; the JSON is the authoritative machine-readable form.

The domain pack's current hash must be committed to the CTL as a `CommitmentRecord` before the pack is used operationally.

---

## S — State

The State is the **mutable entity profile** — a compressed representation of what the orchestrator currently believes about the entity being served. It is updated incrementally from structured evidence after each interaction turn. The specific state fields are defined by each domain's subject state schema; the engine treats sensor state as opaque.

### State Components

The state fields populated in any given session depend entirely on the domain's subject state schema. The following are the components defined in the **education domain** (provided as an illustrative example):

**Affect (SVA triad):**
- `salience` (0..1) — engagement and focus
- `valence` (-1..1) — emotional tone (negative to positive)
- `arousal` (0..1) — activation level (flat to frantic)

**Mastery:**
- Per-skill mastery estimates (0..1 per skill defined in the Domain)
- Updated from evidence: correctness, hint usage, response patterns

**Operating Band (education: ZPD Band):**
- `min_challenge`, `max_challenge` — the entity's current optimal operating range, as defined by the domain sensor (e.g., Zone of Proximal Development in education)
- Compared against the challenge level of the current task to detect drift
- This field is populated and interpreted by the domain sensor; the engine does not read it directly

**Recent Window:**
- Rolling window of `window_turns` turns
- Tracks: attempts, consecutive incorrect, hint count, outside_pct, consecutive_outside
- Used for drift detection and frustration estimation

**Challenge and Uncertainty:**
- `challenge` (0..1) — estimated difficulty of current task
- `uncertainty` (0..1) — orchestrator's confidence in the state estimate

Additional state fields may be defined by the domain's subject state schema and populated by its sensor array.

### Evidence Inputs

State is never inferred from conversation content. Evidence is a structured summary:

```json
{
  "correctness": "correct | incorrect | partial",
  "hint_used": true,
  "response_latency_sec": 12.4,
  "frustration_marker_count": 0,
  "repeated_error": false,
  "off_task_ratio": 0.0
}
```

Evidence summaries are provided by the Domain's tool adapters or by the orchestrator's observation layer, not by reading raw text.

### State Storage

- The compressed state is stored in the entity profile (YAML)
- A hash of the state is committed to the CTL as part of each `TraceEvent`
- The full state object is not stored in the CTL (only its hash)

---

## A — Action

The Action layer is the **orchestrator** — the AI component that drives the session. Its role is to:
1. Observe incoming evidence
2. Update the State
3. Check the Domain's invariants
4. Select a response within the Domain's standing orders
5. Escalate when it cannot stabilize

### Action Constraints

**The Action layer may ONLY:**
- Apply standing orders defined in the current Domain
- Issue one probe per drift detection (minimal probing principle)
- Call tool adapters authorized in the Domain
- Escalate to the Meta Authority per the escalation triggers

**The Action layer may NOT:**
- Override or modify Domain invariants
- Store transcripts
- Use preferences data for grading or mastery assessment
- Issue probes more frequently than one per drift event
- Expand the scope of the session without explicit escalation and Meta Authority approval

### Decision Tiers

The orchestrator's decisions follow a tiered response model:

| Tier | Condition | Response |
|------|-----------|----------|
| `ok` | Within operating band, no invariant violations | Continue normally |
| `minor` | Minor sensor drift or warning invariant | Apply the standing order defined for this tier |
| `major` | Major sensor drift or critical invariant | Apply the standing order defined for this tier |
| `escalate` | Standing orders exhausted, system cannot stabilize | Assemble `EscalationRecord`, freeze, notify Meta Authority |

### Grounding Contract

Every response that uses retrieved content must cite the retrieved artifact by ID and version. If required context cannot be retrieved, the orchestrator must escalate rather than hallucinate.

---

## Interaction Loop

One turn of a D.S.A. session:

```
1. [Domain] Domain Physics loaded and hash-verified
2. [State] Entity profile loaded; compressed state available
3. [Action] Task presented to entity (within operating bounds)
4. [Entity] Entity responds
5. [Action] Evidence summary extracted (tool adapters)
6. [State] State updated via domain sensor
7. [Domain] Invariant checks run against updated state + evidence
8. [Action] Decision tier calculated: ok / minor / major / escalate
9. [Action] Standing order applied if needed
10. [CTL] TraceEvent appended (state hash + decision + evidence summary)
11. [Action] Response generated (grounded, within Domain scope)
12. → repeat from step 3
```

---

## Worked Example

See [`../examples/README.md`](../examples/README.md) for a complete walkthrough of one interaction loop using the Algebra Level 1 domain pack.

---

## References

- [`../standards/lumina-core-v1.md`](../standards/lumina-core-v1.md) — conformance requirements
- [`../standards/domain-physics-schema-v1.json`](../standards/domain-physics-schema-v1.json) — Domain schema
- [`../domain-packs/education/schemas/compressed-state-schema-v1.json`](../domain-packs/education/schemas/compressed-state-schema-v1.json) — Education domain subject state schema (example)
- [`../domain-packs/education/reference-implementations/zpd-monitor-v0.2.py`](../domain-packs/education/reference-implementations/zpd-monitor-v0.2.py) — education domain sensor reference implementation
