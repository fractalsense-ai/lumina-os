"""Tests for lumina.core.slm — SLM compute distribution layer.

Covers task weight classification, provider dispatch, SLM availability,
glossary rendering, physics interpretation, and admin command parsing.
"""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from lumina.core.slm import (
    ADMIN_OPERATIONS,
    TaskWeight,
    _empty_physics_context,
    call_slm,
    classify_task_weight,
    slm_available,
    slm_interpret_physics_context,
    slm_parse_admin_command,
    slm_render_glossary,
)


# ── Task Weight Classification ────────────────────────────────────────────────


class TestClassifyTaskWeight:

    @pytest.mark.unit
    def test_definition_lookup_is_low(self) -> None:
        assert classify_task_weight("definition_lookup") is TaskWeight.LOW

    @pytest.mark.unit
    def test_physics_interpretation_is_low(self) -> None:
        assert classify_task_weight("physics_interpretation") is TaskWeight.LOW

    @pytest.mark.unit
    def test_state_format_is_low(self) -> None:
        assert classify_task_weight("state_format") is TaskWeight.LOW

    @pytest.mark.unit
    def test_admin_command_is_low(self) -> None:
        assert classify_task_weight("admin_command") is TaskWeight.LOW

    @pytest.mark.unit
    def test_field_validation_is_low(self) -> None:
        assert classify_task_weight("field_validation") is TaskWeight.LOW

    @pytest.mark.unit
    def test_instruction_is_high(self) -> None:
        assert classify_task_weight("instruction") is TaskWeight.HIGH

    @pytest.mark.unit
    def test_correction_is_high(self) -> None:
        assert classify_task_weight("correction") is TaskWeight.HIGH

    @pytest.mark.unit
    def test_novel_synthesis_is_high(self) -> None:
        assert classify_task_weight("novel_synthesis") is TaskWeight.HIGH

    @pytest.mark.unit
    def test_unknown_type_defaults_to_high(self) -> None:
        assert classify_task_weight("completely_unknown") is TaskWeight.HIGH

    @pytest.mark.unit
    def test_empty_string_defaults_to_high(self) -> None:
        assert classify_task_weight("") is TaskWeight.HIGH


class TestWeightOverrides:

    @pytest.mark.unit
    def test_override_high_to_low(self) -> None:
        result = classify_task_weight("instruction", overrides={"instruction": "low"})
        assert result is TaskWeight.LOW

    @pytest.mark.unit
    def test_override_low_to_high(self) -> None:
        result = classify_task_weight("definition_lookup", overrides={"definition_lookup": "high"})
        assert result is TaskWeight.HIGH

    @pytest.mark.unit
    def test_override_is_case_insensitive(self) -> None:
        result = classify_task_weight("instruction", overrides={"instruction": "LOW"})
        assert result is TaskWeight.LOW

    @pytest.mark.unit
    def test_unrelated_override_does_not_affect(self) -> None:
        result = classify_task_weight("instruction", overrides={"other_type": "low"})
        assert result is TaskWeight.HIGH

    @pytest.mark.unit
    def test_invalid_override_value_falls_through(self) -> None:
        result = classify_task_weight("definition_lookup", overrides={"definition_lookup": "invalid"})
        assert result is TaskWeight.LOW  # falls through to built-in


# ── SLM Availability ─────────────────────────────────────────────────────────


