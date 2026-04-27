"""Tests for the multi-task turn interpreter.

Covers:
  - turn-task-graph-schema-v1.json validity and example conformance
  - nlp_preprocess intent_scores output (multi-intent detection signal)
  - interpret_multi_task_input — valid graph, fallback, degenerate single-intent
  - multi-task spec file existence
  - processing.py graph walk integration (secondary task dispatch)
  - pending_tasks carry-forward for blocked nodes
  - degenerate case: one-node graph is equivalent to single-task path
"""

from __future__ import annotations

import functools
import importlib
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
ASSISTANT_PACK = REPO_ROOT / "model-packs" / "assistant"
STANDARDS_DIR = REPO_ROOT / "standards"

# ── Load the assistant runtime_adapters module in isolation ──
_CONTROLLERS_DIR = str(ASSISTANT_PACK / "controllers")
_DOMAIN_LIB_DIR = str(ASSISTANT_PACK / "domain-lib")
for _dir in (_CONTROLLERS_DIR, _DOMAIN_LIB_DIR):
    if _dir not in sys.path:
        sys.path.insert(0, _dir)

_SENTINEL = object()


def _force_import(name: str, search_dir: str):
    """Import *name* from *search_dir*, bypassing the module cache."""
    saved = sys.modules.pop(name, _SENTINEL)
    if not sys.path or sys.path[0] != search_dir:
        sys.path.insert(0, search_dir)
    mod = importlib.import_module(name)
    mod_file = getattr(mod, "__file__", "") or ""
    if search_dir not in mod_file:
        sys.modules.pop(name, None)
        mod = importlib.import_module(name)
    if saved is _SENTINEL:
        sys.modules.pop(name, None)
    else:
        sys.modules[name] = saved
    return mod


# ════════════════════════════════════════════════════════════
# 1. Schema file structure
# ════════════════════════════════════════════════════════════

@pytest.mark.unit
class TestTurnTaskGraphSchema:
    """The turn-task-graph-schema-v1.json must exist, parse, and validate examples."""

    @pytest.fixture(autouse=True)
    def _load_schema(self):
        schema_path = STANDARDS_DIR / "turn-task-graph-schema-v1.json"
        assert schema_path.is_file(), f"Schema not found: {schema_path}"
        self.schema = json.loads(schema_path.read_text(encoding="utf-8"))

    def test_schema_has_required_root_field(self):
        assert "tasks" in self.schema.get("required", [])

    def test_schema_tasks_is_array(self):
        tasks_prop = self.schema["properties"]["tasks"]
        assert tasks_prop["type"] == "array"

    def test_schema_task_node_has_required_fields(self):
        node_schema = self.schema["properties"]["tasks"]["items"]
        required = set(node_schema.get("required", []))
        assert {"task_id", "intent", "status", "blocked_by", "turn_data"} <= required

    def test_schema_status_enum_contains_expected_values(self):
        node_schema = self.schema["properties"]["tasks"]["items"]
        status_enum = set(node_schema["properties"]["status"]["enum"])
        assert {"pending", "in_progress", "completed", "abandoned", "blocked"} <= status_enum

    def test_examples_are_valid_shape(self):
        """Each example in the schema must conform to the graph shape."""
        for example in self.schema.get("examples", []):
            assert isinstance(example.get("tasks"), list)
            assert len(example["tasks"]) >= 1
            for task in example["tasks"]:
                assert "task_id" in task
                assert "intent" in task
                assert "status" in task
                assert "blocked_by" in task
                assert "turn_data" in task

    def test_two_node_example_has_blocking_edge(self):
        two_node = next(
            (e for e in self.schema.get("examples", []) if len(e.get("tasks", [])) == 2),
            None,
        )
        assert two_node is not None, "No two-node example in schema"
        blocked_task = next(
            (t for t in two_node["tasks"] if t.get("blocked_by")), None
        )
        assert blocked_task is not None, "Two-node example should have a blocked task"
        assert blocked_task["blocked_by"] == [1]


# ════════════════════════════════════════════════════════════
# 2. Multi-task spec file existence
# ════════════════════════════════════════════════════════════

