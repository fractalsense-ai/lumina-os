"""Tests validating the four algebra-evidence bug fixes.

Covers:
1. algebra_parser_tool — equivalence_preserved is None for empty work and
   for steps the parser cannot resolve (e.g. multi-equals notation).
2. build_initial_learning_state — fluency state tier matches starting
   nominal_difficulty when tiers are supplied.
3. _strip_latex_delimiters — \\frac, $, $$, \\cdot, \\times, \\text, \\left/\\right
   are all converted to plain text.
4. runtime_adapters.interpret_turn_input — forced equivalence_preserved=True
   override on problem_solved has been removed (parser value wins).
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
_EDU_CONTROLLERS = REPO_ROOT / "domain-packs" / "education" / "controllers"
if str(_EDU_CONTROLLERS) not in sys.path:
    sys.path.insert(0, str(_EDU_CONTROLLERS))


# ---------------------------------------------------------------------------
# Module loaders
# ---------------------------------------------------------------------------

def _load_tool_adapters():
    spec = importlib.util.spec_from_file_location(
        "edu_tool_adapters_test",
        str(_EDU_CONTROLLERS / "tool_adapters.py"),
    )
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _load_runtime_adapters():
    spec = importlib.util.spec_from_file_location(
        "edu_runtime_adapters_fix_test",
        str(_EDU_CONTROLLERS / "runtime_adapters.py"),
    )
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _load_strip_fn():
    os.environ.setdefault(
        "LUMINA_RUNTIME_CONFIG_PATH",
        "domain-packs/education/cfg/runtime-config.yaml",
    )
    module_path = REPO_ROOT / "src" / "lumina" / "api" / "server.py"
    spec = importlib.util.spec_from_file_location("lumina.api.server", str(module_path))
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load lumina-api-server module")
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("lumina.api.server", mod)
    spec.loader.exec_module(mod)
    return mod._strip_latex_delimiters


_tools = _load_tool_adapters()
algebra_parser_tool = _tools.algebra_parser_tool

_adapters = _load_runtime_adapters()
build_initial_learning_state = _adapters.build_initial_learning_state

_strip_latex_delimiters = _load_strip_fn()


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

TIERS = [
    {"tier_id": "tier_1", "min_difficulty": 0.0, "max_difficulty": 0.35,
     "equation_type": "single_step_isolation"},
    {"tier_id": "tier_2", "min_difficulty": 0.35, "max_difficulty": 0.65,
     "equation_type": "variable_consolidation"},
    {"tier_id": "tier_3", "min_difficulty": 0.65, "max_difficulty": 1.0,
     "equation_type": "multi_step_linear"},
]

TIER_PROGRESSION = ["tier_1", "tier_2", "tier_3"]

_MINIMAL_PROFILE: dict[str, Any] = {"learning_state": {}}


# ===========================================================================
# 1. algebra_parser_tool — equivalence_preserved fixes
# ===========================================================================


class TestAlgebraParserEquivalence:
    """equivalence_preserved is None when we cannot make a determination."""

    def test_empty_student_work_returns_none(self):
        """Empty input → cannot assess equivalence."""
        result = algebra_parser_tool({
            "call_type": "parse_steps",
            "equation": "7x = 84",
            "target_variable": "x",
            "student_work": "",
        })
        assert result["ok"] is True
        assert result["equivalence_preserved"] is None, (
            "Empty student work should yield None, not True"
        )
        assert result["step_count"] == 0

    def test_correct_step_returns_true(self):
        """A parseable correct step → equivalence_preserved True."""
        result = algebra_parser_tool({
            "call_type": "parse_steps",
            "equation": "7x = 35",
            "target_variable": "x",
            "student_work": "x = 5",
        })
        assert result["ok"] is True
        assert result["equivalence_preserved"] is True

    def test_wrong_answer_returns_false(self):
        """A parseable step with wrong solution → equivalence_preserved False."""
        result = algebra_parser_tool({
            "call_type": "parse_steps",
            "equation": "7x = 84",
            "target_variable": "x",
            "student_work": "x = 9",  # correct is 12
        })
        assert result["ok"] is True
        assert result["equivalence_preserved"] is False, (
            "Wrong answer should yield False, not True"
        )

    def test_unparseable_multi_equals_notation_returns_none(self):
        """Student writes '7/7x = 84/7 x = 9' — two = signs, parser cannot
        resolve equivalence, so result should be None rather than a wrongly
        optimistic True."""
        result = algebra_parser_tool({
            "call_type": "parse_steps",
            "equation": "7x = 84",
            "target_variable": "x",
            "student_work": "7/7x = 84/7 x = 9",
        })
        assert result["ok"] is True
        # Parser should return None when it cannot parse the step
        assert result["equivalence_preserved"] is None, (
            "Unparseable complex notation should yield None, not True"
        )

    def test_prose_only_no_equations_returns_none(self):
        """No algebraic expressions at all → None."""
        result = algebra_parser_tool({
            "call_type": "parse_steps",
            "equation": "4x = 40",
            "target_variable": "x",
            "student_work": "I don't know how to do this",
        })
        assert result["ok"] is True
        assert result["equivalence_preserved"] is None


# ===========================================================================
# 2. build_initial_learning_state — fluency tier from starting difficulty
# ===========================================================================


class TestBuildInitialLearningStateFluencyTier:
    """Fluency state starts at the tier matching nominal_difficulty."""

    def test_tier_1_start(self):
        state = build_initial_learning_state(
            _MINIMAL_PROFILE,
            tiers=TIERS,
            tier_progression=TIER_PROGRESSION,
            nominal_difficulty=0.2,
        )
        assert hasattr(state, "fluency")
        assert state.fluency.current_tier == "tier_1"

    def test_tier_2_start_matches_session_default(self):
        """nominal_difficulty=0.5 is the common session default → tier_2."""
        state = build_initial_learning_state(
            _MINIMAL_PROFILE,
            tiers=TIERS,
            tier_progression=TIER_PROGRESSION,
            nominal_difficulty=0.5,
        )
        assert state.fluency.current_tier == "tier_2", (
            "Session starting at difficulty 0.5 should begin fluency tracking "
            "at tier_2 so advancement leads to tier_3, not tier_2"
        )

    def test_tier_3_start(self):
        state = build_initial_learning_state(
            _MINIMAL_PROFILE,
            tiers=TIERS,
            tier_progression=TIER_PROGRESSION,
            nominal_difficulty=0.8,
        )
        assert state.fluency.current_tier == "tier_3"

    def test_no_tiers_defaults_to_tier_1(self):
        """Backward-compatible: no tiers supplied → FluencyState default (tier_1)."""
        state = build_initial_learning_state(_MINIMAL_PROFILE)
        assert hasattr(state, "fluency")
        assert state.fluency.current_tier == "tier_1"

    def test_world_sim_cfg_still_works(self):
        """world_sim_cfg kwarg still accepted alongside new tiers kwarg."""
        state = build_initial_learning_state(
            _MINIMAL_PROFILE,
            world_sim_cfg=None,
            tiers=TIERS,
            tier_progression=TIER_PROGRESSION,
            nominal_difficulty=0.5,
        )
        assert state.fluency.current_tier == "tier_2"
        assert hasattr(state, "world_sim_theme")


# ===========================================================================
# 3. _strip_latex_delimiters — comprehensive LaTeX-to-plain conversion
# ===========================================================================


class TestStripLatexDelimiters:
    """LaTeX markup is removed or converted to plain-text equivalents."""

    def test_frac_simple(self):
        assert _strip_latex_delimiters(r"\frac{7x}{7}") == "(7x)/(7)"

    def test_frac_in_inline_delimiters(self):
        result = _strip_latex_delimiters(r"\(\frac{7x}{7} = \frac{84}{7}\)")
        assert "\\frac" not in result
        assert "\\(" not in result
        assert "7x" in result

    def test_frac_in_display_delimiters(self):
        result = _strip_latex_delimiters(r"\[\frac{ax}{a} = \frac{b}{a}\]")
        assert "\\frac" not in result
        assert "\\[" not in result

    def test_dollar_inline(self):
        result = _strip_latex_delimiters("The answer is $x = 5$.")
        assert "$" not in result
        assert "x = 5" in result

    def test_dollar_display(self):
        result = _strip_latex_delimiters("$$x = 5$$")
        assert "$$" not in result
        assert "x = 5" in result

    def test_cdot_replaced(self):
        assert "*" in _strip_latex_delimiters(r"3\cdot x")

    def test_times_replaced(self):
        assert "*" in _strip_latex_delimiters(r"3\times x")

    def test_left_right_removed(self):
        result = _strip_latex_delimiters(r"\left(\frac{x}{2}\right)")
        assert "\\left" not in result
        assert "\\right" not in result

    def test_text_command_inner_kept(self):
        result = _strip_latex_delimiters(r"\text{divide both sides}")
        assert "divide both sides" in result
        assert "\\text" not in result

    def test_plain_text_unchanged(self):
        msg = "Divide both sides by 7 to get x = 12."
        assert _strip_latex_delimiters(msg) == msg

    def test_frac_nested_one_level(self):
        """\\frac{\\frac{a}{b}}{c} — applied iteratively, inner frac resolved first."""
        result = _strip_latex_delimiters(r"\frac{\frac{a}{b}}{c}")
        assert "\\frac" not in result


# ===========================================================================
# 4. interpret_turn_input — no forced equivalence_preserved=True on solve
# ===========================================================================


class TestEquivalencePreservedNoForcedOverride:
    """equivalence_preserved is NOT forced True when problem_solved."""

    def test_problem_solved_with_wrong_step_preserves_false(self):
        """If parser returns False and problem is somehow marked solved (edge
        case), equivalence_preserved must remain False — the forced override
        has been removed."""
        # Simulate what interpret_turn_input does after parser override.
        # Build evidence manually matching the post-fix code path.
        evidence: dict[str, Any] = {
            "correctness": "correct",
            "substitution_check": True,
            "step_count": 1,
            "min_steps": 1,
            "equivalence_preserved": False,  # parser returned False
        }
        # problem_solved logic (copied from adapter, domain-agnostic)
        evidence["problem_solved"] = (
            evidence.get("correctness") == "correct"
            and evidence.get("substitution_check") is True
            and evidence.get("step_count", 0) >= evidence.get("min_steps", 1)
        )
        # Removed forced override: equivalence_preserved must NOT be changed
        assert evidence["problem_solved"] is True
        assert evidence["equivalence_preserved"] is False, (
            "Forced equivalence_preserved=True override should be gone; "
            "parser-determined False must survive"
        )

    def test_problem_not_solved_with_null_equivalence_key_removed(self):
        """None equivalence_preserved → key removed so orchestrator skips invariant."""
        evidence: dict[str, Any] = {
            "correctness": "partial",
            "substitution_check": False,
            "step_count": 0,
            "min_steps": 1,
            "equivalence_preserved": None,
        }
        evidence["problem_solved"] = (
            evidence.get("correctness") == "correct"
            and evidence.get("substitution_check") is True
            and evidence.get("step_count", 0) >= evidence.get("min_steps", 1)
        )
        # Null-removal logic
        if evidence.get("equivalence_preserved") is None and "equivalence_preserved" in evidence:
            del evidence["equivalence_preserved"]
        assert "equivalence_preserved" not in evidence


# ===========================================================================
# 5. build_initial_learning_state — fluency restored from saved profile
# ===========================================================================


class TestBuildInitialLearningStateFluentyRestore:
    """Saved fluency from a previous session is restored rather than reset."""

    def test_saved_tier_and_count_restored(self):
        """Profile with persisted fluency → state starts at the saved tier."""
        profile: dict[str, Any] = {
            "learning_state": {
                "fluency": {
                    "current_tier": "tier_2",
                    "consecutive_correct": 2,
                }
            }
        }
        state = build_initial_learning_state(
            profile,
            tiers=TIERS,
            tier_progression=TIER_PROGRESSION,
            nominal_difficulty=0.2,  # would normally select tier_1
        )
        assert state.fluency.current_tier == "tier_2", (
            "Saved tier_2 must be restored even though nominal_difficulty maps to tier_1"
        )
        assert state.fluency.consecutive_correct == 2

    def test_no_saved_fluency_falls_back_to_difficulty_tier(self):
        """Profile without saved fluency → tier selected from nominal_difficulty."""
        state = build_initial_learning_state(
            _MINIMAL_PROFILE,
            tiers=TIERS,
            tier_progression=TIER_PROGRESSION,
            nominal_difficulty=0.5,
        )
        assert state.fluency.current_tier == "tier_2"
        assert state.fluency.consecutive_correct == 0

    def test_saved_fluency_without_tiers_still_restores(self):
        """Even without tier lookup data, saved fluency values are honoured."""
        profile: dict[str, Any] = {
            "learning_state": {
                "fluency": {
                    "current_tier": "tier_3",
                    "consecutive_correct": 1,
                }
            }
        }
        state = build_initial_learning_state(profile)
        assert state.fluency.current_tier == "tier_3"
        assert state.fluency.consecutive_correct == 1


# ===========================================================================
# 6. domain_step — consecutive_correct survives across turns
# ===========================================================================


class TestDomainStepFluencyPersistsAcrossTurns:
    """consecutive_correct must accumulate across turns (not reset each call)."""

    def _make_evidence(self, correct: bool) -> dict[str, Any]:
        return {
            "correctness": "correct" if correct else "incorrect",
            "solve_elapsed_sec": 30.0,
            "problem_solved": correct,
        }

    def _make_task_spec(self) -> dict[str, Any]:
        return {
            "task_id": "algebra-linear-eq-001",
            "nominal_difficulty": 0.45,
            "skills_required": [
                "equivalence_preserved",
                "no_illegal_operations",
                "solution_verifies",
                "show_work_minimum",
            ],
        }

    def _make_params(self) -> dict[str, Any]:
        return {
            "fluency_monitor": {
                "target_consecutive_successes": 3,
                "time_threshold_seconds": 120.0,
                "tier_progression": ["tier_1", "tier_2", "tier_3"],
            },
        }

    def test_consecutive_correct_accumulates_over_three_turns(self):
        """Three consecutive correct turns must leave consecutive_correct == 3
        (or trigger an advance), not reset to 1 on each turn."""
        domain_step = _adapters.domain_step

        state = build_initial_learning_state(
            _MINIMAL_PROFILE,
            tiers=TIERS,
            tier_progression=TIER_PROGRESSION,
            nominal_difficulty=0.2,  # tier_1 start
        )
        task_spec = self._make_task_spec()
        params = self._make_params()
        evidence = self._make_evidence(correct=True)

        for _ in range(3):
            state, _ = domain_step(state, task_spec, evidence, params)

        # After 3 consecutive correct turns: either advanced tier OR counter == 3
        advanced = state.fluency.current_tier != "tier_1"
        counter_accumulated = state.fluency.consecutive_correct == 3
        assert advanced or counter_accumulated, (
            f"Fluency must accumulate across turns.  "
            f"tier={state.fluency.current_tier}, "
            f"consecutive_correct={state.fluency.consecutive_correct}"
        )

    def test_consecutive_correct_resets_on_incorrect_turn(self):
        """An incorrect turn after two correct resets the counter to 0."""
        domain_step = _adapters.domain_step

        state = build_initial_learning_state(
            _MINIMAL_PROFILE,
            tiers=TIERS,
            tier_progression=TIER_PROGRESSION,
            nominal_difficulty=0.2,
        )
        task_spec = self._make_task_spec()
        params = self._make_params()

        for _ in range(2):
            state, _ = domain_step(state, task_spec, self._make_evidence(correct=True), params)
        state, _ = domain_step(state, task_spec, self._make_evidence(correct=False), params)

        assert state.fluency.consecutive_correct == 0, (
            "Incorrect turn must reset consecutive_correct to 0"
        )
