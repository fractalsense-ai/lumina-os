---
version: 1.1.0
last_updated: 2026-06-15
---

# HMVC Heritage — Architectural Lineage

**Version:** 1.1.0
**Status:** Active
**Last updated:** 2026-06-15

---

Project Lumina's domain-pack architecture descends from the Hierarchical
Model–View–Controller (HMVC) pattern. Understanding this lineage clarifies why domain
packs are structured the way they are, why each pack owns its own controllers, and why
the core engine knows nothing about any domain's internals.

This document maps HMVC concepts to their Lumina equivalents. It is not a tutorial on
HMVC itself — familiarity with the triad pattern is assumed.

---

## A. The HMVC Principle

In HMVC, an application is composed of self-contained **modules** (sometimes called
"triads"). Each module owns its own Model, View, and Controller. A central framework
dispatches requests to the appropriate module and renders the result. Modules communicate
through the framework, never by reaching into each other's internals.

The critical property is **module isolation**: adding a new module requires zero changes to
the framework or to any existing module. The module declares what it handles; the framework
routes to it. This is exactly how Lumina works.

---

## B. The Mapping

| HMVC Concept | Lumina Equivalent | Location | Notes |
|---|---|---|---|
| **Module** (self-contained app) | **Domain Pack** | `domain-packs/{domain}/` | Each pack is a bounded cognitive subsystem — education, agriculture, system admin |
| **Model** (data, rules, state) | **Physics + Schemas + Evidence** | `modules/{mod}/domain-physics.*`, `schemas/`, `evidence-schema.json` | Invariants, standing orders, entity state schemas, evidence vocabulary |
| **Controller** (input→logic→output) | **Controllers directory** | `controllers/runtime_adapters.py`, `nlp_pre_interpreter.py`, `tool_adapters.py` | Runtime adapter (synthesis), NLP pre-interpreter (information gate), tool adapters (active verifiers) |
| **View** (presentation layer) | **Prompts + World-Sim Persona** | `prompts/`, `world-sim/` | Domain system override, turn interpretation prompt, narrative framing |
| **Service layer** (shared domain logic) | **Domain Library** | `domain-lib/` specs + `controllers/` implementations | Passive state estimators (ZPD, fluency, fatigue) — called by controllers, never by the engine |
| **Module routes / config** | **Runtime Config** | `cfg/runtime-config.yaml` | Adapter bindings, access control, module routing, world-sim config |
| **Module API endpoints** | **Domain API Route Handlers** | `controllers/api_handlers.py` + `cfg/runtime-config.yaml` §adapters.api_routes | Domain-owned HTTP endpoints dynamically mounted by the core server at startup — the domain declares routes, the framework provides auth/role middleware |
| **Framework router** | **Domain Registry** | `cfg/domain-registry.yaml` + `src/lumina/core/domain_registry.py` | Maps domain_id → runtime context; role-based defaults; NLP routing |
| **Framework core** | **Core Engine** | `src/lumina/` | Zero domain-specific names — reads only `problem_solved` and `problem_status` |
| **Sub-request** (module→module) | **Cross-Domain Synthesis** | Opt-in, dual-key DA approval | See [`cross-domain-synthesis(7)`](cross-domain-synthesis.md) |

---

## C. Each Domain Pack Is an App

In HMVC, a module is an app. In Lumina, a domain pack is an app.

A domain pack declares everything needed to bring a subject area into the engine:

1. **What is correct** — physics invariants (Model)
2. **How to process input** — NLP pre-interpreter + runtime adapter (Controller)
3. **How to present output** — prompts and optional world-sim persona (View)
4. **What state to track** — entity profile schemas + domain library estimators (Model + Service)
5. **What tools to use** — tool adapter YAML specs + Python implementations (Controller)

The engine loads a pack at session start by reading its `cfg/runtime-config.yaml` manifest,
wiring up its controllers, and routing all subsequent turns through the pack's processing
pipeline. The engine does not know what "correctness" means in algebra, what "moisture
levels" mean in agriculture, or what "privilege escalation" means in system admin. It reads
two contract fields and moves on.

This is the self-containment contract, and it is the HMVC module isolation principle enforced
at the architecture level:

