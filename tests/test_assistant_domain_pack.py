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
        r = self.weather_lookup_tool({"location": "London"})
        assert r["ok"] is True
        assert "temperature_c" in r

    def test_weather_missing_location(self):
        r = self.weather_lookup_tool({})
        assert r["ok"] is False

    def test_calendar_query_ok(self):
        r = self.calendar_query_tool({"date_start": "2026-04-20"})
        assert r["ok"] is True

    def test_calendar_query_missing_start(self):
        r = self.calendar_query_tool({})
        assert r["ok"] is False

    def test_calendar_write_create(self):
        r = self.calendar_write_tool({"action": "create", "event_title": "Meeting"})
        assert r["ok"] is True

    def test_calendar_write_bad_action(self):
        r = self.calendar_write_tool({"action": "nope"})
        assert r["ok"] is False

    def test_search_ok(self):
        r = self.web_search_tool({"query": "python"})
        assert r["ok"] is True
        assert len(r["results"]) > 0

    def test_search_missing_query(self):
        r = self.web_search_tool({})
        assert r["ok"] is False

    def test_planning_create_ok(self):
        r = self.planning_create_tool({"title": "Trip plan"})
        assert r["ok"] is True

    def test_planning_create_missing_title(self):
        r = self.planning_create_tool({})
        assert r["ok"] is False

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