@pytest.mark.unit
class TestMultiTaskSpecFile:
    def test_spec_file_exists(self):
        spec = ASSISTANT_PACK / "domain-lib" / "reference" / "multi-task-turn-interpreter-spec-v1.md"
        assert spec.is_file(), "Multi-task turn interpreter spec not found"

    def test_spec_file_contains_task_graph_marker(self):
        spec = ASSISTANT_PACK / "domain-lib" / "reference" / "multi-task-turn-interpreter-spec-v1.md"
        content = spec.read_text(encoding="utf-8")
        assert '"tasks"' in content

    def test_runtime_config_has_multi_task_prompt_path(self):
        import yaml
        cfg_path = ASSISTANT_PACK / "cfg" / "runtime-config.yaml"
        cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
        assert "multi_task_interpretation_prompt_path" in cfg.get("runtime", {})

    def test_runtime_config_has_multi_task_adapter(self):
        import yaml
        cfg_path = ASSISTANT_PACK / "cfg" / "runtime-config.yaml"
        cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
        assert "multi_task_turn_interpreter" in cfg.get("adapters", {})


# ════════════════════════════════════════════════════════════
# 3. nlp_preprocess intent_scores
# ════════════════════════════════════════════════════════════

@pytest.mark.unit
class TestNlpPreprocessIntentScores:
    """nlp_preprocess must return intent_scores when keywords are detected."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.nlp = _force_import("nlp_pre_interpreter", _CONTROLLERS_DIR)

    def test_single_intent_has_intent_scores(self):
        result = self.nlp.nlp_preprocess("What's the weather in London?")
        assert "intent_scores" in result
        assert result["intent_scores"]["weather"] >= 1

    def test_multi_intent_scores_populated(self):
        result = self.nlp.nlp_preprocess(
            "What's the weather in Okinawa — I'm thinking of planning a trip in June."
        )
        assert "intent_scores" in result
        scores = result["intent_scores"]
        assert scores.get("weather", 0) >= 1
        assert scores.get("planning", 0) >= 1

    def test_multi_intent_detects_two_or_more_non_zero(self):
        result = self.nlp.nlp_preprocess(
            "Check the weather and search for flights to Tokyo"
        )
        scores = result.get("intent_scores", {})
        non_zero = [v for v in scores.values() if v > 0]
        assert len(non_zero) >= 2

    def test_no_intent_keywords_no_intent_scores(self):
        result = self.nlp.nlp_preprocess("Hello, how are you?")
        # No intent keywords → intent_scores key absent (or empty)
        assert result.get("intent_scores") is None or result.get("intent_scores") == {}

    def test_intent_scores_is_dict(self):
        result = self.nlp.nlp_preprocess("Write a poem and plan my week")
        assert isinstance(result.get("intent_scores"), dict)

    def test_intent_hint_still_present_with_scores(self):
        """Adding intent_scores must not remove intent_hint."""
        result = self.nlp.nlp_preprocess("What's the weather in Paris?")
        assert "intent_hint" in result
        assert result["intent_hint"] == "weather"


# ════════════════════════════════════════════════════════════
# 4. interpret_multi_task_input
# ════════════════════════════════════════════════════════════

@pytest.mark.unit
class TestInterpretMultiTaskInput:
    """Unit tests for interpret_multi_task_input in runtime_adapters."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.adapters = _force_import("runtime_adapters", _CONTROLLERS_DIR)

    def _call(self, llm_response: str, input_text: str = "test"):
        call_llm = MagicMock(return_value=llm_response)
        return self.adapters.interpret_multi_task_input(
            call_llm=call_llm,
            input_text=input_text,
            task_context={},
            prompt_text="[MULTI-TASK PROMPT]",
        )

    # ── Valid two-task graph ────────────────────────────────

    def test_two_task_graph_returned(self):
        llm_json = json.dumps({
            "tasks": [
                {
                    "task_id": 1,
                    "intent": "weather",
                    "status": "pending",
                    "blocked_by": [],
                    "turn_data": {
                        "intent_type": "weather",
                        "task_status": "open",
                        "tool_call_requested": True,
                        "location": "Okinawa",
                    },
                },
                {
                    "task_id": 2,
                    "intent": "planning",
                    "status": "pending",
                    "blocked_by": [1],
                    "turn_data": {
                        "intent_type": "planning",
                        "task_status": "open",
                        "tool_call_requested": False,
                    },
                },
            ]
        })
        result = self._call(llm_json)
        assert "tasks" in result
        assert len(result["tasks"]) == 2

    def test_primary_task_has_no_blocked_by(self):
        llm_json = json.dumps({
            "tasks": [
                {"task_id": 1, "intent": "weather", "blocked_by": [],
                 "turn_data": {"intent_type": "weather", "task_status": "open", "tool_call_requested": True}},
                {"task_id": 2, "intent": "planning", "blocked_by": [1],
                 "turn_data": {"intent_type": "planning", "task_status": "open", "tool_call_requested": False}},
            ]
        })
        result = self._call(llm_json)
        primary = result["tasks"][0]
        assert primary["blocked_by"] == []

    def test_secondary_task_blocked_by_preserved(self):
        llm_json = json.dumps({
            "tasks": [
                {"task_id": 1, "intent": "weather", "blocked_by": [],
                 "turn_data": {"intent_type": "weather", "task_status": "open", "tool_call_requested": True}},
                {"task_id": 2, "intent": "planning", "blocked_by": [1],
                 "turn_data": {"intent_type": "planning", "task_status": "open", "tool_call_requested": False}},
            ]
        })
        result = self._call(llm_json)
        assert result["tasks"][1]["blocked_by"] == [1]

    def test_all_tasks_status_is_pending(self):
        llm_json = json.dumps({
            "tasks": [
                {"task_id": 1, "intent": "weather", "blocked_by": [],
                 "turn_data": {"intent_type": "weather", "task_status": "open", "tool_call_requested": True}},
                {"task_id": 2, "intent": "planning", "blocked_by": [1],
                 "turn_data": {"intent_type": "planning", "task_status": "open", "tool_call_requested": False}},
            ]
        })
        result = self._call(llm_json)
        for task in result["tasks"]:
            assert task["status"] == "pending"

    def test_defaults_applied_to_turn_data(self):
        llm_json = json.dumps({
            "tasks": [
                {"task_id": 1, "intent": "weather", "blocked_by": [],
                 "turn_data": {"intent_type": "weather"}},
            ]
        })
        result = self._call(llm_json)
        td = result["tasks"][0]["turn_data"]
        assert "off_task_ratio" in td
        assert "satisfaction_signal" in td

    def test_invalid_intent_type_corrected_from_intent_field(self):
        llm_json = json.dumps({
            "tasks": [
                {"task_id": 1, "intent": "weather", "blocked_by": [],
                 "turn_data": {"intent_type": "BADVALUE", "task_status": "open", "tool_call_requested": False}},
            ]
        })
        result = self._call(llm_json)
        # Should fall back to the task's intent field
        assert result["tasks"][0]["turn_data"]["intent_type"] == "weather"

    def test_invalid_task_status_corrected(self):
        llm_json = json.dumps({
            "tasks": [
                {"task_id": 1, "intent": "general", "blocked_by": [],
                 "turn_data": {"intent_type": "general", "task_status": "NOTVALID", "tool_call_requested": False}},
            ]
        })
        result = self._call(llm_json)
        assert result["tasks"][0]["turn_data"]["task_status"] == "open"

    # ── Fallback paths ──────────────────────────────────────

    def test_invalid_json_falls_back_to_single_node(self):
        result = self._call("{NOT VALID JSON")
        assert "tasks" in result
        assert len(result["tasks"]) == 1
        assert result["tasks"][0]["blocked_by"] == []

    def test_flat_single_task_json_wrapped_in_one_node_graph(self):
        """SLM returns flat evidence dict → wrapped as one-node graph."""
        llm_json = json.dumps({
            "intent_type": "weather",
            "task_status": "open",
            "tool_call_requested": True,
            "off_task_ratio": 0.0,
        })
        result = self._call(llm_json)
        assert "tasks" in result
        assert len(result["tasks"]) == 1
        assert result["tasks"][0]["blocked_by"] == []
        assert result["tasks"][0]["turn_data"]["intent_type"] == "weather"

    def test_empty_tasks_array_falls_back(self):
        result = self._call(json.dumps({"tasks": []}))
        assert len(result["tasks"]) == 1

    def test_tasks_with_non_dict_items_skipped(self):
        llm_json = json.dumps({"tasks": ["not_a_dict", None]})
        result = self._call(llm_json)
        # All tasks are non-dict → fallback to single-node
        assert len(result["tasks"]) == 1

    # ── Degenerate single-intent case ───────────────────────

    def test_single_intent_graph_has_one_node(self):
        llm_json = json.dumps({
            "tasks": [
                {"task_id": 1, "intent": "weather", "blocked_by": [],
                 "turn_data": {"intent_type": "weather", "task_status": "open", "tool_call_requested": True}},
            ]
        })
        result = self._call(llm_json)
        assert len(result["tasks"]) == 1

    def test_independent_two_tasks_both_unblocked(self):
        """Write a poem AND check weather — two independent tasks, no edges."""
        llm_json = json.dumps({
            "tasks": [
                {"task_id": 1, "intent": "creative", "blocked_by": [],
                 "turn_data": {"intent_type": "creative", "task_status": "open", "tool_call_requested": False}},
                {"task_id": 2, "intent": "weather", "blocked_by": [],
                 "turn_data": {"intent_type": "weather", "task_status": "open", "tool_call_requested": True}},
            ]
        })
        result = self._call(llm_json)
        assert len(result["tasks"]) == 2
        for task in result["tasks"]:
            assert task["blocked_by"] == []


