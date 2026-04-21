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
    SLM_COMMAND_MAX_TOKENS,
    SLM_PHYSICS_MAX_TOKENS,
    TaskWeight,
    _compact_operations,
    _empty_physics_context,
    call_slm,
    classify_task_weight,
    slm_available,
    slm_interpret_physics_context,
    slm_parse_admin_command,
    slm_render_glossary,
    SLM_TIMEOUT,
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

    @pytest.mark.unit
    def test_system_command_defaults_to_high(self) -> None:
        # system_command is a system-domain type; without slm_weight_overrides from
        # the domain runtime-config it falls through to HIGH (the safe default).
        assert classify_task_weight("system_command") is TaskWeight.HIGH

    @pytest.mark.unit
    def test_system_status_defaults_to_high(self) -> None:
        # system_status is a system-domain type; without overrides it is HIGH.
        assert classify_task_weight("system_status") is TaskWeight.HIGH


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
        mock_local.assert_called_once_with("system prompt", "user message", None, max_tokens=None)

    @pytest.mark.unit
    @patch("lumina.core.slm.SLM_PROVIDER", "openai")
    @patch("lumina.core.slm._call_openai_slm", return_value="openai response")
    @patch("lumina.core.slm._validate_slm_provider")
    def test_openai_dispatch(self, _validate: Any, mock_openai: MagicMock) -> None:
        result = call_slm("system prompt", "user message")
        assert result == "openai response"
        mock_openai.assert_called_once_with("system prompt", "user message", None, max_tokens=None)

    @pytest.mark.unit
    @patch("lumina.core.slm.SLM_PROVIDER", "anthropic")
    @patch("lumina.core.slm._call_anthropic_slm", return_value="anthropic response")
    @patch("lumina.core.slm._validate_slm_provider")
    def test_anthropic_dispatch(self, _validate: Any, mock_anthropic: MagicMock) -> None:
        result = call_slm("system prompt", "user message")
        assert result == "anthropic response"
        mock_anthropic.assert_called_once_with("system prompt", "user message", None, max_tokens=None)

    @pytest.mark.unit
    @patch("lumina.core.slm.SLM_PROVIDER", "local")
    @patch("lumina.core.slm._call_local_slm", return_value="model response")
    @patch("lumina.core.slm._validate_slm_provider")
    def test_custom_model_passed_through(self, _validate: Any, mock_local: MagicMock) -> None:
        call_slm("sys", "usr", model="custom-model")
        mock_local.assert_called_once_with("sys", "usr", "custom-model", max_tokens=None)

    @pytest.mark.unit
    @patch("lumina.core.slm.SLM_PROVIDER", "local")
    @patch("lumina.core.slm._call_local_slm", return_value="response")
    @patch("lumina.core.slm._validate_slm_provider")
    def test_max_tokens_forwarded_to_local(self, _validate: Any, mock_local: MagicMock) -> None:
        """max_tokens kwarg must be threaded through to the provider function."""
        call_slm("sys", "usr", max_tokens=2048)
        mock_local.assert_called_once_with("sys", "usr", None, max_tokens=2048)


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
            "applicable_standing_orders": ["irrigate_on_deficit"],
            "relevant_glossary_terms": ["irrigation"],
            "context_summary": "Soil moisture below threshold.",
            "suggested_evidence_fields": {"deficit_severity": "moderate"},
        })
        result = slm_interpret_physics_context(
            incoming_signals={"moisture_pct": 12},
            domain_physics={
                "invariants": [{"id": "moisture_deficit", "check": "moisture_pct < 20",
                                 "severity": "warning", "description": "Soil moisture low",
                                 "standing_order_on_violation": "irrigate_on_deficit"}],
                "standing_orders": [{"id": "irrigate_on_deficit", "action": "schedule_irrigation",
                                      "description": "Trigger irrigation cycle",
                                      "trigger_condition": "moisture_pct < 20",
                                      "max_attempts": 3, "escalation_on_exhaust": True}],
            },
            glossary=[{"term": "irrigation"}],
        )
        assert result["matched_invariants"] == ["moisture_deficit"]
        assert result["applicable_standing_orders"] == ["irrigate_on_deficit"]
        assert result["relevant_glossary_terms"] == ["irrigation"]
        assert result["context_summary"] == "Soil moisture below threshold."
        assert result["suggested_evidence_fields"] == {"deficit_severity": "moderate"}

    @pytest.mark.unit
    @patch("lumina.core.slm.call_slm")
    def test_handles_markdown_fenced_json(self, mock_call: MagicMock) -> None:
        mock_call.return_value = '```json\n{"matched_invariants": [], "applicable_standing_orders": [], "relevant_glossary_terms": [], "context_summary": "clean", "suggested_evidence_fields": {}}\n```'
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
    @patch("lumina.core.slm.call_slm")
    def test_enriched_invariants_sent_to_slm(self, mock_call: MagicMock) -> None:
        """Verify that description and standing_order_on_violation reach the SLM payload."""
        mock_call.return_value = json.dumps({
            "matched_invariants": [], "applicable_standing_orders": [],
            "relevant_glossary_terms": [], "context_summary": "",
            "suggested_evidence_fields": {},
        })
        slm_interpret_physics_context(
            incoming_signals={"val": 1},
            domain_physics={
                "invariants": [{
                    "id": "inv1",
                    "description": "Value too high",
                    "severity": "critical",
                    "check": "val > 100",
                    "standing_order_on_violation": "so1",
                    "handled_by": "safety_module",
                }],
                "standing_orders": [{
                    "id": "so1",
                    "action": "shutdown",
                    "description": "Emergency shutdown",
                    "trigger_condition": "val > 100",
                    "max_attempts": 1,
                    "escalation_on_exhaust": True,
                }],
            },
        )
        call_args = mock_call.call_args
        user_payload = json.loads(call_args[1].get("user") or call_args[0][1])
        physics = user_payload["domain_physics"]
        inv = physics["invariants"][0]
        assert inv["description"] == "Value too high"
        assert inv["standing_order_on_violation"] == "so1"
        assert inv["handled_by"] == "safety_module"
        so = physics["standing_orders"][0]
        assert so["action"] == "shutdown"
        assert so["max_attempts"] == 1
        assert so["escalation_on_exhaust"] is True

    @pytest.mark.unit
    @patch("lumina.core.slm.call_slm")
    def test_escalation_triggers_sent_to_slm(self, mock_call: MagicMock) -> None:
        """Verify escalation_triggers block is included in the SLM payload."""
        mock_call.return_value = json.dumps({
            "matched_invariants": [], "applicable_standing_orders": [],
            "relevant_glossary_terms": [], "context_summary": "",
            "suggested_evidence_fields": {},
        })
        slm_interpret_physics_context(
            incoming_signals={},
            domain_physics={
                "escalation_triggers": [{
                    "id": "et1",
                    "condition": "attempts_exhausted",
                    "target_role": "admin",
                }],
            },
        )
        call_args = mock_call.call_args
        user_payload = json.loads(call_args[1].get("user") or call_args[0][1])
        triggers = user_payload["domain_physics"]["escalation_triggers"]
        assert len(triggers) == 1
        assert triggers[0]["id"] == "et1"
        assert triggers[0]["target_role"] == "admin"

    @pytest.mark.unit
    @patch("lumina.core.slm.call_slm")
    def test_applicable_standing_orders_returned(self, mock_call: MagicMock) -> None:
        """applicable_standing_orders from SLM output is propagated in result."""
        mock_call.return_value = json.dumps({
            "matched_invariants": ["inv1"],
            "applicable_standing_orders": ["so1", "so2"],
            "relevant_glossary_terms": [],
            "context_summary": "Two orders apply.",
            "suggested_evidence_fields": {},
        })
        result = slm_interpret_physics_context(
            incoming_signals={"x": 5},
            domain_physics={},
        )
        assert result["applicable_standing_orders"] == ["so1", "so2"]

    @pytest.mark.unit
    @patch("lumina.core.slm.call_slm")
    def test_missing_applicable_standing_orders_defaults_to_empty(self, mock_call: MagicMock) -> None:
        """If SLM omits applicable_standing_orders, result defaults to []."""
        mock_call.return_value = json.dumps({
            "matched_invariants": [],
            "relevant_glossary_terms": [],
            "context_summary": "",
            "suggested_evidence_fields": {},
        })
        result = slm_interpret_physics_context(
            incoming_signals={},
            domain_physics={},
        )
        assert result["applicable_standing_orders"] == []

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

    @pytest.mark.unit
    @patch("lumina.core.slm.call_slm", return_value='{"matched_invariants": ["inv1"],')
    def test_fallback_on_truncated_json(self, mock_call: MagicMock) -> None:
        """Truncated JSON (e.g. from SLM hitting max_tokens) returns empty context."""
        result = slm_interpret_physics_context(
            incoming_signals={},
            domain_physics={},
        )
        assert result == _empty_physics_context()

    @pytest.mark.unit
    @patch("lumina.core.slm.call_slm")
    def test_physics_interpretation_uses_extended_token_budget(self, mock_call: MagicMock) -> None:
        """slm_interpret_physics_context must pass SLM_PHYSICS_MAX_TOKENS, not SLM_MAX_TOKENS."""
        mock_call.return_value = json.dumps({
            "matched_invariants": [],
            "applicable_standing_orders": [],
            "relevant_glossary_terms": [],
            "context_summary": "",
            "suggested_evidence_fields": {},
        })
        slm_interpret_physics_context(incoming_signals={}, domain_physics={})
        call_kwargs = mock_call.call_args[1]
        assert call_kwargs.get("max_tokens") == SLM_PHYSICS_MAX_TOKENS, (
            f"Expected max_tokens={SLM_PHYSICS_MAX_TOKENS}, got {call_kwargs.get('max_tokens')}"
        )


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
    def test_update_user_role_has_governed_modules(self) -> None:
        """update_user_role must advertise governed_modules so DA promotions\n        carry domain scope in a single operation."""
        op = next(o for o in ADMIN_OPERATIONS if o["name"] == "update_user_role")
        assert "governed_modules" in op["params_schema"]

    @pytest.mark.unit
    @patch("lumina.core.slm.call_slm")
    def test_custom_operations_list_used(self, mock_call: MagicMock) -> None:
        mock_call.return_value = json.dumps({"operation": "custom_op", "target": "t", "params": {}})
        custom_ops = [{"name": "custom_op", "description": "Custom", "params_schema": {}}]
        result = slm_parse_admin_command("do custom", available_operations=custom_ops)
        assert result is not None
        assert result["operation"] == "custom_op"
        # Verify the custom ops were compacted and sent in the payload
        call_args = mock_call.call_args
        user_payload = call_args[1].get("user") or call_args[0][1]
        parsed = json.loads(user_payload)
        expected_compacted = [{"name": "custom_op", "description": "Custom", "params": []}]
        assert parsed["available_operations"] == expected_compacted