class TestSlmAvailable:

    @pytest.mark.unit
    @patch("lumina.core.slm.SLM_PROVIDER", "local")
    @patch("lumina.core.slm.SLM_ENDPOINT", "http://localhost:11434")
    def test_local_available_when_probe_succeeds(self) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        with patch("httpx.get", return_value=mock_resp):
            assert slm_available() is True

    @pytest.mark.unit
    @patch("lumina.core.slm.SLM_PROVIDER", "local")
    def test_local_unavailable_when_probe_fails(self) -> None:
        with patch("httpx.get", side_effect=ConnectionError("refused")):
            assert slm_available() is False

    @pytest.mark.unit
    @patch("lumina.core.slm.SLM_PROVIDER", "openai")
    def test_openai_available_when_key_set(self) -> None:
        with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}):
            assert slm_available() is True

    @pytest.mark.unit
    @patch("lumina.core.slm.SLM_PROVIDER", "openai")
    def test_openai_unavailable_when_no_key(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            assert slm_available() is False

    @pytest.mark.unit
    @patch("lumina.core.slm.SLM_PROVIDER", "anthropic")
    def test_anthropic_available_when_key_set(self) -> None:
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
            assert slm_available() is True

    @pytest.mark.unit
    @patch("lumina.core.slm.SLM_PROVIDER", "anthropic")
    def test_anthropic_unavailable_when_no_key(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            assert slm_available() is False


# ── call_slm Provider Dispatch ────────────────────────────────────────────────


class TestCallSlm:

    @pytest.mark.unit
    @patch("lumina.core.slm.SLM_PROVIDER", "local")
    @patch("lumina.core.slm._call_local_slm", return_value="local response")
    @patch("lumina.core.slm._validate_slm_provider")
    def test_local_dispatch(self, _validate: Any, mock_local: MagicMock) -> None:
        result = call_slm("system prompt", "user message")
        assert result == "local response"
        mock_local.assert_called_once_with("system prompt", "user message", None)

    @pytest.mark.unit
    @patch("lumina.core.slm.SLM_PROVIDER", "openai")
    @patch("lumina.core.slm._call_openai_slm", return_value="openai response")
    @patch("lumina.core.slm._validate_slm_provider")
    def test_openai_dispatch(self, _validate: Any, mock_openai: MagicMock) -> None:
        result = call_slm("system prompt", "user message")
        assert result == "openai response"
        mock_openai.assert_called_once_with("system prompt", "user message", None)

    @pytest.mark.unit
    @patch("lumina.core.slm.SLM_PROVIDER", "anthropic")
    @patch("lumina.core.slm._call_anthropic_slm", return_value="anthropic response")
    @patch("lumina.core.slm._validate_slm_provider")
    def test_anthropic_dispatch(self, _validate: Any, mock_anthropic: MagicMock) -> None:
        result = call_slm("system prompt", "user message")
        assert result == "anthropic response"
        mock_anthropic.assert_called_once_with("system prompt", "user message", None)

    @pytest.mark.unit
    @patch("lumina.core.slm.SLM_PROVIDER", "local")
    @patch("lumina.core.slm._call_local_slm", return_value="model response")
    @patch("lumina.core.slm._validate_slm_provider")
    def test_custom_model_passed_through(self, _validate: Any, mock_local: MagicMock) -> None:
        call_slm("sys", "usr", model="custom-model")
        mock_local.assert_called_once_with("sys", "usr", "custom-model")


# ── Provider Validation ──────────────────────────────────────────────────────


class TestProviderValidation:

    @pytest.mark.unit
    def test_openai_raises_without_key(self) -> None:
        from lumina.core.slm import _validate_slm_provider

        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
                _validate_slm_provider("openai")

    @pytest.mark.unit
    def test_anthropic_raises_without_key(self) -> None:
        from lumina.core.slm import _validate_slm_provider

        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
                _validate_slm_provider("anthropic")

    @pytest.mark.unit
    def test_local_does_not_raise(self) -> None:
        from lumina.core.slm import _validate_slm_provider

        _validate_slm_provider("local")  # Should not raise


# ── Glossary Rendering ────────────────────────────────────────────────────────


class TestSlmRenderGlossary:

    @pytest.mark.unit
    @patch("lumina.core.slm.call_slm", return_value="A coefficient is the number multiplied by a variable.")
    def test_renders_glossary_entry(self, mock_call: MagicMock) -> None:
        entry = {
            "term": "coefficient",
            "definition": "The number multiplied by a variable.",
            "aliases": ["coefficients"],
            "related_terms": ["variable"],
            "example_in_context": "In 4x = 28, the coefficient is 4.",
        }
        result = slm_render_glossary(entry)
        assert "coefficient" in result.lower()
        mock_call.assert_called_once()
        # Verify the system prompt is the librarian prompt
        args = mock_call.call_args
        assert "librarian" in args[1]["system"].lower() or "librarian" in args[0][0].lower()


# ── Physics Interpretation ────────────────────────────────────────────────────


class TestPhysicsInterpretation:

    @pytest.mark.unit
    @patch("lumina.core.slm.call_slm")
    def test_returns_structured_context(self, mock_call: MagicMock) -> None:
        mock_call.return_value = json.dumps({
            "matched_invariants": ["moisture_deficit"],
            "relevant_glossary_terms": ["irrigation"],
            "context_summary": "Soil moisture below threshold.",
            "suggested_evidence_fields": {"deficit_severity": "moderate"},
        })
        result = slm_interpret_physics_context(
            incoming_signals={"moisture_pct": 12},
            domain_physics={"invariants": [{"id": "moisture_deficit", "check": "moisture_pct < 20", "severity": "warning"}]},
            glossary=[{"term": "irrigation"}],
        )
        assert result["matched_invariants"] == ["moisture_deficit"]
        assert result["relevant_glossary_terms"] == ["irrigation"]
        assert result["context_summary"] == "Soil moisture below threshold."
        assert result["suggested_evidence_fields"] == {"deficit_severity": "moderate"}

    @pytest.mark.unit
    @patch("lumina.core.slm.call_slm")
    def test_handles_markdown_fenced_json(self, mock_call: MagicMock) -> None:
        mock_call.return_value = '```json\n{"matched_invariants": [], "relevant_glossary_terms": [], "context_summary": "clean", "suggested_evidence_fields": {}}\n```'
        result = slm_interpret_physics_context(
            incoming_signals={},
            domain_physics={"invariants": []},
        )
        assert result["context_summary"] == "clean"

    @pytest.mark.unit
    @patch("lumina.core.slm.call_slm", side_effect=RuntimeError("SLM down"))
    def test_fallback_on_slm_failure(self, mock_call: MagicMock) -> None:
        result = slm_interpret_physics_context(
            incoming_signals={"sensor": 42},
            domain_physics={"invariants": []},
        )
        assert result == _empty_physics_context()

    @pytest.mark.unit
    @patch("lumina.core.slm.call_slm", return_value="not json at all")
    def test_fallback_on_invalid_json(self, mock_call: MagicMock) -> None:
        result = slm_interpret_physics_context(
            incoming_signals={},
            domain_physics={},
        )
        assert result == _empty_physics_context()

    @pytest.mark.unit
    @patch("lumina.core.slm.call_slm", return_value='"just a string"')
    def test_fallback_on_non_dict_json(self, mock_call: MagicMock) -> None:
        result = slm_interpret_physics_context(
            incoming_signals={},
            domain_physics={},
        )
        assert result == _empty_physics_context()


# ── Admin Command Parsing ─────────────────────────────────────────────────────


class TestAdminCommandParsing:

    @pytest.mark.unit
    @patch("lumina.core.slm.call_slm")
    def test_parses_update_physics_command(self, mock_call: MagicMock) -> None:
        mock_call.return_value = json.dumps({
            "operation": "update_domain_physics",
            "target": "algebra",
            "params": {"updates": {"coefficient_threshold": 0.8}},
        })
        result = slm_parse_admin_command("update the coefficient threshold in algebra to 0.8")
        assert result is not None
        assert result["operation"] == "update_domain_physics"
        assert result["target"] == "algebra"
        assert result["params"]["updates"]["coefficient_threshold"] == 0.8

    @pytest.mark.unit
    @patch("lumina.core.slm.call_slm", return_value="null")
    def test_returns_none_for_unparseable(self, mock_call: MagicMock) -> None:
        result = slm_parse_admin_command("what's the weather?")
        assert result is None

    @pytest.mark.unit
    @patch("lumina.core.slm.call_slm", return_value="none")
    def test_returns_none_for_none_string(self, mock_call: MagicMock) -> None:
        result = slm_parse_admin_command("random text")
        assert result is None

    @pytest.mark.unit
    @patch("lumina.core.slm.call_slm", return_value="not json")
    def test_returns_none_for_invalid_json(self, mock_call: MagicMock) -> None:
        result = slm_parse_admin_command("do something")
        assert result is None

    @pytest.mark.unit
    @patch("lumina.core.slm.call_slm", return_value='{"no_operation": true}')
    def test_returns_none_when_no_operation_key(self, mock_call: MagicMock) -> None:
        result = slm_parse_admin_command("do something")
        assert result is None

    @pytest.mark.unit
    @patch("lumina.core.slm.call_slm", side_effect=RuntimeError("SLM error"))
    def test_returns_none_on_slm_failure(self, mock_call: MagicMock) -> None:
        result = slm_parse_admin_command("update something")
        assert result is None

    @pytest.mark.unit
    @patch("lumina.core.slm.call_slm")
    def test_handles_markdown_fenced_json(self, mock_call: MagicMock) -> None:
        mock_call.return_value = '```json\n{"operation": "deactivate_user", "target": "user123", "params": {}}\n```'
        result = slm_parse_admin_command("deactivate user123")
        assert result is not None
        assert result["operation"] == "deactivate_user"
        assert result["target"] == "user123"

    @pytest.mark.unit
    def test_admin_operations_list_contains_expected(self) -> None:
        op_names = [op["name"] for op in ADMIN_OPERATIONS]
        assert "update_domain_physics" in op_names
        assert "commit_domain_physics" in op_names
        assert "update_user_role" in op_names
        assert "deactivate_user" in op_names
        assert "resolve_escalation" in op_names

    @pytest.mark.unit
    @patch("lumina.core.slm.call_slm")
    def test_custom_operations_list_used(self, mock_call: MagicMock) -> None:
        mock_call.return_value = json.dumps({"operation": "custom_op", "target": "t", "params": {}})
        custom_ops = [{"name": "custom_op", "description": "Custom", "params_schema": {}}]
        result = slm_parse_admin_command("do custom", available_operations=custom_ops)
        assert result is not None
        assert result["operation"] == "custom_op"
        # Verify the custom ops were sent in the payload
        call_args = mock_call.call_args
        user_payload = call_args[1].get("user") or call_args[0][1]
        parsed = json.loads(user_payload)
        assert parsed["available_operations"] == custom_ops


# ── Empty Physics Context ─────────────────────────────────────────────────────


class TestEmptyPhysicsContext:

    @pytest.mark.unit
    def test_structure(self) -> None:
        ctx = _empty_physics_context()
        assert ctx["matched_invariants"] == []
        assert ctx["relevant_glossary_terms"] == []
        assert ctx["context_summary"] == ""
        assert ctx["suggested_evidence_fields"] == {}
