# Artifact and Mastery Specification — Education Domain (V1)

> **Domain scope:** This specification defines how artifacts and mastery are recognized within the education domain. Other domains may adapt this pattern — for example, "certifications" in agriculture or "clinical competency records" in medical. The generic artifact *slot* in domain physics and the `OutcomeRecord` in the CTL are engine-level structural contracts; the *award process and rules* specified here are education-specific.

**Version:** 1.1.0  
**Status:** Active  
**Last updated:** 2026-03-06

---

## Overview

**Artifacts** are domain-defined recognition items earned by entities when they demonstrate sustained competence in a defined skill set. They serve as clear, verifiable milestones rather than opaque scores.

**Boss challenges** are high-stakes assessment tasks that gate artifact award — the entity must demonstrate mastery under conditions that test the skill comprehensively.

---

## Artifacts

### Definition

An artifact is defined in the Domain Physics with the following fields:

```yaml
artifacts:
  - id: core_operation_foundations
    name: "Core Operation — Foundations"
    description: "Demonstrates reliable completion of required domain checks under constrained conditions."
    unlock_condition: "proficiency >= 0.8 on all required capabilities, confirmed by boss challenge"
    proficiency_threshold: 0.8
    skills_required:
      - capability_a
      - capability_b
      - capability_c
```

### Artifact Award Process

1. **Threshold check**: All `skills_required` must have score >= `proficiency_threshold`
2. **Boss challenge**: A boss challenge task is presented (see below)
3. **Boss pass**: The entity must pass the boss challenge
4. **OutcomeRecord**: An `OutcomeRecord` is appended to the CTL with `artifact_earned: <artifact_id>`
5. **Profile update**: The artifact is recorded in the entity profile

Artifacts may not be awarded without the boss challenge, even if score thresholds are met.

### Artifact Integrity

- Artifacts are non-revocable once awarded (the CTL is append-only)
- An entity may re-attempt a boss challenge if they fail; each attempt is a separate `OutcomeRecord`
- Proficiency estimates may decrease over time (decay), but awarded artifacts are permanent records of demonstrated competence at the time of award

---

## Boss Challenges

### Definition

A boss challenge is a focused assessment task designed to confirm that mastery is genuine, not incidental. Characteristics:

- **Comprehensive**: Tests all skills required for the target artifact in a single coherent task
- **Novel**: Uses a problem the subject has not seen in the current session
- **No scaffolding**: No hints are available during a boss challenge
- **Timed**: Response latency is recorded (unusually fast responses may indicate pattern-matching rather than understanding)
- **Verified**: The outcome is verified by tool adapters, not by AI interpretation alone

### Boss Challenge Task Structure

The following YAML is a universal template. Domain packs provide concrete instantiations.

```yaml
boss_challenge:
  id: "boss_capability_bundle_v1"
  target_artifact: core_operation_foundations
  skills_assessed:
    - capability_a
    - capability_b
    - capability_c
  task_description: >
    A constrained scenario requiring the entity to complete a sequence of
    domain checks and produce verifiable outcomes.
  grading:
    - check: verify_primary_constraint
      weight: 0.5
    - check: verify_secondary_constraint
      weight: 0.3
    - check: verify_traceability
      weight: 0.2
  pass_threshold: 0.8
  hints_allowed: false
  max_attempts_per_session: 1
```

Education-specific worked examples are in [`../artifact-and-mastery-examples.md`](../artifact-and-mastery-examples.md).

### Boss Challenge Outcome

| Outcome | CTL Record | Next Action |
|---------|-----------|-------------|
| Pass (score >= pass_threshold) | OutcomeRecord: pass, artifact_earned | Award artifact, update proficiency |
| Partial (threshold not met) | OutcomeRecord: partial | Continue practice, suggest weak skills |
| Fail | OutcomeRecord: fail | Continue practice, no escalation unless repeated failure |
| Abandoned | OutcomeRecord: abandoned | No penalty; subject may retry in future session |

---

## Proficiency Estimation (Mastery in Domain Terms)

### Proficiency Scale

Proficiency is expressed as a float 0..1 per skill or capability:

| Range | Interpretation |
|-------|---------------|
| 0.0 – 0.2 | No demonstrated proficiency |
| 0.2 – 0.4 | Early exposure, significant errors |
| 0.4 – 0.6 | Developing; correct with support |
| 0.6 – 0.8 | Proficient; mostly correct, minor errors |
| 0.8 – 1.0 | Strongly demonstrated; consistent, reliable |

### Proficiency Update Rules

Proficiency is updated by the active domain lib after each task:

- **Pass with no assist**: score increases (larger increase if no assist)
- **Pass with assist**: score increases modestly
- **Fail/constraint violation**: score decreases
- **Abandoned**: score unchanged

Concrete update functions are domain-owned. See the ZPD monitor implementation at [`../reference-implementations/zpd-monitor-v0.2.py`](../reference-implementations/zpd-monitor-v0.2.py).

### Proficiency Decay

Proficiency may decay over time if the subject has not exercised a capability recently. Decay is configurable per domain pack:

```yaml
proficiency_decay:
  enabled: true
  decay_rate_per_day: 0.01  # 1% per day of inactivity
  minimum_retained: 0.4     # score never decays below this
```

Decay is applied when the entity profile is loaded for a new session.

---

## Assessment vs. Surveillance

These two principles govern all assessment:

1. **Proficiency is measured from verifiable outcomes, not behavioral inference.** The system uses structured result fields from tool checks and invariant outcomes, not conversational tone or unstructured cues.

2. **Preferences do not affect assessment.** An entity's stated interests are used for example theming only (see [`world-sim-spec-v1.md`](world-sim-spec-v1.md)). The same mathematical equivalence check applies to a rocket-themed problem and an apple-themed problem.

---

## References

- [`../../../standards/domain-physics-schema-v1.json`](../../../standards/domain-physics-schema-v1.json) — artifact field definition in domain physics schema (engine-level)
- [`../../../standards/causal-trace-ledger-v1.md`](../../../standards/causal-trace-ledger-v1.md) — OutcomeRecord definition (engine-level)
- [`../artifact-and-mastery-examples.md`](../artifact-and-mastery-examples.md) — education-domain worked examples
- [`world-sim-spec-v1.md`](world-sim-spec-v1.md) — how preferences shape the simulation context without affecting assessment
- [`magic-circle-consent-v1.md`](magic-circle-consent-v1.md) — consent boundary required before any session containing boss challenges
