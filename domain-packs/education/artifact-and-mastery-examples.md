# Education Artifact and Mastery Examples

This document holds education-domain examples that are intentionally not part of universal core specs.

## Algebra Boss Challenge Example

```yaml
boss_challenge:
  id: "boss_linear_equations_v1"
  target_artifact: linear_equations_basic
  skills_assessed:
    - solve_one_variable
    - check_equivalence
    - show_work_steps
  task_description: >
    A multi-step problem requiring the subject to solve for x in a two-step
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

## Education Mastery Update Reference

In education packs, score updates are implemented by the education domain lib (ZPD monitor implementation):
- [`reference-implementations/zpd-monitor-v0.2.py`](reference-implementations/zpd-monitor-v0.2.py)
- [`modules/algebra-level-1/domain-physics.yaml`](modules/algebra-level-1/domain-physics.yaml)

## Core Boundary

The artifact and mastery specification for this domain is at:
- [`world-sim/artifact-and-mastery-spec-v1.md`](world-sim/artifact-and-mastery-spec-v1.md)

Education-specific scoring semantics and examples live here.
