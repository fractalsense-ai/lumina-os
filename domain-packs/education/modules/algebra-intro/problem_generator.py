"""Algebra-intro problem generator.

Produces randomised problems whose generator keys match the
``equation_difficulty_tiers`` declared in the algebra-intro
domain-physics:

  tier_1 → slope_and_rates            (slope from table/graph, y = mx + b)
  tier_2 → linear_equations_y_equals_mx_b  (write equation from point+slope)
  tier_3 → systems_of_two_variables   (2×2 systems)

All answers are guaranteed clean integers or simple fractions.
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


# ── Generators ────────────────────────────────────────────────


def _generate_slope_and_rates() -> dict[str, Any]:
    """Tier 1: slope / rate of change problems.

    Forms: find slope from two points, identify m and b from y = mx + b.
    """
    if random.choice([True, False]):
        # Slope from two points
        x1, y1 = random.randint(0, 5), random.randint(0, 10)
        m = random.choice([-3, -2, -1, 1, 2, 3, 4, 5])
        dx = random.randint(1, 4)
        x2 = x1 + dx
        y2 = y1 + m * dx
        equation = f"Find the slope of the line through ({x1}, {y1}) and ({x2}, {y2})"
        expected = f"m = {m}"
    else:
        # Identify m and b
        m = random.choice([-4, -3, -2, -1, 1, 2, 3, 4, 5])
        b = random.randint(-10, 10)
        equation = f"Identify the slope and y-intercept of y = {m}x + {b}"
        expected = f"m = {m}, b = {b}"
    return {
        "equation": equation,
        "target_variable": "x",
        "expected_answer": expected,
        "min_steps": 1,
    }


def _generate_linear_equations_y_equals_mx_b() -> dict[str, Any]:
    """Tier 2: write equation of a line from point and slope.

    Form: given point (x1, y1) and slope m, write y = mx + b.
    """
    m = random.choice([-3, -2, -1, 1, 2, 3, 4])
    x1 = random.randint(1, 6)
    b = random.randint(-8, 8)
    y1 = m * x1 + b
    equation = f"Write the equation of the line through ({x1}, {y1}) with slope {m}"
    expected = f"y = {m}x + {b}"
    return {
        "equation": equation,
        "target_variable": "x",
        "expected_answer": expected,
        "min_steps": 2,
    }


def _generate_systems_of_two_variables() -> dict[str, Any]:
    """Tier 3: 2×2 systems of linear equations.

    Form: {y = ax + b, cx + dy = e} with integer solution.
    """
    # Generate a solution first
    x_ans = random.randint(-5, 8)
    y_ans = random.randint(-5, 8)

    # Equation 1: y = mx + b
    m1 = random.choice([-3, -2, -1, 1, 2, 3])
    b1 = y_ans - m1 * x_ans
    eq1 = f"y = {m1}x + {b1}"

    # Equation 2: ax + by = c
    a2 = random.randint(1, 4)
    b2 = random.choice([-3, -2, -1, 1, 2, 3])
    c2 = a2 * x_ans + b2 * y_ans
    eq2 = f"{a2}x + {b2}y = {c2}"

    equation = f"Solve the system: {eq1} and {eq2}"
    expected = f"x = {x_ans}, y = {y_ans}"
    return {
        "equation": equation,
        "target_variable": "x",
        "expected_answer": expected,
        "min_steps": 4,
    }


_GENERATORS: dict[str, Any] = {
    "slope_and_rates": _generate_slope_and_rates,
    "linear_equations_y_equals_mx_b": _generate_linear_equations_y_equals_mx_b,
    "systems_of_two_variables": _generate_systems_of_two_variables,
}


# ── Public API ────────────────────────────────────────────────


def generate_problem(
    difficulty: float,
    subsystem_configs: dict[str, Any],
) -> dict[str, Any]:
    """Generate an algebra-intro problem appropriate for *difficulty*."""
    tiers: list[dict[str, Any]] = subsystem_configs.get("equation_difficulty_tiers") or []
    tier = select_tier(difficulty, tiers)
    equation_type = str(tier.get("equation_type", "slope_and_rates"))
    tier_id = str(tier.get("tier_id", "tier_1"))

    generator = _GENERATORS.get(equation_type, _generate_slope_and_rates)
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
