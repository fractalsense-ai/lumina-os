---
version: 1.0.0
last_updated: 2026-04-27
---

# lumina-framework-ontology(7) — Engine, systems, model-packs, and modules

## Name

lumina-framework-ontology — the naming and architecture model for the
Lumina Neuro-Symbolic Systems Framework.

## Synopsis

Lumina is the **engine**. A model-pack is a **modeled system** loaded by
that engine. A module is a **subsystem routine** inside a model-pack.

This distinction is the core architecture:

| Term | Meaning | Example |
|------|---------|---------|
| Framework | The domain-agnostic runtime, APIs, orchestration, persistence, logging, governance mechanisms, and signal instruments. | `src/lumina/` |
| System | A real or simulated environment being modeled. | school, farm, assistant workspace |
| Model-pack | The authored bundle that teaches Lumina how one class of system works. | education, agriculture, assistant |
| Module | A subsystem routine, workflow, or scenario within a model-pack. | pre-algebra, operations-level-1, weather |
| Domain physics | The rules, invariants, standing orders, glossary, and constraints for a module or system. | `domain-physics.json` |
| Actor | An evidence-producing participant or entity inside the modeled system. | student, teacher, field, sensor, operator |
| State | The compact evolving condition of an actor, module, or system. | mastery, affect baseline, sensor baseline |
| Tool adapter | A deterministic capability exposed by a model-pack to the runtime. | calculator, roster lookup, sensor adapter |
| Governance | The human authority model and escalation policy for the system. | Domain Authority, Meta Authority, HITL gate |

## Description

Lumina was originally described as an operating system because it wraps
LLM execution in a deterministic runtime: prompt packet assembly,
inspection middleware, state updates, tool verification, system logging,
and escalation gates. That metaphor remains useful internally, but the
more precise public identity is **Lumina Neuro-Symbolic Systems
Framework**.

The framework is not the school, farm, assistant, or future research
institute. The framework is the reusable engine underneath them.

Model-packs are the authored systems that plug into the engine. They
are intentionally analogous to mods in a game engine: the engine stays
the same, but a different model-pack can make the runtime behave as a
completely different system.

## Object-Oriented Analogy

The architecture also maps cleanly to ordinary object-oriented dispatch:

| OOP concept | Lumina concept |
|-------------|----------------|
| Class / system type | The Lumina system contract and runtime environment |
| Object instance | A loaded model-pack: an authored model of one system |
| Method | A module routine, workflow, adapter, or exposed capability inside that model-pack |
| Method dispatch | Knowledge graph and semantic routing select the model-pack and module |

In this framing, multi-model-pack routing is not exotic. The runtime is
calling methods across multiple loaded objects that share the same system
contract. The deterministic layer owns dispatch, guardrails, invariants,
RBAC, hash commitments, and auditability. The neural layer executes
inside the selected module context after deterministic routing has
selected the object and method.

This is an architectural analogy, not a claim that every implementation
artifact must be a Python class. The invariant is the dispatch boundary:
system contract first, model-pack instance second, module routine third.

## Reference Model-Packs

### Education

The education model-pack is the reference vertical slice. It models a
school / learning system with actors such as students, teachers,
guardians, teaching assistants, and domain authorities. Its modules
include learning routines such as pre-algebra and algebra, plus
administrative/governance workflows.

### Agriculture

The agriculture model-pack proves that Lumina is not education-specific.
It models a farm / agricultural operations system with field, sensor,
and operations signals such as soil pH, moisture, air temperature, and
motor vibration.

### Assistant

The assistant model-pack models a cognitive interaction workspace. It
contains personal-assistant workflows such as conversation, planning,
search, weather, calendar, and persona craft. It is also the historical
home of the SVA affect-monitoring implementation that has since been
generalized into framework-level signal decomposition.

## Boundary Rules

1. `src/lumina/` is framework code. It must not hardcode education,
   agriculture, assistant, or any other model-pack-specific vocabulary.
2. `model-packs/` contains model-pack code, configuration, prompts,
   physics, tools, docs, and pack-owned UI contributions.
3. A module belongs to a model-pack. It should be treated as a subsystem
   routine/workflow inside the modeled system, not as a product by itself.
4. `domain_physics` remains a valid term. It names the rule/constraint
   layer of a modeled domain; the packaging layer is now called a
   model-pack.
5. Pack-level compatibility names such as `domain_pack_id` are legacy
   implementation vocabulary. New records should use `model_pack_id`.

## See Also

- [dsa-framework(7)](dsa-framework.md)
- [hmvc-heritage(7)](hmvc-heritage.md)
- [domain-pack-anatomy(7)](domain-pack-anatomy.md)
- [authoring-a-domain-pack(7)](authoring-a-domain-pack.md)
- [signal-decomposition-framework(7)](signal-decomposition-framework.md)
