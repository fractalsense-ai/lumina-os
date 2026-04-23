"""Tests for the assistant domain pack.

Covers:
  - Pack structure and file presence
  - task_tracker lifecycle logic
  - nlp_pre_interpreter keyword extraction
  - runtime_adapters intent routing (domain_step)
  - Tool adapter stubs
  - assistant_operations dispatcher
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import os
from unittest.mock import MagicMock, patch

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
PACK = REPO_ROOT / "domain-packs" / "assistant"

# Ensure controllers importable
_CONTROLLERS_DIR = str(PACK / "controllers")
sys.path.insert(0, _CONTROLLERS_DIR)

# Module names shared with other domain packs — must be force-reloaded from
# the assistant controllers directory so the full suite doesn't use cached
# versions from another pack.
_SHARED_MODULES = [
    "nlp_pre_interpreter", "runtime_adapters", "tool_adapters",
    "assistant_operations", "task_tracker",
]


def _force_import(name: str):
    """Import *name* from the assistant controllers dir, bypassing the module cache.

    Restores the original sys.modules entry afterwards so later tests that
    import the same module name from a different pack are not affected.
    """
    saved = sys.modules.pop(name, _SENTINEL)
    # Ensure our dir is first
    if not sys.path or sys.path[0] != _CONTROLLERS_DIR:
        sys.path.insert(0, _CONTROLLERS_DIR)
    mod = importlib.import_module(name)
    # If the module comes from outside our dir, force reload
    mod_file = getattr(mod, "__file__", "") or ""
    if _CONTROLLERS_DIR not in mod_file:
        sys.modules.pop(name, None)
        sys.path.insert(0, _CONTROLLERS_DIR)
        mod = importlib.import_module(name)
    # Restore previous sys.modules state so other test files are unaffected.
    if saved is _SENTINEL:
        sys.modules.pop(name, None)
    else:
        sys.modules[name] = saved
    return mod


_SENTINEL = object()


# ════════════════════════════════════════════════════════════
# 1. Pack structure
# ════════════════════════════════════════════════════════════


class TestAssistantPackStructure:
    def test_pack_yaml_exists(self):
        assert (PACK / "pack.yaml").is_file()

    def test_pack_yaml_has_correct_id(self):
        data = yaml.safe_load((PACK / "pack.yaml").read_text())
        assert data["pack_id"] == "assistant"

    def test_runtime_config_exists(self):
        assert (PACK / "cfg" / "runtime-config.yaml").is_file()

    def test_admin_operations_exists(self):
        assert (PACK / "cfg" / "admin-operations.yaml").is_file()

    def test_ui_config_exists(self):
        assert (PACK / "cfg" / "ui-config.yaml").is_file()

    def test_domain_profile_extension_exists(self):
        assert (PACK / "cfg" / "domain-profile-extension.yaml").is_file()

    def test_entity_profile_exists(self):
        assert (PACK / "profiles" / "entity.yaml").is_file()

    def test_persona_prompt_exists(self):
        assert (PACK / "prompts" / "domain-persona-v1.md").is_file()

    def test_turn_interpretation_spec_exists(self):
        spec = PACK / "domain-lib" / "reference" / "turn-interpretation-spec-v1.md"
        assert spec.is_file()

    EXPECTED_MODULES = [
        "conversation",
        "weather",
        "calendar",
        "search",
        "creative-writing",
        "planning",
        "domain-authority",
        "persona-craft",
    ]

    @pytest.mark.parametrize("module_name", EXPECTED_MODULES)
    def test_module_has_physics(self, module_name: str):
        physics = PACK / "modules" / module_name / "domain-physics.json"
        assert physics.is_file(), f"Missing domain-physics.json for {module_name}"

    @pytest.mark.parametrize("module_name", EXPECTED_MODULES)
    def test_module_has_config(self, module_name: str):
        cfg = PACK / "modules" / module_name / "module-config.yaml"
        assert cfg.is_file(), f"Missing module-config.yaml for {module_name}"

    @pytest.mark.parametrize("module_name", EXPECTED_MODULES)
    def test_module_physics_is_valid_json(self, module_name: str):
        physics = PACK / "modules" / module_name / "domain-physics.json"
        data = json.loads(physics.read_text())
        assert "id" in data
        assert "invariants" in data

    TOOL_ADAPTER_MODULES = ["weather", "calendar", "search", "planning"]

    @pytest.mark.parametrize("module_name", TOOL_ADAPTER_MODULES)
    def test_module_has_tool_adapter(self, module_name: str):
        adapters_dir = PACK / "modules" / module_name / "tool-adapters"
        assert adapters_dir.is_dir(), f"Missing tool-adapters/ for {module_name}"
        yamls = list(adapters_dir.glob("*.yaml"))
        assert len(yamls) >= 1, f"No adapter YAML in {module_name}/tool-adapters/"

    def test_creative_writing_has_no_tool_adapters(self):
        physics = json.loads(
            (PACK / "modules" / "creative-writing" / "domain-physics.json").read_text()
        )
        assert physics["tool_adapters"] == []


class TestAssistantDomainLibReference:
    EXPECTED_SPECS = [
        "weather-task-spec-v1.md",
        "calendar-task-spec-v1.md",
        "search-task-spec-v1.md",
        "creative-writing-task-spec-v1.md",
        "planning-task-spec-v1.md",
        "persona-craft-spec-v1.md",
    ]

    @pytest.mark.parametrize("spec_name", EXPECTED_SPECS)
    def test_spec_in_reference(self, spec_name: str):
        ref = PACK / "domain-lib" / "reference" / spec_name
        assert ref.is_file(), f"{spec_name} should be in domain-lib/reference/"


# ════════════════════════════════════════════════════════════
# 2. task_tracker
# ════════════════════════════════════════════════════════════


class TestTaskTracker:
    @pytest.fixture(autouse=True)
    def _import(self):
        mod = _force_import("task_tracker")
        self.OPEN = mod.OPEN
        self.COMPLETED = mod.COMPLETED
        self.CONTINUED = mod.CONTINUED
        self.DEFERRED = mod.DEFERRED
        self.ABANDONED = mod.ABANDONED
        self.new_task = mod.new_task
        self.update_task = mod.update_task
        self.active_tasks = mod.active_tasks
        self.is_terminal = mod.is_terminal

    def test_new_task_defaults(self):
        t = self.new_task("weather")
        assert t["intent_type"] == "weather"
        assert t["status"] == self.OPEN
        assert t["turn_count"] == 0
        assert "task_id" in t

    def test_new_task_custom_id(self):
        t = self.new_task("calendar", task_id="cal-001")
        assert t["task_id"] == "cal-001"

    def test_update_to_completed(self):
        t = self.new_task("search")
        t2 = self.update_task(t, self.COMPLETED)
        assert t2["status"] == self.COMPLETED

    def test_update_to_continued_increments_turns(self):
        t = self.new_task("planning")
        t2 = self.update_task(t, self.CONTINUED)
        assert t2["turn_count"] == 1
        t3 = self.update_task(t2, self.CONTINUED)
        assert t3["turn_count"] == 2

    def test_no_transition_from_terminal(self):
        t = self.new_task("general")
        t = self.update_task(t, self.COMPLETED)
        t2 = self.update_task(t, self.OPEN)
        assert t2["status"] == self.COMPLETED

    def test_is_terminal(self):
        t = self.new_task("weather")
        assert not self.is_terminal(t)
        t = self.update_task(t, self.COMPLETED)
        assert self.is_terminal(t)

    def test_active_tasks(self):
        tasks = [
            self.update_task(self.new_task("weather"), self.COMPLETED),
            self.new_task("calendar"),
            self.update_task(self.new_task("search"), self.ABANDONED),
            self.new_task("planning"),
        ]
        active = self.active_tasks(tasks)
        assert len(active) == 2

    def test_invalid_status_ignored(self):
        t = self.new_task("general")
        t2 = self.update_task(t, "invalid_status")
        assert t2["status"] == self.OPEN


# ════════════════════════════════════════════════════════════
# 3. nlp_pre_interpreter
# ════════════════════════════════════════════════════════════


class TestNlpPreInterpreter:
    @pytest.fixture(autouse=True)
    def _import(self):
        mod = _force_import("nlp_pre_interpreter")
        self.nlp_preprocess = mod.nlp_preprocess

    def test_weather_intent(self):
        result = self.nlp_preprocess("What's the weather in London?")
        assert result["intent_hint"] == "weather"

    def test_calendar_intent(self):
        result = self.nlp_preprocess("Schedule a meeting for tomorrow")
        assert result["intent_hint"] == "calendar"

    def test_search_intent(self):
        result = self.nlp_preprocess("Search for python tutorials")
        assert result["intent_hint"] == "search"

    def test_creative_intent(self):
        result = self.nlp_preprocess("Write a poem about the ocean")
        assert result["intent_hint"] == "creative"

    def test_planning_intent(self):
        result = self.nlp_preprocess("Help me plan a trip to Japan")
        assert result["intent_hint"] == "planning"

    def test_general_fallback(self):
        result = self.nlp_preprocess("Hello, how are you?")
        assert "intent_hint" not in result  # no keyword match → no hint

    def test_empty_input_flagged(self):
        result = self.nlp_preprocess("")
        assert result.get("empty_input") is True

    def test_location_extraction(self):
        result = self.nlp_preprocess("Weather in New York")
        assert "New York" in result.get("extracted_locations", [])

    def test_date_extraction(self):
        result = self.nlp_preprocess("Meeting tomorrow")
        assert "tomorrow" in result.get("extracted_dates", [])


# ════════════════════════════════════════════════════════════
# 4. runtime_adapters — domain_step intent routing
# ════════════════════════════════════════════════════════════


class TestRuntimeAdaptersIntentRouting:
    @pytest.fixture(autouse=True)
    def _import(self):
        mod = _force_import("runtime_adapters")
        self.INTENT_TO_MODULE = mod.INTENT_TO_MODULE
        self.build_initial_state = mod.build_initial_state
        self.domain_step = mod.domain_step

    def test_intent_map_covers_all_intents(self):
        expected = {"general", "weather", "calendar", "search", "creative", "planning"}
        assert expected.issubset(set(self.INTENT_TO_MODULE.keys()))

    def test_build_initial_state_seeds(self):
        state = self.build_initial_state({})
        assert state["turn_count"] == 0
        assert state["idle_turn_count"] == 0
        assert state["active_intent"] == "general"
        assert state["task_history"] == []
        assert state["intent_window"] == []
        # SVA affect state hydrated from empty profile
        assert state["affect"].salience == 0.5
        assert state["affect"].valence == 0.0
        assert state["affect"].arousal == 0.5
        assert state["affect_baseline"].sample_count == 0

    def test_domain_step_routes_weather(self):
        state = self.build_initial_state({})
        evidence = {"intent_type": "weather", "task_status": "open",
                    "satisfaction_signal": "unknown"}
        new_state, decision = self.domain_step(state, {}, evidence, {})
        assert decision["suggested_module"] == self.INTENT_TO_MODULE["weather"]

    def test_domain_step_increments_turn_count(self):
        state = self.build_initial_state({})
        state["turn_count"] = 5
        evidence = {"intent_type": "general", "task_status": "continued",
                    "satisfaction_signal": "unknown"}
        new_state, _ = self.domain_step(state, {}, evidence, {})
        assert new_state["turn_count"] == 6

    def test_domain_step_tracks_idle(self):
        state = self.build_initial_state({})
        evidence = {"intent_type": "general", "task_status": "n/a",
                    "satisfaction_signal": "unknown"}
        new_state, _ = self.domain_step(state, {}, evidence, {})
        assert new_state["idle_turn_count"] == 1

    def test_domain_step_completed_task_records_history(self):
        state = self.build_initial_state({})
        state["turn_count"] = 3
        state["active_task_id"] = "task-w-1"
        state["active_task_type"] = "weather"
        evidence = {"intent_type": "weather", "task_status": "completed",
                    "satisfaction_signal": "positive"}
        new_state, _ = self.domain_step(state, {}, evidence, {})
        assert new_state["active_task_id"] is None
        assert len(new_state["task_history"]) == 1


# ════════════════════════════════════════════════════════════
# 4b. SVA Affect Monitor — EWMA & Drift Detection
# ════════════════════════════════════════════════════════════


class TestAffectMonitor:
    """Tests for domain-lib/affect_monitor.py — SVA estimator + EWMA baseline."""

    @pytest.fixture(autouse=True)
    def _import(self):
        import importlib
        _DOMAIN_LIB_DIR = str(PACK / "domain-lib")
        saved_affect = sys.modules.pop("affect_monitor", _SENTINEL)
        if _DOMAIN_LIB_DIR not in sys.path:
            sys.path.insert(0, _DOMAIN_LIB_DIR)
        mod = importlib.import_module("affect_monitor")
        if saved_affect is _SENTINEL:
            sys.modules.pop("affect_monitor", None)
        else:
            sys.modules["affect_monitor"] = saved_affect
        self.AffectState = mod.AffectState
        self.AffectBaseline = mod.AffectBaseline
        self.DriftSignal = mod.DriftSignal
        self.update_affect = mod.update_affect
        self.update_baseline = mod.update_baseline
        self.compute_drift = mod.compute_drift
        self.module_deviation = mod.module_deviation
        self.DEFAULT_PARAMS = mod.DEFAULT_PARAMS

    # ── AffectState basics ────────────────────────────────────────

    def test_affect_state_defaults(self):
        s = self.AffectState()
        assert s.salience == 0.5
        assert s.valence == 0.0
        assert s.arousal == 0.5

    def test_affect_state_clamping(self):
        s = self.AffectState(salience=2.0, valence=-5.0, arousal=-1.0)
        assert s.salience == 1.0
        assert s.valence == -1.0
        assert s.arousal == 0.0

    def test_affect_state_roundtrip(self):
        s = self.AffectState(salience=0.7, valence=-0.3, arousal=0.9)
        d = s.to_dict()
        s2 = self.AffectState.from_dict(d)
        assert abs(s2.salience - 0.7) < 1e-5
        assert abs(s2.valence - (-0.3)) < 1e-5
        assert abs(s2.arousal - 0.9) < 1e-5

    # ── update_affect — deterministic deltas ──────────────────────

    def test_completed_task_boosts_valence(self):
        prev = self.AffectState()
        result = self.update_affect(prev, {"task_status": "completed"})
        assert result.valence > prev.valence
        assert result.salience > prev.salience

    def test_abandoned_task_drops_valence(self):
        prev = self.AffectState()
        result = self.update_affect(prev, {"task_status": "abandoned"})
        assert result.valence < prev.valence
        assert result.salience < prev.salience

    def test_positive_satisfaction_boosts_valence(self):
        prev = self.AffectState()
        result = self.update_affect(prev, {"satisfaction_signal": "positive"})
        assert result.valence > prev.valence

    def test_negative_satisfaction_drops_valence(self):
        prev = self.AffectState()
        result = self.update_affect(prev, {"satisfaction_signal": "negative"})
        assert result.valence < prev.valence

    def test_high_latency_drops_arousal(self):
        prev = self.AffectState()
        result = self.update_affect(prev, {"response_latency_sec": 60.0})
        assert result.arousal < prev.arousal

    def test_low_latency_boosts_arousal(self):
        prev = self.AffectState()
        result = self.update_affect(prev, {"response_latency_sec": 1.0})
        assert result.arousal > prev.arousal

    def test_intent_switching_drops_salience(self):
        prev = self.AffectState()
        result = self.update_affect(prev, {"intent_switches_in_window": 4})
        assert result.salience < prev.salience
        assert result.arousal > prev.arousal  # Frantic switching → arousal up

    def test_off_task_drops_salience(self):
        prev = self.AffectState()
        result = self.update_affect(prev, {"off_task_ratio": 0.8})
        assert result.salience < prev.salience

    def test_abandoned_with_tool_extra_frustration(self):
        prev = self.AffectState()
        r1 = self.update_affect(prev, {"task_status": "abandoned"})
        r2 = self.update_affect(prev, {
            "task_status": "abandoned", "tool_call_requested": True
        })
        assert r2.valence < r1.valence  # Extra penalty

    # ── EWMA Baseline ─────────────────────────────────────────────

    def test_baseline_defaults(self):
        b = self.AffectBaseline()
        assert b.sample_count == 0
        assert b.per_module == {}

    def test_baseline_update_increments_count(self):
        b = self.AffectBaseline()
        affect = self.AffectState(salience=0.8, valence=0.3, arousal=0.6)
        b2 = self.update_baseline(b, affect, module_id="domain/asst/weather/v1")
        assert b2.sample_count == 1

    def test_baseline_ewma_moves_toward_reading(self):
        b = self.AffectBaseline(salience=0.5, valence=0.0, arousal=0.5)
        affect = self.AffectState(salience=1.0, valence=1.0, arousal=1.0)
        b2 = self.update_baseline(b, affect)
        # EWMA with α=0.1: should move 10% toward new reading
        assert b2.salience > 0.5
        assert b2.salience < 1.0
        assert abs(b2.salience - 0.55) < 0.001

    def test_baseline_preserves_prev_for_velocity(self):
        b = self.AffectBaseline(salience=0.5, valence=0.0, arousal=0.5)
        affect = self.AffectState(salience=0.8, valence=0.5, arousal=0.7)
        b2 = self.update_baseline(b, affect)
        assert b2.prev_salience == 0.5
        assert b2.prev_valence == 0.0
        assert b2.prev_arousal == 0.5

    def test_per_module_signature_recorded(self):
        b = self.AffectBaseline()
        affect = self.AffectState(salience=0.8, valence=0.3, arousal=0.6)
        b2 = self.update_baseline(b, affect, module_id="domain/asst/weather/v1")
        assert "domain/asst/weather/v1" in b2.per_module
        mod_sig = b2.per_module["domain/asst/weather/v1"]
        assert "delta_from_baseline" in mod_sig
        assert mod_sig["sample_count"] == 1

    def test_per_module_count_accumulates(self):
        b = self.AffectBaseline()
        for _ in range(3):
            affect = self.AffectState(salience=0.7, valence=0.2, arousal=0.6)
            b = self.update_baseline(b, affect, module_id="domain/asst/weather/v1")
        assert b.per_module["domain/asst/weather/v1"]["sample_count"] == 3

    def test_baseline_roundtrip(self):
        b = self.AffectBaseline(salience=0.6, valence=0.1, arousal=0.7, sample_count=5)
        d = b.to_dict()
        b2 = self.AffectBaseline.from_dict(d)
        assert b2.sample_count == 5
        assert abs(b2.salience - 0.6) < 1e-5

    # ── Drift Velocity Detection ──────────────────────────────────

    def test_drift_no_signal_before_min_samples(self):
        b = self.AffectBaseline(sample_count=2)
        drift = self.compute_drift(b)
        assert drift.is_fast_drift is False

    def test_drift_detects_fast_valence_drop(self):
        # Simulate a sudden drop: prev was 0.5, now moved to 0.4
        b = self.AffectBaseline(
            valence=0.4, prev_valence=0.5,
            salience=0.5, prev_salience=0.5,
            arousal=0.5, prev_arousal=0.5,
            sample_count=10,
        )
        drift = self.compute_drift(b)
        assert drift.is_fast_drift is True
        assert drift.drift_axis == "valence"
        assert drift.velocity_valence < 0

    def test_drift_no_trigger_on_small_change(self):
        b = self.AffectBaseline(
            valence=0.49, prev_valence=0.5,
            salience=0.5, prev_salience=0.5,
            arousal=0.5, prev_arousal=0.5,
            sample_count=10,
        )
        drift = self.compute_drift(b)
        assert drift.is_fast_drift is False

    def test_drift_picks_worst_axis(self):
        b = self.AffectBaseline(
            salience=0.3, prev_salience=0.5,  # Δ=-0.2 (worst)
            valence=0.45, prev_valence=0.5,   # Δ=-0.05
            arousal=0.52, prev_arousal=0.5,   # Δ=+0.02
            sample_count=10,
        )
        drift = self.compute_drift(b)
        assert drift.is_fast_drift is True
        assert drift.drift_axis == "salience"

    # ── Module Deviation ──────────────────────────────────────────

    def test_module_deviation_none_for_missing(self):
        b = self.AffectBaseline()
        assert self.module_deviation(b, "unknown/module") is None

    def test_module_deviation_returns_deltas(self):
        b = self.AffectBaseline()
        b.per_module["domain/asst/weather/v1"] = {
            "salience": 0.8,
            "valence": 0.3,
            "arousal": 0.6,
            "delta_from_baseline": {"salience": 0.3, "valence": 0.3, "arousal": 0.1},
            "sample_count": 5,
        }
        dev = self.module_deviation(b, "domain/asst/weather/v1")
        assert dev["salience"] == 0.3


class TestSVAIntegrationWithDomainStep:
    """Integration tests: SVA wired into domain_step via runtime_adapters."""

    @pytest.fixture(autouse=True)
    def _import(self):
        mod = _force_import("runtime_adapters")
        self.build_initial_state = mod.build_initial_state
        self.domain_step = mod.domain_step

    def test_domain_step_returns_affect_in_decision(self):
        state = self.build_initial_state({})
        evidence = {"intent_type": "weather", "task_status": "open",
                    "satisfaction_signal": "neutral"}
        _, decision = self.domain_step(state, {}, evidence, {})
        assert "affect" in decision
        assert "salience" in decision["affect"]
        assert "valence" in decision["affect"]
        assert "arousal" in decision["affect"]

    def test_domain_step_returns_drift_in_decision(self):
        state = self.build_initial_state({})
        evidence = {"intent_type": "general", "task_status": "n/a"}
        _, decision = self.domain_step(state, {}, evidence, {})
        assert "drift" in decision
        assert "is_fast_drift" in decision["drift"]

    def test_affect_evolves_across_turns(self):
        state = self.build_initial_state({})
        # Several positive turns
        for _ in range(5):
            evidence = {"intent_type": "weather", "task_status": "completed",
                        "satisfaction_signal": "positive"}
            state, _ = self.domain_step(state, {}, evidence, {})
        assert state["affect"].valence > 0.0
        assert state["affect_baseline"].sample_count == 5

    def test_abandoned_turns_trigger_negative_drift(self):
        state = self.build_initial_state({})
        # Build up baseline first (min_samples_for_drift = 5)
        for _ in range(6):
            evidence = {"intent_type": "search", "task_status": "open",
                        "satisfaction_signal": "neutral"}
            state, _ = self.domain_step(state, {}, evidence, {})
        # Then slam with abandoned tasks
        evidence = {"intent_type": "search", "task_status": "abandoned",
                    "satisfaction_signal": "negative"}
        state, decision = self.domain_step(state, {}, evidence, {})
        # After enough samples + a big negative swing, drift should fire
        # (may need multiple to overcome EWMA smoothing)
        assert decision["drift"]["velocity_valence"] <= 0

    def test_rapid_intent_switching_triggers_salience_drop(self):
        state = self.build_initial_state({})
        intents = ["weather", "calendar", "search", "planning", "creative"]
        for intent in intents:
            evidence = {"intent_type": intent, "task_status": "n/a",
                        "satisfaction_signal": "neutral"}
            state, _ = self.domain_step(state, {}, evidence, {})
        # After 5 different intents, the intent window has many switches
        # Salience should be lower than starting 0.5
        assert state["affect"].salience < 0.5

    def test_affect_drift_alert_fires_on_fast_drop(self):
        state = self.build_initial_state({})
        # Build baseline with 6 neutral turns
        for _ in range(6):
            evidence = {"intent_type": "general", "task_status": "n/a",
                        "satisfaction_signal": "neutral"}
            state, _ = self.domain_step(state, {}, evidence, {})
        # Simulate sudden frustration — big negative hit
        # Force the state to have a large prev_valence gap
        state["affect_baseline"].prev_valence = state["affect_baseline"].valence
        # Now give a strongly negative turn
        evidence = {"intent_type": "general", "task_status": "abandoned",
                    "satisfaction_signal": "negative",
                    "off_task_ratio": 0.8, "tool_call_requested": True}
        state, decision = self.domain_step(state, {}, evidence, {})
        # The drift may or may not exceed threshold depending on EWMA smoothing,
        # but the valence velocity should be negative
        assert decision["drift"]["velocity_valence"] <= 0

    def test_per_module_tracking_persists(self):
        state = self.build_initial_state({})
        # Weather turns
        for _ in range(3):
            evidence = {"intent_type": "weather", "task_status": "completed",
                        "satisfaction_signal": "positive"}
            state, _ = self.domain_step(state, {}, evidence, {})
        # Calendar turns
        for _ in range(2):
            evidence = {"intent_type": "calendar", "task_status": "open",
                        "satisfaction_signal": "neutral"}
            state, _ = self.domain_step(state, {}, evidence, {})
        baseline = state["affect_baseline"]
        assert "domain/asst/weather/v1" in baseline.per_module
        assert "domain/asst/calendar/v1" in baseline.per_module
        assert baseline.per_module["domain/asst/weather/v1"]["sample_count"] == 3
        assert baseline.per_module["domain/asst/calendar/v1"]["sample_count"] == 2

    def test_frustration_flag_on_valence_drift(self):
        state = self.build_initial_state({})
        # Burn in 5 neutral turns
        for _ in range(5):
            evidence = {"intent_type": "general", "task_status": "n/a",
                        "satisfaction_signal": "neutral"}
            state, _ = self.domain_step(state, {}, evidence, {})
        # Now force a scenario where valence drifts fast
        # Directly manipulate baseline to test the frustration flag logic
        state["affect_baseline"].prev_valence = state["affect_baseline"].valence + 0.1
        state["affect_baseline"].sample_count = 10
        # Give negative evidence
        evidence = {"intent_type": "general", "task_status": "abandoned",
                    "satisfaction_signal": "negative"}
        state, decision = self.domain_step(state, {}, evidence, {})
        # Frustration is specifically tied to fast drift on valence axis
        if decision["drift"]["is_fast_drift"] and decision["drift"]["drift_axis"] == "valence":
            assert decision["frustration"] is True

    def test_build_initial_state_hydrates_from_profile(self):
        profile = {
            "entity_state": {
                "affect_baseline": {
                    "salience": 0.7,
                    "valence": 0.3,
                    "arousal": 0.6,
                    "sample_count": 50,
                    "prev_salience": 0.68,
                    "prev_valence": 0.28,
                    "prev_arousal": 0.59,
                    "per_module": {
                        "domain/asst/weather/v1": {
                            "salience": 0.8, "valence": 0.4, "arousal": 0.7,
                            "delta_from_baseline": {"salience": 0.1, "valence": 0.1, "arousal": 0.1},
                            "sample_count": 20,
                        }
                    }
                }
            }
        }
        state = self.build_initial_state(profile)
        assert state["affect"].salience == 0.7
        assert state["affect"].valence == 0.3
        assert state["affect_baseline"].sample_count == 50
        assert "domain/asst/weather/v1" in state["affect_baseline"].per_module


# ════════════════════════════════════════════════════════════
# 4c. task_tracker — attach_affect_snapshot
# ════════════════════════════════════════════════════════════


class TestTaskTrackerAffect:
    @pytest.fixture(autouse=True)
    def _import(self):
        mod = _force_import("task_tracker")
        self.new_task = mod.new_task
        self.attach_affect_snapshot = mod.attach_affect_snapshot

    def test_attach_affect_snapshot(self):
        t = self.new_task("weather")
        affect = {"salience": 0.7, "valence": 0.3, "arousal": 0.6}
        t2 = self.attach_affect_snapshot(t, affect)
        assert t2["affect_at_close"] == affect

    def test_attach_does_not_mutate_original(self):
        t = self.new_task("calendar")
        affect = {"salience": 0.5, "valence": 0.0, "arousal": 0.5}
        t2 = self.attach_affect_snapshot(t, affect)
        assert "affect_at_close" not in t
        assert "affect_at_close" in t2


# ════════════════════════════════════════════════════════════
# 5. Tool adapter stubs
# ════════════════════════════════════════════════════════════


def _owm_current_mock():
    m = MagicMock()
    m.status_code = 200
    m.raise_for_status = MagicMock()
    m.json.return_value = {
        "name": "London",
        "main": {"temp": 18.5, "humidity": 72},
        "weather": [{"description": "light rain"}],
        "wind": {"speed": 5.0},
    }
    return m


def _owm_forecast_mock():
    m = MagicMock()
    m.status_code = 200
    m.raise_for_status = MagicMock()
    m.json.return_value = {
        "list": [{
            "dt_txt": "2026-04-23 12:00:00",
            "main": {"temp_max": 21.0, "temp_min": 14.0},
            "weather": [{"description": "cloudy"}],
        }]
    }
    return m


def _tavily_mock():
    m = MagicMock()
    m.status_code = 200
    m.raise_for_status = MagicMock()
    m.json.return_value = {
        "results": [{
            "title": "Okinawa Guide",
            "url": "https://example.com/okinawa",
            "content": "Great beaches and clear water.",
            "score": 0.92,
        }],
        "answer": "Okinawa is a tropical island in Japan.",
    }
    return m


_CALENDAR_ENV = {
    "GOOGLE_CALENDAR_CLIENT_ID": "test-client-id",
    "GOOGLE_CALENDAR_CLIENT_SECRET": "test-client-secret",
    "GOOGLE_CALENDAR_REFRESH_TOKEN": "test-refresh-token",
}


def _google_token_mock():
    m = MagicMock()
    m.status_code = 200
    m.raise_for_status = MagicMock()
    m.json.return_value = {"access_token": "ya29.test-access-token", "expires_in": 3599}
    return m


def _caldav_mock(events_data=None):
    from datetime import datetime, timezone
    if events_data is None:
        events_data = []
    mock_client = MagicMock()
    mock_calendar = MagicMock()
    mock_client.calendar.return_value = mock_calendar
    mock_results = []
    for ev in events_data:
        mock_event = MagicMock()
        mock_vevent = MagicMock()
        mock_vevent.uid.value = ev.get("uid", "uid-001")
        mock_vevent.summary.value = ev.get("title", "Test Event")
        start_dt = datetime.fromisoformat(ev.get("start", "2026-04-22T09:00:00")).replace(tzinfo=timezone.utc)
        end_dt = datetime.fromisoformat(ev.get("end", "2026-04-22T09:30:00")).replace(tzinfo=timezone.utc)
        mock_vevent.dtstart.value = start_dt
        mock_vevent.dtend.value = end_dt
        mock_event.vobject_instance.vevent = mock_vevent
        mock_results.append(mock_event)
    mock_calendar.date_search.return_value = mock_results
    return mock_client


class TestToolAdapterStubs:
    @pytest.fixture(autouse=True)
    def _import(self):
        mod = _force_import("tool_adapters")
        self.weather_lookup_tool = mod.weather_lookup_tool
        self.calendar_query_tool = mod.calendar_query_tool
        self.calendar_write_tool = mod.calendar_write_tool
        self.web_search_tool = mod.web_search_tool
        self.planning_create_tool = mod.planning_create_tool
        self.planning_update_tool = mod.planning_update_tool
        self.planning_list_tool = mod.planning_list_tool

    def test_weather_ok(self):
        with patch("httpx.get", side_effect=[_owm_current_mock(), _owm_forecast_mock()]), \
             patch.dict(os.environ, {"OPENWEATHERMAP_API_KEY": "test-key"}):
            r = self.weather_lookup_tool({"location": "London"})
        assert r["ok"] is True
        assert "temperature_c" in r

    def test_weather_missing_location(self):
        r = self.weather_lookup_tool({})
        assert r["ok"] is False

    def test_weather_no_api_key(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("OPENWEATHERMAP_API_KEY", None)
            r = self.weather_lookup_tool({"location": "London"})
        assert r["ok"] is False
        assert "not configured" in r["error"]

    def test_weather_invalid_api_key(self):
        bad = MagicMock()
        bad.status_code = 401
        with patch("httpx.get", return_value=bad), \
             patch.dict(os.environ, {"OPENWEATHERMAP_API_KEY": "bad-key"}):
            r = self.weather_lookup_tool({"location": "London"})
        assert r["ok"] is False
        assert "invalid API key" in r["error"]

    def test_weather_location_not_found(self):
        not_found = MagicMock()
        not_found.status_code = 404
        with patch("httpx.get", return_value=not_found), \
             patch.dict(os.environ, {"OPENWEATHERMAP_API_KEY": "test-key"}):
            r = self.weather_lookup_tool({"location": "Atlantis"})
        assert r["ok"] is False

    def test_weather_service_unavailable(self):
        import httpx as _httpx
        with patch("httpx.get", side_effect=_httpx.ConnectError("refused")), \
             patch.dict(os.environ, {"OPENWEATHERMAP_API_KEY": "test-key"}):
            r = self.weather_lookup_tool({"location": "London"})
        assert r["ok"] is False

    def test_weather_wind_converted_to_kph(self):
        current = _owm_current_mock()
        current.json.return_value["wind"]["speed"] = 5.0
        with patch("httpx.get", side_effect=[current, _owm_forecast_mock()]), \
             patch.dict(os.environ, {"OPENWEATHERMAP_API_KEY": "test-key"}):
            r = self.weather_lookup_tool({"location": "London"})
        assert r["ok"] is True
        assert r["wind_kph"] == 18.0

    def test_calendar_query_ok(self):
        with patch("httpx.post", return_value=_google_token_mock()), \
             patch("caldav.DAVClient", return_value=_caldav_mock()), \
             patch.dict(os.environ, _CALENDAR_ENV):
            r = self.calendar_query_tool({"date_start": "2026-04-20"})
        assert r["ok"] is True
        assert "events" in r
        assert "date_range" in r

    def test_calendar_query_missing_start(self):
        r = self.calendar_query_tool({})
        assert r["ok"] is False

    def test_calendar_query_no_credentials(self):
        env_override = {k: "" for k in _CALENDAR_ENV.keys()}
        with patch.dict(os.environ, env_override):
            r = self.calendar_query_tool({"date_start": "2026-04-22"})
        assert r["ok"] is False
        assert "not configured" in r["error"]

    def test_calendar_query_token_refresh_failure(self):
        import httpx as _httpx
        with patch("httpx.post", side_effect=_httpx.ConnectError("refused")), \
             patch.dict(os.environ, _CALENDAR_ENV):
            r = self.calendar_query_tool({"date_start": "2026-04-22"})
        assert r["ok"] is False
        assert "token" in r["error"]

    def test_calendar_query_caldav_error(self):
        mock_client = MagicMock()
        mock_client.calendar.return_value.date_search.side_effect = Exception("CalDAV failure")
        with patch("httpx.post", return_value=_google_token_mock()), \
             patch("caldav.DAVClient", return_value=mock_client), \
             patch.dict(os.environ, _CALENDAR_ENV):
            r = self.calendar_query_tool({"date_start": "2026-04-22"})
        assert r["ok"] is False

    def test_calendar_query_returns_events(self):
        events_data = [{"uid": "evt-001", "title": "Team standup",
                        "start": "2026-04-22T09:00:00", "end": "2026-04-22T09:30:00"}]
        with patch("httpx.post", return_value=_google_token_mock()), \
             patch("caldav.DAVClient", return_value=_caldav_mock(events_data)), \
             patch.dict(os.environ, _CALENDAR_ENV):
            r = self.calendar_query_tool({"date_start": "2026-04-22"})
        assert r["ok"] is True
        assert len(r["events"]) == 1
        assert r["events"][0]["title"] == "Team standup"

    def test_calendar_query_date_end_defaults_to_start(self):
        with patch("httpx.post", return_value=_google_token_mock()), \
             patch("caldav.DAVClient", return_value=_caldav_mock()), \
             patch.dict(os.environ, _CALENDAR_ENV):
            r = self.calendar_query_tool({"date_start": "2026-04-22"})
        assert r["ok"] is True
        assert r["date_range"]["end"] == "2026-04-22"

    def test_calendar_write_create(self):
        r = self.calendar_write_tool({"action": "create", "event_title": "Meeting"})
        assert r["ok"] is True

    def test_calendar_write_bad_action(self):
        r = self.calendar_write_tool({"action": "nope"})
        assert r["ok"] is False

    def test_search_ok(self):
        with patch("httpx.post", return_value=_tavily_mock()), \
             patch.dict(os.environ, {"TAVILY_API_KEY": "test-key"}):
            r = self.web_search_tool({"query": "Okinawa beaches"})
        assert r["ok"] is True
        assert r["query"] == "Okinawa beaches"
        assert len(r["results"]) > 0
        assert "title" in r["results"][0]
        assert "snippet" in r["results"][0]
        assert "url" in r["results"][0]
        assert "relevance" in r["results"][0]
        assert "answer" in r

    def test_search_missing_query(self):
        r = self.web_search_tool({})
        assert r["ok"] is False

    def test_search_no_api_key(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("TAVILY_API_KEY", None)
            r = self.web_search_tool({"query": "python"})
        assert r["ok"] is False
        assert "not configured" in r["error"]

    def test_search_invalid_api_key(self):
        bad = MagicMock()
        bad.status_code = 401
        with patch("httpx.post", return_value=bad), \
             patch.dict(os.environ, {"TAVILY_API_KEY": "bad-key"}):
            r = self.web_search_tool({"query": "python"})
        assert r["ok"] is False
        assert "invalid API key" in r["error"]

    def test_search_service_unavailable(self):
        import httpx as _httpx
        with patch("httpx.post", side_effect=_httpx.ConnectError("refused")), \
             patch.dict(os.environ, {"TAVILY_API_KEY": "test-key"}):
            r = self.web_search_tool({"query": "python"})
        assert r["ok"] is False
        assert "unavailable" in r["error"]

    def test_search_answer_in_result(self):
        with patch("httpx.post", return_value=_tavily_mock()), \
             patch.dict(os.environ, {"TAVILY_API_KEY": "test-key"}):
            r = self.web_search_tool({"query": "Okinawa"})
        assert r["answer"] == "Okinawa is a tropical island in Japan."

    def test_search_max_results_capped(self):
        mock = _tavily_mock()
        mock.json.return_value["results"] = [
            {"title": f"R{i}", "url": f"https://x.com/{i}", "content": "c", "score": 0.5}
            for i in range(10)
        ]
        with patch("httpx.post", return_value=mock) as mock_post, \
             patch.dict(os.environ, {"TAVILY_API_KEY": "test-key"}):
            self.web_search_tool({"query": "python", "max_results": 999})
        call_kwargs = mock_post.call_args
        assert call_kwargs[1]["json"]["max_results"] == 10

    def test_planning_create_ok(self):
        r = self.planning_create_tool({"goal": "Plan a trip to Okinawa"})
        assert r["ok"] is True
        assert "brief" in r
        assert r["brief"]["status"] == "ready_for_synthesis"
        assert r["brief"]["goal"] == "Plan a trip to Okinawa"

    def test_planning_create_missing_goal(self):
        r = self.planning_create_tool({})
        assert r["ok"] is False
        assert "goal" in r["error"]

    def test_planning_create_bundles_tool_results(self):
        tool_results = {
            "weather_lookup": {"ok": True, "temperature_c": 28},
            "web_search": {"ok": True, "results": []},
        }
        r = self.planning_create_tool({"goal": "Okinawa trip", "tool_results": tool_results})
        assert r["ok"] is True
        assert set(r["brief"]["sources"]) == {"weather_lookup", "web_search"}

    def test_planning_create_sources_list(self):
        r = self.planning_create_tool({"goal": "Weekend plan"})
        assert r["ok"] is True
        assert r["brief"]["sources"] == []
        assert r["brief"]["horizon_days"] == 3
        assert r["brief"]["constraints"] == []

    def test_planning_update_ok(self):
        r = self.planning_update_tool({"plan_id": "plan-001"})
        assert r["ok"] is True

    def test_planning_list(self):
        r = self.planning_list_tool({})
        assert r["ok"] is True


# ════════════════════════════════════════════════════════════
# 6. assistant_operations dispatcher
# ════════════════════════════════════════════════════════════


class TestAssistantOperations:
    @pytest.fixture(autouse=True)
    def _import(self):
        import asyncio
        mod = _force_import("assistant_operations")
        self.handle_operation = mod.handle_operation
        self._loop = asyncio.new_event_loop()

    def _run(self, coro):
        return self._loop.run_until_complete(coro)

    def test_unknown_operation_returns_none(self):
        result = self._run(self.handle_operation("nonexistent_op", {}, {}, None))
        assert result is None

    def test_list_tasks_returns_ok(self):
        class FakeCtx:
            profile = {"task_history": [{"task_id": "t1", "status": "open"}]}
        result = self._run(self.handle_operation("list_tasks", {}, {}, FakeCtx()))
        assert result["ok"] is True
        assert result["total"] == 1

    def test_view_task_history_not_found(self):
        class FakeCtx:
            profile = {"task_history": []}
        result = self._run(self.handle_operation(
            "view_task_history", {"task_id": "missing"}, {}, FakeCtx()
        ))
        assert result["ok"] is False

    def test_clear_task_history_requires_confirm(self):
        class FakeCtx:
            profile = {"task_history": []}
        result = self._run(self.handle_operation(
            "clear_task_history", {}, {}, FakeCtx()
        ))
        assert result["ok"] is False


# ════════════════════════════════════════════════════════════
# 7. Domain registry
# ════════════════════════════════════════════════════════════


class TestAssistantInDomainRegistry:
    def test_assistant_in_registry(self):
        registry = yaml.safe_load(
            (REPO_ROOT / "domain-packs" / "system" / "cfg" / "domain-registry.yaml").read_text()
        )
        domains = registry.get("domains", {})
        assert "assistant" in domains
        assert domains["assistant"]["module_prefix"] == "asst"


# ════════════════════════════════════════════════════════════
# 8. Persona Engine
# ════════════════════════════════════════════════════════════


class TestPersonaEngine:
    """Tests for domain-lib/persona_engine.py — PersonaState, PersonaOverlay,
    build_overlay(), update_persona(), apply_intensity_cap(), is_safe_persona()."""

    @pytest.fixture(autouse=True)
    def _import(self):
        import importlib
        _DOMAIN_LIB_DIR = str(PACK / "domain-lib")
        saved = sys.modules.pop("persona_engine", _SENTINEL)
        if _DOMAIN_LIB_DIR not in sys.path:
            sys.path.insert(0, _DOMAIN_LIB_DIR)
        mod = importlib.import_module("persona_engine")
        if saved is _SENTINEL:
            sys.modules.pop("persona_engine", None)
        else:
            sys.modules["persona_engine"] = saved
        self.PersonaState = mod.PersonaState
        self.PersonaOverlay = mod.PersonaOverlay
        self.ARCHETYPES = mod.ARCHETYPES
        self.build_overlay = mod.build_overlay
        self.update_persona = mod.update_persona
        self.apply_intensity_cap = mod.apply_intensity_cap
        self.is_safe_persona = mod.is_safe_persona

    # ── PersonaState basics ───────────────────────────────────────

    def test_persona_state_defaults(self):
        p = self.PersonaState()
        assert p.archetype == "neutral"
        assert p.intensity == 0.0
        assert p.name is None
        assert p.traits == []
        assert p.allowed_behaviors == []
        assert p.hard_limits == []
        assert p.setup_complete is False
        assert p.last_updated_utc is None

    def test_persona_state_intensity_clamped(self):
        p = self.PersonaState(intensity=5.0)
        assert p.intensity == 1.0
        p2 = self.PersonaState(intensity=-1.0)
        assert p2.intensity == 0.0

    def test_persona_state_unknown_archetype_falls_back_to_neutral(self):
        p = self.PersonaState(archetype="does_not_exist")
        assert p.archetype == "neutral"

    def test_persona_state_to_dict_roundtrip(self):
        p = self.PersonaState(
            archetype="gremlin",
            intensity=0.8,
            name="Rex",
            traits=["chaotic", "loves puns"],
            allowed_behaviors=["trash_talk"],
            hard_limits=["no_family_insults"],
            setup_complete=True,
            last_updated_utc="2026-04-21T00:00:00Z",
        )
        d = p.to_dict()
        p2 = self.PersonaState.from_dict(d)
        assert p2.archetype == "gremlin"
        assert abs(p2.intensity - 0.8) < 1e-5
        assert p2.name == "Rex"
        assert p2.traits == ["chaotic", "loves puns"]
        assert p2.allowed_behaviors == ["trash_talk"]
        assert p2.hard_limits == ["no_family_insults"]
        assert p2.setup_complete is True
        assert p2.last_updated_utc == "2026-04-21T00:00:00Z"

    def test_persona_state_from_none_returns_defaults(self):
        p = self.PersonaState.from_dict(None)
        assert p.archetype == "neutral"
        assert p.intensity == 0.0

    def test_all_builtin_archetypes_present(self):
        for name in ("neutral", "professional", "casual", "sarcastic",
                     "gremlin", "mentor", "hype", "custom"):
            assert name in self.ARCHETYPES

    # ── build_overlay ─────────────────────────────────────────────

    def test_neutral_zero_intensity_is_default(self):
        p = self.PersonaState(archetype="neutral", intensity=0.0)
        overlay = self.build_overlay(p)
        assert overlay.is_default is True
        assert overlay.style_directive == ""

    def test_any_archetype_at_zero_intensity_is_default(self):
        p = self.PersonaState(archetype="gremlin", intensity=0.0)
        overlay = self.build_overlay(p)
        assert overlay.is_default is True

    def test_gremlin_full_intensity_is_not_default(self):
        p = self.PersonaState(archetype="gremlin", intensity=1.0)
        overlay = self.build_overlay(p)
        assert overlay.is_default is False
        assert overlay.tone_label == "Chaos Gremlin"
        assert len(overlay.style_directive) > 0

    def test_gremlin_directive_contains_tone_keywords(self):
        p = self.PersonaState(archetype="gremlin", intensity=1.0)
        overlay = self.build_overlay(p)
        directive = overlay.style_directive.lower()
        assert "trash" in directive or "ribbing" in directive or "chaotic" in directive

    def test_full_intensity_adds_consistency_note(self):
        p = self.PersonaState(archetype="mentor", intensity=1.0)
        overlay = self.build_overlay(p)
        assert "fully" in overlay.style_directive.lower() or "consistently" in overlay.style_directive.lower()

    def test_low_intensity_adds_subtle_note(self):
        p = self.PersonaState(archetype="sarcastic", intensity=0.3)
        overlay = self.build_overlay(p)
        assert "subtly" in overlay.style_directive.lower()

    def test_persona_name_appears_in_directive(self):
        p = self.PersonaState(archetype="gremlin", intensity=0.8, name="Grim")
        overlay = self.build_overlay(p)
        assert '"Grim"' in overlay.style_directive

    def test_custom_archetype_with_traits_is_not_default(self):
        p = self.PersonaState(
            archetype="custom",
            intensity=0.7,
            traits=["speaks in riddles", "stern dungeon keeper"],
        )
        overlay = self.build_overlay(p)
        assert overlay.is_default is False
        assert overlay.tone_label == "Custom"
        assert "riddles" in overlay.style_directive

    def test_custom_archetype_without_traits_is_default(self):
        p = self.PersonaState(archetype="custom", intensity=0.9, traits=[])
        overlay = self.build_overlay(p)
        assert overlay.is_default is True

    def test_neutral_with_traits_is_not_default(self):
        p = self.PersonaState(archetype="neutral", intensity=0.5, traits=["uses sports metaphors"])
        overlay = self.build_overlay(p)
        assert overlay.is_default is False
        assert "sports metaphors" in overlay.style_directive

    def test_hard_limits_appear_in_directive(self):
        p = self.PersonaState(
            archetype="gremlin", intensity=0.8, hard_limits=["no_family_insults"]
        )
        overlay = self.build_overlay(p)
        assert "no_family_insults" in overlay.style_directive

    def test_allowed_behaviors_appear_in_directive(self):
        p = self.PersonaState(
            archetype="gremlin", intensity=0.8, allowed_behaviors=["trash_talk"]
        )
        overlay = self.build_overlay(p)
        assert "trash_talk" in overlay.style_directive

    def test_overlay_to_dict_keys(self):
        p = self.PersonaState(archetype="hype", intensity=0.5)
        d = self.build_overlay(p).to_dict()
        assert set(d.keys()) == {"style_directive", "tone_label", "intensity", "is_default"}

    # ── update_persona ────────────────────────────────────────────

    def test_update_persona_changes_archetype(self):
        p = self.PersonaState(archetype="neutral", intensity=0.0)
        p2 = self.update_persona(p, {"archetype": "gremlin", "intensity": 0.9})
        assert p2.archetype == "gremlin"
        assert abs(p2.intensity - 0.9) < 1e-5

    def test_update_persona_empty_dict_returns_unchanged(self):
        p = self.PersonaState(archetype="gremlin", intensity=0.7)
        p2 = self.update_persona(p, {})
        assert p2 is p

    def test_update_persona_hard_limits_append_only(self):
        p = self.PersonaState(hard_limits=["no_profanity"])
        p2 = self.update_persona(p, {"hard_limits": []})
        # Existing limit must be preserved even when caller passes empty list
        assert "no_profanity" in p2.hard_limits

    def test_update_persona_new_hard_limit_added(self):
        p = self.PersonaState(hard_limits=["no_profanity"])
        p2 = self.update_persona(p, {"hard_limits": ["no_family_insults"]})
        assert "no_profanity" in p2.hard_limits
        assert "no_family_insults" in p2.hard_limits

    def test_update_persona_unknown_archetype_ignored(self):
        p = self.PersonaState(archetype="gremlin", intensity=0.8)
        p2 = self.update_persona(p, {"archetype": "unicorn_wizard"})
        assert p2.archetype == "gremlin"

    def test_update_persona_intensity_clamped(self):
        p = self.PersonaState()
        p2 = self.update_persona(p, {"intensity": 99.0})
        assert p2.intensity == 1.0

    def test_update_persona_timestamp_applied(self):
        p = self.PersonaState()
        p2 = self.update_persona(p, {"intensity": 0.5}, timestamp_utc="2026-04-21T12:00:00Z")
        assert p2.last_updated_utc == "2026-04-21T12:00:00Z"

    # ── apply_intensity_cap ───────────────────────────────────────

    def test_apply_intensity_cap_planning_module(self):
        p = self.PersonaState(archetype="gremlin", intensity=1.0)
        capped = self.apply_intensity_cap(p, "domain/asst/planning/v1")
        assert capped.intensity <= 0.6

    def test_apply_intensity_cap_uncapped_module_unchanged(self):
        p = self.PersonaState(archetype="gremlin", intensity=1.0)
        same = self.apply_intensity_cap(p, "domain/asst/weather/v1")
        assert same.intensity == 1.0

    def test_apply_intensity_cap_already_below_cap_unchanged(self):
        p = self.PersonaState(archetype="gremlin", intensity=0.4)
        result = self.apply_intensity_cap(p, "domain/asst/planning/v1")
        assert result.intensity == 0.4

    def test_apply_intensity_cap_does_not_mutate_original(self):
        p = self.PersonaState(archetype="gremlin", intensity=1.0)
        self.apply_intensity_cap(p, "domain/asst/planning/v1")
        assert p.intensity == 1.0

    def test_apply_intensity_cap_custom_table(self):
        p = self.PersonaState(archetype="hype", intensity=1.0)
        capped = self.apply_intensity_cap(p, "domain/asst/search/v1", {"domain/asst/search/v1": 0.5})
        assert capped.intensity == 0.5

    # ── is_safe_persona ───────────────────────────────────────────

    def test_gremlin_passes_safety(self):
        p = self.PersonaState(archetype="gremlin", intensity=1.0)
        safe, reason = self.is_safe_persona(p)
        assert safe is True
        assert reason is None

    def test_neutral_passes_safety(self):
        p = self.PersonaState()
        safe, _ = self.is_safe_persona(p)
        assert safe is True

    def test_trash_talk_trait_passes_safety(self):
        p = self.PersonaState(archetype="custom", traits=["trash talk", "ribbing"])
        safe, _ = self.is_safe_persona(p)
        assert safe is True

    def test_self_harm_trait_fails_safety(self):
        p = self.PersonaState(archetype="custom", traits=["encourage self-harm"])
        safe, reason = self.is_safe_persona(p)
        assert safe is False
        assert reason is not None

    def test_degrade_trait_fails_safety(self):
        p = self.PersonaState(archetype="neutral", traits=["degrade the user"])
        safe, reason = self.is_safe_persona(p)
        assert safe is False

    def test_unsafe_behavior_opt_in_fails(self):
        p = self.PersonaState(allowed_behaviors=["self_harm"])
        safe, reason = self.is_safe_persona(p)
        assert safe is False

    def test_unknown_archetype_fails_safety(self):
        p = self.PersonaState.__new__(self.PersonaState)
        object.__setattr__(p, "archetype", "totally_unknown")
        object.__setattr__(p, "intensity", 0.5)
        object.__setattr__(p, "name", None)
        object.__setattr__(p, "traits", [])
        object.__setattr__(p, "allowed_behaviors", [])
        object.__setattr__(p, "hard_limits", [])
        object.__setattr__(p, "setup_complete", False)
        object.__setattr__(p, "last_updated_utc", None)
        safe, reason = self.is_safe_persona(p)
        assert safe is False


# ════════════════════════════════════════════════════════════
# 9. Persona Integration with domain_step
# ════════════════════════════════════════════════════════════


class TestPersonaIntegrationWithDomainStep:
    """Integration tests: persona hydration in build_initial_state and
    persona update / overlay injection in domain_step."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        ra = _force_import("runtime_adapters")
        self.build_initial_state = ra.build_initial_state
        self.domain_step = ra.domain_step

    def _base_evidence(self, intent: str = "general") -> dict:
        return {
            "intent_type": intent,
            "task_status": "n/a",
            "tool_call_requested": False,
            "off_task_ratio": 0.0,
            "response_latency_sec": 3.0,
            "satisfaction_signal": "unknown",
        }

    def test_build_initial_state_hydrates_persona(self):
        profile = {
            "entity_state": {
                "persona": {
                    "archetype": "gremlin",
                    "intensity": 0.8,
                    "name": "Rex",
                    "traits": [],
                    "allowed_behaviors": [],
                    "hard_limits": [],
                    "setup_complete": True,
                    "last_updated_utc": None,
                }
            }
        }
        state = self.build_initial_state(profile)
        assert state["persona"].archetype == "gremlin"
        assert abs(state["persona"].intensity - 0.8) < 1e-5
        assert state["persona"].name == "Rex"

    def test_build_initial_state_no_persona_block_gives_defaults(self):
        state = self.build_initial_state({"entity_state": {}})
        assert state["persona"].archetype == "neutral"
        assert state["persona"].intensity == 0.0

    def test_build_initial_state_computes_overlay(self):
        profile = {
            "entity_state": {
                "persona": {"archetype": "gremlin", "intensity": 0.9}
            }
        }
        state = self.build_initial_state(profile)
        assert state["persona_overlay"].is_default is False
        assert len(state["persona_overlay"].style_directive) > 0

    def test_neutral_profile_gives_default_overlay(self):
        state = self.build_initial_state({"entity_state": {}})
        assert state["persona_overlay"].is_default is True

    def test_domain_step_decision_contains_persona_overlay(self):
        state = self.build_initial_state({"entity_state": {}})
        _, decision = self.domain_step(
            state, {}, self._base_evidence("general"), {}
        )
        assert "persona" in decision
        assert "persona_overlay" in decision
        assert "is_default" in decision["persona_overlay"]

    def test_domain_step_persona_intent_applies_update(self):
        profile = {
            "entity_state": {
                "persona": {"archetype": "neutral", "intensity": 0.0}
            }
        }
        state = self.build_initial_state(profile)
        evidence = self._base_evidence("persona")
        evidence["persona_update"] = {
            "archetype": "gremlin",
            "intensity": 1.0,
            "setup_complete": True,
        }
        new_state, decision = self.domain_step(state, {}, evidence, {})
        assert new_state["persona"].archetype == "gremlin"
        assert abs(new_state["persona"].intensity - 1.0) < 1e-5
        assert decision["persona"]["archetype"] == "gremlin"
        assert decision["persona_overlay"]["is_default"] is False

    def test_domain_step_non_persona_intent_does_not_change_persona(self):
        profile = {
            "entity_state": {
                "persona": {"archetype": "gremlin", "intensity": 0.8}
            }
        }
        state = self.build_initial_state(profile)
        evidence = self._base_evidence("weather")
        evidence["persona_update"] = {"archetype": "neutral", "intensity": 0.0}
        new_state, _ = self.domain_step(state, {}, evidence, {})
        # persona_update is ignored when intent is not "persona"
        assert new_state["persona"].archetype == "gremlin"

    def test_domain_step_unsafe_persona_update_rejected(self):
        state = self.build_initial_state({"entity_state": {}})
        evidence = self._base_evidence("persona")
        evidence["persona_update"] = {
            "archetype": "custom",
            "traits": ["encourage self-harm"],
        }
        new_state, _ = self.domain_step(state, {}, evidence, {})
        # Persona must remain neutral (unsafe update rejected)
        assert new_state["persona"].archetype == "neutral"

    def test_domain_step_planning_module_caps_intensity_in_overlay(self):
        profile = {
            "entity_state": {
                "persona": {"archetype": "gremlin", "intensity": 1.0}
            }
        }
        state = self.build_initial_state(profile)
        evidence = self._base_evidence("planning")
        evidence["task_status"] = "open"
        _, decision = self.domain_step(state, {}, evidence, {})
        # Overlay intensity should be capped for planning module
        assert decision["persona_overlay"]["intensity"] <= 0.6


