"""Tests for the deterministic problem generator."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

# Ensure the education domain-pack reference-implementations are importable.
_EDU_REF = Path(__file__).resolve().parent.parent / "domain-packs" / "education" / "reference-implementations"
if str(_EDU_REF) not in sys.path:
    sys.path.insert(0, str(_EDU_REF))

from problem_generator import generate_problem, select_tier  # noqa: E402

# ── Tier definitions matching domain-physics.json ────────────

TIERS = [
    {
        "tier_id": "tier_1",
        "equation_type": "single_step_isolation",
        "equation_template": "x + a = b",
        "min_difficulty": 0.0,
        "max_difficulty": 0.35,
    },
    {
        "tier_id": "tier_2",
        "equation_type": "variable_consolidation",
        "equation_template": "ax = b",
        "min_difficulty": 0.35,
        "max_difficulty": 0.65,
    },
    {
        "tier_id": "tier_3",
        "equation_type": "multi_step_linear",
        "equation_template": "ax + b = c  or  ax - b = c",
        "min_difficulty": 0.65,
        "max_difficulty": 1.0,
    },
]


# ── select_tier ──────────────────────────────────────────────


class TestSelectTier:

    def test_entry_range(self):
        for d in [0.0, 0.1, 0.2, 0.34]:
            tier = select_tier(d, TIERS)
            assert tier["tier_id"] == "tier_1"

    def test_intermediate_range(self):
        for d in [0.35, 0.45, 0.5, 0.64]:
            tier = select_tier(d, TIERS)
            assert tier["tier_id"] == "tier_2"

    def test_advanced_range(self):
        for d in [0.65, 0.8, 0.99]:
            tier = select_tier(d, TIERS)
            assert tier["tier_id"] == "tier_3"

    def test_boundary_exactly_1_returns_last_tier(self):
        tier = select_tier(1.0, TIERS)
        assert tier["tier_id"] == "tier_3"

    def test_above_range_returns_last_tier(self):
        tier = select_tier(1.5, TIERS)
        assert tier["tier_id"] == "tier_3"


# ── generate_problem — tier 1 (single-step isolation) ────────


class TestGenerateTier1:

    def test_equation_format(self):
        problem = generate_problem(0.2, TIERS)
        assert re.match(r"^x \+ \d+ = \d+$", problem["equation"])

    def test_integer_solution(self):
        for _ in range(20):
            p = generate_problem(0.1, TIERS)
            # expected_answer is "x = <int>"
            answer_val = int(p["expected_answer"].split("=")[1].strip())
            assert answer_val >= 1

    def test_equation_is_correct(self):
        for _ in range(20):
            p = generate_problem(0.2, TIERS)
            # parse: x + a = b  →  answer = b - a
            m = re.match(r"^x \+ (\d+) = (\d+)$", p["equation"])
            assert m, f"Unexpected format: {p['equation']}"
            a, b = int(m.group(1)), int(m.group(2))
            answer = int(p["expected_answer"].split("=")[1].strip())
            assert answer == b - a

    def test_metadata(self):
        p = generate_problem(0.15, TIERS)
        assert p["equation_type"] == "single_step_isolation"
        assert p["difficulty_tier"] == "tier_1"
        assert p["target_variable"] == "x"
        assert p["status"] == "in_progress"


# ── generate_problem — tier 2 (variable consolidation) ───────


class TestGenerateTier2:

    def test_equation_format(self):
        problem = generate_problem(0.5, TIERS)
        assert re.match(r"^\d+x = \d+$", problem["equation"])

    def test_integer_solution(self):
        for _ in range(20):
            p = generate_problem(0.5, TIERS)
            answer_val = int(p["expected_answer"].split("=")[1].strip())
            assert answer_val >= 1

    def test_equation_is_correct(self):
        for _ in range(20):
            p = generate_problem(0.45, TIERS)
            m = re.match(r"^(\d+)x = (\d+)$", p["equation"])
            assert m, f"Unexpected format: {p['equation']}"
            a, b = int(m.group(1)), int(m.group(2))
            answer = int(p["expected_answer"].split("=")[1].strip())
            assert answer == b // a
            assert b % a == 0  # solution must be exact integer

    def test_metadata(self):
        p = generate_problem(0.5, TIERS)
        assert p["equation_type"] == "variable_consolidation"
        assert p["difficulty_tier"] == "tier_2"


# ── generate_problem — tier 3 (multi-step linear) ────────────


class TestGenerateTier3:

    def test_equation_format(self):
        problem = generate_problem(0.8, TIERS)
        assert re.match(r"^\d+x [+-] \d+ = -?\d+$", problem["equation"])

    def test_integer_solution(self):
        for _ in range(30):
            p = generate_problem(0.8, TIERS)
            answer_val = int(p["expected_answer"].split("=")[1].strip())
            assert answer_val >= 1

    def test_equation_is_correct(self):
        for _ in range(30):
            p = generate_problem(0.75, TIERS)
            eq = p["equation"]
            answer = int(p["expected_answer"].split("=")[1].strip())

            # Parse both forms: "ax + b = c" or "ax - b = c"
            m_add = re.match(r"^(\d+)x \+ (\d+) = (-?\d+)$", eq)
            m_sub = re.match(r"^(\d+)x - (\d+) = (-?\d+)$", eq)
            if m_add:
                a, b, c = int(m_add.group(1)), int(m_add.group(2)), int(m_add.group(3))
                assert a * answer + b == c
            elif m_sub:
                a, b, c = int(m_sub.group(1)), int(m_sub.group(2)), int(m_sub.group(3))
                assert a * answer - b == c
            else:
                pytest.fail(f"Unexpected format: {eq}")

    def test_metadata(self):
        p = generate_problem(0.8, TIERS)
        assert p["equation_type"] == "multi_step_linear"
        assert p["difficulty_tier"] == "tier_3"
