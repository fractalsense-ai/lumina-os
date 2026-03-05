# Artifact and Mastery Specification — V1

**Version:** 1.1.0  
**Status:** Active  
**Last updated:** 2026-03-05

---

## Overview

**Artifacts** are mastery recognition items earned by entities when they demonstrate sustained competence in a defined skill set. They serve as clear, verifiable milestones rather than opaque "scores."

**Boss challenges** are high-stakes assessment tasks that gate artifact award — the entity must demonstrate mastery under conditions that test the skill comprehensively.

---

## Artifacts

### Definition

An artifact is defined in the Domain Physics with the following fields:

```yaml
artifacts:
  - id: linear_equations_basic
    name: "Linear Equations — Foundations"
    description: "Demonstrates ability to solve single-variable linear equations with equivalence preservation."
    unlock_condition: "mastery >= 0.8 on all required skills, confirmed by boss challenge"
    mastery_threshold: 0.8
    skills_required:
      - solve_one_variable
      - check_equivalence
      - show_work_steps
```

### Artifact Award Process

1. **Threshold check**: All `skills_required` must have mastery ≥ `mastery_threshold`
2. **Boss challenge**: A boss challenge task is presented (see below)
3. **Boss pass**: The entity must pass the boss challenge
4. **OutcomeRecord**: An `OutcomeRecord` is appended to the CTL with `artifact_earned: <artifact_id>`
5. **Profile update**: The artifact is recorded in the entity profile

Artifacts may not be awarded without the boss challenge, even if mastery thresholds are met.

### Artifact Integrity

- Artifacts are non-revocable once awarded (the CTL is append-only)
- An entity may re-attempt a boss challenge if they fail; each attempt is a separate `OutcomeRecord`
- Mastery estimates may decrease over time (decay), but awarded artifacts are permanent records of demonstrated mastery at the time of award

---

## Boss Challenges

### Definition

A boss challenge is a focused assessment task designed to confirm that mastery is genuine, not incidental. Characteristics:

- **Comprehensive**: Tests all skills required for the target artifact in a single coherent task
- **Novel**: Uses a problem the learner has not seen in the current session
- **No scaffolding**: No hints are available during a boss challenge
- **Timed**: Response latency is recorded (unusually fast responses may indicate pattern-matching rather than understanding)
- **Verified**: The outcome is verified by tool adapters, not by AI interpretation alone

### Boss Challenge Task Structure

> **Education domain example.** The following YAML shows an algebra boss challenge from the education domain. Other domains define equivalent boss challenge structures for their own skill assessments (e.g., an agriculture domain might gate a "Crop Rotation Certification" artifact on a field-planning assessment task).

```yaml
boss_challenge:
  id: "boss_linear_equations_v1"
  target_artifact: linear_equations_basic
  skills_assessed:
    - solve_one_variable
    - check_equivalence
    - show_work_steps
  task_description: >
    A multi-step problem requiring the entity to solve for x in a two-step
    equation and verify their solution.
  grading:
    - check: verify_algebraic_equivalence
      weight: 0.5
    - check: verify_solution_substitution
      weight: 0.3
    - check: step_count_minimum
      weight: 0.2
  pass_threshold: 0.8
  hints_allowed: false
  max_attempts_per_session: 1
```

### Boss Challenge Outcome

| Outcome | CTL Record | Next Action |
|---------|-----------|-------------|
| Pass (score ≥ pass_threshold) | OutcomeRecord: pass, artifact_earned | Award artifact, update mastery |
| Partial (threshold not met) | OutcomeRecord: partial | Continue practice, suggest weak skills |
| Fail | OutcomeRecord: fail | Continue practice, no escalation unless repeated failure |
| Abandoned | OutcomeRecord: abandoned | No penalty; learner may retry in future session |

---

## Mastery Estimation

### Mastery Scale

Mastery is expressed as a float 0..1 per skill:

| Range | Interpretation |
|-------|---------------|
| 0.0 – 0.2 | No demonstrated mastery |
| 0.2 – 0.4 | Early exposure, significant errors |
| 0.4 – 0.6 | Developing; correct with support |
| 0.6 – 0.8 | Proficient; mostly correct, minor errors |
| 0.8 – 1.0 | Mastered; consistent, reliable |

### Mastery Update Rules

Mastery is updated by the domain sensor after each task (in the education domain, this is the ZPD monitor):

- **Correct + no hint**: mastery increases (larger increase if no hint)
- **Correct + hint used**: mastery increases modestly
- **Incorrect**: mastery decreases (larger decrease if repeated error)
- **Abandoned**: mastery unchanged

The exact update function for the education domain is in [`../domain-packs/education/reference-implementations/zpd-monitor-v0.2.py`](../domain-packs/education/reference-implementations/zpd-monitor-v0.2.py).

### Mastery Decay

Mastery may decay over time if the learner has not practiced a skill recently. Decay is configurable per domain pack:

```yaml
mastery_decay:
  enabled: true
  decay_rate_per_day: 0.01  # 1% per day of inactivity
  minimum_retained: 0.4     # mastery never decays below this
```

Decay is applied when the entity profile is loaded for a new session.

---

## Assessment vs. Surveillance

These two principles govern all assessment:

1. **Mastery is measured from task performance, not behavioral inference.** The system looks at whether the learner solved the problem correctly, how many steps they showed, whether they needed a hint — not at how they phrased things, their tone, or other conversational signals.

2. **Preferences do not affect assessment.** An entity's stated interests are used for example theming only. The same mathematical equivalence check applies to a rocket-themed problem and an apple-themed problem.

---

## References

- [`../standards/domain-physics-schema-v1.json`](../standards/domain-physics-schema-v1.json) — artifact schema
- [`../domain-packs/education/reference-implementations/zpd-monitor-v0.2.py`](../domain-packs/education/reference-implementations/zpd-monitor-v0.2.py) — mastery update implementation
- [`../domain-packs/education/algebra-level-1/domain-physics.yaml`](../domain-packs/education/algebra-level-1/domain-physics.yaml) — worked example
