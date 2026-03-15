"""Tests for PPAOrchestrator check expression evaluation functions.

Covers _parse_check_literal (int, float paths) and _evaluate_check_expr
(!=, >=, <=, >, <, unknown operator, field-ref RHS, malformed expressions).
"""
from __future__ import annotations

import pytest
from lumina.orchestrator.ppa_orchestrator import _evaluate_check_expr, _parse_check_literal


# ── _parse_check_literal ──────────────────────────────────────────────────────

@pytest.mark.unit
def test_parse_check_literal_empty_list():
    assert _parse_check_literal("[]") == []


@pytest.mark.unit
def test_parse_check_literal_true():
    assert _parse_check_literal("true") is True
    assert _parse_check_literal("True") is True


@pytest.mark.unit
def test_parse_check_literal_false():
    assert _parse_check_literal("false") is False


@pytest.mark.unit
def test_parse_check_literal_int():
    assert _parse_check_literal("42") == 42
    assert isinstance(_parse_check_literal("42"), int)


@pytest.mark.unit
def test_parse_check_literal_float():
    result = _parse_check_literal("3.14")
    assert abs(result - 3.14) < 1e-9
    assert isinstance(result, float)


@pytest.mark.unit
def test_parse_check_literal_string_fallback():
    assert _parse_check_literal("some_field") == "some_field"


# ── _evaluate_check_expr ──────────────────────────────────────────────────────

@pytest.mark.unit
def test_evaluate_check_expr_truthy_present():
    assert _evaluate_check_expr("equivalence_preserved", {"equivalence_preserved": True}) is True


@pytest.mark.unit
def test_evaluate_check_expr_truthy_absent_returns_none():
    assert _evaluate_check_expr("some_field", {}) is None


@pytest.mark.unit
def test_evaluate_check_expr_equality_match():
    assert _evaluate_check_expr("x == []", {"x": []}) is True


@pytest.mark.unit
def test_evaluate_check_expr_equality_no_match():
    assert _evaluate_check_expr("x == []", {"x": [1]}) is False


@pytest.mark.unit
def test_evaluate_check_expr_inequality():
    assert _evaluate_check_expr("x != []", {"x": []}) is False
    assert _evaluate_check_expr("x != []", {"x": [1]}) is True


@pytest.mark.unit
def test_evaluate_check_expr_gte():
    assert _evaluate_check_expr("step_count >= 3", {"step_count": 5}) is True
    assert _evaluate_check_expr("step_count >= 3", {"step_count": 2}) is False


@pytest.mark.unit
def test_evaluate_check_expr_lte():
    assert _evaluate_check_expr("errors <= 0", {"errors": 0}) is True
    assert _evaluate_check_expr("errors <= 0", {"errors": 1}) is False


@pytest.mark.unit
def test_evaluate_check_expr_gt():
    assert _evaluate_check_expr("x > 10", {"x": 11}) is True
    assert _evaluate_check_expr("x > 10", {"x": 10}) is False


@pytest.mark.unit
def test_evaluate_check_expr_lt():
    assert _evaluate_check_expr("x < 5", {"x": 4}) is True
    assert _evaluate_check_expr("x < 5", {"x": 5}) is False


@pytest.mark.unit
def test_evaluate_check_expr_field_ref_rhs():
    """When RHS is a string that is a key in evidence, resolve it as a field ref."""
    assert _evaluate_check_expr("step_count >= min_steps", {"step_count": 5, "min_steps": 3}) is True


@pytest.mark.unit
def test_evaluate_check_expr_field_ref_rhs_missing_returns_none():
    """RHS field reference that is absent from evidence returns None."""
    assert _evaluate_check_expr("step_count >= min_steps", {"step_count": 5}) is None


@pytest.mark.unit
def test_evaluate_check_expr_field_absent_in_binary():
    """LHS field absent → returns None."""
    assert _evaluate_check_expr("step_count >= 3", {}) is None


@pytest.mark.unit
def test_evaluate_check_expr_unknown_operator_returns_none():
    """Unknown operator → returns None."""
    assert _evaluate_check_expr("x ** 2", {"x": 4}) is None


@pytest.mark.unit
def test_evaluate_check_expr_malformed_returns_none():
    """Expression with two tokens (not 1 or 3) → returns None."""
    assert _evaluate_check_expr("field_a field_b", {"field_a": 1, "field_b": 2}) is None
