"""Tests for the 6 new deterministic diagnostic call_types added to algebra_parser_tool.

Covers:
  - check_step_order         → reversibility_order_correct   (Law 2A)
  - check_inequality_direction → inequality_direction_correct (Law 2B)
  - check_system_verification  → substitution_valid           (Law 3)
  - check_slope_computation    → relationship_correctly_mapped (Law 5)
  - check_polynomial_structure → structure_preserved          (Law 4)
  - check_model_transcription  → model_accurately_transcribed (Law 6)
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
_EDU_CONTROLLERS = REPO_ROOT / "domain-packs" / "education" / "controllers"
if str(_EDU_CONTROLLERS) not in sys.path:
    sys.path.insert(0, str(_EDU_CONTROLLERS))


def _load_tool_adapters():
    spec = importlib.util.spec_from_file_location(
        "edu_tool_adapters_new_checks_test",
        str(_EDU_CONTROLLERS / "tool_adapters.py"),
    )
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


_tools = _load_tool_adapters()
algebra_parser_tool = _tools.algebra_parser_tool


# ---------------------------------------------------------------------------
# TestCheckStepOrder — Law 2A
# ---------------------------------------------------------------------------

class TestCheckStepOrder:
    """reversibility_order_correct: constant must be removed before coefficient divided."""

    def test_correct_order_returns_true(self):
        # 3x - 7 = 14 → student shows 3x = 21 first (constant gone), then x = 7
        result = algebra_parser_tool({
            "call_type": "check_step_order",
            "equation": "3x - 7 = 14",
            "target_variable": "x",
            "student_work": "3x - 7 = 14\n3x = 21\nx = 7",
        })
        assert result["ok"] is True
        assert result["reversibility_order_correct"] is True

    def test_wrong_order_returns_false(self):
        # 3x - 7 = 14 → student divides coefficient first: x - 7/3 = 14/3
        result = algebra_parser_tool({
            "call_type": "check_step_order",
            "equation": "3x - 7 = 14",
            "target_variable": "x",
            "student_work": "3x - 7 = 14\nx - 7 = 14",
        })
        assert result["ok"] is True
        # coefficient divided first (a≈1) before constant removed → False
        # Note: "x - 7 = 14" has a=1, which means student divided coefficient first
        assert result["reversibility_order_correct"] is False

    def test_single_step_equation_returns_none(self):
        # 3x = 21 has no constant term — ordering not applicable
        result = algebra_parser_tool({
            "call_type": "check_step_order",
            "equation": "3x = 21",
            "target_variable": "x",
            "student_work": "3x = 21\nx = 7",
        })
        assert result["ok"] is True
        assert result["reversibility_order_correct"] is None

    def test_unparseable_equation_returns_none(self):
        result = algebra_parser_tool({
            "call_type": "check_step_order",
            "equation": "not an equation",
            "target_variable": "x",
            "student_work": "some work",
        })
        assert result["ok"] is True
        assert result["reversibility_order_correct"] is None


# ---------------------------------------------------------------------------
# TestCheckInequalityDirection — Law 2B
# ---------------------------------------------------------------------------

class TestCheckInequalityDirection:
    """inequality_direction_correct: symbol must flip when dividing by a negative."""

    def test_correct_flip_returns_true(self):
        # -2x < 8  →  x > -4  (symbol flipped because dividing by -2)
        result = algebra_parser_tool({
            "call_type": "check_inequality_direction",
            "inequality": "-2x < 8",
            "target_variable": "x",
            "student_work": "-2x < 8\nx > -4",
        })
        assert result["ok"] is True
        assert result["inequality_direction_correct"] is True

    def test_missing_flip_returns_false(self):
        # -2x < 8  →  x < -4  (symbol NOT flipped — incorrect)
        result = algebra_parser_tool({
            "call_type": "check_inequality_direction",
            "inequality": "-2x < 8",
            "target_variable": "x",
            "student_work": "-2x < 8\nx < -4",
        })
        assert result["ok"] is True
        assert result["inequality_direction_correct"] is False

    def test_positive_divisor_no_flip_returns_true(self):
        # 2x < 8 → divide by +2, symbol stays <; student shows x < 4 → correct
        result = algebra_parser_tool({
            "call_type": "check_inequality_direction",
            "inequality": "2x < 8",
            "target_variable": "x",
            "student_work": "2x < 8\nx < 4",
        })
        assert result["ok"] is True
        # Positive divisor detected, symbol correctly unchanged → True
        assert result["inequality_direction_correct"] is True

    def test_no_inequality_lines_returns_none(self):
        result = algebra_parser_tool({
            "call_type": "check_inequality_direction",
            "inequality": "2x = 8",
            "target_variable": "x",
            "student_work": "prose answer with no inequality symbols",
        })
        assert result["ok"] is True
        assert result["inequality_direction_correct"] is None


# ---------------------------------------------------------------------------
# TestCheckSystemVerification — Law 3
# ---------------------------------------------------------------------------

class TestCheckSystemVerification:
    """substitution_valid: (x,y) must satisfy ALL equations in the system."""

    def test_valid_solution_returns_true(self):
        # x + y = 5, x - y = 1 → solution (3, 2): 3+2=5 ✓, 3-2=1 ✓
        result = algebra_parser_tool({
            "call_type": "check_system_verification",
            "system_equations": ["x + y = 5", "x - y = 1"],
            "x_variable": "x",
            "y_variable": "y",
            "x_val": 3,
            "y_val": 2,
        })
        assert result["ok"] is True
        assert result["substitution_valid"] is True

    def test_invalid_solution_returns_false(self):
        # x + y = 5, x - y = 1 → (1, 3): 1+3=4 ≠ 5 ✗
        result = algebra_parser_tool({
            "call_type": "check_system_verification",
            "system_equations": ["x + y = 5", "x - y = 1"],
            "x_variable": "x",
            "y_variable": "y",
            "x_val": 1,
            "y_val": 3,
        })
        assert result["ok"] is True
        assert result["substitution_valid"] is False

    def test_solution_satisfies_first_but_not_second_returns_false(self):
        # x + y = 5, 2*x + y = 8 → (3, 2): 3+2=5 ✓, 2*3+2=8 ✓ actually correct
        # Use (2, 3): 2+3=5 ✓, 2*2+3=7 ≠ 8 ✗
        result = algebra_parser_tool({
            "call_type": "check_system_verification",
            "system_equations": ["x + y = 5", "2*x + y = 8"],
            "x_variable": "x",
            "y_variable": "y",
            "x_val": 2,
            "y_val": 3,
        })
        assert result["ok"] is True
        assert result["substitution_valid"] is False

    def test_missing_x_val_returns_error(self):
        result = algebra_parser_tool({
            "call_type": "check_system_verification",
            "system_equations": ["x + y = 5"],
            "x_variable": "x",
            "y_variable": "y",
        })
        assert result["ok"] is False

    def test_empty_equations_returns_none(self):
        result = algebra_parser_tool({
            "call_type": "check_system_verification",
            "system_equations": [],
            "x_variable": "x",
            "y_variable": "y",
            "x_val": 1,
            "y_val": 1,
        })
        assert result["ok"] is True
        assert result["substitution_valid"] is None


# ---------------------------------------------------------------------------
# TestCheckSlopeComputation — Law 5
# ---------------------------------------------------------------------------

class TestCheckSlopeComputation:
    """relationship_correctly_mapped: extracted slope must match correct_slope."""

    def test_correct_integer_slope_returns_true(self):
        result = algebra_parser_tool({
            "call_type": "check_slope_computation",
            "student_work": "The slope is 2, so the equation is y = 2x + 1",
            "correct_slope": 2,
        })
        assert result["ok"] is True
        assert result["relationship_correctly_mapped"] is True

    def test_correct_fraction_slope_returns_true(self):
        result = algebra_parser_tool({
            "call_type": "check_slope_computation",
            "student_work": "slope = 2/3",
            "correct_slope": 2 / 3,
        })
        assert result["ok"] is True
        assert result["relationship_correctly_mapped"] is True

    def test_wrong_slope_returns_false(self):
        # Student writes 3/2 but correct is 2/3
        result = algebra_parser_tool({
            "call_type": "check_slope_computation",
            "student_work": "slope = 3/2",
            "correct_slope": 2 / 3,
        })
        assert result["ok"] is True
        assert result["relationship_correctly_mapped"] is False

    def test_no_slope_in_prose_returns_none(self):
        result = algebra_parser_tool({
            "call_type": "check_slope_computation",
            "student_work": "I think the answer is positive and goes upward",
            "correct_slope": 2,
        })
        assert result["ok"] is True
        assert result["relationship_correctly_mapped"] is None
        assert result["extracted_slope"] is None

    def test_slope_from_table_data(self):
        # table: (0,1), (2,5) → slope = (5-1)/(2-0) = 2
        result = algebra_parser_tool({
            "call_type": "check_slope_computation",
            "student_work": "slope = 2",
            "table_data": [{"x": 0, "y": 1}, {"x": 2, "y": 5}],
        })
        assert result["ok"] is True
        assert result["relationship_correctly_mapped"] is True


# ---------------------------------------------------------------------------
# TestCheckPolynomialStructure — Law 4
# ---------------------------------------------------------------------------

class TestCheckPolynomialStructure:
    """structure_preserved: student expression must expand to the same polynomial."""

    def test_factored_form_correct_returns_true(self):
        # 3*(x+4) expanded is 3x+12 — same polynomial
        result = algebra_parser_tool({
            "call_type": "check_polynomial_structure",
            "original_expression": "3*(x+4)",
            "student_expression": "3*x + 12",
            "target_variable": "x",
        })
        assert result["ok"] is True
        assert result["structure_preserved"] is True

    def test_foil_correct_returns_true(self):
        # (x+2)*(x+3) = x^2 + 5*x + 6
        result = algebra_parser_tool({
            "call_type": "check_polynomial_structure",
            "original_expression": "(x+2)*(x+3)",
            "student_expression": "x**2 + 5*x + 6",
            "target_variable": "x",
        })
        assert result["ok"] is True
        assert result["structure_preserved"] is True

    def test_wrong_expansion_returns_false(self):
        # 3*(x+4) ≠ 3*x + 4 (student forgot to distribute the 4)
        result = algebra_parser_tool({
            "call_type": "check_polynomial_structure",
            "original_expression": "3*(x+4)",
            "student_expression": "3*x + 4",
            "target_variable": "x",
        })
        assert result["ok"] is True
        assert result["structure_preserved"] is False

    def test_foil_wrong_constant_returns_false(self):
        # (x+2)*(x+3) ≠ x^2 + 5x + 5
        result = algebra_parser_tool({
            "call_type": "check_polynomial_structure",
            "original_expression": "(x+2)*(x+3)",
            "student_expression": "x**2 + 5*x + 5",
            "target_variable": "x",
        })
        assert result["ok"] is True
        assert result["structure_preserved"] is False

    def test_missing_expressions_returns_error(self):
        result = algebra_parser_tool({
            "call_type": "check_polynomial_structure",
            "original_expression": "",
            "student_expression": "",
        })
        assert result["ok"] is False

    def test_unparseable_expression_returns_none(self):
        result = algebra_parser_tool({
            "call_type": "check_polynomial_structure",
            "original_expression": "3*(x+4)",
            "student_expression": "not valid !!@#$% math",
        })
        assert result["ok"] is True
        assert result["structure_preserved"] is None


# ---------------------------------------------------------------------------
# TestCheckModelTranscription — Law 6
# ---------------------------------------------------------------------------

class TestCheckModelTranscription:
    """model_accurately_transcribed: student equation must match canonical from model_params."""

    def test_area_product_correct_returns_true(self):
        # params: w * (w+3) - 40 = 0  → student writes w*(w+3) - 40 = 0
        result = algebra_parser_tool({
            "call_type": "check_model_transcription",
            "model_params": {
                "type": "area_product",
                "factor1": "w",
                "factor2": "w+3",
                "result": 40,
            },
            "student_equation": "w*(w+3) - 40 = 0",
            "target_variable": "w",
        })
        assert result["ok"] is True
        assert result["model_accurately_transcribed"] is True

    def test_area_product_expanded_equivalent_returns_true(self):
        # w^2 + 3w - 40 = 0 is algebraically identical
        result = algebra_parser_tool({
            "call_type": "check_model_transcription",
            "model_params": {
                "type": "area_product",
                "factor1": "w",
                "factor2": "w+3",
                "result": 40,
            },
            "student_equation": "w**2 + 3*w - 40 = 0",
            "target_variable": "w",
        })
        assert result["ok"] is True
        assert result["model_accurately_transcribed"] is True

    def test_area_product_wrong_sign_returns_false(self):
        # w*(w-3) - 40 = 0 uses subtraction instead of addition
        result = algebra_parser_tool({
            "call_type": "check_model_transcription",
            "model_params": {
                "type": "area_product",
                "factor1": "w",
                "factor2": "w+3",
                "result": 40,
            },
            "student_equation": "w*(w-3) - 40 = 0",
            "target_variable": "w",
        })
        assert result["ok"] is True
        assert result["model_accurately_transcribed"] is False

    def test_rate_time_distance_correct_returns_true(self):
        # 60 * t - 300 = 0  (rate=60, time=t, distance=300)
        result = algebra_parser_tool({
            "call_type": "check_model_transcription",
            "model_params": {
                "type": "rate_time_distance",
                "rate": 60,
                "time": "t",
                "distance": 300,
            },
            "student_equation": "60*t - 300 = 0",
            "target_variable": "t",
        })
        assert result["ok"] is True
        assert result["model_accurately_transcribed"] is True

    def test_no_model_params_returns_none(self):
        result = algebra_parser_tool({
            "call_type": "check_model_transcription",
            "model_params": None,
            "student_equation": "x = 5",
        })
        assert result["ok"] is True
        assert result["model_accurately_transcribed"] is None

    def test_unknown_model_type_returns_none(self):
        result = algebra_parser_tool({
            "call_type": "check_model_transcription",
            "model_params": {
                "type": "unsupported_type",
                "a": 1,
            },
            "student_equation": "x = 5",
        })
        assert result["ok"] is True
        assert result["model_accurately_transcribed"] is None

    def test_no_equals_sign_in_student_equation_returns_none(self):
        result = algebra_parser_tool({
            "call_type": "check_model_transcription",
            "model_params": {
                "type": "area_product",
                "factor1": "w",
                "factor2": "w+3",
                "result": 40,
            },
            "student_equation": "w times w plus 3 minus 40",
        })
        assert result["ok"] is True
        assert result["model_accurately_transcribed"] is None
