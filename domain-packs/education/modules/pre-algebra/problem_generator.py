"""Pre-algebra problem generator.

Produces randomised problems whose generator keys match the
``equation_difficulty_tiers`` declared in the pre-algebra
domain-physics:

  tier_1 → single_operation        (x + a = b, or evaluate f(x))
  tier_2 → single_step_equations   (ax = b, multi-digit x + a = b)
  tier_3 → multi_step_and_inequalities  (ax ± b = c, ax ± b < c)

All answers are guaranteed positive integers.
"""

from __future__ import annotations

import random
from typing import Any


# ── Tier Selection (same logic as the shared domain-lib generator) ─


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


def _generate_single_operation() -> dict[str, Any]:
    """Tier 1: basic single-operation arithmetic.

    Forms: x + a = b, x - a = c, a + x = b
    Constraints: operands in [1..20], answer always positive.
    """
    form = random.choice(["add", "sub", "add_rev"])
    if form == "add":
        a = random.randint(1, 20)
        answer = random.randint(1, 20)
        equation = f"x + {a} = {answer + a}"
    elif form == "sub":
        # x - a = c  →  x = c + a.  Pick c positive so answer > a.
        a = random.randint(1, 15)
        c = random.randint(1, 15)
        answer = c + a
        equation = f"x - {a} = {c}"
    else:
        a = random.randint(1, 20)
        answer = random.randint(1, 20)
        equation = f"{a} + x = {a + answer}"
    return {
        "equation": equation,
        "target_variable": "x",
        "expected_answer": f"x = {answer}",
        "min_steps": 1,
    }


def _generate_single_step_equations() -> dict[str, Any]:
    """Tier 2: single-step equations with multiplication or larger numbers.

    Forms: ax = b  (a in [2..12], answer in [1..15])
           x + a = b  with multi-digit numbers (a in [10..50])
    """
    if random.choice([True, False]):
        # ax = b
        a = random.randint(2, 12)
        answer = random.randint(1, 15)
        b = a * answer
        equation = f"{a}x = {b}"
    else:
        # x + a = b with larger numbers
        a = random.randint(10, 50)
        answer = random.randint(10, 50)
        b = answer + a
        equation = f"x + {a} = {b}"
    return {
        "equation": equation,
        "target_variable": "x",
        "expected_answer": f"x = {answer}",
        "min_steps": 1,
    }


def _generate_multi_step_and_inequalities() -> dict[str, Any]:
    """Tier 3: two-step linear equations and inequalities.

    Forms: ax + b = c, ax - b = c, ax + b < c, ax + b >= c
    Constraints: a in [2..8], b in [1..15], answer in [1..12]
    """
    a = random.randint(2, 8)
    b = random.randint(1, 15)
    answer = random.randint(1, 12)
    is_inequality = random.choice([True, False])

    if random.choice([True, False]):
        c = a * answer + b
        lhs = f"{a}x + {b}"
    else:
        c = a * answer - b
        lhs = f"{a}x - {b}"

    if is_inequality:
        op = random.choice(["<", ">", "\u2264", "\u2265"])
        equation = f"{lhs} {op} {c}"
        expected = f"x {_flip_op(op) if False else op} {answer}"
        # For the student, the answer is the boundary value
        # (the direction stays the same when dividing by positive a)
        expected = f"x {op} {answer}"
    else:
        equation = f"{lhs} = {c}"
        expected = f"x = {answer}"

    return {
        "equation": equation,
        "target_variable": "x",
        "expected_answer": expected,
        "min_steps": 2,
    }


def _flip_op(op: str) -> str:
    return {"<": ">", ">": "<", "\u2264": "\u2265", "\u2265": "\u2264"}.get(op, op)


_GENERATORS: dict[str, Any] = {
    "single_operation": _generate_single_operation,
    "single_step_equations": _generate_single_step_equations,
    "multi_step_and_inequalities": _generate_multi_step_and_inequalities,
}


# ── Public API (same signature as the shared generator) ───────


def generate_problem(
    difficulty: float,
    subsystem_configs: dict[str, Any],
) -> dict[str, Any]:
    """Generate a pre-algebra problem appropriate for *difficulty*."""
    tiers: list[dict[str, Any]] = subsystem_configs.get("equation_difficulty_tiers") or []
    tier = select_tier(difficulty, tiers)
    equation_type = str(tier.get("equation_type", "single_operation"))
    tier_id = str(tier.get("tier_id", "tier_1"))

    generator = _GENERATORS.get(equation_type, _generate_single_operation)
    problem = generator()

    problem["equation_type"] = equation_type
    problem["difficulty_tier"] = tier_id
    problem["status"] = "in_progress"
    return problem
