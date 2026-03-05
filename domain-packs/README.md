# Domain Packs — Project Lumina

Domain packs are the authored rulesets that bound a Project Lumina session to a specific subject area. This directory contains the authored domain packs for the Project Lumina reference implementation.

---

## What Is a Domain Pack?

A domain pack is the **D (Domain)** pillar of the D.S.A. Framework. It defines:

- **Invariants** — conditions that must always hold (critical or warning severity)
- **Standing Orders** — bounded automated responses the orchestrator may take
- **Escalation Triggers** — when to pass control to the Meta Authority
- **Artifacts** — milestones that can be earned in this domain
- **Subsystem Configuration** — domain-specific sensor parameters and drift thresholds (e.g., ZPD band for education, soil moisture band for agriculture)

See [`../specs/domain-profile-spec-v1.md`](../specs/domain-profile-spec-v1.md) for the full authoring specification.

---

## Directory Structure

```
domain-packs/
├── README.md                   ← this file
├── education/
│   ├── sensors/                ← education-domain sensor array (ZPD, affect, fatigue)
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
    └── README.md               ← placeholder for future domain
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

Use `student-profile-template.yaml` from `algebra-level-1` as a base (or the equivalent template for your domain — the filename follows your domain's own naming conventions). The template defines the initial state for new entities.

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