# ── Empty Physics Context ─────────────────────────────────────────────────────


class TestEmptyPhysicsContext:

    @pytest.mark.unit
    def test_structure(self) -> None:
        ctx = _empty_physics_context()
        assert ctx["matched_invariants"] == []
        assert ctx["applicable_standing_orders"] == []
        assert ctx["relevant_glossary_terms"] == []
        assert ctx["context_summary"] == ""
        assert ctx["suggested_evidence_fields"] == {}


# ── SLM Timeout Configuration ────────────────────────────────────────────────


class TestSlmTimeout:

    @pytest.mark.unit
    def test_default_timeout_is_60(self) -> None:
        assert SLM_TIMEOUT == 60.0

    @pytest.mark.unit
    def test_timeout_env_var_override(self) -> None:
        with patch.dict("os.environ", {"LUMINA_SLM_TIMEOUT": "90"}):
            import importlib
            import lumina.core.slm as slm_mod
            importlib.reload(slm_mod)
            assert slm_mod.SLM_TIMEOUT == 90.0
            # Restore default
        import importlib
        import lumina.core.slm as slm_mod
        importlib.reload(slm_mod)

    @pytest.mark.unit
    @patch("lumina.core.slm.SLM_PROVIDER", "local")
    @patch("lumina.core.slm._validate_slm_provider")
    def test_call_local_slm_uses_configured_timeout(self, _validate: Any) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "test response"}}]
        }
        with patch("httpx.post", return_value=mock_resp) as mock_post:
            from lumina.core.slm import _call_local_slm, SLM_TIMEOUT
            _call_local_slm("system", "user")
            call_kwargs = mock_post.call_args
            assert call_kwargs.kwargs.get("timeout") == SLM_TIMEOUT


