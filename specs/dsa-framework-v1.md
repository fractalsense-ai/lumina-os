# D.S.A. Framework — V1 Specification

**Version:** 1.3.0  
**Status:** Active  
**Last updated:** 2026-03-21

> **Relationship to PPA:** The D.S.A. Framework is the *structural contract schema* that the Prompt Packet Assembly (PPA) engine uses to assemble each prompt packet. D.S.A. defines the three-pillar model (Domain, State, Actor) that governs what goes into the packet; PPA is the mechanism that reads those pillars and produces the assembled `prompt_contract` sent to the LLM. See [`docs/7-concepts/prompt-packet-assembly.md`](../docs/7-concepts/prompt-packet-assembly.md) for the PPA assembly process.

---

## Overview

The **D.S.A. Framework** is the structural foundation of all Project Lumina orchestration systems. Every Lumina session is governed by exactly three components:

| Pillar | Name | Mutability | Owner |
|--------|------|------------|-------|
| **D** | **Domain** | Immutable per session | Domain Authority (human) |
| **S** | **State** | Mutable, updated from evidence | Orchestrator + Entity |
| **A** | **Actor** | Context-dependent per domain | Domain Authority (defined) |

---

## D — Domain

The Domain is the **immutable ruleset** for a session. It is authored by the Domain Authority before the session begins. The orchestrator may not modify the Domain during a session.

### Domain Components

**Invariants** — conditions that must always hold:
- `critical` severity: violation halts autonomous action immediately
- `warning` severity: violation triggers a standing order
- Each invariant has an explicit check description and a designated response

**Standing Orders** — bounded automated responses the orchestrator may take:
- Defined in advance by the Domain Authority
- Have explicit `max_attempts` limits
- Must escalate when exhausted (`escalation_on_exhaust: true`)
- Action vocabulary is domain-defined (education, agriculture, medical, and others)

**Escalation Triggers** — conditions causing the system to pass control to the Meta Authority:
- Named conditions are domain-defined
- Target role (who receives the escalation)
- SLA for acknowledgement

**Artifacts** — domain-defined outcome items that can be earned or recorded:
- Defined by unlock conditions and domain thresholds
- Used for assessment and accountability, not surveillance

**Subsystem Configuration** — domain-specific parameters keyed by subsystem ID in `subsystem_configs`:
- Parameters are interpreted by the active domain lib
- Typical controls include tolerance-band bounds, drift windows, and escalation thresholds
- The engine treats subsystem configuration as opaque; each domain lib interprets semantics

### Domain Pack Format

Domains are authored in YAML (human-readable) and converted to JSON (machine-queryable) using the `yaml-to-json-converter.py` reference tool. Both files are committed to Git; the JSON is the authoritative machine-readable form.

The domain pack's current hash must be committed to the System Logs as a `CommitmentRecord` before the pack is used operationally.
At runtime, session startup should enforce this as a gate: if the active module hash has no matching commitment, autonomous execution is blocked.
Material domain-policy updates require semantic version update, YAML->JSON regeneration, and a new System Log commitment of the updated JSON hash before activation.

---

## S — State

The State is the **mutable entity profile** — a compressed representation of what the orchestrator currently believes about the entity being served. It is updated incrementally from structured evidence after each interaction turn. The specific state fields are defined by each domain's subject state schema; the engine treats domain-lib state as opaque.

### State Components

The state fields populated in any given session depend entirely on the domain's subject state schema. Core D.S.A. does not prescribe human-specific or domain-specific variables.

**Observed Signals:**
- Domain-defined measurements and derived indicators (numeric or categorical)
- Updated from structured evidence through the domain lib

**Tolerance Band (domain-defined):**
- Lower and upper bounds defining acceptable operating range
- Compared against current observed signals to detect drift
- Populated and interpreted by the domain lib; the engine does not interpret signal semantics directly

**Recent Window:**
- Rolling `window_turns` history for drift persistence checks
- Tracks domain-relevant counts, ratios, and deviation patterns

**Uncertainty:**
- `uncertainty` (0..1) captures confidence in the current state estimate
- Domain packs may define additional confidence or quality fields

Additional state fields may be defined by the domain's subject state schema and populated by domain libs.

### Turn Data Inputs

State is never inferred from raw conversation content. Turn data is a structured summary emitted by authorized tool adapters and domain turn-interpretation runtime paths.

```json
{
  "signal_id": "domain_metric_name",
  "signal_value": 0.72,
  "within_tolerance": false,
  "latency_sec": 12.4,
  "source": "tool_adapter_id"
}
```

Each domain defines its own evidence schema and runtime pipeline (for example, agriculture and medical domains use different fields and thresholds).

### State Storage

