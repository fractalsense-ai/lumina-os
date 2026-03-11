"""Deterministic problem generator for algebra equations.

Maps a ZPD-derived difficulty value to the matching difficulty tier
defined in domain-physics ``equation_difficulty_tiers`` and produces
a randomised equation whose solution is always a positive integer.

All generation is server-side Python (stdlib ``random`` only) so that
correct answers are guaranteed, fast to produce, and fully auditable.
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
    contains *difficulty*.  Falls back to the last tier when *difficulty*
    equals or exceeds the upper bound of every tier.
    """
    for tier in tiers:
        lo = float(tier.get("min_difficulty", 0.0))
        hi = float(tier.get("max_difficulty", 1.0))
        if lo <= difficulty < hi:
            return tier
    # Edge case: difficulty == 1.0 or above all tiers → last tier
    return tiers[-1]


# ── Equation Generators (one per tier) ────────────────────────


def _generate_single_step_isolation() -> dict[str, Any]:
    """Tier 1: x + a = b  (one-step addition/subtraction).

    Constraints:
      * a in [1..20], answer in [1..20]
      * b = answer + a  → always a positive integer
    """
    a = random.randint(1, 20)
    answer = random.randint(1, 20)
    b = answer + a
    return {
        "equation": f"x + {a} = {b}",
        "target_variable": "x",
        "expected_answer": f"x = {answer}",
    }


def _generate_variable_consolidation() -> dict[str, Any]:
    """Tier 2: ax = b  (one-step multiplication).

    Constraints:
      * a in [2..12], answer in [1..15]
      * b = a * answer  → always a positive integer
    """
    a = random.randint(2, 12)
    answer = random.randint(1, 15)
    b = a * answer
    return {
        "equation": f"{a}x = {b}",
        "target_variable": "x",
        "expected_answer": f"x = {answer}",
    }


def _generate_multi_step_linear() -> dict[str, Any]:
    """Tier 3: ax ± b = c  (two-step linear equation).

    Constraints:
      * a in [2..8], b in [1..15], answer in [1..12]
      * Randomly choose addition or subtraction
      * c is computed so the solution is always a positive integer
    """
    a = random.randint(2, 8)
    b = random.randint(1, 15)
    answer = random.randint(1, 12)
    if random.choice([True, False]):
        # ax + b = c  →  c = a*answer + b
        c = a * answer + b
        equation = f"{a}x + {b} = {c}"
    else:
        # ax - b = c  →  c = a*answer - b
        c = a * answer - b
        equation = f"{a}x - {b} = {c}"
    return {
        "equation": equation,
        "target_variable": "x",
        "expected_answer": f"x = {answer}",
    }


_GENERATORS: dict[str, Any] = {
    "single_step_isolation": _generate_single_step_isolation,
    "variable_consolidation": _generate_variable_consolidation,
    "multi_step_linear": _generate_multi_step_linear,
}


# ── Public API ────────────────────────────────────────────────


def generate_problem(
    difficulty: float,
    tiers: list[dict[str, Any]],
) -> dict[str, Any]:
    """Generate a random equation appropriate for *difficulty*.

    Parameters
    ----------
    difficulty:
        Float in ``[0, 1]`` — typically ``nominal_difficulty`` or the
        current challenge estimate from the ZPD monitor.
    tiers:
        The ``equation_difficulty_tiers`` list from domain-physics
        ``subsystem_configs``.

    Returns
    -------
    dict with keys: ``equation``, ``target_variable``, ``expected_answer``,
    ``equation_type``, ``difficulty_tier``, ``status``.
    """
    tier = select_tier(difficulty, tiers)
    equation_type = str(tier.get("equation_type", "single_step_isolation"))
    tier_id = str(tier.get("tier_id", "tier_1"))

    generator = _GENERATORS.get(equation_type, _generate_single_step_isolation)
    problem = generator()

    problem["equation_type"] = equation_type
    problem["difficulty_tier"] = tier_id
    problem["status"] = "in_progress"
    return problem
