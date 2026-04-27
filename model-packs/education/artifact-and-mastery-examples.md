# Education Artifact and Mastery Examples

This is the living curriculum reference for all algebra domain packs. It documents
the diagnostic law framework, the 15-artifact progression across 3 grade-band modules,
and the boss challenge specification format.

Education-specific scoring semantics and examples are defined here. The formal
artifact/mastery contract is at [`world-sim/artifact-and-mastery-spec-v1.md`](world-sim/artifact-and-mastery-spec-v1.md).

---

## The Sensor Principle

**The equation is the sensor. The student's work-steps are the signal. The
invariant violation is the diagnosis.**

We do not ask students "do you understand the law of equivalence?" We give them
`3x + 2 = 11` and watch which side they subtract 2 from. Every equation type in
these modules is chosen *specifically* because it makes a target diagnostic law
observable. A student cannot pass the boss challenge without demonstrating the law —
the problem structure forces the signal.

---

## The 6 Diagnostic Laws

| # | Law Name | What the Sensor Tests | Canonical Failure Signal | Invariant ID | Active From |
|---|----------|-----------------------|--------------------------|--------------|-------------|
| 1 | Balance Principle | Both sides of the equation must stay equal after every step | Subtracts 2 from one side only in `3x + 2 = 11` | `equivalence_preserved` | Pre-Algebra |
| 2 | Inverse Operations | Undo operations in reverse PEMDAS order to isolate x | Multiplies by 4 before adding 5 when solving `x/4 - 5 = 10` | `reversibility_order_correct` | Pre-Algebra |
| 3 | Interchangeability | Expressions are swappable entities — knowing `y` means you can replace it anywhere | Substitutes into only one equation of a system, not propagating consistently | `substitution_valid` | Algebra Intro |
| 4 | Structure Preservation | Shape of an expression can change (factor/distribute) without changing its value | Distributes `3(x + 4)` as `3x + 4` instead of `3x + 12` | `structure_preserved` | Algebra 1 |
| 5 | Relational Mapping | x and y move together; rate is the engine, y-intercept is the start | Inverts slope (reads y-change as x-change) or mistakes intercept for rate | `relationship_correctly_mapped` | Algebra Intro |
| 6 | Abstraction | Real-world constraints can be transcribed into a precise mathematical sentence | Writes `C = 30m + 0.15` instead of `C = 0.15m + 30` for a per-mile cost problem | `model_accurately_transcribed` | Algebra 1 |

Laws activate **progressively** — a law only becomes an enforceable invariant once
the module where it is *observable* begins. Earlier modules do not fire invariants
for laws their equation forms cannot expose.

---

## 15 Artifacts Across 3 Grade-Band Modules

### Module 1: `pre-algebra` — Grades 6–7 — Laws 1 + 2 active

Establish the foundational understanding of balance and inverse operations before
introducing dynamic variable relationships.

| # | Artifact ID | Unit | Boss Challenge Sensor Form | Laws Diagnosed |
|---|-------------|------|---------------------------|----------------|
| 1 | `variables_and_expressions` | 1 — Foundations | Evaluate `3(x + 4y) - 2z` given x=2, y=1, z=3, show every step | Law 1 introduction — substitution preserves structure |
| 2 | `order_of_operations` | 1 — Foundations | Simplify `4 + 3 × (8 − 2)² ÷ 9`, show each operation in order | Law 2 foundation — must know the order before reversing it |
| 3 | `single_step_equations` | 2 — Linear Eqs | Solve `7x = 84`, show inverse operation on both sides, verify | Laws 1+2 basic form |
| 4 | `multi_step_linear_equations` | 2 — Linear Eqs | Solve `3x − 7 = 14`, show both steps in correct order, verify | Laws 1+2 combined — **reverse order is the critical diagnostic** |
| 5 | `linear_inequalities` | 2 — Linear Eqs | Solve `−4x + 3 > −9`, flip inequality sign, state solution set | Laws 1+2 + the direction-flip rule |

**Sensor note for Artifact 4**: If the student divides by 3 before adding 7, they
have failed the Law 2 test. The work-steps reveal this without asking. The boss
challenge equation is specifically designed to require two steps where the wrong
order is tempting and detectable.

**Sensor note for Artifact 5**: The negative coefficient on x forces the direction-
flip signal. A student who arrives at `x > 3` instead of `x < 3` after dividing by
−4 has produced the canonical Law 2 direction-flip failure.

---

### Module 2: `algebra-intro` — Grade 8 — Adds Laws 3 + 5

Variables stop being static hidden numbers and start moving together. Two rules can
now be in play at the same time.

