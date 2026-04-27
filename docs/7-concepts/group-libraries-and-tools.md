---
version: 1.1.0
last_updated: 2026-03-30
---

# Group Libraries and Group Tools

**Version:** 1.1.0  
**Status:** Active  
**Last updated:** 2026-03-30  

---

Domain packs traditionally own all of their components privately — physics, tools, domain
library, NLP pre-interpreter.  This self-containment contract is a hard boundary: a domain
pack must not import from another domain pack.

But **within** a single domain pack, identical logic often recurs across modules.  Every
agriculture module that reads soil-moisture sensors calls the same normalisation routine.
Every education module that tracks engagement applies the same fatigue formula.  Copying
that logic into every module violates DRY and creates maintenance risk.

Group Libraries and Group Tools solve this by declaring **domain-scoped shared resources**
that multiple modules within the same domain can reference.  They are the domain-level
equivalent of shared libraries in a compiled operating system, but they never cross the
domain boundary.

---

## A. What Are Group Libraries?

A Group Library is a **passive, deterministic Python module** placed in the domain pack's
`domain-lib/` directory and declared in the domain-physics file of every module that uses
it.

Properties:

- **Pure functions only** — same inputs always produce the same outputs
- **No LLM involvement** — the library never calls inference
- **No external dependencies** — only stdlib and domain-internal imports
- **Called by the runtime adapter** — the core engine never references a Group Library
  directly

The canonical analogy is the Entity Component System (ECS) pattern: in a game engine,
components are shared data/logic pools that multiple entity types can attach to.  A Group
Library is a shared computation pool that multiple modules within a domain can attach to.

### Physics file declaration

Each module that uses a Group Library declares it in `domain-physics.json` under the
`group_libraries` array:

```json
{
  "group_libraries": [
    {
      "id": "environmental_sensors",
      "path": "domain-lib/sensors/environmental_sensors.py",
      "description": "Sensor normalisation and anomaly detection",
      "shared_with_modules": [
        "operations-level-1",
        "crop-planning"
      ]
    }
  ]
}
```

| Field | Type | Purpose |
|-------|------|---------|
| `id` | string | Unique identifier within the domain pack |
| `path` | string | Relative path from the domain pack root |
| `description` | string | Human-readable summary |
| `shared_with_modules` | array | Module IDs that may reference this library |

---

## B. What Are Group Tools?

A Group Tool is an **active, deterministic verifier** shared across modules.  It follows the
same contract as a tool adapter — `payload: dict → dict` — but lives at the domain level
rather than inside a single module's `tool-adapters/` directory.

Properties:

- **Deterministic** — same payload always returns the same result
- **Callable by policy or by the runtime adapter directly**
- **Shared across modules** — multiple modules declare the same Group Tool
- **Distinguished by `call_types`** — whether the tool is policy-driven, direct, or both

### Physics file declaration

```json
{
  "group_tools": [
    {
      "id": "irrigation_validator",
      "path": "controllers/group_tool_adapters.py",
      "description": "Cross-module irrigation constraint checker",
      "call_types": ["policy"],
      "shared_with_modules": [
        "operations-level-1",
        "crop-planning"
      ]
    }
  ]
}
```

| Field | Type | Purpose |
|-------|------|---------|
| `id` | string | Unique identifier within the domain pack |
| `path` | string | Relative to domain pack root |
| `description` | string | Human-readable summary |
| `call_types` | array | `"policy"`, `"direct"`, or both |
| `shared_with_modules` | array | Module IDs that may reference this tool |

---

## C. Resolution at Runtime

Group resources are discovered at startup by two subsystems working in sequence.

### Step 1 — Adapter Indexer (`scan_group_resources`)

`adapter_indexer.scan_group_resources()` walks every `domain-physics.json` in the domain
pack, collecting `group_libraries` and `group_tools` declarations into two typed indexes:

- `dict[str, GroupLibraryEntry]` — keyed by `library_id`
- `dict[str, GroupToolEntry]` — keyed by `tool_id`

Both entry types are frozen dataclasses with `.to_dict()` serialisation for the runtime
context.

### Step 2 — Runtime Loader

`load_runtime_context()` calls `scan_group_resources()` and stores the results:

```python
libs, grp_tools = scan_group_resources(domain_pack_dir)
ctx["group_libraries"] = {k: e.to_dict() for k, e in libs.items()}
ctx["group_tools"]     = {k: e.to_dict() for k, e in grp_tools.items()}
```

The runtime adapter can then reference `ctx["group_libraries"]["environmental_sensors"]` to
load and invoke shared library functions.  The route compiler also uses the library index
for validation — see [`execution-route-compilation(7)`](execution-route-compilation.md).

---

## D. Agriculture Example — Environmental Sensors

The agriculture domain provides the reference implementation of a Group Library:
`model-packs/agriculture/domain-lib/sensors/environmental_sensors.py`.

This module provides:

