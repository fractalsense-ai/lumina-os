"""Tests for the education domain dashboard_handlers (roster_status + risk scoring)
and the escalation enrichment logic (_enrich_escalation_records, _TRIGGER_LABELS)."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any

import asyncio

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]

# ── Import helpers ────────────────────────────────────────────

def _import_dashboard_handlers():
    """Import the dashboard_handlers module from the education domain pack."""
    path = _REPO_ROOT / "domain-packs" / "education" / "controllers" / "dashboard_handlers.py"
    spec = importlib.util.spec_from_file_location("dashboard_handlers", str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _import_escalation_handlers():
    """Import escalation_handlers from the education domain pack."""
    path = _REPO_ROOT / "domain-packs" / "education" / "controllers" / "escalation_handlers.py"
    spec = importlib.util.spec_from_file_location("escalation_handlers", str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── Fixtures ──────────────────────────────────────────────────

@pytest.fixture
def dh():
    return _import_dashboard_handlers()


@pytest.fixture
def eh():
    return _import_escalation_handlers()


# ═════════════════════════════════════════════════════════════
# Risk scoring — _compute_student_risk
# ═════════════════════════════════════════════════════════════

class TestComputeStudentRisk:

    def test_none_module_state_returns_green(self, dh):
        result = dh._compute_student_risk(None)
        assert result["risk_score"] == 0.0
        assert result["color"] == "green"

    def test_empty_module_state_returns_green(self, dh):
        result = dh._compute_student_risk({})
        assert result["risk_score"] == 0.0
        assert result["color"] == "green"

    def test_all_maxed_factors_returns_red(self, dh):
        state = {
            "recent_window": {
                "consecutive_incorrect": 10,
                "hint_count": 10,
                "outside_pct": 1.0,
            },
            "affect": {
                "frustration": True,
                "valence": -0.5,
            },
        }
        result = dh._compute_student_risk(state)
        assert result["risk_score"] == 1.0
        assert result["color"] == "red"

    def test_moderate_factors_yellow_range(self, dh):
        state = {
            "recent_window": {
                "consecutive_incorrect": 1,
                "hint_count": 2,
                "outside_pct": 0.2,
            },
            "affect": {"frustration": False, "valence": 0.5},
        }
        result = dh._compute_student_risk(state)
        assert 0.20 <= result["risk_score"] <= 0.50
        assert result["color"] in ("green", "yellow")

    def test_frustration_alone_pushes_score(self, dh):
        state = {
            "recent_window": {},
            "affect": {"frustration": True, "valence": 0.5},
        }
        result = dh._compute_student_risk(state)
        assert result["risk_score"] == pytest.approx(0.15, abs=0.01)
        assert result["color"] == "green"

    def test_low_valence_contributes(self, dh):
        state = {
            "recent_window": {},
            "affect": {"valence": 0.0},
        }
        result = dh._compute_student_risk(state)
        # valence_factor = max(0, min(0.5-0.0, 1.0)) = 0.5
        # score = 0.15 * 0.5 = 0.075
        assert result["risk_score"] == pytest.approx(0.075, abs=0.01)

    def test_factors_are_clamped(self, dh):
        """Inputs above expected range should be clamped, never producing >1.0."""
        state = {
            "recent_window": {
                "consecutive_incorrect": 100,
                "hint_count": 100,
                "outside_pct": 5.0,
            },
            "affect": {"frustration": True, "valence": -5.0},
        }
        result = dh._compute_student_risk(state)
        assert 0.0 <= result["risk_score"] <= 1.0
        assert result["color"] == "red"


# ═════════════════════════════════════════════════════════════
# Color threshold helpers
# ═════════════════════════════════════════════════════════════

class TestRiskColor:

    @pytest.mark.parametrize("score,expected", [
        (0.0, "green"),
        (0.24, "green"),
        (0.25, "yellow"),
        (0.49, "yellow"),
        (0.50, "orange"),
        (0.74, "orange"),
        (0.75, "red"),
        (1.0, "red"),
    ])
    def test_risk_color_thresholds(self, dh, score, expected):
        assert dh._risk_color(score) == expected


class TestTeacherStatusColor:

    def test_green_low_load(self, dh):
        assert dh._teacher_status_color(3, 0, False) == "green"

    def test_yellow_moderate_students(self, dh):
        assert dh._teacher_status_color(5, 0, False) == "yellow"

    def test_yellow_with_pending(self, dh):
        assert dh._teacher_status_color(2, 1, False) == "yellow"

    def test_orange_high_load(self, dh):
        assert dh._teacher_status_color(11, 0, False) == "orange"

    def test_orange_several_pending(self, dh):
        assert dh._teacher_status_color(2, 3, False) == "orange"

    def test_red_many_pending(self, dh):
        assert dh._teacher_status_color(2, 5, False) == "red"

    def test_red_sla_breach(self, dh):
        assert dh._teacher_status_color(2, 0, True) == "red"


# ═════════════════════════════════════════════════════════════
# Escalation enrichment — _TRIGGER_LABELS + _enrich_escalation_records
# ═════════════════════════════════════════════════════════════

class TestTriggerLabels:

    def test_all_expected_triggers_have_labels(self, eh):
        expected = [
            "zpd_drift_major",
            "standing_order_exhausted",
            "critical_invariant_violation",
            "frustration_detected",
            "content_safety",
            "consecutive_incorrect",
            "manual_escalation",
        ]
        for trigger in expected:
            assert trigger in eh._TRIGGER_LABELS
            assert isinstance(eh._TRIGGER_LABELS[trigger], str)
            assert len(eh._TRIGGER_LABELS[trigger]) > 5


class TestEnrichEscalationRecords:

    @pytest.fixture
    def mock_persistence(self):
        class FakePersistence:
            def __init__(self):
                self._users = {}

            def add_user(self, uid: str, username: str):
                self._users[uid] = {"username": username, "user_id": uid}

            def get_user(self, uid: str):
                return self._users.get(uid)

        return FakePersistence()

    def test_enrichment_adds_reason_and_evidence(self, eh, mock_persistence):
        mock_persistence.add_user("stu-1", "alice")
        records = [
            {
                "escalation_id": "esc-001",
                "actor_id": "stu-1",
                "trigger": "frustration_detected",
                "domain_pack_id": "general-education",
                "domain_lib_decision": {
                    "domain_alert_flag": True,
                    "domain_metric_pct": 0.8,
                    "tier": "A2",
                },
            },
        ]

        enriched = asyncio.run(eh._enrich_escalation_records(records, mock_persistence))

        assert len(enriched) == 1
        rec = enriched[0]
        assert rec["reason"] == eh._TRIGGER_LABELS["frustration_detected"]
        assert rec["student_username"] == "alice"
        assert rec["active_module"] == "general-education"
        assert rec["evidence"]["frustration"] is True
        assert rec["evidence"]["drift_pct"] == 0.8
        assert rec["evidence"]["tier"] == "A2"

    def test_enrichment_with_unknown_trigger(self, eh, mock_persistence):
        records = [
            {
                "escalation_id": "esc-002",
                "actor_id": "stu-2",
                "trigger": "some_new_trigger",
                "domain_lib_decision": {},
            },
        ]
        enriched = asyncio.run(eh._enrich_escalation_records(records, mock_persistence))
        rec = enriched[0]
        # Falls back to the raw trigger string
        assert rec["reason"] == "some_new_trigger"
        assert rec["student_username"] == "stu-2"

    def test_enrichment_with_empty_records(self, eh, mock_persistence):
        enriched = asyncio.run(eh._enrich_escalation_records([], mock_persistence))
        assert enriched == []

    def test_enrichment_preserves_original_fields(self, eh, mock_persistence):
        records = [
            {
                "escalation_id": "esc-003",
                "actor_id": "stu-3",
                "trigger": "zpd_drift_major",
                "status": "pending",
                "custom_field": "preserved",
            },
        ]
        enriched = asyncio.run(eh._enrich_escalation_records(records, mock_persistence))
        rec = enriched[0]
        assert rec["escalation_id"] == "esc-003"
        assert rec["status"] == "pending"
        assert rec["custom_field"] == "preserved"


# ═════════════════════════════════════════════════════════════
# roster_status handler — role gating
# ═════════════════════════════════════════════════════════════

class TestRosterStatusRoleGating:

    def test_student_is_forbidden(self, dh):
        result = asyncio.run(dh.roster_status(
            user_data={"role": "user", "sub": "stu-1", "domain_roles": {}},
            persistence=None,
        ))
        assert result.get("__status") == 403

    def test_no_domain_roles_forbidden(self, dh):
        result = asyncio.run(dh.roster_status(
            user_data={"role": "user", "sub": "stu-1"},
            persistence=None,
        ))
        assert result.get("__status") == 403
