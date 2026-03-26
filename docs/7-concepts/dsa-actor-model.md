---
version: 1.0.0
last_updated: 2026-03-23
---

# D.S.A. Actor Model

**Version:** 1.0.0
**Status:** Active
**Last updated:** 2026-03-23

---

## Purpose

This document defines the **Actor** pillar of the D.S.A. Framework in operational
detail: what an Actor is, how Actors are typed and grouped, how evidence flows through
Actors into State, and how the Actor model differs from RBAC roles.

For the full three-pillar contract see
[`dsa-framework-v1`](../../specs/dsa-framework-v1.md).

---

## What Is an Actor?

An Actor is **whatever changes the state of the system relative to a given domain**.
Actors are context-dependent:

- In an education domain the Actor is a **student**.
- In an agriculture domain an Actor may be a **pH sensor**, a **farm operator**, or a
  **weather station**.
- In the system domain the Actor is the **administrator** who manages configuration and
  lifecycle.

A single Actor can be a person, a sensor, a device, or any other evidence-producing
entity. The Domain Authority declares which entities qualify as Actors in the domain
physics file.

### The Orchestrator Is Not an Actor

The AI orchestrator is an **executor and translator**, not an Actor. It does not produce
evidence — it mediates between the D.S.A. pillars. Its pipeline is:

```
sensor → domain logic → module action → actuator → feedback → system state
```

The orchestrator observes incoming evidence (produced by Actors), updates the State,
checks Domain invariants, selects a response within standing orders, and escalates when
it cannot stabilize. See [`dsa-framework-v1 § A`](../../specs/dsa-framework-v1.md) for
the full constraint set.

---

## Actor Types

Every domain physics file declares an `actor_types` array. Each entry is a typed Actor
definition:

```json
{
  "id": "sensor",
  "label": "Sensor",
  "description": "IoT device producing field-operations evidence.",
  "evidence_sources": ["adapter/agri/collar-sensor/v1"],
  "groups": ["environmental_monitors"]
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | yes | Unique identifier within the module (e.g. `sensor`, `student`, `operator`) |
| `label` | string | yes | Human-readable display name |
| `description` | string | yes | What this Actor does and what evidence it produces |
| `evidence_sources` | array of strings | yes | Tool adapter URIs that produce evidence for this Actor type (may be empty) |
| `groups` | array of strings | no | Actor group IDs this Actor belongs to (may overlap across groups) |

The schema is defined in
[`domain-physics-schema-v1.json § $defs/actor_type`](../../standards/domain-physics-schema-v1.json).

---

## Actor Groups

Actors always need groups. A sensor monitoring a barn and a sensor monitoring a silo are
both sensors, but they belong to different operational groups. Groups enable the system
to reason about collections of Actors that share a common operational context.

Each domain physics file may declare an `actor_groups` object at the top level:

```json
{
  "actor_groups": {
    "environmental_monitors": {
      "description": "Sensors and IoT devices producing continuous environmental readings.",
      "members": ["sensor"]
    },
    "field_crew": {
      "description": "Human operators making field decisions and recording observations.",
      "members": ["operator"]
    }
  }
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `description` | string | yes | What this group represents operationally |
| `members` | array of strings | yes | Actor type IDs that belong to this group |

### Overlapping Membership

An Actor type may appear in multiple groups. For example, in a larger agriculture
deployment a `sensor` Actor might belong to both `barn_monitors` and `silo_monitors`
if it feeds evidence into both operational contexts. Groups are not exclusive — they
describe **operational scope**, not ownership.

### Groups vs. RBAC Permission Groups

Actor groups and RBAC permission groups serve different purposes:

| Aspect | Actor Groups | Permission Groups |
|--------|-------------|-------------------|
| **Defined in** | `actor_groups` in domain physics | `permission_groups` in domain physics |
| **Members are** | Actor type IDs (`sensor`, `student`) | Domain role IDs (`teacher`, `farm_manager`) |
| **Purpose** | Classify evidence-producing entities by operational context | Control access to domain modules and operations |
| **Enforced by** | Domain lib and orchestrator routing | `permissions.py` RBAC engine |

A `domain_authority` is always an implicit member of every permission group (see
[`rbac-spec-v1`](../../specs/rbac-spec-v1.md)). There is no equivalent implicit
membership for Actor groups — membership is always explicit.

---

## Signal Flow

When an Actor produces evidence, the system processes it through a deterministic
pipeline:

1. **Actor** produces a raw signal (sensor reading, problem attempt, manual observation)
2. **Tool adapter** translates the raw signal into a structured `turn_data` evidence
   record with `signal_id`, `signal_value`, `within_tolerance`, and `source`
3. **Domain lib** interprets the evidence against domain state (tolerance bands, drift
   windows, uncertainty)
4. **Orchestrator** checks Domain invariants and selects a response tier
   (`ok` / `minor` / `major` / `escalate`)
5. **Actuator** executes the approved response (standing order or escalation)
6. **State** is updated with the new signal and any resulting state transitions

The orchestrator never produces evidence itself. It is a mediator that routes Actor
signals through the domain logic and enforces the Domain Authority's standing orders.

---

## Defining Actors for a New Domain

When creating a new domain pack:

1. **Identify evidence-producing entities** — anything that changes domain state is an
   Actor type. A person answering questions, a sensor reporting metrics, a device
   recording readings.
2. **Define actor types** — add entries to the `actor_types` array in the module's
   `domain-physics.json` with unique IDs, descriptions, and evidence source bindings.
3. **Group actors by operational context** — add an `actor_groups` block that clusters
   actors by the context in which they operate (monitoring zone, learning cohort,
   operational unit).
4. **Bind evidence sources** — each actor type's `evidence_sources` should reference the
   tool adapter URIs that produce evidence for that actor.
5. **Validate** — run the domain physics schema validator to confirm the file conforms
   to `domain-physics-schema-v1.json`.

---

## See Also

- [`dsa-framework-v1`](../../specs/dsa-framework-v1.md) — Full D.S.A. three-pillar
  specification
- [`domain-pack-anatomy`](domain-pack-anatomy.md) — Six-component domain pack structure
- [`prompt-packet-assembly`](prompt-packet-assembly.md) — How D.S.A. pillars are
  assembled into prompt packets
- [`domain-physics-schema-v1.json`](../../standards/domain-physics-schema-v1.json) —
  JSON Schema defining `actor_types` and `actor_groups`