> **Zero domain-specific names may appear in `src/lumina/`.** All domain logic, domain field
> names, domain computations, and domain vocabulary live exclusively inside the domain pack.

For the eight-component anatomy of a domain pack (physics, tool adapters, runtime adapter,
NLP pre-interpreter, domain library, group libraries, API route handlers, world-sim), see
[`domain-pack-anatomy(7)`](domain-pack-anatomy.md).

---

## D. The Controller Layer

The HMVC controller receives input, coordinates model queries and service calls, and returns
a response for the view to render. In Lumina, this role is fulfilled by the **controllers
directory** (`controllers/`) inside each domain pack.

The controllers directory contains three distinct responsibilities:

| File | HMVC Role | What It Does |
|---|---|---|
| `runtime_adapters.py` | **Primary controller** | Synthesis layer — runs Phase A (NLP pre-processing) and Phase B (signal synthesis after tools); emits engine contract fields `problem_solved` and `problem_status` |
| `nlp_pre_interpreter.py` | **Input filter / front controller** | Information gate — deterministic extraction of domain-meaningful signals before any LLM inference; produces `_nlp_anchors` |
| `tool_adapters.py` | **Action controller** | Active verifier dispatch — wraps tool-adapter YAML specs as callable Python functions for the orchestrator |

Additional controller files are domain-specific:

- `problem_generator.py` (education) — task generation controller
- `fluency_monitor.py` (education) — fluency estimation invoked by the runtime adapter
- `zpd_monitor_v0_2.py` (education) — ZPD state estimation reference implementation

These files were historically named `systools/` (system tools). The rename to `controllers/`
surfaces the HMVC heritage: these are the pack's controllers, not generic system utilities.
The engine's own system utilities remain at `src/lumina/systools/` — a deliberately different
namespace.

For the engine contract fields the controller must emit, and the Phase A/B implementation
contract, see [`domain-adapter-pattern(7)`](domain-adapter-pattern.md).

---

## E. The Model Layer

HMVC models hold data, enforce rules, and define state. In Lumina, this maps to two
complementary structures:

### Physics files (declarative rules)

`modules/{module}/domain-physics.yaml` and `.json` declare invariants, standing orders,
escalation triggers, and artifacts. These are the domain's law — what must be true, what the
orchestrator may do, and when to escalate. They are immutable per session (hash-committed to
the System Log before activation).

### Schemas and evidence (state definition)

- `schemas/{entity}-profile-schema-v1.json` — entity state shape
- `modules/{module}/evidence-schema.json` — per-turn evidence vocabulary
- `modules/{module}/{entity}-profile-template.yaml` — initial state template

The domain library (`domain-lib/`) provides pure state estimators that compute model updates
from structured evidence. These are akin to HMVC model methods — they never interact with
input or output directly; they are called by controllers to update state.

---

## F. The View Layer

HMVC views render output for the user. In Lumina, the view layer is composed of:

- `prompts/domain-system-override.md` — tone, persona, rendering rules for LLM output
- `prompts/turn-interpretation.md` — turn classification prompt
- `world-sim/` (optional) — narrative framing that wraps domain content in a persona

The view layer is cosmetic. It changes how the domain presents itself to the entity
(student, operator, admin) but does not alter invariants, standing orders, or any
computational logic. A domain pack with world-sim disabled and a domain pack with a
"space exploration" theme produce identical evidence dicts — only the LLM's surface
prose changes.

Additionally, each domain pack declares a `ui_manifest` in its `runtime-config.yaml`.
This manifest is the **declarative View binding** for the frontend:

- `title`, `subtitle`, `domain_label` — chrome text and breadcrumb
- `theme` — CSS custom property overrides (primary, accent, background)
- `panels` — an array of domain-specific dashboard views, each specifying:
  - `id` — unique panel identifier
  - `label` — human-readable tab label
  - `endpoint` — the API path the panel fetches data from
  - `roles` — which RBAC roles may see this panel
  - `type` — rendering hint (`chart`, `table`, or `metric`)