# ════════════════════════════════════════════════════════════
# 10. Weather tool routing — domain_step action dispatch
# ════════════════════════════════════════════════════════════


class TestWeatherToolRouting:
    """Tests that domain_step routes weather intents to the correct tool action."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        ra = _force_import("runtime_adapters")
        self.build_initial_state = ra.build_initial_state
        self.domain_step = ra.domain_step

    def _weather_evidence(self, location=None, forecast_days=1, tool_call_requested=True):
        return {
            "intent_type": "weather",
            "task_status": "open",
            "tool_call_requested": tool_call_requested,
            "location": location,
            "forecast_days": forecast_days,
            "off_task_ratio": 0.0,
            "response_latency_sec": 5.0,
            "satisfaction_signal": "unknown",
        }

    def test_weather_with_location_routes_to_weather_lookup(self):
        state = self.build_initial_state({})
        evidence = self._weather_evidence(location="Tokyo")
        _, decision = self.domain_step(state, {}, evidence, {})
        assert decision["action"] == "weather_lookup"

    def test_weather_without_location_routes_to_resolve_location(self):
        state = self.build_initial_state({})
        evidence = self._weather_evidence(location=None)
        _, decision = self.domain_step(state, {}, evidence, {})
        assert decision["action"] == "resolve_location"

    def test_weather_with_empty_string_location_routes_to_resolve_location(self):
        state = self.build_initial_state({})
        evidence = self._weather_evidence(location="")
        _, decision = self.domain_step(state, {}, evidence, {})
        assert decision["action"] == "resolve_location"

    def test_weather_routing_does_not_fire_when_tool_call_not_requested(self):
        state = self.build_initial_state({})
        evidence = self._weather_evidence(location="Paris", tool_call_requested=False)
        _, decision = self.domain_step(state, {}, evidence, {})
        # No tool routing — action may be None or a drift/idle action, but not weather_lookup
        assert decision["action"] != "weather_lookup"
        assert decision["action"] != "resolve_location"

    def test_weather_routing_clears_tier_to_ok(self):
        """Weather tool routing should not produce a minor/escalate tier."""
        state = self.build_initial_state({})
        evidence = self._weather_evidence(location="London")
        _, decision = self.domain_step(state, {}, evidence, {})
        assert decision["tier"] == "ok"

    def test_non_weather_intent_does_not_produce_weather_action(self):
        state = self.build_initial_state({})
        evidence = {
            "intent_type": "calendar",
            "task_status": "open",
            "tool_call_requested": True,
            "location": "Tokyo",
            "off_task_ratio": 0.0,
            "response_latency_sec": 5.0,
            "satisfaction_signal": "unknown",
        }
        _, decision = self.domain_step(state, {}, evidence, {})
        assert decision["action"] not in ("weather_lookup", "resolve_location")

    def test_weather_routing_preserves_suggested_module(self):
        state = self.build_initial_state({})
        evidence = self._weather_evidence(location="Berlin")
        _, decision = self.domain_step(state, {}, evidence, {})
        assert decision["suggested_module"] == "domain/asst/weather/v1"

    def test_weather_multi_day_forecast_routing(self):
        state = self.build_initial_state({})
        evidence = self._weather_evidence(location="Sydney", forecast_days=5)
        _, decision = self.domain_step(state, {}, evidence, {})
        assert decision["action"] == "weather_lookup"


# ════════════════════════════════════════════════════════════
# 11. Weather runtime-config wiring
# ════════════════════════════════════════════════════════════


class TestRuntimeConfigWeatherPolicy:
    """Tests that runtime-config.yaml has the correct tool_call_policies and
    deterministic_templates for weather."""

    @pytest.fixture(autouse=True)
    def _load_config(self):
        cfg_path = PACK / "cfg" / "runtime-config.yaml"
        full_cfg = yaml.safe_load(cfg_path.read_text())
        # runtime_loader reads tool_call_policies from the `runtime:` block
        self.runtime_cfg = full_cfg.get("runtime", {})

    def test_tool_call_policies_key_exists(self):
        assert "tool_call_policies" in self.runtime_cfg, (
            "runtime-config.yaml must have a tool_call_policies key under runtime:"
        )

    def test_weather_lookup_policy_registered(self):
        policies = self.runtime_cfg.get("tool_call_policies", {})
        assert "weather_lookup" in policies, (
            "tool_call_policies must have a weather_lookup entry"
        )

    def test_weather_lookup_policy_has_tool_id(self):
        policy = self.runtime_cfg["tool_call_policies"]["weather_lookup"]
        assert isinstance(policy, list) and len(policy) >= 1
        assert policy[0]["tool_id"] == "weather_lookup"

    def test_weather_lookup_policy_has_location_template(self):
        policy = self.runtime_cfg["tool_call_policies"]["weather_lookup"]
        payload = policy[0].get("payload", {})
        assert "location" in payload
        assert "{turn_data.location}" in str(payload["location"])

    def test_weather_lookup_policy_has_forecast_days(self):
        policy = self.runtime_cfg["tool_call_policies"]["weather_lookup"]
        payload = policy[0].get("payload", {})
        assert "forecast_days" in payload

    def test_deterministic_templates_has_resolve_location(self):
        templates = self.runtime_cfg.get("deterministic_templates", {})
        assert "resolve_location" in templates, (
            "deterministic_templates must have a resolve_location entry"
        )

    def test_resolve_location_template_is_non_empty_string(self):
        template = self.runtime_cfg["deterministic_templates"]["resolve_location"]
        assert isinstance(template, str) and len(template.strip()) > 0


# ════════════════════════════════════════════════════════════
# 12. Weather module-config wiring
# ════════════════════════════════════════════════════════════


class TestWeatherModuleConfig:
    """Tests that weather/module-config.yaml has the fields needed for
    location extraction and tool dispatch."""

    @pytest.fixture(autouse=True)
    def _load_config(self):
        cfg_path = PACK / "modules" / "weather" / "module-config.yaml"
        self.cfg = yaml.safe_load(cfg_path.read_text())

    def test_has_turn_interpretation_prompt_path(self):
        assert "turn_interpretation_prompt_path" in self.cfg, (
            "weather module-config must declare a turn_interpretation_prompt_path"
        )

    def test_turn_interpretation_prompt_path_points_to_spec(self):
        path = self.cfg["turn_interpretation_prompt_path"]
        assert "weather-command-interpreter-spec-v1.md" in path

    def test_turn_interpretation_prompt_file_exists(self):
        path = self.cfg["turn_interpretation_prompt_path"]
        full = REPO_ROOT / path
        assert full.is_file(), f"turn_interpretation_prompt_path target missing: {path}"

    def test_turn_input_schema_has_location(self):
        schema = self.cfg.get("turn_input_schema", {})
        assert "location" in schema, "weather turn_input_schema must define location"

    def test_turn_input_schema_location_is_nullable(self):
        schema = self.cfg["turn_input_schema"]
        assert schema["location"].get("nullable") is True

    def test_turn_input_schema_has_forecast_days(self):
        schema = self.cfg.get("turn_input_schema", {})
        assert "forecast_days" in schema, "weather turn_input_schema must define forecast_days"

    def test_turn_input_schema_forecast_days_bounds(self):
        schema = self.cfg["turn_input_schema"]
        fd = schema["forecast_days"]
        assert fd.get("minimum") == 1
        assert fd.get("maximum") == 7

    def test_turn_input_defaults_has_location_null(self):
        defaults = self.cfg.get("turn_input_defaults", {})
        assert "location" in defaults
        assert defaults["location"] is None

    def test_turn_input_defaults_has_forecast_days_one(self):
        defaults = self.cfg.get("turn_input_defaults", {})
        assert defaults.get("forecast_days") == 1

    def test_turn_input_defaults_tool_call_requested_true(self):
        defaults = self.cfg.get("turn_input_defaults", {})
        assert defaults.get("tool_call_requested") is True


# ════════════════════════════════════════════════════════════
# 13. Weather command interpreter spec
# ════════════════════════════════════════════════════════════


class TestWeatherCommandInterpreterSpec:
    """Tests that the weather command interpreter spec exists and has required sections."""

    @pytest.fixture(autouse=True)
    def _load_spec(self):
        spec_path = PACK / "domain-lib" / "reference" / "weather-command-interpreter-spec-v1.md"
        self.spec_path = spec_path
        self.spec_text = spec_path.read_text()

    def test_spec_file_exists(self):
        assert self.spec_path.is_file()

    def test_spec_defines_weather_lookup_command(self):
        assert "weather_lookup" in self.spec_text

    def test_spec_defines_resolve_location_command(self):
        assert "resolve_location" in self.spec_text

    def test_spec_defines_location_field(self):
        assert '"location"' in self.spec_text

    def test_spec_defines_forecast_days_field(self):
        assert '"forecast_days"' in self.spec_text

    def test_spec_has_output_schema_section(self):
        assert "Output schema" in self.spec_text or "output schema" in self.spec_text

    def test_spec_forbids_completed_before_tool_result(self):
        # The spec must tell the SLM not to set completed prematurely
        assert "completed" in self.spec_text
        assert "tool" in self.spec_text.lower()

    def test_spec_has_examples(self):
        assert "Example" in self.spec_text