# ════════════════════════════════════════════════════════════
# 5. processing.py graph walk integration
# ════════════════════════════════════════════════════════════

@pytest.mark.unit
class TestProcessingGraphWalk:
    """Integration tests for the multi-task graph walk in processing.py."""

    def _make_orch(self, action: str = "task_presentation"):
        mock_orch = MagicMock()
        mock_orch.state = {"turn_count": 0}
        mock_orch.process_turn.return_value = (
            {"action": action, "prompt_type": action},
            action,
        )
        mock_orch.log_records = []
        mock_orch.get_standing_order_attempts.return_value = {}
        mock_orch.last_invariant_results = []
        mock_orch.last_domain_lib_decision = {}
        return mock_orch

    def _make_session(self, orch=None, module_key="domain/asst/conversation/v1"):
        if orch is None:
            orch = self._make_orch()
        return {
            "orchestrator": orch,
            "task_spec": {"task_id": "task-1"},
            "current_task": {},
            "turn_count": 0,
            "module_key": module_key,
            "session_id": "test-sess",
            "domain_id": "assistant",
            "user": {"sub": "u1"},
            "holodeck": False,
            "consent": True,
        }

    def _make_runtime(self):
        return {
            "turn_interpreter_fn": MagicMock(return_value={"intent_type": "general", "task_status": "n/a"}),
            "multi_task_turn_interpreter_fn": None,
            "nlp_pre_interpreter_fn": None,
            "turn_interpretation_prompt": "PROMPT",
            "multi_task_interpretation_prompt": None,
            "turn_input_schema": {},
            "turn_input_defaults": {
                "intent_type": "general",
                "task_status": "n/a",
                "tool_call_requested": False,
                "off_task_ratio": 0.0,
                "response_latency_sec": 5.0,
                "satisfaction_signal": "unknown",
            },
            "action_prompt_type_map": {},
            "deterministic_templates": {},
            "deterministic_templates_mud": {},
            "tool_call_policies": {},
            "slm_weight_overrides": {},
            "system_prompt": "SYS",
            "domain": {"id": "assistant", "physics": {}},
            "module_id": "assistant",
            "runtime_provenance": {},
            "state_builder_fn": MagicMock(return_value={}),
            "domain_step_fn": MagicMock(return_value=({}, {})),
            "domain_step_params": {},
            "default_task_spec": {"task_id": "task-1"},
            "pre_turn_checks": [],
            "local_only": False,
            "module_map": {},
            "tool_fns": {},
            "ui_manifest": None,
            "ui_plugin": None,
            "api_route_defs": [],
        }

    def test_secondary_task_orch_process_turn_called(self):
        """With a 2-node graph (1 primary, 1 unblocked secondary), process_turn called twice."""
        from lumina.api import processing as proc

        orch = self._make_orch()
        session = self._make_session(orch)
        runtime = self._make_runtime()

        two_task_graph = {
            "tasks": [
                {"task_id": 1, "intent": "weather", "status": "pending", "blocked_by": [],
                 "turn_data": {"intent_type": "weather", "task_status": "open", "tool_call_requested": True}},
                {"task_id": 2, "intent": "creative", "status": "pending", "blocked_by": [],
                 "turn_data": {"intent_type": "creative", "task_status": "open", "tool_call_requested": False}},
            ]
        }

        with (
            patch.object(proc, "get_or_create_session", return_value=session),
            patch.object(proc._cfg, "DOMAIN_REGISTRY", MagicMock(**{"get_runtime_context.return_value": runtime})),
            patch.object(proc._cfg, "PERSISTENCE", MagicMock()),
            patch.object(proc, "detect_glossary_query", return_value=None),
            patch.object(proc, "slm_available", return_value=False),
            patch.object(proc, "normalize_turn_data", side_effect=lambda d, _s: d),
            patch.object(proc, "interpret_turn_input", return_value=two_task_graph),
            patch.object(proc, "apply_tool_call_policy", return_value=[]),
            patch.object(proc, "build_escalation_content", return_value=(False, None)),
            patch.object(proc, "build_command_content", return_value=None),
            patch.object(proc, "assemble_llm_payload", return_value={}),
            patch.object(proc, "strip_latex_delimiters", side_effect=lambda s: s),
            patch.object(proc, "call_llm", return_value="OK"),
            patch("lumina.api.processing._session_containers", {}),
            patch("lumina.api.processing._persist_session_container"),
        ):
            proc.process_message("sess-mt", "weather poem", deterministic_response=False)

        # Two unblocked tasks → process_turn called twice (primary + secondary)
        assert orch.process_turn.call_count == 2

    def test_blocked_task_deferred_to_pending_tasks(self):
        """A task with blocked_by=[1] must be stored in orch.state['pending_tasks']."""
        from lumina.api import processing as proc

        orch = self._make_orch()
        orch.state = {"turn_count": 0}
        session = self._make_session(orch)
        runtime = self._make_runtime()

        two_task_graph_with_dep = {
            "tasks": [
                {"task_id": 1, "intent": "weather", "status": "pending", "blocked_by": [],
                 "turn_data": {"intent_type": "weather", "task_status": "open", "tool_call_requested": True}},
                {"task_id": 2, "intent": "planning", "status": "pending", "blocked_by": [1],
                 "turn_data": {"intent_type": "planning", "task_status": "open", "tool_call_requested": False}},
            ]
        }

        with (
            patch.object(proc, "get_or_create_session", return_value=session),
            patch.object(proc._cfg, "DOMAIN_REGISTRY", MagicMock(**{"get_runtime_context.return_value": runtime})),
            patch.object(proc._cfg, "PERSISTENCE", MagicMock()),
            patch.object(proc, "detect_glossary_query", return_value=None),
            patch.object(proc, "slm_available", return_value=False),
            patch.object(proc, "normalize_turn_data", side_effect=lambda d, _s: d),
            patch.object(proc, "interpret_turn_input", return_value=two_task_graph_with_dep),
            patch.object(proc, "apply_tool_call_policy", return_value=[]),
            patch.object(proc, "build_escalation_content", return_value=(False, None)),
            patch.object(proc, "build_command_content", return_value=None),
            patch.object(proc, "assemble_llm_payload", return_value={}),
            patch.object(proc, "strip_latex_delimiters", side_effect=lambda s: s),
            patch.object(proc, "call_llm", return_value="OK"),
            patch("lumina.api.processing._session_containers", {}),
            patch("lumina.api.processing._persist_session_container"),
        ):
            proc.process_message("sess-blocked", "weather trip", deterministic_response=False)

        # Primary task processed; blocked secondary deferred
        assert orch.process_turn.call_count == 1
        assert isinstance(orch.state, dict)
        pending = orch.state.get("pending_tasks") or []
        assert len(pending) == 1
        assert pending[0]["task_id"] == 2
        assert pending[0]["intent"] == "planning"

    def test_degenerate_one_node_graph_calls_process_turn_once(self):
        """A one-node graph (degenerate case) must call process_turn exactly once."""
        from lumina.api import processing as proc

        orch = self._make_orch()
        session = self._make_session(orch)
        runtime = self._make_runtime()

        one_task_graph = {
            "tasks": [
                {"task_id": 1, "intent": "weather", "status": "pending", "blocked_by": [],
                 "turn_data": {"intent_type": "weather", "task_status": "open", "tool_call_requested": True}},
            ]
        }

        with (
            patch.object(proc, "get_or_create_session", return_value=session),
            patch.object(proc._cfg, "DOMAIN_REGISTRY", MagicMock(**{"get_runtime_context.return_value": runtime})),
            patch.object(proc._cfg, "PERSISTENCE", MagicMock()),
            patch.object(proc, "detect_glossary_query", return_value=None),
            patch.object(proc, "slm_available", return_value=False),
            patch.object(proc, "normalize_turn_data", side_effect=lambda d, _s: d),
            patch.object(proc, "interpret_turn_input", return_value=one_task_graph),
            patch.object(proc, "apply_tool_call_policy", return_value=[]),
            patch.object(proc, "build_escalation_content", return_value=(False, None)),
            patch.object(proc, "build_command_content", return_value=None),
            patch.object(proc, "assemble_llm_payload", return_value={}),
            patch.object(proc, "strip_latex_delimiters", side_effect=lambda s: s),
            patch.object(proc, "call_llm", return_value="OK"),
            patch("lumina.api.processing._session_containers", {}),
            patch("lumina.api.processing._persist_session_container"),
        ):
            proc.process_message("sess-degen", "just weather", deterministic_response=False)

        assert orch.process_turn.call_count == 1

    def test_flat_turn_data_no_task_graph_still_works(self):
        """Normal single-task path (flat turn_data) must work unchanged (regression)."""
        from lumina.api import processing as proc

        orch = self._make_orch()
        session = self._make_session(orch)
        runtime = self._make_runtime()

        flat_turn_data = {
            "intent_type": "weather",
            "task_status": "open",
            "tool_call_requested": True,
        }

        with (
            patch.object(proc, "get_or_create_session", return_value=session),
            patch.object(proc._cfg, "DOMAIN_REGISTRY", MagicMock(**{"get_runtime_context.return_value": runtime})),
            patch.object(proc._cfg, "PERSISTENCE", MagicMock()),
            patch.object(proc, "detect_glossary_query", return_value=None),
            patch.object(proc, "slm_available", return_value=False),
            patch.object(proc, "normalize_turn_data", side_effect=lambda d, _s: d),
            patch.object(proc, "interpret_turn_input", return_value=flat_turn_data),
            patch.object(proc, "apply_tool_call_policy", return_value=[]),
            patch.object(proc, "build_escalation_content", return_value=(False, None)),
            patch.object(proc, "build_command_content", return_value=None),
            patch.object(proc, "assemble_llm_payload", return_value={}),
            patch.object(proc, "strip_latex_delimiters", side_effect=lambda s: s),
            patch.object(proc, "call_llm", return_value="OK"),
            patch("lumina.api.processing._session_containers", {}),
            patch("lumina.api.processing._persist_session_container"),
        ):
            result = proc.process_message("sess-flat", "weather please", deterministic_response=False)

        # Single-task path: process_turn called once, no pending_tasks
        assert orch.process_turn.call_count == 1
        assert result is not None

    def test_secondary_tool_results_aggregated(self):
        """apply_tool_call_policy called for each unblocked secondary task."""
        from lumina.api import processing as proc

        orch = self._make_orch()
        session = self._make_session(orch)
        runtime = self._make_runtime()

        two_independent_tasks = {
            "tasks": [
                {"task_id": 1, "intent": "weather", "status": "pending", "blocked_by": [],
                 "turn_data": {"intent_type": "weather", "task_status": "open", "tool_call_requested": True}},
                {"task_id": 2, "intent": "search", "status": "pending", "blocked_by": [],
                 "turn_data": {"intent_type": "search", "task_status": "open", "tool_call_requested": True}},
            ]
        }

        mock_tool_policy = MagicMock(side_effect=[
            [{"tool_id": "weather_lookup", "result": "sunny"}],
            [{"tool_id": "web_search", "result": "flights found"}],
        ])

        captured_payload: dict[str, Any] = {}

        def capture_payload(prompt_contract, *args, **kwargs):
            tool_results = args[2] if len(args) > 2 else kwargs.get("tool_results", [])
            captured_payload["tool_results"] = tool_results
            return {}

        with (
            patch.object(proc, "get_or_create_session", return_value=session),
            patch.object(proc._cfg, "DOMAIN_REGISTRY", MagicMock(**{"get_runtime_context.return_value": runtime})),
            patch.object(proc._cfg, "PERSISTENCE", MagicMock()),
            patch.object(proc, "detect_glossary_query", return_value=None),
            patch.object(proc, "slm_available", return_value=False),
            patch.object(proc, "normalize_turn_data", side_effect=lambda d, _s: d),
            patch.object(proc, "interpret_turn_input", return_value=two_independent_tasks),
            patch.object(proc, "apply_tool_call_policy", mock_tool_policy),
            patch.object(proc, "build_escalation_content", return_value=(False, None)),
            patch.object(proc, "build_command_content", return_value=None),
            patch.object(proc, "assemble_llm_payload", side_effect=capture_payload),
            patch.object(proc, "strip_latex_delimiters", side_effect=lambda s: s),
            patch.object(proc, "call_llm", return_value="OK"),
            patch("lumina.api.processing._session_containers", {}),
            patch("lumina.api.processing._persist_session_container"),
        ):
            proc.process_message("sess-agg", "weather and search", deterministic_response=False)

        # apply_tool_call_policy called twice (once per task)
        assert mock_tool_policy.call_count == 2


