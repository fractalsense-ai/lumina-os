"""Tests for the baseline-before-escalation gate.

Three layers:
  1. Framework gate (ActorResolver) — escalation_eligible suppresses metric escalation
  2. ZPD window gate (learning_adapters.domain_step) — window fill vs drift_window_turns
  3. SVA baseline gate (freeform_adapters.freeform_domain_step) — baseline_sessions_remaining
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

# ── Setup: import ActorResolver ──────────────────────────────
from lumina.orchestrator.actor_resolver import ActorResolver

# ── Setup: import education controllers via importlib ─────────
_CTRL_DIR = Path(__file__).resolve().parent.parent / "domain-packs" / "education" / "controllers"
_LIB_DIR = Path(__file__).resolve().parent.parent / "domain-packs" / "education" / "domain-lib"

# Ensure the controllers directory is importable (for learning_adapters / freeform_adapters).
if str(_CTRL_DIR) not in sys.path:
    sys.path.insert(0, str(_CTRL_DIR))

# Import ZPD types for building test state
from zpd_monitor_v0_2 import (  # noqa: E402
    AffectState,
    LearningState,
    RecentWindow,
    zpd_monitor_step,
)

from learning_adapters import domain_step, build_initial_learning_state, FluencyState  # noqa: E402
from freeform_adapters import freeform_domain_step, freeform_build_initial_state  # noqa: E402


# ── Helpers ──────────────────────────────────────────────────

def _minimal_domain(standing_orders=None, invariants=None):
    return {
        "id": "test/domain/v1",
        "version": "1.0.0",
        "domain_authority": {"name": "Test", "role": "Tester"},
        "invariants": invariants or [],
        "standing_orders": standing_orders or [],
    }


def _fresh_zpd_state(*, attempts=0, min_challenge=0.3, max_challenge=0.7):
    state = LearningState(
        affect=AffectState(),
        mastery={"algebra_isolation": 0.5},
        challenge_band={"min_challenge": min_challenge, "max_challenge": max_challenge},
        recent_window=RecentWindow(attempts=attempts),
        challenge=0.5,
        uncertainty=0.5,
    )
    # Attach fluency and world-sim stubs that domain_step expects
    state.fluency = FluencyState()  # type: ignore[attr-defined]
    state.world_sim_theme = None  # type: ignore[attr-defined]
    state.mud_world_state = None  # type: ignore[attr-defined]
    return state


# ═══════════════════════════════════════════════════════════════
# Layer 1: Framework gate in ActorResolver
# ═══════════════════════════════════════════════════════════════

class TestActorResolverBaselineGate:
    """ActorResolver.resolve() must honour escalation_eligible."""

    def test_escalation_suppressed_when_not_eligible(self):
        resolver = ActorResolver(_minimal_domain())
        decision = {
            "action": "zpd_intervene_or_escalate",
            "should_escalate": True,
            "escalation_eligible": False,
        }
        _action, should_escalate, trigger = resolver.resolve([], decision)
        assert should_escalate is False
        assert trigger is None

    def test_escalation_fires_when_eligible(self):
        resolver = ActorResolver(_minimal_domain())
        decision = {
            "action": "zpd_intervene_or_escalate",
            "should_escalate": True,
            "escalation_eligible": True,
        }
        _action, should_escalate, trigger = resolver.resolve([], decision)
        assert should_escalate is True
        assert trigger == "domain_lib_escalation_event"

    def test_escalation_fires_when_field_absent_backward_compat(self):
        """Missing escalation_eligible defaults to True (backward-compat)."""
        resolver = ActorResolver(_minimal_domain())
        decision = {
            "action": "zpd_intervene_or_escalate",
            "should_escalate": True,
        }
        _action, should_escalate, trigger = resolver.resolve([], decision)
        assert should_escalate is True
        assert trigger == "domain_lib_escalation_event"

    def test_no_escalation_when_should_escalate_false(self):
        """escalation_eligible has no effect when should_escalate is False."""
        resolver = ActorResolver(_minimal_domain())
        decision = {
            "action": None,
            "should_escalate": False,
            "escalation_eligible": False,
        }
        _action, should_escalate, trigger = resolver.resolve([], decision)
        assert should_escalate is False
        assert trigger is None

    def test_invariant_escalation_not_gated(self):
        """Standing-order exhaustion must bypass the baseline gate."""
        domain = _minimal_domain(
            invariants=[{
                "id": "inv_a",
                "severity": "critical",
                "check": "flag_a",
                "standing_order_on_violation": "so_a",
            }],
            standing_orders=[{
                "id": "so_a",
                "action": "so_a",
                "max_attempts": 1,
                "escalation_on_exhaust": True,
            }],
        )
        resolver = ActorResolver(domain)
        failing = [{
            "id": "inv_a",
            "severity": "critical",
            "passed": False,
            "standing_order_on_violation": "so_a",
            "signal_type": None,
        }]
        # Attempt 1: fires standing order action
        resolver.resolve(failing, {"action": None, "should_escalate": False, "escalation_eligible": False})
        # Attempt 2: exhausted — must escalate regardless of escalation_eligible
        _action, should_escalate, trigger = resolver.resolve(
            failing,
            {"action": None, "should_escalate": False, "escalation_eligible": False},
        )
        assert should_escalate is True
        assert "standing_order_exhausted" in trigger


# ═══════════════════════════════════════════════════════════════
# Layer 2: ZPD window gate in learning_adapters.domain_step()
# ═══════════════════════════════════════════════════════════════

class TestZpdWindowGate:
    """domain_step must set escalation_eligible=False while window is filling."""

    _TASK_SPEC = {
        "skills_required": ["algebra_isolation"],
        "nominal_difficulty": 0.5,
    }
    _EVIDENCE = {
        "correctness": "correct",
        "hint_used": False,
        "off_task_ratio": 0.0,
    }

    def test_escalation_ineligible_on_first_turn(self):
        state = _fresh_zpd_state(attempts=0)
        _new_state, decision = domain_step(
            state, self._TASK_SPEC, self._EVIDENCE, {},
        )
        assert decision.get("escalation_eligible") is False

    def test_escalation_ineligible_before_window_full(self):
        state = _fresh_zpd_state(attempts=5)
        _new_state, decision = domain_step(
            state, self._TASK_SPEC, self._EVIDENCE, {},
        )
        # After step, window has 6 attempts — still < 10 default window
        assert decision.get("escalation_eligible") is False

    def test_escalation_eligible_after_window_full(self):
        state = _fresh_zpd_state(attempts=9)
        _new_state, decision = domain_step(
            state, self._TASK_SPEC, self._EVIDENCE, {},
        )
        # After step, window has 10 attempts == 10 window turns
        assert decision.get("escalation_eligible", True) is True


# ═══════════════════════════════════════════════════════════════
# Layer 3: SVA baseline gate in freeform_adapters
# ═══════════════════════════════════════════════════════════════

class TestSvaBaselineGate:
    """freeform_domain_step must set escalation_eligible=False during baseline."""

    _TASK_SPEC = {}
    _EVIDENCE = {"intent_type": "reflection"}

    def test_ineligible_during_baseline_priming(self):
        state = freeform_build_initial_state({})
        assert state["vocabulary_tracking"]["baseline_sessions_remaining"] == 3
        _new_state, decision = freeform_domain_step(
            state, self._TASK_SPEC, self._EVIDENCE, {},
        )
        assert decision.get("escalation_eligible") is False

    def test_ineligible_with_partial_baseline(self):
        state = freeform_build_initial_state({})
        state["vocabulary_tracking"]["baseline_sessions_remaining"] = 1
        _new_state, decision = freeform_domain_step(
            state, self._TASK_SPEC, self._EVIDENCE, {},
        )
        assert decision.get("escalation_eligible") is False

    def test_eligible_after_baseline_locked(self):
        state = freeform_build_initial_state({})
        state["vocabulary_tracking"]["baseline_sessions_remaining"] = 0
        _new_state, decision = freeform_domain_step(
            state, self._TASK_SPEC, self._EVIDENCE, {},
        )
        # escalation_eligible should not be set to False
        assert decision.get("escalation_eligible", True) is True


# ═══════════════════════════════════════════════════════════════
# Layer 2+: ZPD decision includes window_turns_filled
# ═══════════════════════════════════════════════════════════════

class TestZpdDecisionWindowTurnsFilled:
    """zpd_monitor_step must expose window_turns_filled in decision."""

    def test_window_turns_filled_present(self):
        state = LearningState(
            affect=AffectState(),
            mastery={"algebra_isolation": 0.5},
            challenge_band={"min_challenge": 0.3, "max_challenge": 0.7},
            recent_window=RecentWindow(attempts=4),
            challenge=0.5,
            uncertainty=0.5,
        )
        task_spec = {
            "skills_required": ["algebra_isolation"],
            "nominal_difficulty": 0.5,
        }
        evidence = {
            "correctness": "correct",
            "hint_used": False,
            "off_task_ratio": 0.0,
        }
        _new_state, decision = zpd_monitor_step(state, task_spec, evidence)
        assert "window_turns_filled" in decision
        assert decision["window_turns_filled"] == 5  # was 4, +1 after step
