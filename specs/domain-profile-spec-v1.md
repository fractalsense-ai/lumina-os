# Domain Profile Specification — V1

**Version:** 1.0.0  
**Status:** Active  
**Last updated:** 2026-03-02

---

## Overview

A **Domain Profile** (also called a **Domain Pack**) bounds a Project Lumina system to a specific subject area and operating context. This document specifies how to author a Domain Profile, what it must contain, and how it is activated.

---

## What a Domain Profile Does

A Domain Profile:
1. **Defines what is correct** — invariants specify the rules of the domain
2. **Defines what the system may do** — standing orders bound the orchestrator's automated responses
3. **Defines when to escalate** — escalation triggers specify when human intervention is needed
4. **Defines what mastery means** — artifacts specify achievable outcomes
5. **Sets the ZPD parameters** — challenge band and drift thresholds

A Domain Profile does not define conversation scripts, specific problem sets, or lesson plans. Those are content, not structure. The profile governs the structure.

---

## Authoring Process

### Step 1: Author the YAML

Write `domain-physics.yaml` following the structure below. The YAML is the source of truth — human-readable and version-controlled.

```yaml
id: domain/org/subject-level/v1
version: "0.1.0"

domain_authority:
  name: "Jane Smith"
  role: "Lead Algebra Teacher"

meta_authority_id: domain/org/curriculum/v1

description: "Algebra Level 1 for middle school students"

lumina_core_version: "1.0.0"

invariants:
  - id: equivalence_preserved
    description: "Both sides of an equation must remain equal after each step"
    severity: critical
    check: "verify_algebraic_equivalence(before_step, after_step)"
    standing_order_on_violation: request_more_steps

standing_orders:
  - id: request_more_steps
    action: request_more_steps
    trigger_condition: equivalence_preserved
    max_attempts: 3
    escalation_on_exhaust: true
    description: "Ask the student to show their work step by step"

escalation_triggers:
  - id: critical_invariant_unresolvable
    condition: "critical invariant violated and standing order exhausted"
    target_role: teacher
    sla_minutes: 30

artifacts:
  - id: linear_equations_basic
    name: "Linear Equations — Foundations"
    unlock_condition: "mastery >= 0.8 on solve_one_variable"
    mastery_threshold: 0.8
    skills_required:
      - solve_one_variable

zpd_config:
  min_challenge: 0.3
  max_challenge: 0.7
  drift_window_turns: 10
  minor_drift_threshold: 0.3
  major_drift_threshold: 0.5
  persistence_required: 3
```

### Step 2: Validate and Convert

Run the converter to validate and produce the JSON:

```bash
python reference-implementations/yaml-to-json-converter.py \
  domain-packs/education/algebra-level-1/domain-physics.yaml \
  --schema standards/domain-physics-schema-v1.json
```

If validation passes, the JSON file is written alongside the YAML.

### Step 3: Commit the Hash

Before the domain pack is used operationally, commit its hash to the CTL:

```bash
python reference-implementations/ctl-commitment-validator.py \
  --commit domain-packs/education/algebra-level-1/domain-physics.json \
  --actor-id <pseudonymous-id> \
  --ledger path/to/ledger.jsonl
```

This writes a `CommitmentRecord` to the ledger. The hash in the `CommitmentRecord` must match the hash of the JSON file at session time.

### Step 4: Write a CHANGELOG Entry

Every version must have a CHANGELOG entry. Format:

```markdown
## v0.2.0 — 2026-03-02
### Added
- ZPD configuration with drift thresholds
- `zpd_drift_minor` and `zpd_drift_major` warning invariants
### Changed
- `show_work_minimum` max_attempts increased from 2 to 3
```

---

## Domain Pack File Layout

```
domain-packs/{org}/{subject-level}/
├── domain-physics.yaml          ← authored YAML (source)
├── domain-physics.json          ← derived JSON (machine-authoritative)
├── tool-adapters/
│   └── {tool-name}-adapter-v{N}.yaml
├── student-profile-template.yaml
├── example-student-{name}.yaml  ← optional test profiles
├── prompt-contract-schema.json
└── CHANGELOG.md
```

---

## Invariant Design Guidelines

**DO:**
- Write invariants that can be checked deterministically (not by reading conversation tone)
- Make critical invariants correspond to observable, verifiable properties
- Pair every critical invariant with a standing order
- Set `max_attempts` conservatively — err on the side of escalating sooner

**DON'T:**
- Write invariants that require the system to infer intent or emotion
- Create invariants that have no corresponding standing order
- Set `max_attempts` so high that the system loops forever before escalating
- Use conversation content as the basis for invariant checks

---

## ZPD Configuration Guidelines

The ZPD band should be set based on the Domain Authority's pedagogical judgment:

- **Too narrow**: frequent drift, too many interventions
- **Too wide**: drift goes undetected, learner struggles or disengages

Typical starting values:
- `min_challenge: 0.25` (25th percentile of current mastery)
- `max_challenge: 0.75` (75th percentile — stretch but achievable)
- `drift_window_turns: 10`
- `minor_drift_threshold: 0.3` (3 of 10 turns outside ZPD → minor)
- `major_drift_threshold: 0.5` (5 of 10 turns outside ZPD → major)
- `persistence_required: 3`

---

## Multi-Domain Sessions

A session may span multiple Domain Profiles if the Meta Authority authorizes it. In this case:
- Each domain has its own invariant set
- The session's escalation policy is the union of both domains' escalation triggers
- The CTL records which domain was active for each TraceEvent

Multi-domain sessions are advanced usage and require explicit Meta Authority approval in the session's CommitmentRecord.

---

## References

- [`../standards/domain-physics-schema-v1.json`](../standards/domain-physics-schema-v1.json)
- [`../domain-packs/README.md`](../domain-packs/README.md)
- [`../domain-packs/education/algebra-level-1/`](../domain-packs/education/algebra-level-1/) — worked example
- [`../reference-implementations/yaml-to-json-converter.py`](../reference-implementations/yaml-to-json-converter.py)
