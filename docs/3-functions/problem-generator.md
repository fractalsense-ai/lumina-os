# problem-generator(3)

## NAME

`problem_generator.py` — Deterministic tier-based algebra problem generator

## SYNOPSIS

```python
from problem_generator import generate_problem, select_tier

problem = generate_problem(difficulty, tiers)
```

## DESCRIPTION

`problem_generator.py` generates randomised algebra equations for the education domain. It maps a ZPD-derived difficulty value to the appropriate difficulty tier and returns an equation with a guaranteed positive-integer solution.

All generation is server-side Python (stdlib `random` only) — no external dependencies, no LLM calls. Solutions are always positive integers, making automated verification trivial.

**When it is called:** The API server calls `generate_problem` when the fluency monitor or ZPD monitor returns an `advance_tier` action, or when initialising a new session. The resulting `ProblemSpec` dict is stored as `current_problem` in session state and surfaced in task context for the turn interpreter and domain adapters.

**Difficulty tiers** are defined in `domain-physics.yaml` under `equation_difficulty_tiers` and loaded at runtime via the domain physics config. The three tiers in the education algebra-level-1 pack are:

| Tier | Form | Steps | Example |
|------|------|-------|---------|
| `tier_1` | `x + a = b` | 1 | `x + 7 = 12` → `x = 5` |
| `tier_2` | `ax = b` | 1 | `3x = 15` → `x = 5` |
| `tier_3` | `ax ± b = c` | 2 | `3x + 4 = 19` → `x = 5` |

---

## FUNCTIONS

### `generate_problem(difficulty, tiers) → dict`

Generate a random equation appropriate for the given difficulty value.

**Parameters**

| Name | Type | Description |
|------|------|-------------|
| `difficulty` | `float` | Value in `[0, 1]` — typically `nominal_difficulty` or the current challenge estimate from the ZPD monitor |
| `tiers` | `list[dict]` | Tier definitions from domain physics (`equation_difficulty_tiers`); each entry must have `min_difficulty`, `max_difficulty`, and `generator` keys |

**Returns**

A `ProblemSpec` dict:

```json
{
  "equation": "3x + 4 = 19",
  "target_variable": "x",
  "expected_answer": "x = 5",
  "tier_id": "tier_3",
  "tier_label": "Multi-step linear",
  "min_difficulty": 0.6,
  "max_difficulty": 1.0
}
```

| Key | Type | Description |
|-----|------|-------------|
| `equation` | `str` | Equation string (e.g. `"3x + 4 = 19"`) |
| `target_variable` | `str` | Variable to solve for (always `"x"` in algebra-level-1) |
| `expected_answer` | `str` | Solution in `"x = N"` form |
| `tier_id` | `str` | Tier identifier from domain physics |
| `tier_label` | `str` | Human-readable tier name |
| `min_difficulty` | `float` | Lower bound of this tier's difficulty range |
| `max_difficulty` | `float` | Upper bound of this tier's difficulty range |

**Equation constraints by tier:**

| Tier | Constraints |
|------|-------------|
| `tier_1` (`single_step_isolation`) | `a ∈ [1, 20]`, `answer ∈ [1, 20]`, `b = answer + a` |
| `tier_2` (`variable_consolidation`) | `a ∈ [2, 12]`, `answer ∈ [1, 15]`, `b = a × answer` |
| `tier_3` (`multi_step_linear`) | `a ∈ [2, 8]`, `b ∈ [1, 15]`, `answer ∈ [1, 12]`, randomly `ax + b = c` or `ax − b = c` |

---

### `select_tier(difficulty, tiers) → dict`

Returns the tier whose `[min_difficulty, max_difficulty)` range contains `difficulty`. Falls back to the last tier when `difficulty` equals or exceeds the upper bound of all tiers.

**Parameters**

| Name | Type | Description |
|------|------|-------------|
| `difficulty` | `float` | Value in `[0, 1]` |
| `tiers` | `list[dict]` | Ordered list of tier dicts from domain physics |

**Returns** a single tier dict from the `tiers` list.

---

## PROPERTIES

- **Deterministic structure:** Given the same `difficulty` and `tiers` config, the tier selected is always the same. The specific equation within that tier varies (uses `stdlib.random`).
- **Always positive-integer solutions:** All generators guarantee `answer ≥ 1` and `answer ∈ ℤ`.
- **No external dependencies:** Standard library only (`random`).
- **Auditable:** All parameters and the generated equation are stored in the `ProblemSpec` dict in session state.

---

## SOURCE

`domain-packs/education/reference-implementations/problem_generator.py`

## SEE ALSO

- `domain-packs/education/modules/algebra-level-1/domain-physics.yaml` — defines `equation_difficulty_tiers` (tier boundaries and generator names)
- `domain-packs/education/reference-implementations/fluency_monitor.py` — `advance_tier` action triggers a new problem generation call
- `domain-packs/education/reference-implementations/runtime-adapters.py` — `domain_step()` merges fluency decision and triggers problem generation
- `reference-implementations/lumina-api-server.py` — wrapper that calls `generate_problem` when `advance_tier` is received
