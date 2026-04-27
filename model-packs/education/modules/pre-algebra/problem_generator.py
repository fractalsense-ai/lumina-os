"""Pre-algebra problem generator.

Produces randomised problems whose generator keys match the
``equation_difficulty_tiers`` declared in the pre-algebra
domain-physics:

  tier_1 → integer_and_fraction_ops  (integer arithmetic, fraction ops)
  tier_2 → ratios_and_expressions    (proportions, evaluate expressions)
  tier_3 → single_step_equations     (x + a = b, ax = b)

All answers are guaranteed positive integers or simple fractions.
"""

from __future__ import annotations

import random
from typing import Any


# ── Tier Selection ────────────────────────────────────────────


def select_tier(
    difficulty: float,
    tiers: list[dict[str, Any]],
) -> dict[str, Any]:
    """Return the tier whose ``[min_difficulty, max_difficulty)`` range
    contains *difficulty*.  Falls back to the last tier."""
    for tier in tiers:
        lo = float(tier.get("min_difficulty", 0.0))
        hi = float(tier.get("max_difficulty", 1.0))
        if lo <= difficulty < hi:
            return tier
    return tiers[-1]


# ── Generators (keyed to pre-algebra tier equation_types) ─────


def _generate_integer_and_fraction_ops() -> dict[str, Any]:
    """Tier 1: integer arithmetic and basic fraction operations.

    Forms: a + b, a - b, a * b, a / b with integers;
           simple fraction addition/subtraction.
    """
    form = random.choice(["int_add", "int_sub", "int_mul", "int_neg", "frac_add"])
    if form == "int_add":
        a = random.randint(-20, 20)
        b = random.randint(1, 20)
        answer = a + b
        equation = f"{a} + {b}"
        expected = str(answer)
    elif form == "int_sub":
        a = random.randint(-15, 25)
        b = random.randint(1, 20)
        answer = a - b
        equation = f"{a} - {b}"
        expected = str(answer)
    elif form == "int_mul":
        a = random.randint(-10, 10)
        b = random.randint(2, 10)
        answer = a * b
        equation = f"{a} × {b}"
        expected = str(answer)
    elif form == "int_neg":
        a = random.randint(1, 20)
        equation = f"|–{a}|"
        answer = a
        expected = str(answer)
    else:
        # Simple fraction addition with same denominator
        d = random.choice([2, 3, 4, 5, 6, 8])
        n1 = random.randint(1, d - 1)
        n2 = random.randint(1, d - 1)
        answer_n = n1 + n2
        equation = f"{n1}/{d} + {n2}/{d}"
        expected = f"{answer_n}/{d}"
    return {
        "equation": equation,
        "target_variable": None,
        "expected_answer": expected,
        "min_steps": 1,
    }


def _generate_ratios_and_expressions() -> dict[str, Any]:
    """Tier 2: proportions and expression evaluation.

    Forms: a/b = x/d (solve for x), or evaluate expression given x.
    """
    if random.choice([True, False]):
        # Proportion: a/b = x/d
        a = random.randint(1, 10)
        b = random.randint(2, 8)
        d = random.randint(2, 12)
        answer = a * d // b if (a * d) % b == 0 else a * d / b
        # Ensure clean integer answer
        mult = random.randint(2, 5)
        a = random.randint(1, 8)
        b = random.randint(2, 6)
        d = b * mult
        answer = a * mult
        equation = f"{a}/{b} = x/{d}"
        expected = f"x = {answer}"
    else:
        # Evaluate expression: given x = val, find result
        val = random.randint(2, 8)
        coeff = random.randint(2, 6)
        const = random.randint(1, 10)
        answer = coeff * val + const
        equation = f"Evaluate {coeff}x + {const} when x = {val}"
        expected = str(answer)
    return {
        "equation": equation,
        "target_variable": "x",
        "expected_answer": expected,
        "min_steps": 1,
    }


def _generate_single_step_equations() -> dict[str, Any]:
    """Tier 3: single-step equations.

    Forms: x + a = b, ax = b
    Constraints: answer always a positive integer.
    """
    if random.choice([True, False]):
        # x + a = b
        a = random.randint(1, 20)
        answer = random.randint(1, 20)
        b = answer + a
        equation = f"x + {a} = {b}"
    else:
        # ax = b
        a = random.randint(2, 12)
        answer = random.randint(1, 15)
        b = a * answer
        equation = f"{a}x = {b}"
    return {
        "equation": equation,
        "target_variable": "x",
        "expected_answer": f"x = {answer}",
        "min_steps": 1,
    }


_GENERATORS: dict[str, Any] = {
    "integer_and_fraction_ops": _generate_integer_and_fraction_ops,
    "ratios_and_expressions": _generate_ratios_and_expressions,
    "single_step_equations": _generate_single_step_equations,
}


# ── Public API (same signature as the shared generator) ───────


def generate_problem(
    difficulty: float,
    subsystem_configs: dict[str, Any],
) -> dict[str, Any]:
    """Generate a pre-algebra problem appropriate for *difficulty*."""
    tiers: list[dict[str, Any]] = subsystem_configs.get("equation_difficulty_tiers") or []
    tier = select_tier(difficulty, tiers)
    equation_type = str(tier.get("equation_type", "integer_and_fraction_ops"))
    tier_id = str(tier.get("tier_id", "tier_1"))

    generator = _GENERATORS.get(equation_type, _generate_integer_and_fraction_ops)
    problem = generator()

    problem["equation_type"] = equation_type
    problem["difficulty_tier"] = tier_id
    problem["status"] = "in_progress"
    return problem


def initialize_task(
    task_spec: dict[str, Any],
    runtime: dict[str, Any],
    *,
    domain_id: str | None = None,
) -> dict[str, Any]:
    """Task initializer adapter — creates ``current_problem`` at session start."""
    difficulty = float(task_spec.get("nominal_difficulty", 0.5))
    subsystem_configs = (runtime.get("domain") or {}).get("subsystem_configs") or {}
    return generate_problem(difficulty, subsystem_configs)