- The compressed state is stored in the entity profile (YAML)
- A hash of the state is committed to the System Logs as part of each `TraceEvent`
- The full state object is not stored in the System Logs (only its hash)

---

## A — Actor

The **Actor** is whatever changes the state of the system relative to a given domain. Actors are context-dependent: in an education domain the Actor may be a student; in agriculture it may be a pH sensor, a farmer operating equipment, or a weather station. The Domain Authority defines which entities qualify as Actors in the domain pack.

The AI orchestrator is **not** an Actor — it is an executor and translator that mediates between the DSA pillars. Its pipeline is: sensor → domain logic → module action → actuator → feedback → system state.

The orchestrator's role with respect to Actor-generated evidence is to:
1. Observe incoming evidence (produced by Actors)
2. Update the State
3. Check the Domain's invariants
4. Select a response within the Domain's standing orders
5. Escalate when it cannot stabilize

### Orchestrator Constraints

**The orchestrator may ONLY:**
- Apply standing orders defined in the current Domain
- Issue one bounded probe per drift detection cycle
- Call tool adapters authorized in the Domain
- Escalate to the Meta Authority per the escalation triggers

**The orchestrator may NOT:**
- **Execute state changes directly** — all state-changing commands (domain-physics updates, RBAC modifications, system configuration changes) must be expressed as structured JSON proposal schemas, validated by the applicable domain deterministic tool, and approved by a system-level user via the HITL review gate (accept / reject / modify) before the actuator layer executes them
- Override or modify Domain invariants
- Store transcripts
- Use preferences or profile metadata to alter invariant checks, tolerance evaluation, or escalation policy
- Issue probes more frequently than one per drift event
- Expand the scope of the session without explicit escalation and Meta Authority approval

### Decision Tiers

The orchestrator's decisions follow a tiered response model:

| Tier | Condition | Response |
|------|-----------|----------|
| `ok` | Within tolerance band, no invariant violations | Continue normally |
| `minor` | Minor tolerance drift or warning invariant | Apply the standing order defined for this tier |
| `major` | Major tolerance drift or critical invariant | Apply the standing order defined for this tier |
| `escalate` | Standing orders exhausted or escalation policy triggered | Assemble `EscalationRecord`, freeze, notify Meta Authority |

### Grounding Contract

Every response that uses retrieved content must cite the retrieved artifact by ID and version. If required context cannot be retrieved, the orchestrator must escalate rather than hallucinate.

---

## Interaction Loop

One turn of a D.S.A. session:

```
1. [Domain] Domain Physics loaded and hash-verified
2. [State] Entity profile loaded; compressed state available
3. [Actor] Actor produces input or evidence (within tolerance band)
4. [Runtime] Structured signals/evidence produced by authorized tool adapters
5. [State] Domain-lib runtime updates machine-readable state summaries from structured signals
6. [Domain/Orchestrator] Orchestrator evaluates module invariants and state signals, then resolves standing order/escalation decisions
7. [Orchestrator] Decision tier calculated: ok / minor / major / escalate
8. [Orchestrator] Standing order applied if needed
9. [System Log] TraceEvent appended (state hash + decision + evidence summary + provenance hash lineage)
10. [Orchestrator] Response generated (grounded, within Domain scope)
11. [Actor] Actor receives response and acts
12. -> repeat from step 3
```

Provenance hash lineage fields recorded in System Log metadata (when applicable):
- Runtime policy/prompt hashes: `domain_physics_hash`, `global_prompt_hash`, `domain_prompt_hash`, `turn_interpretation_prompt_hash`, `system_prompt_hash`
- Runtime policy identity: `domain_pack_id`, `domain_pack_version`
- Turn/prompt hashes: `turn_data_hash`, `prompt_contract_hash`
- Post-payload hashes: `tool_results_hash`, `llm_payload_hash`, `response_hash`

---

## Worked Example

See [`../examples/README.md`](../examples/README.md) for a complete walkthrough of one interaction loop using the Algebra Level 1 domain pack.

---

## Legacy Terminology Note

Earlier documents may use `sensor` where this spec now uses `domain lib`. In this architecture, those terms refer to the same domain-specific state-estimation and drift-detection layer.

---

## References

- [`../standards/lumina-core-v1.md`](../standards/lumina-core-v1.md) — conformance requirements
- [`../standards/domain-physics-schema-v1.json`](../standards/domain-physics-schema-v1.json) — Domain schema
- [`../domain-packs/education/schemas/compressed-state-schema-v1.json`](../domain-packs/education/schemas/compressed-state-schema-v1.json) — education domain subject state schema (example)
- [`../domain-packs/education/reference-implementations/zpd-monitor-v0.2.py`](../domain-packs/education/reference-implementations/zpd-monitor-v0.2.py) — education domain lib reference implementation (example)