The frontend reads `ui_manifest.panels` and merges them into the Dashboard tab bar
alongside the static governance tabs.  Each domain can define its own telemetry and
monitoring views (e.g., education: ZPD distribution; system: pack integrity; agriculture:

---

## D. Ledger Tier Separation — HMVC Applied to the System Log

The HMVC principle of module isolation extends to the **System Log**.  Just as
each domain pack is an independent application (Section C), its ledger records
live in an isolated directory tier:

| HMVC layer        | Ledger tier                                       |
|-------------------|---------------------------------------------------|
| System (kernel)   | ``system/session-{session_id}.jsonl``             |
| Domain pack       | ``domains/{domain_id}/domain.jsonl``              |
| Module            | ``domains/{domain_id}/modules/{module_id}.jsonl`` |

A ``ScopedPersistenceAdapter`` enforces this boundary at write time — domain
packs receive a persistence object that can only write to their own tier.
Attempts to write system-tier records raise ``PermissionError``.

This mirrors the HMVC contract: a child triad cannot mutate the parent's
state.  The system log's hash chains remain per-file, so domain disruptions
never corrupt the system-level audit trail.

See [Ledger Tier Separation](ledger-tier-separation.md) for full details.
yield variance) without the framework or other domains knowing about them — full HMVC
View isolation.

For the world-sim pattern and its invariant preservation guarantee, see
[`world-sim-persona-pattern(7)`](world-sim-persona-pattern.md).

---

## G. The Framework — Why `src/lumina/` Is Not a Domain

In HMVC, the framework dispatches, but it does not contain application logic.
`src/lumina/` follows this principle:

- `core/domain_registry.py` — the framework router; resolves domain_id to runtime context
- `core/runtime_loader.py` — dynamic module loader; imports pack controllers via importlib
- `orchestrator/ppa_orchestrator.py` — the framework's action coordinator; reads contract
  fields, checks invariants, drafts prompt contracts, writes System Log
- `middleware/invariant_checker.py` — evaluates domain invariants from structured evidence

None of these files contain domain-specific field names, vocabulary, or computations.
They read generic contract fields and delegate domain-specific work to the pack.

The engine's own `src/lumina/systools/` directory (hardware probes, manifest integrity,
YAML converter, repo verifier) is a separate concern — engine-level utilities, not
domain-pack controllers. The naming distinction (`systools` for engine utilities,
`controllers` for domain-pack processing) makes this boundary explicit.

---

## H. Adding a New Domain — The HMVC Guarantee

The HMVC promise: adding a new module requires zero changes to the framework. Lumina
honours this. To add a new domain pack:

1. Create `domain-packs/{new-domain}/` with the canonical layout
2. Author `modules/{module}/domain-physics.yaml` (Model)
3. Implement `controllers/runtime_adapters.py` and `controllers/nlp_pre_interpreter.py` (Controller)
4. Write `prompts/domain-system-override.md` (View)
5. Create `cfg/runtime-config.yaml` with adapter bindings (Module config)
6. Register in `cfg/domain-registry.yaml` (Framework routing)
7. Commit the physics hash to System Log

No file in `src/lumina/` is touched. No existing domain pack is modified. The engine
loads the new pack at session start and routes through it — exactly as HMVC prescribes.

For the complete authoring process, see `domain-packs/README.md`. For the `pack.yaml`
manifest format that declares pack identity and component inventory, see the `pack.yaml`
file at the root of any domain pack directory.

---

## I. Cross-References

| Document | Relevance |
|---|---|
| [`domain-pack-anatomy(7)`](domain-pack-anatomy.md) | Six-component anatomy, self-containment contract, file layout reference |
| [`domain-adapter-pattern(7)`](domain-adapter-pattern.md) | Engine contract fields, three-layer component distinction, Phase A/B implementation |
| [`dsa-framework-v1`](../../specs/dsa-framework-v1.md) | D.S.A. structural schema — Domain (Model), State (Model update), Actor (Controller output) |
| [`cross-domain-synthesis(7)`](cross-domain-synthesis.md) | HMVC sub-request equivalent — opt-in bridging between domain packs |
| [`nlp-semantic-router(7)`](nlp-semantic-router.md) | Two-tier NLP routing — framework-level domain classification before per-pack pre-interpretation |
| [`world-sim-persona-pattern(7)`](world-sim-persona-pattern.md) | View-layer narrative framing pattern |
| [`domain-profile-spec-v1`](../../specs/domain-profile-spec-v1.md) | Domain profile authoring specification |
