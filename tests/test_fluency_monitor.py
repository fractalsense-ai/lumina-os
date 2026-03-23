"""Tests for the fluency monitor — consecutive-success gate with time threshold."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure the education domain-pack reference-implementations are importable.
_EDU_REF = Path(__file__).resolve().parent.parent / "domain-packs" / "education" / "controllers"
if str(_EDU_REF) not in sys.path:
    sys.path.insert(0, str(_EDU_REF))

from fluency_monitor import (  # noqa: E402
    FluencyState,
    build_initial_fluency_state,
    fluency_monitor_step,
)

TIERS = [
    {"tier_id": "tier_1", "min_difficulty": 0.0, "max_difficulty": 0.35},
    {"tier_id": "tier_2", "min_difficulty": 0.35, "max_difficulty": 0.65},
    {"tier_id": "tier_3", "min_difficulty": 0.65, "max_difficulty": 1.0},
]

PARAMS = {
    "target_consecutive_successes": 3,
    "time_threshold_seconds": 45.0,
    "tier_progression": ["tier_1", "tier_2", "tier_3"],
}

TASK_SPEC = {"task_id": "test", "nominal_difficulty": 0.5}


def _correct_fast(elapsed: float = 10.0) -> dict:
    return {"correctness": "correct", "solve_elapsed_sec": elapsed}


def _correct_slow(elapsed: float = 60.0) -> dict:
    return {"correctness": "correct", "solve_elapsed_sec": elapsed}


def _incorrect() -> dict:
    return {"correctness": "incorrect", "solve_elapsed_sec": 15.0}


class TestConsecutiveSuccessGate:
    """3 fast correct solves → advance_tier."""

    def test_three_fast_correct_advances(self):
        state = FluencyState(current_tier="tier_1")
        for i in range(2):
            state, decision = fluency_monitor_step(state, TASK_SPEC, _correct_fast(), PARAMS)
            assert not decision["advanced"]
            assert decision["action"] is None
            assert state.consecutive_correct == i + 1

        # Third correct → advance
        state, decision = fluency_monitor_step(state, TASK_SPEC, _correct_fast(), PARAMS)
        assert decision["advanced"] is True
        assert decision["action"] == "advance_tier"
        assert decision["next_tier"] == "tier_2"
        assert state.current_tier == "tier_2"
        assert state.consecutive_correct == 0  # reset after advance

    def test_incorrect_resets_counter(self):
        state = FluencyState(current_tier="tier_1", consecutive_correct=2)
        state, decision = fluency_monitor_step(state, TASK_SPEC, _incorrect(), PARAMS)
        assert state.consecutive_correct == 0
        assert decision["action"] is None
        assert not decision["advanced"]

    def test_partial_resets_counter(self):
        state = FluencyState(current_tier="tier_1", consecutive_correct=2)
        evidence = {"correctness": "partial", "solve_elapsed_sec": 10.0}
        state, decision = fluency_monitor_step(state, TASK_SPEC, evidence, PARAMS)
        assert state.consecutive_correct == 0


class TestTimeThreshold:
    """Correct but slow → fluency_bottleneck, no advancement."""

    def test_slow_correct_triggers_targeted_hint(self):
        state = FluencyState(current_tier="tier_1", consecutive_correct=1)
        state, decision = fluency_monitor_step(state, TASK_SPEC, _correct_slow(), PARAMS)
        assert decision["fluency_bottleneck"] is True
        assert decision["action"] == "trigger_targeted_hint"
        assert state.consecutive_correct == 0  # reset on slow

    def test_exactly_at_threshold_counts(self):
        state = FluencyState(current_tier="tier_1")
        evidence = {"correctness": "correct", "solve_elapsed_sec": 45.0}
        state, decision = fluency_monitor_step(state, TASK_SPEC, evidence, PARAMS)
        # Exactly at threshold → still counts as fast
        assert state.consecutive_correct == 1
        assert decision["action"] is None


class TestTierProgression:
    """Tier advancement follows progression order."""

    def test_advance_through_all_tiers(self):
        state = FluencyState(current_tier="tier_1")
        # Advance tier_1 → tier_2
        for _ in range(3):
            state, _ = fluency_monitor_step(state, TASK_SPEC, _correct_fast(), PARAMS)
        assert state.current_tier == "tier_2"

        # Advance tier_2 → tier_3
        for _ in range(3):
            state, _ = fluency_monitor_step(state, TASK_SPEC, _correct_fast(), PARAMS)
        assert state.current_tier == "tier_3"

    def test_no_advance_past_last_tier(self):
        state = FluencyState(current_tier="tier_3")
        for _ in range(3):
            state, decision = fluency_monitor_step(state, TASK_SPEC, _correct_fast(), PARAMS)
        # Should stay at tier_3, no advance
        assert state.current_tier == "tier_3"
        assert decision["advanced"] is False
        assert decision["next_tier"] is None


class TestBuildInitialFluencyState:
    """Initial fluency state from nominal difficulty."""

    def test_entry_difficulty(self):
        fs = build_initial_fluency_state(0.2, TIERS, ["tier_1", "tier_2", "tier_3"])
        assert fs.current_tier == "tier_1"
        assert fs.consecutive_correct == 0

    def test_intermediate_difficulty(self):
        fs = build_initial_fluency_state(0.45, TIERS, ["tier_1", "tier_2", "tier_3"])
        assert fs.current_tier == "tier_2"

    def test_advanced_difficulty(self):
        fs = build_initial_fluency_state(0.8, TIERS, ["tier_1", "tier_2", "tier_3"])
        assert fs.current_tier == "tier_3"

    def test_edge_1_0(self):
        fs = build_initial_fluency_state(1.0, TIERS, ["tier_1", "tier_2", "tier_3"])
        assert fs.current_tier == "tier_3"


class TestMixedSequences:
    """Realistic scenarios mixing correct, incorrect, fast and slow."""

    def test_two_fast_one_slow_resets(self):
        """Two fast correct then one slow: counter resets, no advance."""
        state = FluencyState(current_tier="tier_1")
        state, _ = fluency_monitor_step(state, TASK_SPEC, _correct_fast(), PARAMS)
        state, _ = fluency_monitor_step(state, TASK_SPEC, _correct_fast(), PARAMS)
        assert state.consecutive_correct == 2

        state, decision = fluency_monitor_step(state, TASK_SPEC, _correct_slow(), PARAMS)
        assert state.consecutive_correct == 0
        assert decision["fluency_bottleneck"] is True
        assert not decision["advanced"]

    def test_two_fast_one_incorrect_then_three_fast(self):
        """Reset after incorrect, then 3 fresh fast correct → advance."""
        state = FluencyState(current_tier="tier_1")
        state, _ = fluency_monitor_step(state, TASK_SPEC, _correct_fast(), PARAMS)
        state, _ = fluency_monitor_step(state, TASK_SPEC, _correct_fast(), PARAMS)
        state, _ = fluency_monitor_step(state, TASK_SPEC, _incorrect(), PARAMS)
        assert state.consecutive_correct == 0

        for _ in range(3):
            state, decision = fluency_monitor_step(state, TASK_SPEC, _correct_fast(), PARAMS)
        assert decision["advanced"] is True
        assert state.current_tier == "tier_2"