# ════════════════════════════════════════════════════════════
# 6. runtime_loader wires multi-task keys
# ════════════════════════════════════════════════════════════

@pytest.mark.unit
class TestRuntimeLoaderMultiTaskKeys:
    """runtime_loader.py must populate multi_task_* ctx keys."""

    def test_multi_task_keys_present_when_no_adapter(self):
        """When no multi_task_turn_interpreter adapter is configured,
        ctx keys exist with None values."""
        from lumina.core import runtime_loader

        _dummy_cfg = {
            "runtime": {
                "global_system_prompt_path": "docs/5-standards/global-system-prompt.md",
                "domain_system_prompt_path": "model-packs/assistant/prompts/domain-persona-v1.md",
                "turn_interpretation_prompt_path": "model-packs/assistant/domain-lib/reference/turn-interpretation-spec-v1.md",
                "domain_physics_path": "model-packs/assistant/modules/conversation/domain-physics.json",
                "subject_profile_path": "model-packs/assistant/profiles/entity.yaml",
            },
            "adapters": {
                "state_builder": {
                    "module_path": "model-packs/assistant/controllers/runtime_adapters.py",
                    "callable": "build_initial_state",
                },
                "domain_step": {
                    "module_path": "model-packs/assistant/controllers/runtime_adapters.py",
                    "callable": "domain_step",
                },
                "turn_interpreter": {
                    "module_path": "model-packs/assistant/controllers/runtime_adapters.py",
                    "callable": "interpret_turn_input",
                },
                # No multi_task_turn_interpreter
            },
        }

        with patch.object(runtime_loader, "load_yaml", return_value=_dummy_cfg):
            ctx = runtime_loader.load_runtime_context(REPO_ROOT, "model-packs/assistant/cfg/runtime-config.yaml")

        assert "multi_task_turn_interpreter_fn" in ctx
        assert ctx["multi_task_turn_interpreter_fn"] is None
        assert "multi_task_interpretation_prompt" in ctx


