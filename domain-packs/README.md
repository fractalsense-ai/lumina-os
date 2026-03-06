# Domain Packs — Project Lumina

Domain packs are the authored rulesets that bound a Project Lumina session to a specific subject area. This directory contains the authored domain packs for the Project Lumina reference implementation.

Each domain owns its own:
- principles
- rules and invariants
- state model and sensors
- domain physics and standing-order vocabulary

Root documentation defines universal engine behavior only.

---

## What Is a Domain Pack?

A domain pack is the **D (Domain)** pillar of the D.S.A. Framework. It defines:

- **Invariants** — conditions that must always hold (critical or warning severity)
- **Standing Orders** — bounded automated responses the orchestrator may take
- **Escalation Triggers** — when to pass control to the Meta Authority
- **Artifacts** — milestones that can be earned in this domain
- **Subsystem Configuration** — domain-specific sensor parameters and drift thresholds

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

## Conformance

All domain packs in this directory must conform to:
- [`../standards/lumina-core-v1.md`](../standards/lumina-core-v1.md) — Section 1
- [`../standards/domain-physics-schema-v1.json`](../standards/domain-physics-schema-v1.json) — JSON Schema

Packs that fail validation are not usable.

---

## Available Domains

| Domain | Pack | Version | Status |
|--------|------|---------|--------|
| Education — Algebra Level 1 | `education/algebra-level-1` | 0.2.0 | Active |
| Agriculture | `agriculture/` | — | Placeholder |

---

## Required Domain Layout

Each top-level domain folder should include a `README.md` that defines or links:
- Domain principles
- Domain rules/invariants authority
- Domain state model (schemas + estimators/sensors)
- Domain physics and standing-order vocabulary
