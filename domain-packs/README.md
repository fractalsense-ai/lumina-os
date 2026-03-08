# Domain Packs — Project Lumina

Domain packs are the authored rulesets that bound a Project Lumina session to a specific subject area. This directory contains the authored domain packs for the Project Lumina reference implementation.

Each domain owns its own:
- principles
- rules and invariants
- state model and domain-lib estimators
- domain physics and standing-order vocabulary

Root documentation defines universal engine behavior only.

---

## What Is a Domain Pack?

A domain pack is the **D (Domain)** pillar of the D.S.A. Framework. It defines:

- **Invariants** — conditions that must always hold (critical or warning severity)
- **Standing Orders** — bounded automated responses the orchestrator may take
- **Escalation Triggers** — when to pass control to the Meta Authority
- **Artifacts** — milestones that can be earned in this domain
- **Subsystem Configuration** — domain-specific domain-lib parameters and drift thresholds

See [`../specs/domain-profile-spec-v1.md`](../specs/domain-profile-spec-v1.md) for the full authoring specification.

---

## Directory Structure

```
domain-packs/
├── README.md                   ← this file
├── education/
│   ├── README.md                ← domain principles/rules/states/physics index
│   ├── domain-lib/             ← education-domain state lib components (ZPD, affect, fatigue)
│   │   ├── README.md
│   │   ├── compressed-state-estimators.md
│   │   ├── zpd-monitor-spec-v1.md
│   │   └── fatigue-estimation-spec-v1.md
│   └── algebra-level-1/        ← complete worked example
│       ├── domain-physics.yaml    (source — human-authored)
│       ├── domain-physics.json    (derived — machine-authoritative)
│       ├── tool-adapters/
│       │   ├── algebra-parser-adapter-v1.yaml
│       │   ├── calculator-adapter-v1.yaml
│       │   └── substitution-checker-adapter-v1.yaml
│       ├── student-profile-template.yaml
│       ├── example-student-alice.yaml
│       ├── prompt-contract-schema.json
│       └── CHANGELOG.md
└── agriculture/
  └── README.md               ← domain principles/rules/states/physics index
```

---

## How to Author a Domain Pack

### 1. Create the directory

```bash
mkdir -p domain-packs/{org}/{subject-level}
```

### 2. Write domain-physics.yaml

Use the template from `algebra-level-1/domain-physics.yaml` as a starting point. Your YAML must conform to [`../standards/domain-physics-schema-v1.json`](../standards/domain-physics-schema-v1.json).

### 3. Validate and convert to JSON

```bash
python ../reference-implementations/yaml-to-json-converter.py \
  domain-packs/{org}/{subject-level}/domain-physics.yaml \
  --schema ../standards/domain-physics-schema-v1.json
```

### 4. Write the entity profile template

Use the profile template from an existing pack as a base (for example, `student-profile-template.yaml` in the education pack, or a domain-equivalent name in your pack). The template defines the initial state for new entities.

### 5. Write tool adapters (if needed)

For each external tool, write a tool adapter YAML conforming to [`../standards/tool-adapter-schema-v1.json`](../standards/tool-adapter-schema-v1.json).

### 6. Write a CHANGELOG.md

Document every version with semver, date, and changes.

### 7. Commit the hash to the CTL

```bash
python ../reference-implementations/ctl-commitment-validator.py \
  --commit domain-packs/{org}/{subject-level}/domain-physics.json \
  --actor-id <pseudonymous-id> \
  --ledger path/to/ledger.jsonl
```

Every material module policy change requires:
- semantic version update,
- YAML -> JSON regeneration,
- CTL commitment of the updated module `domain-physics.json` hash before activation.

---

## Domain Pack Lifecycle

```
Draft → Validated → Committed (CTL) → Active
                                         ↓
                                    New Version (Major/Minor/Patch)
                                         ↓
                                    Validated → Committed → Active
```

A domain pack must be in the `Active` state (CTL commitment present) before use in a production session.

---

## Domain-Lib vs Tool-Adapters

Each domain pack may contain two distinct component types. Understanding the distinction is essential for correct authoring.

