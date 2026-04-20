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
        assert state["satisfaction_trend"] == []

    def test_domain_step_routes_weather(self):
        state = {"turn_count": 0, "idle_turn_count": 0, "active_intent": "general",
                 "task_history": [], "satisfaction_trend": []}
        evidence = {"intent_type": "weather", "task_status": "open",
                    "satisfaction_signal": "unknown"}
        new_state, decision = self.domain_step(state, {}, evidence, {})
        assert decision["suggested_module"] == self.INTENT_TO_MODULE["weather"]

    def test_domain_step_increments_turn_count(self):
        state = {"turn_count": 5, "idle_turn_count": 0, "active_intent": "general",
                 "task_history": [], "satisfaction_trend": []}
        evidence = {"intent_type": "general", "task_status": "continued",
                    "satisfaction_signal": "unknown"}
        new_state, _ = self.domain_step(state, {}, evidence, {})
        assert new_state["turn_count"] == 6

    def test_domain_step_tracks_idle(self):
        state = {"turn_count": 0, "idle_turn_count": 0, "active_intent": "general",
                 "task_history": [], "satisfaction_trend": []}
        evidence = {"intent_type": "general", "task_status": "n/a",
                    "satisfaction_signal": "unknown"}
        new_state, _ = self.domain_step(state, {}, evidence, {})
        assert new_state["idle_turn_count"] == 1

    def test_domain_step_completed_task_records_history(self):
        state = {"turn_count": 3, "idle_turn_count": 0, "active_intent": "weather",
                 "active_task_id": "task-w-1", "active_task_type": "weather",
                 "task_history": [], "satisfaction_trend": []}
        evidence = {"intent_type": "weather", "task_status": "completed",
                    "satisfaction_signal": "positive"}
        new_state, _ = self.domain_step(state, {}, evidence, {})
        assert new_state["active_task_id"] is None
        assert len(new_state["task_history"]) == 1


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