| Component | Purpose |
|-----------|---------|
| `SensorReading` dataclass | Normalised sensor reading (sensor_id, value, unit, timestamp, quality) |
| `SensorThresholds` dataclass | Min/max/critical ranges per sensor type |
| `normalize_reading()` | Clamp raw values, compute quality score, produce structured `SensorReading` |
| `detect_anomalies()` | Compare readings against thresholds, return anomaly descriptors |
| `compute_field_summary()` | Aggregate a batch of readings into a field-level summary dict |
| `DEFAULT_THRESHOLDS` | Pre-configured thresholds for moisture, temperature, pH, nitrogen |

The module is registered in `operations-level-1/domain-physics.json` under
`group_libraries` with `id: "environmental_sensors"`.  Future modules (crop-planning,
livestock) can reference the same library by adding it to their own physics declarations.

```
model-packs/agriculture/
├── domain-lib/
│   ├── sensors/
│   │   └── environmental_sensors.py    ← Group Library (shared)
│   └── reference/
│       └── turn-interpretation-spec-v1.md  ← Reference spec (TM)
├── modules/
│   ├── operations-level-1/
│   │   └── domain-physics.json     ← declares group_libraries: ["environmental_sensors", "turn_interpretation"]
│   └── crop-planning/              ← (future) would also declare the same libraries
└── controllers/
    └── runtime_adapters.py         ← calls environmental_sensors functions via ctx
```

---

## E. When to Use Group Libraries vs Other Components

| Situation | Use |
|-----------|-----|
| Pure computation shared across modules within one domain | **Group Library** |
| Active verifier shared across modules within one domain | **Group Tool** |
| Passive state estimator tracking entity state across turns | **Domain Library** (in `domain-lib/`) |
| Deterministic verifier used by only one module | **Tool Adapter** (in `modules/<m>/tool-adapters/`) |
| Computation needed by a different domain | **Not supported** — the self-containment contract forbids cross-domain imports; refactor into a system-level tool if truly universal |

The decision heuristic: if two or more modules within the same domain call the same function
with the same contract, extract it into a Group Library or Group Tool based on whether it is
passive computation (library) or active on-demand verification (tool).

---

## F. Rebuild Triggers and Vector Impacts

When a Group Library file is modified, the retrieval index for **every module that
references it** must be rebuilt.  The housekeeper exposes this via:

```python
rebuild_group_library_dependents(
    library_id="environmental_sensors",
    registry=vector_registry,
)
```

This function scans each domain pack's physics files for `group_libraries` entries matching
the given `library_id`, then re-indexes only those domains.  The daemon's batch
task list includes vector rebuilds that honour these dependency chains — see
[`edge-vectorization(7)`](edge-vectorization.md) §D and
[`resource-monitor-daemon(7)`](resource-monitor-daemon.md) §F.

---

## G. Reference Specs as Group Libraries

Not all group library entries point to executable Python modules. A group library may also
reference a **passive specification file** — a Markdown document in `domain-lib/reference/`
that defines an interpretation schema, rendering rule set, or domain knowledge spec.

These reference specs are the **Tech Manuals** that physics files (SOPs) reference. They
are consumed by the runtime adapter, the SLM, or the LLM as structured context — not
executed as code. Examples:

| Reference spec | Domain | Purpose |
|----------------|--------|---------|
| `domain-lib/reference/turn-interpretation-spec-v1.md` | All | Defines the JSON output schema for turn-level field extraction |
| `domain-lib/reference/command-interpreter-spec-v1.md` | System | Defines disambiguation rules and parameter schemas for admin commands |
| `domain-lib/reference/compressed-state-estimators.md` | Education | Defines compressed state estimator formulas and thresholds |

Reference specs follow the same `group_libraries` declaration pattern in `domain-physics.json`:

```json
{
  "id": "turn_interpretation",
  "path": "domain-lib/reference/turn-interpretation-spec-v1.md",
  "description": "Turn-level field extraction schema",
  "shared_with_modules": ["algebra-level-1", "algebra-1"]
}
```

The distinction from executable group libraries is that reference specs have no callable
entry point. They are passive knowledge — the domain equivalent of a technical manual that
operators and automated systems read to understand what data fields mean and how to parse
them. The `path` field in the physics declaration serves as a dependency link: if the
reference spec changes, all referencing modules know they may need revalidation.

---

## SEE ALSO

- [`domain-pack-anatomy(7)`](domain-pack-anatomy.md) — six-component anatomy and file layout
- [`domain-adapter-pattern(7)`](domain-adapter-pattern.md) — three-layer distinction (tool adapters / domain-lib / runtime adapter) now extended with Group Libraries
- [`edge-vectorization(7)`](edge-vectorization.md) — per-domain vector isolation and rebuild triggers
- [`execution-route-compilation(7)`](execution-route-compilation.md) — route compiler validates group library dependencies at compile time
- `src/lumina/core/adapter_indexer.py` — `GroupLibraryEntry`, `GroupToolEntry`, `scan_group_resources()`
- `src/lumina/core/runtime_loader.py` — group resource discovery and context injection
- `model-packs/agriculture/domain-lib/sensors/environmental_sensors.py` — reference Group Library implementation
