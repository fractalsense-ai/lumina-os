"""Tests for command dispatch query-type promotion and NLP governance anchors.

Covers:
- _maybe_promote_query_type promotes "general" → "admin_command" for command-discovery inputs
- _maybe_promote_query_type does NOT promote non-"general" query types
- _maybe_promote_query_type does NOT promote unrelated inputs
- NLP pre-interpreter emits governance anchors for command-discovery patterns
- NLP pre-interpreter does NOT emit governance anchors for learning inputs
- System domain adapter has the same promotion logic
- End-to-end: interpret_turn_input promotes and dispatches for command-discovery inputs
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]

# ── Load education governance_adapters via importlib ──────────
_GOV_PATH = (
    _REPO_ROOT / "model-packs" / "education" / "controllers" / "governance_adapters.py"
)
_gov_spec = importlib.util.spec_from_file_location("governance_adapters", str(_GOV_PATH))
_gov_mod = importlib.util.module_from_spec(_gov_spec)  # type: ignore[arg-type]
sys.modules["governance_adapters"] = _gov_mod
_gov_spec.loader.exec_module(_gov_mod)  # type: ignore[union-attr]

_edu_maybe_promote = _gov_mod._maybe_promote_query_type
_edu_interpret_turn = _gov_mod.interpret_turn_input

# ── Load system runtime_adapters via importlib ────────────────
_SYS_PATH = (
    _REPO_ROOT / "model-packs" / "system" / "controllers" / "runtime_adapters.py"
)
_sys_spec = importlib.util.spec_from_file_location("sys_runtime_adapters", str(_SYS_PATH))
_sys_mod = importlib.util.module_from_spec(_sys_spec)  # type: ignore[arg-type]
sys.modules["sys_runtime_adapters"] = _sys_mod
_sys_spec.loader.exec_module(_sys_mod)  # type: ignore[union-attr]

_sys_maybe_promote = _sys_mod._maybe_promote_query_type

# ── Load NLP pre-interpreter via importlib ────────────────────
_NLP_PATH = (
    _REPO_ROOT / "model-packs" / "education" / "controllers" / "nlp_pre_interpreter.py"
)
_nlp_spec = importlib.util.spec_from_file_location("nlp_pre_interp", str(_NLP_PATH))
_nlp_mod = importlib.util.module_from_spec(_nlp_spec)  # type: ignore[arg-type]
sys.modules["nlp_pre_interp"] = _nlp_mod
_nlp_spec.loader.exec_module(_nlp_mod)  # type: ignore[union-attr]

_extract_gov_signals = _nlp_mod.extract_governance_signals
_nlp_preprocess = _nlp_mod.nlp_preprocess


# ─────────────────────────────────────────────────────────────
# Phase 1: Deterministic query-type promotion (education)
# ─────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestEducationQueryTypePromotion:
    """_maybe_promote_query_type must promote general → admin_command."""

    def _promote(self, evidence: dict[str, Any], input_text: str) -> dict[str, Any]:
        _edu_maybe_promote(evidence, input_text)
        return evidence

    def test_what_commands_available(self) -> None:
        ev = {"query_type": "general"}
        self._promote(ev, "what commands do I have available?")
        assert ev["query_type"] == "admin_command"
        assert ev["off_task_ratio"] == 0.0

    def test_show_me_commands(self) -> None:
        ev = {"query_type": "general"}
        self._promote(ev, "show me the commands")
        assert ev["query_type"] == "admin_command"

    def test_list_users(self) -> None:
        ev = {"query_type": "general"}
        self._promote(ev, "show me the students")
        assert ev["query_type"] == "admin_command"

    def test_list_modules(self) -> None:
        ev = {"query_type": "general"}
        self._promote(ev, "what modules are loaded?")
        assert ev["query_type"] == "admin_command"

    def test_check_escalations(self) -> None:
        ev = {"query_type": "general"}
        self._promote(ev, "check escalations")
        assert ev["query_type"] == "admin_command"

    def test_no_promotion_hello(self) -> None:
        ev = {"query_type": "general"}
        self._promote(ev, "hello, how are you?")
        assert ev["query_type"] == "general"

    def test_no_promotion_learning(self) -> None:
        ev = {"query_type": "general"}
        self._promote(ev, "what is an invariant?")
        assert ev["query_type"] == "general"

    def test_no_override_admin_command(self) -> None:
        ev = {"query_type": "admin_command"}
        self._promote(ev, "what commands do I have available?")
        assert ev["query_type"] == "admin_command"

    def test_no_override_status_query(self) -> None:
        ev = {"query_type": "status_query"}
        self._promote(ev, "show me users")
        assert ev["query_type"] == "status_query"


# ─────────────────────────────────────────────────────────────
# Phase 1b: Deterministic query-type promotion (system)
# ─────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestSystemQueryTypePromotion:
    """System domain _maybe_promote_query_type mirrors education."""

    def _promote(self, evidence: dict[str, Any], input_text: str) -> dict[str, Any]:
        _sys_maybe_promote(evidence, input_text)
        return evidence

    def test_what_commands_available(self) -> None:
        ev = {"query_type": "general"}
        self._promote(ev, "what commands do I have?")
        assert ev["query_type"] == "admin_command"

    def test_list_users(self) -> None:
        ev = {"query_type": "general"}
        self._promote(ev, "list all users")
        assert ev["query_type"] == "admin_command"

    def test_no_promotion_greeting(self) -> None:
        ev = {"query_type": "general"}
        self._promote(ev, "good morning")
        assert ev["query_type"] == "general"


# ─────────────────────────────────────────────────────────────
# Phase 2: NLP pre-interpreter governance anchors
# ─────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestNLPGovernanceAnchors:
    """extract_governance_signals emits anchors for command-discovery."""

    def _extract(self, text: str) -> dict[str, Any]:
        return _extract_gov_signals(text)

    def test_command_discovery(self) -> None:
        result = self._extract("what commands do I have available?")
        assert result["query_type"] == "admin_command"
        assert result["suggested_operation"] == "list_commands"
        assert result["off_task_ratio"] == 0.0

    def test_user_listing(self) -> None:
        result = self._extract("show me the students")
        assert result["query_type"] == "admin_command"
        assert result["suggested_operation"] == "list_users"

    def test_module_listing(self) -> None:
        result = self._extract("list modules")
        assert result["query_type"] == "admin_command"
        assert result["suggested_operation"] == "list_modules"

    def test_escalation_listing(self) -> None:
        result = self._extract("check escalations")
        assert result["query_type"] == "admin_command"
        assert result["suggested_operation"] == "list_escalations"

    def test_no_match_greeting(self) -> None:
        result = self._extract("hello there")
        assert result["query_type"] is None
        assert result["suggested_operation"] is None

    def test_no_match_math(self) -> None:
        result = self._extract("x = 4")
        assert result["query_type"] is None


@pytest.mark.unit
class TestNLPPreprocessGovernanceIntegration:
    """nlp_preprocess emits governance anchors alongside learning extractors."""

    def _preprocess(self, text: str) -> dict[str, Any]:
        return _nlp_preprocess(text, {"current_task": {}})

    def test_governance_anchor_emitted(self) -> None:
        result = self._preprocess("what commands do I have?")
        assert result.get("query_type") == "admin_command"
        assert result.get("suggested_operation") == "list_commands"
        anchors = result.get("_nlp_anchors", [])
        gov_anchors = [a for a in anchors if a["field"] == "query_type"]
        assert len(gov_anchors) == 1
        assert gov_anchors[0]["confidence"] == 0.95

    def test_learning_input_no_governance_anchor(self) -> None:
        result = self._preprocess("x = 4")
        assert result.get("query_type") is None
        anchors = result.get("_nlp_anchors", [])
        gov_anchors = [a for a in anchors if a["field"] == "query_type"]
        assert len(gov_anchors) == 0


# ─────────────────────────────────────────────────────────────
# End-to-end: interpret_turn_input dispatches commands
# ─────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestInterpretTurnInputDispatch:
    """interpret_turn_input must promote and dispatch command-discovery queries."""

    def _make_slm_response(self, query_type: str = "general") -> str:
        return json.dumps({
            "query_type": query_type,
            "target_component": None,
            "urgency": "routine",
            "response_latency_sec": 5.0,
            "off_task_ratio": 0.0,
        })

    def test_general_misclass_promoted_and_dispatched(self) -> None:
        """SLM returns 'general' for 'what commands?' → promoted → command_dispatch set."""
        call_slm = MagicMock(return_value=self._make_slm_response("general"))

        # Mock slm_parse_admin_command so the test doesn't try to reach Ollama.
        mock_slm_mod = MagicMock()
        mock_slm_mod.slm_available = MagicMock(return_value=False)
        mock_slm_mod.slm_parse_admin_command = MagicMock(return_value=None)

        with __import__("unittest.mock", fromlist=["patch"]).patch.dict(
            sys.modules, {"lumina.core.slm": mock_slm_mod}
        ):
            evidence = _edu_interpret_turn(
                call_llm=call_slm,
                input_text="what commands do I have available?",
                task_context={},
                prompt_text="You are a governance classifier.",
                call_slm=call_slm,
            )

        assert evidence["query_type"] == "admin_command"

    def test_correct_slm_classification_preserved(self) -> None:
        """SLM correctly returns 'admin_command' → no promotion needed → dispatched."""
        call_slm = MagicMock(return_value=self._make_slm_response("admin_command"))

        mock_slm_mod = MagicMock()
        mock_slm_mod.slm_available = MagicMock(return_value=False)
        mock_slm_mod.slm_parse_admin_command = MagicMock(return_value=None)

        with __import__("unittest.mock", fromlist=["patch"]).patch.dict(
            sys.modules, {"lumina.core.slm": mock_slm_mod}
        ):
            evidence = _edu_interpret_turn(
                call_llm=call_slm,
                input_text="list commands",
                task_context={},
                prompt_text="You are a governance classifier.",
                call_slm=call_slm,
            )

        assert evidence["query_type"] == "admin_command"
