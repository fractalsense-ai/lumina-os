"""Tests for the trip planning module (domain/asst/trip/v1).

Covers:
  1. Module file presence (domain-physics.json, module-config.yaml, trip-task-spec-v1.md)
  2. domain-physics.json schema validity
  3. INTENT_TO_MODULE registration
  4. _compute_trip_days helper
  5. Hard-invariant gating — all three missing → gather_trip_hard_invariants
  6. Hard-invariant gating — partial (two of three present) → still gated
  7. Hard-invariant gating — all three present → advances past hard gate
  8. Soft-degradation heuristic — long trip + 2 unknowns → gather_trip_soft_details
  9. Soft-degradation heuristic — short trip (≤3 days) bypasses soft gate
  10. Carry-forward — evidence wins over accumulated state for non-null fields
  11. Carry-forward — null evidence fields do NOT overwrite accumulated state
  12. tool_adapters — flight_search_tool missing origin returns error
  13. tool_adapters — flight_search_tool happy path returns stub
  14. tool_adapters — hotel_search_tool happy path returns stub
  15. tool_adapters — poi_search_tool happy path returns stub
  16. tool_adapters — routing_tool too few waypoints returns error
  17. tool_adapters — routing_tool happy path returns stub
  18. tool_adapters — restaurant_search_tool happy path returns stub
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
PACK = REPO_ROOT / "domain-packs" / "assistant"
_CONTROLLERS_DIR = str(PACK / "controllers")

if _CONTROLLERS_DIR not in sys.path:
    sys.path.insert(0, _CONTROLLERS_DIR)

_SENTINEL = object()


def _force_import(name: str):
    """Load *name* from the assistant controllers directory, bypassing module cache."""
    saved = sys.modules.pop(name, _SENTINEL)
    if not sys.path or sys.path[0] != _CONTROLLERS_DIR:
        sys.path.insert(0, _CONTROLLERS_DIR)
    mod = importlib.import_module(name)
    mod_file = getattr(mod, "__file__", "") or ""
    if _CONTROLLERS_DIR not in mod_file:
        sys.modules.pop(name, None)
        sys.path.insert(0, _CONTROLLERS_DIR)
        mod = importlib.import_module(name)
    if saved is _SENTINEL:
        sys.modules.pop(name, None)
    else:
        sys.modules[name] = saved
    return mod


# ════════════════════════════════════════════════════════════
# 1. Module file presence
# ════════════════════════════════════════════════════════════


class TestTripModuleFiles:
    def test_domain_physics_exists(self):
        assert (PACK / "modules" / "trip" / "domain-physics.json").is_file()

    def test_module_config_exists(self):
        assert (PACK / "modules" / "trip" / "module-config.yaml").is_file()

    def test_trip_task_spec_exists(self):
        assert (PACK / "domain-lib" / "reference" / "trip-task-spec-v1.md").is_file()


# ════════════════════════════════════════════════════════════
# 2. domain-physics.json schema validity
# ════════════════════════════════════════════════════════════


class TestTripDomainPhysics:
    @pytest.fixture(autouse=True)
    def _load(self):
        path = PACK / "modules" / "trip" / "domain-physics.json"
        self.data = json.loads(path.read_text())

    def test_has_id(self):
        assert self.data["id"] == "domain/asst/trip/v1"

    def test_has_invariants(self):
        assert isinstance(self.data["invariants"], list)
        assert len(self.data["invariants"]) >= 1

    def test_hard_fields_complete_invariant_present(self):
        ids = [inv["id"] for inv in self.data["invariants"]]
        assert "hard_fields_complete" in ids

    def test_hard_fields_invariant_is_warning(self):
        inv = next(i for i in self.data["invariants"] if i["id"] == "hard_fields_complete")
        assert inv["severity"] == "warning"

    def test_standing_order_for_gather(self):
        so_ids = [so["id"] for so in self.data["standing_orders"]]
        assert "gather_trip_hard_invariants" in so_ids

    def test_module_state_schema_has_hard_fields_complete(self):
        fields = self.data["module_state_schema"]["custom_fields"]
        assert "hard_fields_complete" in fields
        assert fields["hard_fields_complete"]["default"] is False

    def test_module_state_schema_has_all_carry_fields(self):
        fields = self.data["module_state_schema"]["custom_fields"]
        for f in (
            "trip_destination", "trip_origin_airport", "trip_date_start",
            "trip_date_end", "trip_activity_preferences", "trip_budget_usd",
            "trip_accommodation_style", "trip_party_size",
        ):
            assert f in fields, f"{f} missing from module_state_schema"


# ════════════════════════════════════════════════════════════
# 3. INTENT_TO_MODULE registration
# ════════════════════════════════════════════════════════════


class TestIntentToModuleRegistration:
    @pytest.fixture(autouse=True)
    def _import(self):
        mod = _force_import("runtime_adapters")
        self.INTENT_TO_MODULE = mod.INTENT_TO_MODULE

    def test_trip_in_intent_to_module(self):
        assert "trip" in self.INTENT_TO_MODULE

    def test_trip_maps_to_correct_module_id(self):
        assert self.INTENT_TO_MODULE["trip"] == "domain/asst/trip/v1"


# ════════════════════════════════════════════════════════════
# 4. _compute_trip_days helper
# ════════════════════════════════════════════════════════════


class TestComputeTripDays:
    @pytest.fixture(autouse=True)
    def _import(self):
        mod = _force_import("runtime_adapters")
        self._fn = mod._compute_trip_days

    def test_same_day_is_one(self):
        assert self._fn("2026-07-10", "2026-07-10") == 1

    def test_two_nights_is_three_days(self):
        assert self._fn("2026-07-01", "2026-07-03") == 3

    def test_two_weeks(self):
        assert self._fn("2026-07-01", "2026-07-14") == 14

    def test_none_when_start_missing(self):
        assert self._fn(None, "2026-07-14") is None

    def test_none_when_end_missing(self):
        assert self._fn("2026-07-01", None) is None

    def test_none_on_bad_format(self):
        assert self._fn("not-a-date", "2026-07-14") is None


# ════════════════════════════════════════════════════════════
# 5–11. domain_step trip routing
# ════════════════════════════════════════════════════════════


def _make_task_spec():
    return {"task_id": "trip-test-001", "nominal_difficulty": 0.5}


def _make_params():
    return {}


def _make_state(overrides: dict | None = None) -> dict:
    base = {
        "turn_count": 0,
        "trip_destination": None,
        "trip_origin_airport": None,
        "trip_date_start": None,
        "trip_date_end": None,
        "trip_activity_preferences": None,
        "trip_budget_usd": None,
        "trip_accommodation_style": None,
        "trip_party_size": 1,
        "hard_fields_complete": False,
        "trip_missing_hard": [],
        "trip_missing_soft": [],
    }
    if overrides:
        base.update(overrides)
    return base


def _make_evidence(intent: str = "trip", tool_call_requested: bool = True, **kwargs):
    ev = {
        "intent_type": intent,
        "tool_call_requested": tool_call_requested,
        "task_status": "open",
        "off_task_ratio": 0.0,
        "response_latency_sec": 5.0,
        "satisfaction_signal": "unknown",
    }
    ev.update(kwargs)
    return ev


class TestDomainStepTripRouting:
    @pytest.fixture(autouse=True)
    def _import(self):
        mod = _force_import("runtime_adapters")
        self.domain_step = mod.domain_step

    def test_all_hard_missing_yields_gather_action(self):
        """All three hard fields absent → action must be gather_trip_hard_invariants."""
        state = _make_state()
        evidence = _make_evidence()
        new_state, decision = self.domain_step(state, _make_task_spec(), evidence, _make_params())
        assert decision["action"] == "gather_trip_hard_invariants"
        assert new_state["hard_fields_complete"] is False
        assert set(new_state["trip_missing_hard"]) == {
            "destination", "travel dates", "departure airport"
        }

    def test_partial_hard_fields_still_gated(self):
        """Two of three hard fields present — still gated."""
        state = _make_state()
        evidence = _make_evidence(
            trip_destination="Paris, France",
            trip_date_start="2026-07-01",
        )
        new_state, decision = self.domain_step(state, _make_task_spec(), evidence, _make_params())
        assert decision["action"] == "gather_trip_hard_invariants"
        assert "departure airport" in new_state["trip_missing_hard"]

    def test_all_hard_fields_present_passes_gate(self):
        """All hard fields present → action is NOT gather_trip_hard_invariants."""
        state = _make_state()
        evidence = _make_evidence(
            trip_destination="Paris, France",
            trip_date_start="2026-07-01",
            trip_date_end="2026-07-07",
            trip_origin_airport="SYR",
        )
        new_state, decision = self.domain_step(state, _make_task_spec(), evidence, _make_params())
        assert decision["action"] != "gather_trip_hard_invariants"
        assert new_state["hard_fields_complete"] is True
        assert new_state["trip_missing_hard"] == []

    def test_long_trip_two_unknown_soft_triggers_soft_gate(self):
        """Trip > 3 days + 2 unknown soft fields → gather_trip_soft_details."""
        state = _make_state()
        evidence = _make_evidence(
            trip_destination="Tokyo, Japan",
            trip_date_start="2026-08-01",
            trip_date_end="2026-08-14",  # 14 days
            trip_origin_airport="JFK",
            # activity_prefs, budget, accommodation all null
        )
        new_state, decision = self.domain_step(state, _make_task_spec(), evidence, _make_params())
        assert decision["action"] == "gather_trip_soft_details"

    def test_short_trip_bypasses_soft_gate(self):
        """Trip ≤ 3 days → soft gate not triggered even with all unknowns."""
        state = _make_state()
        evidence = _make_evidence(
            trip_destination="Montreal, Canada",
            trip_date_start="2026-09-05",
            trip_date_end="2026-09-07",  # 3 days
            trip_origin_airport="SYR",
        )
        new_state, decision = self.domain_step(state, _make_task_spec(), evidence, _make_params())
        assert decision["action"] != "gather_trip_soft_details"
        assert decision["action"] == "trip_plan_create"

    def test_carry_forward_evidence_wins_non_null(self):
        """Non-null evidence fields overwrite accumulated state."""
        state = _make_state({"trip_destination": "Old Destination"})
        evidence = _make_evidence(
            trip_destination="New York, USA",
            trip_date_start="2026-10-01",
            trip_date_end="2026-10-05",
            trip_origin_airport="LAX",
        )
        new_state, _ = self.domain_step(state, _make_task_spec(), evidence, _make_params())
        assert new_state["trip_destination"] == "New York, USA"

    def test_carry_forward_null_evidence_does_not_overwrite(self):
        """Null evidence fields must NOT overwrite accumulated state values."""
        state = _make_state({
            "trip_destination": "Accumulated Destination",
            "trip_origin_airport": "SYR",
            "trip_date_start": "2026-07-01",
            "trip_date_end": "2026-07-10",
        })
        evidence = _make_evidence(
            trip_destination=None,
            trip_origin_airport=None,
            trip_date_start=None,
            trip_date_end=None,
        )
        new_state, _ = self.domain_step(state, _make_task_spec(), evidence, _make_params())
        assert new_state["trip_destination"] == "Accumulated Destination"
        assert new_state["trip_origin_airport"] == "SYR"


# ════════════════════════════════════════════════════════════
# 12–18. Tool adapter stubs
# ════════════════════════════════════════════════════════════


class TestTripToolAdapters:
    @pytest.fixture(autouse=True)
    def _import(self):
        mod = _force_import("tool_adapters")
        self.flight_search = mod.flight_search_tool
        self.flight_status = mod.flight_status_tool
        self.hotel_search = mod.hotel_search_tool
        self.poi_search = mod.poi_search_tool
        self.routing = mod.routing_tool
        self.restaurant_search = mod.restaurant_search_tool

    def test_flight_search_missing_origin_returns_error(self):
        result = self.flight_search({"destination": "Paris", "date_start": "2026-07-01"})
        assert result["ok"] is False
        assert "origin" in result["error"].lower()

    def test_flight_search_happy_path(self):
        result = self.flight_search({
            "origin": "SYR",
            "destination": "Paris, France",
            "date_start": "2026-07-01",
            "date_end": "2026-07-14",
            "party_size": 2,
        })
        assert result["ok"] is True
        assert result["stub"] is True
        assert isinstance(result["flights"], list)
        assert result["party_size"] == 2

    def test_hotel_search_happy_path(self):
        result = self.hotel_search({
            "destination": "Paris, France",
            "check_in": "2026-07-01",
            "check_out": "2026-07-14",
            "accommodation_style": "hotel",
        })
        assert result["ok"] is True
        assert isinstance(result["hotels"], list)

    def test_poi_search_happy_path(self):
        result = self.poi_search({
            "destination": "Paris, France",
            "categories": "history,art",
        })
        assert result["ok"] is True
        assert isinstance(result["pois"], list)

    def test_routing_too_few_waypoints_returns_error(self):
        result = self.routing({"waypoints": ["Only One"]})
        assert result["ok"] is False

    def test_routing_happy_path(self):
        result = self.routing({"waypoints": ["Eiffel Tower", "Louvre", "Notre Dame"]})
        assert result["ok"] is True
        assert len(result["legs"]) == 2

    def test_restaurant_search_happy_path(self):
        result = self.restaurant_search({
            "destination": "Paris, France",
            "cuisine": "French",
        })
        assert result["ok"] is True
        assert isinstance(result["restaurants"], list)
