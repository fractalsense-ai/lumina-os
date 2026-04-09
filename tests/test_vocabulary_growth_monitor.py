"""Tests for vocabulary_growth_monitor_v0_1 — baseline, delta, domain terms."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

# Load the module via importlib (same pattern as test_zpd_monitor.py)
_LIB = Path(__file__).resolve().parent.parent / "domain-packs" / "education" / "domain-lib" / "vocabulary_growth_monitor_v0_1.py"
_spec = importlib.util.spec_from_file_location("vocabulary_growth_monitor_v0_1", str(_LIB))
_mod = importlib.util.module_from_spec(_spec)
sys.modules["vocabulary_growth_monitor_v0_1"] = _mod
_spec.loader.exec_module(_mod)

vocabulary_growth_step = _mod.vocabulary_growth_step
_build_default_vocab_state = _mod._build_default_vocab_state
DEFAULT_PARAMS = _mod.DEFAULT_PARAMS


# ── Helpers ──────────────────────────────────────────────────

def _fresh_state(**overrides):
    s = _build_default_vocab_state()
    s.update(overrides)
    return s


def _evidence(score=0.5, turns=20, valid=True, terms=None):
    return {
        "vocabulary_complexity_score": score,
        "buffer_turns": turns,
        "measurement_valid": valid,
        "domain_terms_detected": terms or [],
    }


# ── Baseline management ─────────────────────────────────────

class TestBaseline:
    def test_first_sample_sets_provisional_baseline(self):
        state = _fresh_state()
        state, decision = vocabulary_growth_step(state, _evidence(score=0.40))
        assert state["baseline_complexity"] == pytest.approx(0.40)
        assert state["baseline_sessions_remaining"] == 2
        assert len(state["baseline_samples"]) == 1

    def test_baseline_locks_after_n_sessions(self):
        state = _fresh_state()
        for score in [0.40, 0.42, 0.44]:
            state, _ = vocabulary_growth_step(state, _evidence(score=score))
        # After 3 samples, baseline is locked (average)
        assert state["baseline_sessions_remaining"] == 0
        assert state["baseline_complexity"] == pytest.approx(0.42, abs=0.001)

    def test_baseline_does_not_change_after_lock(self):
        state = _fresh_state()
        for score in [0.40, 0.42, 0.44]:
            state, _ = vocabulary_growth_step(state, _evidence(score=score))
        locked_baseline = state["baseline_complexity"]
        # Further measurements should not change baseline
        state, _ = vocabulary_growth_step(state, _evidence(score=0.80))
        assert state["baseline_complexity"] == pytest.approx(locked_baseline)


# ── Growth delta computation ─────────────────────────────────

class TestGrowthDelta:
    def test_growth_above_baseline(self):
        state = _fresh_state(baseline_complexity=0.40, baseline_sessions_remaining=0)
        state, decision = vocabulary_growth_step(state, _evidence(score=0.55))
        assert decision["vocab_growth_delta"] == pytest.approx(0.15)
        assert decision["measurement_valid"] is True

    def test_no_negative_delta(self):
        state = _fresh_state(baseline_complexity=0.50, baseline_sessions_remaining=0)
        state, decision = vocabulary_growth_step(state, _evidence(score=0.35))
        assert decision["vocab_growth_delta"] == 0.0
        assert state["growth_delta"] == 0.0

    def test_reward_weight_proportional_to_delta(self):
        state = _fresh_state(baseline_complexity=0.40, baseline_sessions_remaining=0)
        state, decision = vocabulary_growth_step(state, _evidence(score=0.60))
        assert decision["reward_weight_contribution"] == pytest.approx(0.20 * 0.5)


# ── Minimum turns guard ─────────────────────────────────────

class TestMinTurns:
    def test_below_min_turns_returns_invalid(self):
        state = _fresh_state()
        state, decision = vocabulary_growth_step(state, _evidence(turns=5))
        assert decision["measurement_valid"] is False
        assert decision["vocab_growth_delta"] == 0.0

    def test_at_min_turns_processes_normally(self):
        state = _fresh_state()
        state, decision = vocabulary_growth_step(state, _evidence(turns=10))
        assert decision["measurement_valid"] is True


# ── No score / invalid evidence ──────────────────────────────

class TestInvalidEvidence:
    def test_no_score_returns_noop(self):
        state = _fresh_state()
        state, decision = vocabulary_growth_step(state, {"buffer_turns": 20})
        assert decision["measurement_valid"] is False

    def test_explicit_invalid_returns_noop(self):
        state = _fresh_state()
        state, decision = vocabulary_growth_step(
            state, _evidence(valid=False)
        )
        assert decision["measurement_valid"] is False

    def test_score_clamped_to_zero_one(self):
        state = _fresh_state(baseline_complexity=0.5, baseline_sessions_remaining=0)
        state, decision = vocabulary_growth_step(state, _evidence(score=1.5))
        assert state["current_complexity"] == 1.0


# ── Domain term tracking ─────────────────────────────────────

class TestDomainTerms:
    def test_domain_terms_tracked(self):
        state = _fresh_state(baseline_complexity=0.40, baseline_sessions_remaining=0)
        terms = ["photosynthesis", "biology:mitosis", "biology:cell"]
        state, decision = vocabulary_growth_step(
            state, _evidence(terms=terms)
        )
        assert decision["domain_terms_acquired"] == 3
        assert "_commons" in state["domain_vocabulary"]
        assert "biology" in state["domain_vocabulary"]
        assert state["domain_vocabulary"]["biology"]["terms_acquired"] == 2

    def test_empty_terms_no_error(self):
        state = _fresh_state(baseline_complexity=0.40, baseline_sessions_remaining=0)
        state, decision = vocabulary_growth_step(state, _evidence(terms=[]))
        assert decision["domain_terms_acquired"] == 0


# ── Session history ──────────────────────────────────────────

class TestSessionHistory:
    def test_history_accumulates(self):
        state = _fresh_state()
        for _ in range(5):
            state, _ = vocabulary_growth_step(state, _evidence())
        assert len(state["session_history"]) == 5

    def test_history_rolls_at_max(self):
        state = _fresh_state()
        params = {"session_history_max": 3, "min_turns_for_measurement": 10}
        for i in range(5):
            state, _ = vocabulary_growth_step(state, _evidence(score=0.3 + i * 0.01), params)
        assert len(state["session_history"]) == 3

    def test_history_entries_have_expected_keys(self):
        state = _fresh_state()
        state, _ = vocabulary_growth_step(state, _evidence())
        entry = state["session_history"][0]
        assert "complexity" in entry
        assert "delta" in entry
        assert "measured_utc" in entry


# ── Default state initialization ─────────────────────────────

class TestDefaultState:
    def test_build_default_has_all_keys(self):
        state = _build_default_vocab_state()
        assert state["baseline_complexity"] is None
        assert state["growth_delta"] == 0.0
        assert state["baseline_sessions_remaining"] == 3
        assert state["session_history"] == []

    def test_missing_keys_filled_in(self):
        """vocab step should fill missing keys without crashing."""
        state = {}
        state, decision = vocabulary_growth_step(state, _evidence())
        assert "baseline_complexity" in state
        assert "session_history" in state
