"""
Tests for D.S.A. orchestrator standing-order exhaustion, per-invariant
counter reset, and warning fallthrough behaviour.

These tests exercise _resolve_action() and _resolve_standing_order_action()
directly — the orchestrator engine's domain-agnostic decision layer.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from lumina.orchestrator.dsa_orchestrator import DSAOrchestrator


# ── Helpers ──────────────────────────────────────────────────

def _make_domain(invariants: list[dict], standing_orders: list[dict]) -> dict:
    """Build a minimal domain physics dict for testing."""
    return {
        "id": "test/domain/v1",
        "version": "1.0.0",
        "domain_authority": {"name": "Test", "role": "Tester"},
        "invariants": invariants,
        "standing_orders": standing_orders,
    }


def _make_orchestrator(domain: dict) -> DSAOrchestrator:
    """Create an orchestrator with a temp ledger path and minimal profile."""
    tmp = tempfile.mkdtemp()
    return DSAOrchestrator(
        domain_physics=domain,
        subject_profile={"id": "test-student"},
        ledger_path=Path(tmp) / "test-ledger.jsonl",
    )


NOOP_DOMAIN_LIB = {"action": "task_presentation"}


# ── Standing-order exhaustion ────────────────────────────────

class TestStandingOrderExhaustion:
    """After max_attempts the corrective action must stop firing."""

    @pytest.fixture()
    def orch_escalate(self):
        """Orchestrator where the standing order escalates on exhaust."""
        domain = _make_domain(
            invariants=[{
                "id": "inv_a",
                "severity": "warning",
                "check": "flag_a",
                "standing_order_on_violation": "so_a",
            }],
            standing_orders=[{
                "id": "so_a",
                "action": "so_a",
                "max_attempts": 2,
                "escalation_on_exhaust": True,
            }],
        )
        return _make_orchestrator(domain)

    @pytest.fixture()
    def orch_silent(self):
        """Orchestrator where the standing order is silently suppressed."""
        domain = _make_domain(
            invariants=[{
                "id": "inv_b",
                "severity": "warning",
                "check": "flag_b",
                "standing_order_on_violation": "so_b",
            }],
            standing_orders=[{
                "id": "so_b",
                "action": "so_b",
                "max_attempts": 1,
                "escalation_on_exhaust": False,
            }],
        )
        return _make_orchestrator(domain)

    def test_action_fires_within_max_attempts(self, orch_escalate):
        failing = [{"id": "inv_a", "severity": "warning", "passed": False,
                     "standing_order_on_violation": "so_a", "signal_type": None}]
        action, esc, trigger = orch_escalate._resolve_action(failing, NOOP_DOMAIN_LIB)
        assert action == "so_a"
        assert esc is False

    def test_action_stops_after_max_attempts_with_escalation(self, orch_escalate):
        failing = [{"id": "inv_a", "severity": "warning", "passed": False,
                     "standing_order_on_violation": "so_a", "signal_type": None}]
        # Attempts 1 and 2: action fires
        orch_escalate._resolve_action(failing, NOOP_DOMAIN_LIB)
        orch_escalate._resolve_action(failing, NOOP_DOMAIN_LIB)
        # Attempt 3: exhausted — action stops, escalation fires
        action, esc, trigger = orch_escalate._resolve_action(failing, NOOP_DOMAIN_LIB)
        assert action is None, "Action must stop after exhaustion"
        assert esc is True, "Should escalate"
        assert "standing_order_exhausted" in trigger

    def test_action_stops_silently_after_max_attempts(self, orch_silent):
        failing = [{"id": "inv_b", "severity": "warning", "passed": False,
                     "standing_order_on_violation": "so_b", "signal_type": None}]
        # Attempt 1: fires
        action, esc, trigger = orch_silent._resolve_action(failing, NOOP_DOMAIN_LIB)
        assert action == "so_b"
        # Attempt 2: exhausted — suppressed, falls through to domain-lib
        action, esc, trigger = orch_silent._resolve_action(failing, NOOP_DOMAIN_LIB)
        assert action != "so_b", "Corrective action must stop after silent exhaustion"
        assert action == "task_presentation", "Should fall through to domain-lib"
        assert esc is False, "Should NOT escalate"

    def test_exhausted_warning_falls_through_to_domain_lib(self, orch_silent):
        failing = [{"id": "inv_b", "severity": "warning", "passed": False,
                     "standing_order_on_violation": "so_b", "signal_type": None}]
        # Exhaust the standing order
        orch_silent._resolve_action(failing, NOOP_DOMAIN_LIB)
        # Now it should fall through to domain-lib decision
        domain_decision = {"action": "task_presentation"}
        action, esc, trigger = orch_silent._resolve_action(failing, domain_decision)
        assert action == "task_presentation"
        assert esc is False


# ── Per-invariant counter reset ──────────────────────────────

class TestPerInvariantReset:
    """Counters are reset per-invariant, not all-or-nothing."""

    @pytest.fixture()
    def orch(self):
        domain = _make_domain(
            invariants=[
                {"id": "inv_a", "severity": "warning", "check": "flag_a",
                 "standing_order_on_violation": "so_a"},
                {"id": "inv_b", "severity": "warning", "check": "flag_b",
                 "standing_order_on_violation": "so_b"},
            ],
            standing_orders=[
                {"id": "so_a", "action": "so_a", "max_attempts": 3, "escalation_on_exhaust": False},
                {"id": "so_b", "action": "so_b", "max_attempts": 3, "escalation_on_exhaust": False},
            ],
        )
        return _make_orchestrator(domain)

    def test_passing_invariant_resets_its_own_counter(self, orch):
        # Turn 1: both fail → so_a fires (first warning)
        both_fail = [
            {"id": "inv_a", "severity": "warning", "passed": False,
             "standing_order_on_violation": "so_a", "signal_type": None},
            {"id": "inv_b", "severity": "warning", "passed": False,
             "standing_order_on_violation": "so_b", "signal_type": None},
        ]
        orch._resolve_action(both_fail, NOOP_DOMAIN_LIB)
        assert orch._standing_order_attempts.get("so_a") == 1

        # Turn 2: inv_a passes, inv_b still fails
        a_passes = [
            {"id": "inv_a", "severity": "warning", "passed": True,
             "standing_order_on_violation": "so_a", "signal_type": None},
            {"id": "inv_b", "severity": "warning", "passed": False,
             "standing_order_on_violation": "so_b", "signal_type": None},
        ]
        orch._resolve_action(a_passes, NOOP_DOMAIN_LIB)
        assert "so_a" not in orch._standing_order_attempts, \
            "so_a counter should be cleared when inv_a passes"
        assert orch._standing_order_attempts.get("so_b") == 1, \
            "so_b counter should still be tracked"

    def test_old_all_or_nothing_no_longer_blocks(self, orch):
        """Regression: previously inv_b failing prevented inv_a reset."""
        both_fail = [
            {"id": "inv_a", "severity": "warning", "passed": False,
             "standing_order_on_violation": "so_a", "signal_type": None},
            {"id": "inv_b", "severity": "warning", "passed": False,
             "standing_order_on_violation": "so_b", "signal_type": None},
        ]
        # Accumulate attempts
        orch._resolve_action(both_fail, NOOP_DOMAIN_LIB)
        orch._resolve_action(both_fail, NOOP_DOMAIN_LIB)
        assert orch._standing_order_attempts["so_a"] == 2

        # inv_a now passes — its counter must reset even though inv_b still fails
        a_passes = [
            {"id": "inv_a", "severity": "warning", "passed": True,
             "standing_order_on_violation": "so_a", "signal_type": None},
            {"id": "inv_b", "severity": "warning", "passed": False,
             "standing_order_on_violation": "so_b", "signal_type": None},
        ]
        orch._resolve_action(a_passes, NOOP_DOMAIN_LIB)
        assert "so_a" not in orch._standing_order_attempts


# ── Warning fallthrough ──────────────────────────────────────

class TestWarningFallthrough:
    """When a warning's standing order is exhausted, the orchestrator
    should try the next failing warning before falling through."""

    @pytest.fixture()
    def orch(self):
        domain = _make_domain(
            invariants=[
                {"id": "inv_w1", "severity": "warning", "check": "flag_w1",
                 "standing_order_on_violation": "so_w1"},
                {"id": "inv_w2", "severity": "warning", "check": "flag_w2",
                 "standing_order_on_violation": "so_w2"},
            ],
            standing_orders=[
                {"id": "so_w1", "action": "so_w1", "max_attempts": 1, "escalation_on_exhaust": False},
                {"id": "so_w2", "action": "so_w2", "max_attempts": 2, "escalation_on_exhaust": False},
            ],
        )
        return _make_orchestrator(domain)

    def test_falls_through_to_second_warning(self, orch):
        both_fail = [
            {"id": "inv_w1", "severity": "warning", "passed": False,
             "standing_order_on_violation": "so_w1", "signal_type": None},
            {"id": "inv_w2", "severity": "warning", "passed": False,
             "standing_order_on_violation": "so_w2", "signal_type": None},
        ]
        # Turn 1: so_w1 fires (first warning, attempt 1)
        action, _, _ = orch._resolve_action(both_fail, NOOP_DOMAIN_LIB)
        assert action == "so_w1"

        # Turn 2: so_w1 exhausted → falls through to so_w2
        action, _, _ = orch._resolve_action(both_fail, NOOP_DOMAIN_LIB)
        assert action == "so_w2", "Should fall through to second warning"

    def test_all_exhausted_falls_to_domain_lib(self, orch):
        both_fail = [
            {"id": "inv_w1", "severity": "warning", "passed": False,
             "standing_order_on_violation": "so_w1", "signal_type": None},
            {"id": "inv_w2", "severity": "warning", "passed": False,
             "standing_order_on_violation": "so_w2", "signal_type": None},
        ]
        # Exhaust both: so_w1 needs 1, so_w2 needs 2 → 3 turns total
        orch._resolve_action(both_fail, NOOP_DOMAIN_LIB)  # so_w1 fires
        orch._resolve_action(both_fail, NOOP_DOMAIN_LIB)  # so_w2 fires (so_w1 exhausted)
        orch._resolve_action(both_fail, NOOP_DOMAIN_LIB)  # so_w2 fires (attempt 2)

        # Turn 4: both exhausted → falls through to domain-lib
        domain_decision = {"action": "task_presentation"}
        action, esc, _ = orch._resolve_action(both_fail, domain_decision)
        assert action == "task_presentation"
        assert esc is False

    def test_critical_exhaustion_escalates(self):
        """Critical standing order exhaustion produces escalation signal."""
        domain = _make_domain(
            invariants=[{
                "id": "inv_crit",
                "severity": "critical",
                "check": "flag_crit",
                "standing_order_on_violation": "so_crit",
            }],
            standing_orders=[{
                "id": "so_crit",
                "action": "so_crit",
                "max_attempts": 1,
                "escalation_on_exhaust": True,
            }],
        )
        orch = _make_orchestrator(domain)
        failing = [{"id": "inv_crit", "severity": "critical", "passed": False,
                     "standing_order_on_violation": "so_crit", "signal_type": None}]
        # Attempt 1: fires
        action, esc, _ = orch._resolve_action(failing, NOOP_DOMAIN_LIB)
        assert action == "so_crit"
        assert esc is False

        # Attempt 2: exhausted → escalation, no action
        action, esc, trigger = orch._resolve_action(failing, NOOP_DOMAIN_LIB)
        assert action is None
        assert esc is True
        assert "standing_order_exhausted" in trigger