# ── Compact Operations ────────────────────────────────────────────────────────


class TestCompactOperations:

    @pytest.mark.unit
    def test_strips_params_schema_to_key_list(self) -> None:
        ops = [
            {
                "name": "update_domain_physics",
                "description": "Update domain physics.",
                "params_schema": {
                    "domain_id": "string -- domain identifier",
                    "updates": "object -- key/value pairs",
                },
            },
        ]
        result = _compact_operations(ops)
        assert len(result) == 1
        assert result[0]["name"] == "update_domain_physics"
        assert result[0]["description"] == "Update domain physics."
        assert result[0]["params"] == ["domain_id", "updates"]
        assert "params_schema" not in result[0]

    @pytest.mark.unit
    def test_handles_missing_params_schema(self) -> None:
        ops = [{"name": "no_params", "description": "No params."}]
        result = _compact_operations(ops)
        assert result == [{"name": "no_params", "description": "No params."}]
        assert "params" not in result[0]

    @pytest.mark.unit
    def test_handles_empty_list(self) -> None:
        assert _compact_operations([]) == []

    @pytest.mark.unit
    def test_compacts_all_admin_operations(self) -> None:
        """Every entry in ADMIN_OPERATIONS should compact without error."""
        result = _compact_operations(ADMIN_OPERATIONS)
        assert len(result) == len(ADMIN_OPERATIONS)
        for entry in result:
            assert "name" in entry
            assert "description" in entry
            # params_schema should be gone, replaced with params list
            assert "params_schema" not in entry
            assert isinstance(entry.get("params"), list)