| # | Artifact ID | Unit | Boss Challenge Sensor Form | Laws Diagnosed |
|---|-------------|------|---------------------------|----------------|
| 6 | `slope_and_rate_of_change` | 3 — Graphing | Calculate slope from a two-column table and identify what it represents | Law 5 — rate as the engine |
| 7 | `linear_forms_and_graphing` | 3 — Graphing | Given `y = 3x + 5`, identify rate and starting value; graph from two methods | Laws 1+5 — balance + dynamic relationship |
| 8 | `systems_by_graphing` | 4 — Systems | Graph both lines and identify the intersection coordinates | Law 3 entry — two balanced rules agreeing at one point |
| 9 | `systems_by_substitution` | 4 — Systems | Substitute `y = 2x − 4` into `3x + y = 10`, solve, verify in both equations | Laws 1+2+3 — the canonical Law 3 sensor |
| 10 | `systems_by_elimination` | 4 — Systems | Eliminate a variable by adding/subtracting the equations, solve, verify | Laws 1+2+3 — Law 1 applied to whole equations |

**Sensor note for Artifact 9**: Substituting `y = 2x − 4` into only one equation and
not verifying in the second is the Law 3 failure signal. The student has treated the
expression as a local plug-in rather than a binding interchangeable identity.

---

### Module 3: `algebra-1` — Grade 9 — Adds Laws 4 + 6

The sensor runs at full capacity. Structural manipulation and real-world modeling
become the primary diagnostic targets.

| # | Artifact ID | Unit | Boss Challenge Sensor Form | Laws Diagnosed |
|---|-------------|------|---------------------------|----------------|
| 11 | `exponent_rules` | 5 — Exponents | Simplify `(x²)³ · x⁻¹ / x⁴` in one combined expression | Law 4 numeric — shape rules without changing value |
| 12 | `polynomial_operations` | 6 — Polynomials | Expand `(x + 3)(x − 5)` using FOIL, collect like terms | Laws 1+4 — assembly |
| 13 | `factoring_quadratics` | 6 — Polynomials | Factor `x² + 5x + 6` into `(x + 2)(x + 3)` — verify by expanding | Laws 1+4 — **disassembly — the hardest structural sensor** |
| 14 | `quadratic_graphs_and_vertex` | 7 — Quadratics | Find vertex, axis of symmetry, and roots of `y = x² − 6x + 5` | Law 5 — U-shaped dynamic relationship |
| 15 | `quadratic_equations` | 7 — Quadratics | Solve `x² − 5x + 6 = 0` by factoring; confirm with quadratic formula | Laws 1+2+4 — Law 6 word problem extension |

**Sensor note for Artifact 13**: Factoring is "un-multiplying." A student who can
only FOIL but cannot reverse the process (`x² + 5x + 6 → (x+2)(x+3)`) has mastered
assembly but not disassembly. They understand Law 4 in one direction only. The boss
challenge requires both: factor first, then verify by expanding.

---

## Boss Challenge Specification Format

Each artifact has exactly one boss challenge. The challenge is chosen because its
equation structure makes it impossible to pass without correctly applying the target
law(s). Passing by accident is ruled out by the grading weights and pass threshold.

```yaml
boss_challenge:
  id: "<unique_id>"
  task_description: >
    The complete problem text shown to the student.
    Multi-step. No hints available.
  sensor_purpose: >
    [Domain Authority only — not shown to students]
    Why this specific equation form was chosen. What law violation
    it is designed to make visible if the student fails.
  grading:
    - check: <evidence_field>
      weight: <0.0–1.0>  # weights must sum to 1.0
  pass_threshold: 0.8
  hints_allowed: false
  max_attempts_per_session: 1
```

The `sensor_purpose` field is writeable only by the Domain Authority. It documents
the pedagogical intent behind the equation design and is never shown to students.

---

## Module Implementation Status

| Module | Domain ID | Grade Band | Status | Artifacts |
|--------|-----------|------------|--------|-----------|
| `pre-algebra` | `domain/edu/pre-algebra/v1` | Grades 6–7 | **Active (v0.1.0)** | 1–5 |
| `algebra-intro` | `domain/edu/algebra-intro/v1` | Grade 8 | Planned | 6–10 |
| `algebra-1` | `domain/edu/algebra-1/v1` | Grade 9 | Planned | 11–15 |

**Legacy**: `domain/edu/algebra-level-1/v1` covers Artifacts 3–4 of the Pre-Algebra
module (`single_step_equations`, `multi_step_linear_equations`). It is the deployed
reference implementation for those artifacts and remains active for current users.
The `pre-algebra` module extends it with Artifacts 1, 2, and 5.

---

## Education Mastery Update Reference

Per-skill mastery is updated by the ZPD monitor after each turn. Scores are clamped
to `[0, 1]`. Skills not exercised in the current task are unchanged.

| Condition | Δ mastery |
|-----------|-----------|
| Correct, no hint | +0.10 |
| Correct, hint used | +0.03 |
| Partial, no hint | +0.02 |
| Partial, hint used | +0.01 |
| Incorrect, first time | −0.05 |
| Incorrect, repeated error | −0.08 |

Reference implementations:
- [`reference-implementations/zpd-monitor-v0.2.py`](reference-implementations/zpd-monitor-v0.2.py)
- [`modules/pre-algebra/domain-physics.yaml`](modules/pre-algebra/domain-physics.yaml)
- [`modules/algebra-level-1/domain-physics.yaml`](modules/algebra-level-1/domain-physics.yaml)