class TestProcessingWeightRouting:
    """Weight-routing: turn_interpretation path uses SLM vs LLM per slm_weight_overrides."""

    # ── Helpers ─────────────────────────────────────────────────────────────

    @staticmethod
    def _make_interpreter_runtime(weight_overrides: dict | None = None):
        """Minimal runtime for interpret_turn_input unit tests."""
        captured: dict[str, Any] = {}

        def _fake_interpreter(**kwargs: Any) -> dict[str, Any]:
            captured["call_llm"] = kwargs.get("call_llm")
            return {"intent_type": "general", "task_status": "n/a"}

        return {
            "turn_interpreter_fn": _fake_interpreter,
            "turn_interpretation_prompt": "PROMPT",
            "turn_input_defaults": {"intent_type": "general", "task_status": "n/a"},
            "tool_fns": {},
            "nlp_pre_interpreter_fn": None,
        }, captured

    @staticmethod
    def _make_proc_runtime(weight_overrides: dict | None = None):
        """Full processing.py runtime with optional slm_weight_overrides."""
        captured: dict[str, Any] = {}

        def _fake_mti(**kwargs: Any) -> dict[str, Any]:
            captured["call_llm"] = kwargs.get("call_llm")
            return {"intent_type": "weather", "task_status": "open", "tool_call_requested": False}

        return {
            "turn_interpreter_fn": MagicMock(return_value={"intent_type": "general", "task_status": "n/a"}),
            "multi_task_turn_interpreter_fn": _fake_mti,
            "nlp_pre_interpreter_fn": MagicMock(
                return_value={"intent_scores": {"weather": 0.8, "planning": 0.7}}
            ),
            "turn_interpretation_prompt": "PROMPT",
            "multi_task_interpretation_prompt": None,
            "turn_input_schema": {},
            "turn_input_defaults": {
                "intent_type": "general",
                "task_status": "n/a",
                "tool_call_requested": False,
                "off_task_ratio": 0.0,
                "response_latency_sec": 5.0,
                "satisfaction_signal": "unknown",
            },
            "action_prompt_type_map": {},
            "deterministic_templates": {},
            "deterministic_templates_mud": {},
            "tool_call_policies": {},
            "slm_weight_overrides": weight_overrides or {},
            "system_prompt": "SYS",
            "domain": {"id": "assistant", "physics": {}},
            "module_id": "assistant",
            "runtime_provenance": {},
            "state_builder_fn": MagicMock(return_value={}),
            "domain_step_fn": MagicMock(return_value=({}, {})),
            "domain_step_params": {},
            "default_task_spec": {"task_id": "task-1"},
            "pre_turn_checks": [],
            "local_only": False,
            "module_map": {},
            "tool_fns": {},
            "ui_manifest": None,
            "ui_plugin": None,
            "api_route_defs": [],
        }, captured

    # ── interpret_turn_input unit tests ─────────────────────────────────────

    def test_interpret_turn_input_uses_slm_when_override_low(self):
        """interpret_turn_input passes call_slm when override is low and SLM is available."""
        from lumina.api import runtime_helpers as rh

        runtime, captured = self._make_interpreter_runtime()
        mock_slm = MagicMock()
        mock_llm = MagicMock()

        with (
            patch.object(rh, "slm_available", return_value=True),
            patch.object(rh, "call_slm", mock_slm),
            patch.object(rh, "call_llm", mock_llm),
        ):
            rh.interpret_turn_input(
                "hello", {}, runtime,
                slm_weight_overrides={"turn_interpretation": "low"},
            )

        assert isinstance(captured["call_llm"], functools.partial)
        assert captured["call_llm"].func is mock_slm

    def test_interpret_turn_input_uses_llm_when_no_override(self):
        """interpret_turn_input passes call_llm when slm_weight_overrides is empty."""
        from lumina.api import runtime_helpers as rh

        runtime, captured = self._make_interpreter_runtime()
        mock_slm = MagicMock()
        mock_llm = MagicMock()

        with (
            patch.object(rh, "slm_available", return_value=True),
            patch.object(rh, "call_slm", mock_slm),
            patch.object(rh, "call_llm", mock_llm),
        ):
            rh.interpret_turn_input(
                "hello", {}, runtime,
                slm_weight_overrides={},
            )

        assert captured["call_llm"] is mock_llm

    def test_interpret_turn_input_falls_back_to_llm_when_slm_unavailable(self):
        """interpret_turn_input uses call_llm even with low override when SLM is unavailable."""
        from lumina.api import runtime_helpers as rh

        runtime, captured = self._make_interpreter_runtime()
        mock_slm = MagicMock()
        mock_llm = MagicMock()

        with (
            patch.object(rh, "slm_available", return_value=False),
            patch.object(rh, "call_slm", mock_slm),
            patch.object(rh, "call_llm", mock_llm),
        ):
            rh.interpret_turn_input(
                "hello", {}, runtime,
                slm_weight_overrides={"turn_interpretation": "low"},
            )

        assert captured["call_llm"] is mock_llm

    # ── Multi-task branch integration test ──────────────────────────────────

    def test_mti_branch_uses_slm_when_override_low(self):
        """Non-local_only multi-task branch passes call_slm when override is low and SLM available."""
        from lumina.api import processing as proc

        runtime, captured = self._make_proc_runtime(
            weight_overrides={"turn_interpretation": "low"}
        )
        orch = MagicMock()
        orch.state = {"turn_count": 0}
        orch.process_turn.return_value = (
            {"action": "general", "prompt_type": "general"},
            "general",
        )
        orch.log_records = []
        orch.get_standing_order_attempts.return_value = {}
        orch.last_invariant_results = []
        orch.last_domain_lib_decision = {}
        session = {
            "orchestrator": orch,
            "task_spec": {"task_id": "task-1"},
            "current_task": {},
            "turn_count": 0,
            "module_key": "domain/asst/conversation/v1",
            "session_id": "test-sess-wr",
            "domain_id": "assistant",
            "user": {"sub": "u1"},
            "holodeck": False,
            "consent": True,
        }
        mock_slm = MagicMock(return_value="OK")
        mock_llm = MagicMock(return_value="OK")

        with (
            patch.object(proc, "get_or_create_session", return_value=session),
            patch.object(proc._cfg, "DOMAIN_REGISTRY", MagicMock(**{"get_runtime_context.return_value": runtime})),
            patch.object(proc._cfg, "PERSISTENCE", MagicMock()),
            patch.object(proc, "detect_glossary_query", return_value=None),
            patch.object(proc, "slm_available", return_value=True),
            patch.object(proc, "normalize_turn_data", side_effect=lambda d, _s: d),
            patch.object(proc, "apply_tool_call_policy", return_value=[]),
            patch.object(proc, "build_escalation_content", return_value=(False, None)),
            patch.object(proc, "build_command_content", return_value=None),
            patch.object(proc, "assemble_llm_payload", return_value={}),
            patch.object(proc, "strip_latex_delimiters", side_effect=lambda s: s),
            patch.object(proc, "call_slm", mock_slm),
            patch.object(proc, "call_llm", mock_llm),
            patch("lumina.api.processing._session_containers", {}),
            patch("lumina.api.processing._persist_session_container"),
        ):
            proc.process_message("sess-wr-mti", "weather and trip plan", deterministic_response=False)

        # The _fake_mti should have received a partial wrapping call_slm, not call_llm
        assert isinstance(captured["call_llm"], functools.partial)
        assert captured["call_llm"].func is mock_slm