### Domain-Lib (Passive Specifications)

The `domain-lib/` folder holds **passive reference documents** — specifications, estimation models, threshold tables, and subsystem profiles that the orchestrator and LLM *read* but never *execute*.

Examples:
- A ZPD monitor specification that defines zone boundaries and drift thresholds
- A fatigue estimation model describing decay curves and recovery windows
- A pH sensor profile specifying operating ranges and tolerance bands

Domain-lib files have **no callable entry point**. They are consumed by the LLM as context or by the orchestrator as configuration lookup. They describe *what* the domain measures, not *how* to compute it.

`world-sim/` content is a separate optional layer for interaction framing. It is not the source of normative thresholds or standing-order policy.

### Tool-Adapters (Active Deterministic Tools)

The `tool-adapters/` folder holds **active tools** — deterministic functions that accept structured input and produce structured output. Each tool has a YAML adapter specification conforming to [`../standards/tool-adapter-schema-v1.json`](../standards/tool-adapter-schema-v1.json), plus a backing implementation (typically in `reference-implementations/tool-adapters.py`).

Examples:
- An algebra parser that tokenises student work into steps and checks algebraic equivalence
- A substitution checker that plugs a value into an equation and returns pass/fail
- A unit-conversion calculator that converts between measurement systems

Tool-adapters are **called by the orchestrator** (or by the turn interpreter on behalf of the orchestrator). They provide ground-truth signals that the LLM cannot fabricate. The LLM should validate its reasoning against tool-adapter output, not the other way around.

Domain-lib runtime components consume structured tool outputs and produce machine-readable state summaries. The orchestrator then enforces module invariants, standing orders, and escalation triggers defined in module `domain-physics.json`.

Tool adapters should be explicitly linked from module `domain-physics` using `tool_adapters` IDs so tooling and governance can verify that only authorized tools are used for that module's physics.
Repository integrity checks enforce this linkage: a declared `tool_adapters` ID must resolve to a concrete adapter contract file in the module.

### When to use which

| Question | Domain-Lib | Tool-Adapter |
|----------|-----------|--------------|
| Does it have a callable function? | No | Yes |
| Does it produce deterministic output? | N/A | Yes |
| Is it a specification or reference? | Yes | No |
| Does the orchestrator invoke it? | No (reads only) | Yes |
| Does it conform to tool-adapter-schema? | No | Yes |

---

## Execution Flow Contract

The authoritative execution flow is:

1. Module `domain-physics.json` is loaded as machine-authoritative policy truth.
2. Its hash is verified against the committed CTL `CommitmentRecord`.
3. Authorized tool-adapters produce structured signals/evidence.
4. Domain-lib runtime components transform those signals into machine-readable state summaries.
5. Orchestrator evaluates module invariants and resolves standing-order/escalation outcomes.
6. CTL records are appended for accountability.

`world-sim/` may shape interaction framing, but it does not define normative thresholds, standing-order policy, or escalation policy.

---

## Conformance

All domain packs in this directory must conform to:
- [`../standards/lumina-core-v1.md`](../standards/lumina-core-v1.md) — Section 1
- [`../standards/domain-physics-schema-v1.json`](../standards/domain-physics-schema-v1.json) — JSON Schema

YAML authoring constraint:
- The minimal `reference-implementations/yaml-loader.py` parser cannot reliably parse inline list mappings that mix nested keys on the same list item. Prefer explicit nested mapping blocks and plain string lists in `runtime-config.yaml` and `domain-physics.yaml`.

Packs that fail validation are not usable.

---

## Available Domains

| Domain | Pack | Version | Status |
|--------|------|---------|--------|
| Education — Algebra Level 1 | `education/algebra-level-1` | 0.4.0 | Active |
| Agriculture | `agriculture/` | — | Placeholder |

---

## Required Domain Layout

Each top-level domain folder should include a `README.md` that defines or links:
- Domain principles
- Domain rules/invariants authority
- Domain state model (schemas + estimators/sensors)
- Domain physics and standing-order vocabulary
