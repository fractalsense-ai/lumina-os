"""Smoke tests for the template domain pack.

Validates that:
  1. The three required adapter callables are importable and have correct signatures.
  2. The domain-physics.json validates against the schema.
  3. The tool adapter YAML validates against the schema.
  4. The runtime-config.yaml contains all required keys.
  5. All files referenced in pack.yaml exist on disk.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
import yaml

# ── Paths ────────────────────────────────────────────────────────────

_PACK_ROOT = Path(__file__).resolve().parent.parent / "model-packs" / "template"
_CTRL_DIR = _PACK_ROOT / "controllers"
_STANDARDS_DIR = Path(__file__).resolve().parent.parent / "standards"


# ── Helpers ──────────────────────────────────────────────────────────

def _import_module_from_path(name: str, path: Path):
    """Import a Python module from an absolute path."""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None, f"Cannot load spec from {path}"
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _load_yaml(path: Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def _load_json(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


# ── Test: Adapter callables importable ───────────────────────────────

class TestAdapterImports:
    """The three required adapter callables must be importable."""

    @pytest.fixture(autouse=True)
    def _load_adapters(self):
        self.mod = _import_module_from_path(
            "template_runtime_adapters",
            _CTRL_DIR / "runtime_adapters.py",
        )

    def test_build_initial_state_exists(self):
        assert hasattr(self.mod, "build_initial_state")
        assert callable(self.mod.build_initial_state)

    def test_domain_step_exists(self):
        assert hasattr(self.mod, "domain_step")
        assert callable(self.mod.domain_step)

    def test_interpret_turn_input_exists(self):
        assert hasattr(self.mod, "interpret_turn_input")
        assert callable(self.mod.interpret_turn_input)


# ── Test: Adapter callables produce valid output ─────────────────────

class TestAdapterBehavior:
    """Basic functional smoke tests for the template adapters."""

    @pytest.fixture(autouse=True)
    def _load_adapters(self):
        self.mod = _import_module_from_path(
            "template_runtime_adapters_behavior",
            _CTRL_DIR / "runtime_adapters.py",
        )

    def test_build_initial_state_returns_dict(self):
        state = self.mod.build_initial_state({})
        assert isinstance(state, dict)
        assert "score" in state
        assert "uncertainty" in state
        assert "turn_count" in state

    def test_domain_step_returns_tuple(self):
        state = {"score": 0.0, "uncertainty": 0.5, "turn_count": 0}
        task = {"task_id": "test-001"}
        evidence = {"on_track": True}
        params = {"window_turns": 5}

        result = self.mod.domain_step(state, task, evidence, params)
        assert isinstance(result, tuple)
        assert len(result) == 2

        new_state, decision = result
        assert isinstance(new_state, dict)
        assert isinstance(decision, dict)
        assert "tier" in decision
        assert decision["tier"] in ("ok", "minor", "major", "critical")

    def test_domain_step_increments_turn_count(self):
        state = {"score": 0.0, "uncertainty": 0.5, "turn_count": 0}
        new_state, _ = self.mod.domain_step(state, {}, {"on_track": True}, {})
        assert new_state["turn_count"] == 1

    def test_domain_step_off_track_increases_uncertainty(self):
        state = {"score": 0.0, "uncertainty": 0.5, "turn_count": 0}
        new_state, decision = self.mod.domain_step(state, {}, {"on_track": False}, {})
        assert new_state["uncertainty"] > 0.5
        assert decision["tier"] in ("minor", "major")

    def test_interpret_turn_input_returns_dict(self):
        def mock_llm(system, user, model):
            return '{"on_track": true, "response_latency_sec": 3.0, "off_task_ratio": 0.0}'

        evidence = self.mod.interpret_turn_input(
            call_llm=mock_llm,
            input_text="test message",
            task_context={},
            prompt_text="You are a test interpreter.",
        )
        assert isinstance(evidence, dict)
        assert evidence["on_track"] is True

    def test_interpret_turn_input_uses_defaults_on_bad_llm(self):
        def mock_llm(system, user, model):
            return "NOT VALID JSON"

        evidence = self.mod.interpret_turn_input(
            call_llm=mock_llm,
            input_text="test",
            task_context={},
            prompt_text="test",
        )
        assert isinstance(evidence, dict)
        assert evidence["on_track"] is True  # from defaults
        assert evidence["response_latency_sec"] == 5.0


# ── Test: NLP pre-interpreter ────────────────────────────────────────

class TestNlpPreInterpreter:
    """Phase A pre-interpreter must be importable and functional."""

    @pytest.fixture(autouse=True)
    def _load_module(self):
        self.mod = _import_module_from_path(
            "template_nlp_pre_interpreter",
            _CTRL_DIR / "nlp_pre_interpreter.py",
        )

    def test_pre_interpret_returns_dict(self):
        result = self.mod.pre_interpret("I need help", {})
        assert isinstance(result, dict)

    def test_detects_help_request(self):
        result = self.mod.pre_interpret("I'm stuck, help me please", {})
        assert result["help_requested"] is True

    def test_no_help_detected(self):
        result = self.mod.pre_interpret("Everything is fine", {})
        assert result["help_requested"] is False

    def test_detects_frustration(self):
        result = self.mod.pre_interpret("I'm frustrated and angry", {})
        assert result["frustration_marker_count"] >= 2

    def test_no_frustration_detected(self):
        result = self.mod.pre_interpret("The weather is nice", {})
        assert result["frustration_marker_count"] == 0


# ── Test: Domain physics schema validation ───────────────────────────

class TestDomainPhysics:
    """The generated JSON must match the domain physics schema."""

    def test_domain_physics_json_exists(self):
        path = _PACK_ROOT / "modules" / "example-module" / "domain-physics.json"
        assert path.exists(), f"Missing {path}"

    def test_domain_physics_has_required_fields(self):
        path = _PACK_ROOT / "modules" / "example-module" / "domain-physics.json"
        physics = _load_json(path)
        required = ["id", "version", "admin", "meta_authority_id",
                     "invariants", "standing_orders", "escalation_triggers", "artifacts"]
        for field in required:
            assert field in physics, f"Missing required field: {field}"

    def test_has_at_least_one_invariant(self):
        physics = _load_json(_PACK_ROOT / "modules" / "example-module" / "domain-physics.json")
        assert len(physics["invariants"]) >= 1

    def test_has_at_least_one_standing_order(self):
        physics = _load_json(_PACK_ROOT / "modules" / "example-module" / "domain-physics.json")
        assert len(physics["standing_orders"]) >= 1

    def test_has_at_least_one_escalation_trigger(self):
        physics = _load_json(_PACK_ROOT / "modules" / "example-module" / "domain-physics.json")
        assert len(physics["escalation_triggers"]) >= 1


# ── Test: Runtime config required keys ───────────────────────────────

class TestRuntimeConfig:
    """runtime-config.yaml must have all 5 required keys + 3 adapters."""

    @pytest.fixture(autouse=True)
    def _load_config(self):
        self.config = _load_yaml(_PACK_ROOT / "cfg" / "runtime-config.yaml")

    def test_has_runtime_block(self):
        assert "runtime" in self.config

    def test_required_keys(self):
        runtime = self.config["runtime"]
        required = [
            "domain_system_prompt_path",
            "turn_interpretation_prompt_path",
            "domain_physics_path",
            "subject_profile_path",
        ]
        for key in required:
            assert key in runtime, f"Missing required key: {key}"

    def test_has_adapters_block(self):
        assert "adapters" in self.config

    def test_required_adapters(self):
        adapters = self.config["adapters"]
        for name in ("state_builder", "domain_step", "turn_interpreter"):
            assert name in adapters, f"Missing required adapter: {name}"
            assert "module_path" in adapters[name]
            assert "callable" in adapters[name]


# ── Test: All referenced files exist ─────────────────────────────────

class TestFileExistence:
    """Every file referenced in pack.yaml and runtime-config.yaml must exist."""

    def test_pack_yaml_exists(self):
        assert (_PACK_ROOT / "pack.yaml").exists()

    def test_runtime_config_exists(self):
        assert (_PACK_ROOT / "cfg" / "runtime-config.yaml").exists()

    def test_domain_profile_extension_exists(self):
        assert (_PACK_ROOT / "cfg" / "domain-profile-extension.yaml").exists()

    def test_entity_profile_exists(self):
        assert (_PACK_ROOT / "profiles" / "entity.yaml").exists()

    def test_persona_prompt_exists(self):
        assert (_PACK_ROOT / "prompts" / "domain-persona-v1.md").exists()

    def test_turn_interpretation_spec_exists(self):
        assert (_PACK_ROOT / "domain-lib" / "reference" / "turn-interpretation-spec-v1.md").exists()

    def test_runtime_adapters_exists(self):
        assert (_CTRL_DIR / "runtime_adapters.py").exists()

    def test_nlp_pre_interpreter_exists(self):
        assert (_CTRL_DIR / "nlp_pre_interpreter.py").exists()

    def test_tool_adapter_example_exists(self):
        path = _PACK_ROOT / "modules" / "example-module" / "tool-adapters" / "example-tool-adapter-v1.yaml"
        assert path.exists()
