"""Tests for zpd_monitor_v0_2 — boundary tolerance and off-task guard."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_EDU_REF = Path(__file__).resolve().parent.parent / "model-packs" / "education" / "controllers"
if str(_EDU_REF) not in sys.path:
    sys.path.insert(0, str(_EDU_REF))

from zpd_monitor_v0_2 import (  # noqa: E402
    AffectState,
    LearningState,
    RecentWindow,
    _ZPD_TOLERANCE,
    update_zpd_window,
    zpd_monitor_step,
)

# ── Shared fixtures ───────────────────────────────────────────────────────────

def _fresh_state(*, min_challenge: float = 0.3, max_challenge: float = 0.7) -> LearningState:
    return LearningState(
        affect=AffectState(),
        mastery={"algebra_isolation": 0.5},
        challenge_band={"min_challenge": min_challenge, "max_challenge": max_challenge},
        recent_window=RecentWindow(),
        challenge=0.5,
        uncertainty=0.5,
    )


_TASK_SPEC = {
    "skills_required": ["algebra_isolation"],
    "nominal_difficulty": 0.5,
}

# ── ZPD boundary tolerance ────────────────────────────────────────────────────


class TestZpdBoundaryTolerance:

    def test_tolerance_constant_is_positive(self):
        assert _ZPD_TOLERANCE > 0

    def test_challenge_exactly_at_upper_bound_is_not_outside(self):
        """challenge == zpd_max should NOT register as outside_band."""
        state = _fresh_state(max_challenge=0.70)
        evidence = {"correctness": "correct", "hint_used": False, "off_task_ratio": 0.0}
        # Set uncertainty=0 so estimate_challenge returns nominal_difficulty unchanged.
        state = LearningState(
            affect=state.affect,
            mastery=state.mastery,
            challenge_band=state.challenge_band,
            recent_window=state.recent_window,
            challenge=0.70,
            uncertainty=0.0,
        )
        new_state, decision = zpd_monitor_step(state, _TASK_SPEC, evidence)
        assert decision["outside_band"] is False, (
            f"challenge at zpd_max should not be outside_band; got {decision}"
        )

    def test_challenge_above_tolerance_band_is_outside(self):
        """challenge clearly above zpd_max + tolerance is detected as outside_band.

        Drive estimate_challenge above the band by setting mastery=0.0 on the
        required skill: new_challenge = nominal(0.5) + (0.5-0.0)*0.4 = 0.70,
        which is > zpd_max(0.50) + tolerance(0.01) = 0.51.
        """
        state = LearningState(
            affect=AffectState(),
            mastery={"algebra_isolation": 0.0},  # zero mastery → high challenge
            challenge_band={"min_challenge": 0.3, "max_challenge": 0.50},
            recent_window=RecentWindow(),
            challenge=0.5,
            uncertainty=0.0,
        )
        evidence = {"correctness": "correct", "hint_used": False, "off_task_ratio": 0.0}
        new_state, decision = zpd_monitor_step(state, _TASK_SPEC, evidence)
        assert decision["outside_band"] is True, (
            f"expected outside_band=True, challenge={decision.get('challenge')}"
        )

    def test_challenge_within_tolerance_of_lower_bound_is_not_outside(self):
        """challenge == zpd_min should NOT register as outside_band."""
        state = _fresh_state(min_challenge=0.30)
        state = LearningState(
            affect=state.affect,
            mastery=state.mastery,
            challenge_band=state.challenge_band,
            recent_window=state.recent_window,
            challenge=0.30,
            uncertainty=0.0,
        )
        evidence = {"correctness": "correct", "hint_used": False, "off_task_ratio": 0.0}
        new_state, decision = zpd_monitor_step(state, _TASK_SPEC, evidence)
        assert decision["outside_band"] is False


# ── Off-task turn guard ───────────────────────────────────────────────────────


class TestOffTaskGuard:

    def test_high_off_task_ratio_forces_outside_band_false(self):
        """update_zpd_window with off_task_ratio >= 0.8 must override outside_band."""
        window = RecentWindow()
        evidence = {"off_task_ratio": 1.0, "hint_used": False, "correctness": None}
        new_window = update_zpd_window(window, outside_band=True, evidence=evidence)
        # The flag prepended to outside_flags must be False (overridden)
        assert new_window.outside_flags[0] is False

    def test_low_off_task_ratio_does_not_override(self):
        """off_task_ratio < 0.8 leaves outside_band unchanged."""
        window = RecentWindow()
        evidence = {"off_task_ratio": 0.3, "hint_used": False, "correctness": "correct"}
        new_window = update_zpd_window(window, outside_band=True, evidence=evidence)
        assert new_window.outside_flags[0] is True

    def test_off_task_greeting_does_not_accumulate_toward_drift(self):
        """Multiple greeting turns (off_task_ratio=1.0) must never push outside_pct
        to the major-drift threshold (0.5) that triggers zpd_intervene_or_escalate."""
        state = _fresh_state()
        evidence_greeting = {
            "correctness": None,
            "hint_used": False,
            "off_task_ratio": 1.0,
            "response_latency_sec": 1.0,
            "frustration_marker_count": 0,
            "repeated_error": False,
        }
        for _ in range(10):
            state, decision = zpd_monitor_step(state, _TASK_SPEC, evidence_greeting)

        # No drift should have accumulated from pure off-task turns.
        assert state.recent_window.outside_pct == 0.0, (
            f"off-task turns should not accumulate outside_pct; got {state.recent_window.outside_pct}"
        )
        assert decision.get("action") not in ("zpd_intervene", "zpd_intervene_or_escalate"), (
            f"greeting turns must not trigger escalation; got action={decision.get('action')}"
        )