# ── SLM Command Max Tokens ────────────────────────────────────────────────────


class TestSlmCommandMaxTokens:

    @pytest.mark.unit
    @patch("lumina.core.slm.call_slm")
    def test_admin_command_uses_command_token_budget(self, mock_call: MagicMock) -> None:
        """slm_parse_admin_command must pass SLM_COMMAND_MAX_TOKENS to call_slm."""
        mock_call.return_value = json.dumps({
            "operation": "update_domain_physics",
            "target": "algebra",
            "params": {"updates": {}},
        })
        slm_parse_admin_command("update physics")
        call_kwargs = mock_call.call_args[1]
        assert call_kwargs.get("max_tokens") == SLM_COMMAND_MAX_TOKENS, (
            f"Expected max_tokens={SLM_COMMAND_MAX_TOKENS}, got {call_kwargs.get('max_tokens')}"
        )

    @pytest.mark.unit
    def test_command_max_tokens_default_value(self) -> None:
        assert SLM_COMMAND_MAX_TOKENS == 1024

    @pytest.mark.unit
    @patch("lumina.core.slm.call_slm")
    def test_compact_ops_sent_in_payload(self, mock_call: MagicMock) -> None:
        """slm_parse_admin_command sends compacted operations, not full schemas."""
        mock_call.return_value = json.dumps({
            "operation": "update_domain_physics",
            "target": "test",
            "params": {},
        })
        slm_parse_admin_command("update something")
        call_args = mock_call.call_args
        user_payload = json.loads(call_args[1].get("user") or call_args[0][1])
        for op in user_payload["available_operations"]:
            assert "params_schema" not in op
            assert isinstance(op.get("params"), list)


# ── Admin Command Logging ─────────────────────────────────────────────────────


class TestAdminCommandLogging:

    @pytest.mark.unit
    @patch("lumina.core.slm.call_slm", side_effect=RuntimeError("SLM exploded"))
    def test_warning_logged_on_parse_failure(self, mock_call: MagicMock) -> None:
        """slm_parse_admin_command logs a warning (not debug) when parsing fails."""
        with patch("lumina.core.slm.log") as mock_log:
            result = slm_parse_admin_command("update something")
            assert result is None
            mock_log.warning.assert_called_once()
            warning_msg = mock_log.warning.call_args[0][0]
            assert "admin command parsing failed" in warning_msg.lower()
