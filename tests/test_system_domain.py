"""Tests for the system domain — runtime adapters and tool adapters.

Covers:
- build_system_state: initial and restored state
- system_domain_step: all query_type → action code mappings
- system_domain_step: command_dispatch takes precedence over query_type
- interpret_turn_input: accepts call_slm kwarg; populates command_dispatch evidence
- interpret_turn_input: falls back to defaults on bad JSON
- tool_adapters: list_domains
- tool_adapters: show_domain_physics (valid and invalid domain_id)
- tool_adapters: module_status
- tool_adapters: list_escalations (empty System Log, filtered)
- tool_adapters: list_log_records (pagination, record_type filter)
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Make domain-pack controllers importable without installing the package.
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parents[1]
_CONTROLLERS = _REPO_ROOT / "domain-packs" / "system" / "controllers"
# Ensure system controllers path is FIRST so it takes precedence
if str(_CONTROLLERS) in sys.path:
    sys.path.remove(str(_CONTROLLERS))
sys.path.insert(0, str(_CONTROLLERS))
# Evict any cached tool_adapters or nlp_pre_interpreter from a different domain pack
sys.modules.pop("tool_adapters", None)
sys.modules.pop("nlp_pre_interpreter", None)

from runtime_adapters import (  # noqa: E402
    build_system_state,
    interpret_turn_input,
    system_domain_step,
)
from tool_adapters import (  # noqa: E402
    list_log_records,
    list_domains,
    list_escalations,
    module_status,
    show_domain_physics,
)


# ===========================================================================
# build_system_state
# ===========================================================================


class TestBuildSystemState:

    @pytest.mark.unit
    def test_fresh_state_defaults(self) -> None:
        profile: dict[str, Any] = {
            "operator_id": "op-abc",
            "domain_id": "domain/sys/system-core/v1",
        }
        state = build_system_state(profile)
        assert state["turn_count"] == 0
        assert state["operator_id"] == "op-abc"
        assert state["domain_id"] == "domain/sys/system-core/v1"

    @pytest.mark.unit
    def test_restores_turn_count_from_session_state(self) -> None:
        profile = {"operator_id": "op-xyz"}
        state = build_system_state(profile, session_state={"turn_count": 7})
        assert state["turn_count"] == 7

    @pytest.mark.unit
    def test_missing_operator_id_defaults_to_empty_string(self) -> None:
        state = build_system_state({})
        assert state["operator_id"] == ""

    @pytest.mark.unit
    def test_runtime_ctx_accepted_without_error(self) -> None:
        state = build_system_state({"operator_id": "op"}, runtime_ctx={"local_only": True})
        assert state["turn_count"] == 0


# ===========================================================================
# system_domain_step — action code mapping
# ===========================================================================


class TestSystemDomainStep:

    _base_state: dict[str, Any] = {"turn_count": 0, "operator_id": "op", "domain_id": "domain/sys/system-core/v1"}

    @pytest.mark.parametrize(
        "query_type,expected_action",
        [
            ("admin_command",  "system_command"),
            ("status_query",   "system_status"),
            ("diagnostic",     "system_diagnostic"),
            ("config_review",  "system_config_review"),
            ("out_of_domain",  "out_of_domain"),
            ("glossary_lookup","system_general"),
            ("general",        "system_general"),
            ("unknown_type",   "system_general"),   # unmapped → system_general
        ],
    )
    @pytest.mark.unit
    def test_query_type_maps_to_action(self, query_type: str, expected_action: str) -> None:
        evidence = {"query_type": query_type}
        new_state, action = system_domain_step(self._base_state, {}, evidence, {})
        assert action["action"] == expected_action

    @pytest.mark.unit
    def test_command_dispatch_overrides_query_type(self) -> None:
        """Truthy command_dispatch must resolve to system_command regardless of query_type."""
        evidence = {
            "query_type": "general",
            "command_dispatch": {"operation": "list_domains", "target": "", "params": {}},
        }
        _, action = system_domain_step(self._base_state, {}, evidence, {})
        assert action["action"] == "system_command"
        assert action["command_dispatch"] == evidence["command_dispatch"]

    @pytest.mark.unit
    def test_null_command_dispatch_does_not_override(self) -> None:
        evidence = {"query_type": "status_query", "command_dispatch": None}
        _, action = system_domain_step(self._base_state, {}, evidence, {})
        assert action["action"] == "system_status"

    @pytest.mark.unit
    def test_turn_count_increments(self) -> None:
        state = {"turn_count": 3, "operator_id": "op", "domain_id": "x"}
        new_state, _ = system_domain_step(state, {}, {"query_type": "general"}, {})
        assert new_state["turn_count"] == 4

    @pytest.mark.unit
    def test_original_state_not_mutated(self) -> None:
        state = {"turn_count": 1, "operator_id": "op", "domain_id": "x"}
        system_domain_step(state, {}, {"query_type": "general"}, {})
        assert state["turn_count"] == 1

    @pytest.mark.unit
    def test_missing_query_type_defaults_to_general(self) -> None:
        _, action = system_domain_step(self._base_state, {}, {}, {})
        assert action["action"] == "system_general"
        assert action["query_type"] == "general"


# ===========================================================================
# interpret_turn_input
# ===========================================================================


class TestInterpretTurnInput:

    _defaults: dict[str, Any] = {
        "query_type": "general",
        "target_component": None,
        "off_task_ratio": 0.0,
        "response_latency_sec": 5.0,
    }

    @pytest.mark.unit
    def test_parses_valid_json_from_llm(self) -> None:
        response = json.dumps({"query_type": "status_query", "target_component": "ctl"})
        call_llm = MagicMock(return_value=response)
        evidence = interpret_turn_input(call_llm, "show status", {}, "prompt", self._defaults)
        assert evidence["query_type"] == "status_query"
        assert evidence["target_component"] == "ctl"

    @pytest.mark.unit
    def test_falls_back_to_defaults_on_bad_json(self) -> None:
        call_llm = MagicMock(return_value="not json at all")
        evidence = interpret_turn_input(call_llm, "hey", {}, "prompt", self._defaults)
        assert evidence["query_type"] == "general"
        assert evidence["off_task_ratio"] == 0.0

    @pytest.mark.unit
    def test_strips_markdown_fences(self) -> None:
        raw = "```json\n{\"query_type\": \"diagnostic\"}\n```"
        call_llm = MagicMock(return_value=raw)
        evidence = interpret_turn_input(call_llm, "diagnose", {}, "prompt", self._defaults)
        assert evidence["query_type"] == "diagnostic"

    @pytest.mark.unit
    def test_call_slm_kwarg_accepted(self) -> None:
        """call_slm kwarg must not raise TypeError — it's an optional extra."""
        response = json.dumps({"query_type": "general"})
        call_llm = MagicMock(return_value=response)
        call_slm = MagicMock(return_value=response)
        evidence = interpret_turn_input(
            call_llm, "hello", {}, "prompt", self._defaults, call_slm=call_slm
        )
        assert evidence["query_type"] == "general"

    @pytest.mark.unit
    def test_command_dispatch_null_for_non_dispatch_query_types(self) -> None:
        """query_types not in the dispatch set must produce command_dispatch=None
        without attempting SLM command parsing."""
        response = json.dumps({"query_type": "general"})
        call_llm = MagicMock(return_value=response)
        with patch("lumina.core.slm.slm_available", return_value=True):
            evidence = interpret_turn_input(call_llm, "hi", {}, "prompt", self._defaults)
        assert evidence["command_dispatch"] is None

    @pytest.mark.unit
    def test_command_dispatch_populated_when_slm_available(self) -> None:
        """When query_type is in the dispatch set and SLM is available, command_dispatch
        should be populated with the parsed result."""
        response = json.dumps({"query_type": "admin_command"})
        call_llm = MagicMock(return_value=response)
        parsed_cmd = {"operation": "list_domains", "target": "", "params": {}}
        with patch("lumina.core.slm.slm_available", return_value=True), \
             patch("lumina.core.slm.slm_parse_admin_command", return_value=parsed_cmd):
            evidence = interpret_turn_input(call_llm, "show domains", {}, "prompt", self._defaults)
        assert evidence["command_dispatch"] == parsed_cmd

    @pytest.mark.unit
    def test_command_dispatch_none_when_slm_unavailable(self) -> None:
        response = json.dumps({"query_type": "admin_command"})
        call_llm = MagicMock(return_value=response)
        with patch("lumina.core.slm.slm_available", return_value=False):
            evidence = interpret_turn_input(call_llm, "list domains", {}, "prompt", self._defaults)
        assert evidence["command_dispatch"] is None


# ===========================================================================
# tool_adapters — list_domains
# ===========================================================================


class TestListDomains:

    @pytest.mark.unit
    def test_returns_expected_keys(self) -> None:
        result = list_domains({})
        assert "domains" in result
        assert "default_domain" in result
        assert "role_defaults" in result
        assert "count" in result

    @pytest.mark.unit
    def test_count_matches_domains_list(self) -> None:
        result = list_domains({})
        assert result["count"] == len(result["domains"])

    @pytest.mark.unit
    def test_includes_known_domains(self) -> None:
        result = list_domains({})
        domain_ids = [d["domain_id"] for d in result["domains"]]
        assert "education" in domain_ids
        assert "system" in domain_ids

    @pytest.mark.unit
    def test_keywords_excluded_by_default(self) -> None:
        result = list_domains({})
        for d in result["domains"]:
            assert "keywords" not in d

    @pytest.mark.unit
    def test_keywords_included_when_requested(self) -> None:
        result = list_domains({"include_keywords": True})
        for d in result["domains"]:
            assert "keywords" in d

    @pytest.mark.unit
    def test_role_defaults_contains_root(self) -> None:
        result = list_domains({})
        assert "root" in result["role_defaults"]
        assert result["role_defaults"]["root"] == "system"


# ===========================================================================
# tool_adapters — show_domain_physics
# ===========================================================================


class TestShowDomainPhysics:

    @pytest.mark.unit
    def test_system_domain_returns_expected_fields(self) -> None:
        result = show_domain_physics({"domain_id": "system"})
        assert "error" not in result
        assert result["domain"] == "system"
        assert result["id"] == "domain/sys/system-core/v1"

    @pytest.mark.unit
    def test_education_domain_returns_expected_fields(self) -> None:
        result = show_domain_physics({"domain_id": "education"})
        assert "error" not in result
        assert result["domain"] == "education"

    @pytest.mark.unit
    def test_missing_domain_id_returns_error(self) -> None:
        result = show_domain_physics({})
        assert "error" in result

    @pytest.mark.unit
    def test_unknown_domain_id_returns_error(self) -> None:
        result = show_domain_physics({"domain_id": "nonexistent_domain_xyz"})
        assert "error" in result

    @pytest.mark.unit
    def test_glossary_excluded_by_default(self) -> None:
        result = show_domain_physics({"domain_id": "system"})
        assert "glossary" not in result

    @pytest.mark.unit
    def test_glossary_included_when_requested(self) -> None:
        result = show_domain_physics({"domain_id": "system", "include_glossary": True})
        assert "glossary" in result
        assert isinstance(result["glossary"], list)

    @pytest.mark.unit
    def test_topics_included_by_default(self) -> None:
        result = show_domain_physics({"domain_id": "system"})
        assert "topics" in result


# ===========================================================================
# tool_adapters — module_status
# ===========================================================================


class TestModuleStatus:

    @pytest.mark.unit
    def test_missing_domain_id_returns_error(self) -> None:
        result = module_status({})
        assert "error" in result

    @pytest.mark.unit
    def test_unknown_domain_id_returns_error(self) -> None:
        result = module_status({"domain_id": "ghost_domain"})
        assert "error" in result

    @pytest.mark.unit
    def test_known_domain_returns_hash(self) -> None:
        result = module_status({"domain_id": "system"})
        assert "error" not in result
        assert len(result["physics_hash"]) == 64  # sha256 hex
        assert result["domain_id"] == "system"
        assert "committed" in result
        assert "status" in result

    @pytest.mark.unit
    def test_status_is_ok_or_uncommitted(self) -> None:
        result = module_status({"domain_id": "education"})
        assert result["status"] in ("ok", "uncommitted", "unknown")


# ===========================================================================
# tool_adapters — list_escalations  (uses a temp System Log dir)
# ===========================================================================


@pytest.fixture()
def tmp_log_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a temporary System Log directory and point tool_adapters at it."""
    import tool_adapters as ta  # already on sys.path
    monkeypatch.setattr(ta, "_LOG_DIR", tmp_path)
    return tmp_path


def _write_records(log_dir: Path, session_id: str, records: list[dict[str, Any]]) -> None:
    ledger = log_dir / f"session-{session_id}.jsonl"
    with open(ledger, "w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")


class TestListEscalations:

    @pytest.mark.unit
    def test_empty_ctl_returns_empty_list(self, tmp_log_dir: Path) -> None:
        result = list_escalations({})
        assert result["escalations"] == []
        assert result["count"] == 0

    @pytest.mark.unit
    def test_returns_escalation_records(self, tmp_log_dir: Path) -> None:
        records = [
            {"record_type": "EscalationRecord", "session_id": "s1",
             "timestamp_utc": "2026-03-17T01:00:00Z", "domain_id": "education"},
            {"record_type": "TraceEvent", "session_id": "s1",
             "timestamp_utc": "2026-03-17T01:01:00Z"},
        ]
        _write_records(tmp_log_dir, "s1", records)
        result = list_escalations({})
        assert result["count"] == 1
        assert result["escalations"][0]["record_type"] == "EscalationRecord"

    @pytest.mark.unit
    def test_limit_is_respected(self, tmp_log_dir: Path) -> None:
        records = [
            {"record_type": "EscalationRecord", "session_id": f"s{i}",
             "timestamp_utc": f"2026-03-17T0{i}:00:00Z"}
            for i in range(5)
        ]
        _write_records(tmp_log_dir, "bulk", records)
        result = list_escalations({"limit": 2})
        assert result["count"] == 2

    @pytest.mark.unit
    def test_domain_id_filter(self, tmp_log_dir: Path) -> None:
        records = [
            {"record_type": "EscalationRecord", "domain_id": "education",
             "timestamp_utc": "2026-03-17T01:00:00Z"},
            {"record_type": "EscalationRecord", "domain_id": "agriculture",
             "timestamp_utc": "2026-03-17T01:01:00Z"},
        ]
        _write_records(tmp_log_dir, "s2", records)
        result = list_escalations({"domain_id": "education"})
        assert result["count"] == 1
        assert result["escalations"][0]["domain_id"] == "education"

    @pytest.mark.unit
    def test_results_are_most_recent_first(self, tmp_log_dir: Path) -> None:
        records = [
            {"record_type": "EscalationRecord", "timestamp_utc": "2026-03-17T01:00:00Z", "label": "older"},
            {"record_type": "EscalationRecord", "timestamp_utc": "2026-03-17T03:00:00Z", "label": "newer"},
        ]
        _write_records(tmp_log_dir, "s3", records)
        result = list_escalations({})
        assert result["escalations"][0]["label"] == "newer"


# ===========================================================================
# tool_adapters — list_log_records
# ===========================================================================


class TestListSystemLogRecords:

    @pytest.mark.unit
    def test_empty_ctl_returns_empty_list(self, tmp_log_dir: Path) -> None:
        result = list_log_records({})
        assert result["records"] == []

    @pytest.mark.unit
    def test_returns_all_record_types_by_default(self, tmp_log_dir: Path) -> None:
        records = [
            {"record_type": "TraceEvent", "timestamp_utc": "2026-03-17T01:00:00Z"},
            {"record_type": "CommitmentRecord", "timestamp_utc": "2026-03-17T01:01:00Z"},
            {"record_type": "EscalationRecord", "timestamp_utc": "2026-03-17T01:02:00Z"},
        ]
        _write_records(tmp_log_dir, "s1", records)
        result = list_log_records({})
        assert result["count"] == 3

    @pytest.mark.unit
    def test_record_type_filter(self, tmp_log_dir: Path) -> None:
        records = [
            {"record_type": "TraceEvent", "timestamp_utc": "2026-03-17T01:00:00Z"},
            {"record_type": "CommitmentRecord", "timestamp_utc": "2026-03-17T01:01:00Z"},
        ]
        _write_records(tmp_log_dir, "s1", records)
        result = list_log_records({"record_type": "TraceEvent"})
        assert result["count"] == 1
        assert result["records"][0]["record_type"] == "TraceEvent"

    @pytest.mark.unit
    def test_session_id_filter(self, tmp_log_dir: Path) -> None:
        _write_records(tmp_log_dir, "session-a", [
            {"record_type": "TraceEvent", "session_id": "session-a",
             "timestamp_utc": "2026-03-17T01:00:00Z"},
        ])
        _write_records(tmp_log_dir, "session-b", [
            {"record_type": "TraceEvent", "session_id": "session-b",
             "timestamp_utc": "2026-03-17T01:01:00Z"},
        ])
        result = list_log_records({"session_id": "session-a"})
        assert result["count"] == 1
        assert result["records"][0]["session_id"] == "session-a"

    @pytest.mark.unit
    def test_limit_capped_at_200(self, tmp_log_dir: Path) -> None:
        records = [
            {"record_type": "TraceEvent", "timestamp_utc": "2026-03-17T01:00:00Z"}
            for _ in range(10)
        ]
        _write_records(tmp_log_dir, "bulk", records)
        result = list_log_records({"limit": 500})
        # limit is capped at 200; we only wrote 10 so all 10 come back
        assert result["count"] == 10


# ===========================================================================
# nlp_pre_interpreter — unit tests for each extractor
# ===========================================================================

# Import the new module (same sys.path as runtime_adapters already inserted above)
from nlp_pre_interpreter import (  # noqa: E402
    detect_compound_command,
    extract_admin_verb,
    extract_glossary_match,
    extract_target_role,
    extract_target_user,
    nlp_preprocess,
)


class TestNlpPreInterpreter:

    # --- extract_admin_verb ---

    @pytest.mark.unit
    def test_mutation_verb_remove(self) -> None:
        result = extract_admin_verb("please remove root from the user")
        assert result["intent_type"] == "mutation"
        assert result["verb"] == "remove"
        assert result["confidence"] >= 0.85

    @pytest.mark.unit
    def test_mutation_verb_give(self) -> None:
        result = extract_admin_verb("give user Matt domain authority access")
        assert result["intent_type"] == "mutation"
        assert result["verb"] == "give"

    @pytest.mark.unit
    def test_read_verb_list(self) -> None:
        result = extract_admin_verb("list all active users")
        assert result["intent_type"] == "read"
        assert result["verb"] == "list"

    @pytest.mark.unit
    def test_read_verb_show(self) -> None:
        result = extract_admin_verb("show me the current domain physics")
        assert result["intent_type"] == "read"

    @pytest.mark.unit
    def test_polite_mutation_still_detected(self) -> None:
        result = extract_admin_verb("Can you please remove root from user Alice")
        assert result["intent_type"] == "mutation"

    @pytest.mark.unit
    def test_unknown_intent_when_no_verbs(self) -> None:
        result = extract_admin_verb("hello there")
        assert result["intent_type"] == "unknown"
        assert result["confidence"] == 0.0

    # --- extract_target_user ---

    @pytest.mark.unit
    def test_user_named_pattern(self) -> None:
        result = extract_target_user("remove root from user named Matt")
        assert result["target_user"] == "Matt"
        assert result["confidence"] == 0.95

    @pytest.mark.unit
    def test_for_user_pattern(self) -> None:
        result = extract_target_user("assign domain authority for user Alice")
        assert result["target_user"] == "Alice"

    @pytest.mark.unit
    def test_bare_user_pattern(self) -> None:
        result = extract_target_user("deactivate user Bob")
        assert result["target_user"] == "Bob"

    @pytest.mark.unit
    def test_no_user_found(self) -> None:
        result = extract_target_user("list all escalations")
        assert result["target_user"] is None
        assert result["confidence"] == 0.0

    # --- extract_target_role ---

    @pytest.mark.unit
    def test_domain_authority_with_domain(self) -> None:
        result = extract_target_role("give domain authority access to education")
        assert result["target_role"] == "domain_authority"
        assert result["governed_domains"] == ["education"]

    @pytest.mark.unit
    def test_remove_root_role(self) -> None:
        result = extract_target_role("Can you please remove root from user Matt")
        assert result["target_role"] == "root"
        assert result["confidence"] >= 0.85

    @pytest.mark.unit
    def test_plain_role_name_auditor(self) -> None:
        result = extract_target_role("promote user Sam to auditor")
        assert result["target_role"] == "auditor"

    @pytest.mark.unit
    def test_no_role_found(self) -> None:
        result = extract_target_role("show me the system log")
        assert result["target_role"] is None

    # --- detect_compound_command ---

    @pytest.mark.unit
    def test_compound_remove_and_give(self) -> None:
        msg = "remove root from user Matt and give domain authority access to Education only"
        result = detect_compound_command(msg)
        assert result["is_compound"] is True
        assert result["operation_count_estimate"] == 2

    @pytest.mark.unit
    def test_single_operation_not_compound(self) -> None:
        result = detect_compound_command("remove root from user Alice")
        assert result["is_compound"] is False

    # --- extract_glossary_match ---

    @pytest.mark.unit
    def test_glossary_ctl_matched(self) -> None:
        result = extract_glossary_match("check the ctl for recent commits")
        assert "ctl" in result["glossary_terms_matched"]

    @pytest.mark.unit
    def test_glossary_underscore_form_matched(self) -> None:
        result = extract_glossary_match("review the domain physics file")
        assert "domain_physics" in result["glossary_terms_matched"]

    @pytest.mark.unit
    def test_no_glossary_match(self) -> None:
        result = extract_glossary_match("hello how are you today")
        assert result["glossary_terms_matched"] == []

    # --- nlp_preprocess (integration) ---

    @pytest.mark.unit
    def test_full_preprocess_produces_anchors(self) -> None:
        msg = "Can you please remove root from user named Matt"
        result = nlp_preprocess(msg, {})
        anchors = result["_nlp_anchors"]
        assert isinstance(anchors, list)
        fields = [a["field"] for a in anchors]
        assert "intent_type" in fields
        assert "target_user" in fields
        assert "target_role" in fields

    @pytest.mark.unit
    def test_compound_command_anchor_present(self) -> None:
        msg = "remove root from user Matt and give domain authority access to Education only"
        result = nlp_preprocess(msg, {})
        fields = [a["field"] for a in result["_nlp_anchors"]]
        assert "compound_command" in fields
        assert result.get("is_compound_command") is True

    @pytest.mark.unit
    def test_empty_context_does_not_raise(self) -> None:
        result = nlp_preprocess("", {})
        assert "_nlp_anchors" in result


# ===========================================================================
# interpret_turn_input — NLP anchor injection
# ===========================================================================


class TestInterpretTurnInputNlp:

    _defaults: dict[str, Any] = {
        "query_type": "general",
        "target_component": None,
        "response_latency_sec": 5.0,
    }

    @pytest.mark.unit
    def test_nlp_fn_anchors_injected_into_prompt(self) -> None:
        """Anchor block must appear in the user= argument passed to call_llm."""
        def fake_nlp(text: str, ctx: dict) -> dict:
            return {
                "_nlp_anchors": [
                    {"field": "intent_type", "value": "mutation", "confidence": 0.90, "detail": "verb: remove"},
                ],
            }

        call_llm = MagicMock(return_value=json.dumps({"query_type": "admin_command"}))
        with patch("lumina.core.slm.slm_available", return_value=False):
            interpret_turn_input(
                call_llm, "remove root", {}, "prompt",
                self._defaults, nlp_pre_interpreter_fn=fake_nlp,
            )
        user_arg = call_llm.call_args[1].get("user") or call_llm.call_args[0][1]
        assert "NLP pre-analysis (deterministic)" in user_arg
        assert "intent_type: mutation" in user_arg

    @pytest.mark.unit
    def test_compound_hint_appended_when_is_compound(self) -> None:
        """When NLP fn sets is_compound_command, the compound hint must appear in prompt."""
        def fake_nlp(text: str, ctx: dict) -> dict:
            return {
                "_nlp_anchors": [],
                "is_compound_command": True,
            }

        call_llm = MagicMock(return_value=json.dumps({"query_type": "general"}))
        with patch("lumina.core.slm.slm_available", return_value=False):
            interpret_turn_input(
                call_llm, "remove X and give Y", {}, "prompt",
                self._defaults, nlp_pre_interpreter_fn=fake_nlp,
            )
        user_arg = call_llm.call_args[1].get("user") or call_llm.call_args[0][1]
        assert "Compound command detected" in user_arg

    @pytest.mark.unit
    def test_nlp_fn_not_required(self) -> None:
        """Omitting nlp_pre_interpreter_fn must not raise and must not change behaviour."""
        call_llm = MagicMock(return_value=json.dumps({"query_type": "general"}))
        evidence = interpret_turn_input(call_llm, "hello", {}, "prompt", self._defaults)
        assert evidence["query_type"] == "general"

    @pytest.mark.unit
    def test_nlp_fn_exception_is_swallowed(self) -> None:
        """A crashing NLP fn must not propagate — interpret_turn_input should still return."""
        def bad_nlp(text: str, ctx: dict) -> dict:
            raise RuntimeError("explode")

        call_llm = MagicMock(return_value=json.dumps({"query_type": "general"}))
        evidence = interpret_turn_input(
            call_llm, "hello", {}, "prompt",
            self._defaults, nlp_pre_interpreter_fn=bad_nlp,
        )
        assert evidence["query_type"] == "general"


# ===========================================================================
# processing.py — local-only NLP wiring
# ===========================================================================

class TestProcessingLocalOnlyNlpWiring:
    """Verify that process_message passes nlp_pre_interpreter_fn to the
    local-only interpreter when the runtime provides one."""

    def _make_session(self) -> dict[str, Any]:
        mock_orch = MagicMock()
        mock_orch.state = MagicMock(world_sim_theme={}, mud_world_state={})
        mock_orch.last_domain_lib_decision = {}
        mock_orch.process_turn.return_value = (
            {
                "prompt_type": "admin_response",
                "domain_pack_id": "system",
                "domain_pack_version": "1",
                "task_id": "sys",
                "task_nominal_difficulty": 0.0,
                "skills_targeted": [],
                "theme": None,
                "standing_order_trigger": None,
                "references": [],
                "grounded": True,
            },
            "admin_response",
        )
        mock_orch.log_records = []
        mock_orch.get_standing_order_attempts.return_value = {}
        mock_orch.append_provenance_trace.return_value = None
        return {
            "orchestrator": mock_orch,
            "task_spec": {"task_id": "sys", "nominal_difficulty": 0.0, "skills_required": []},
            "current_problem": {},
            "turn_count": 0,
            "domain_id": "system",
            "problem_presented_at": None,
        }

    def _make_runtime(self, *, interpreter_fn, nlp_fn=None) -> dict[str, Any]:
        rt: dict[str, Any] = {
            "system_prompt": "sys",
            "domain": {"id": "system", "version": "1", "glossary": []},
            "runtime_provenance": {},
            "turn_input_schema": {},
            "turn_input_defaults": {"query_type": "general"},
            "slm_weight_overrides": {},
            "tool_fns": None,
            "action_prompt_type_map": {},
            "deterministic_templates": {},
            "local_only": True,
            "turn_interpreter_fn": interpreter_fn,
            "turn_interpretation_prompt": "classify this turn",
        }
        if nlp_fn is not None:
            rt["nlp_pre_interpreter_fn"] = nlp_fn
        return rt

    @pytest.mark.unit
    def test_nlp_fn_forwarded_to_local_interpreter(self) -> None:
        """When runtime has nlp_pre_interpreter_fn, it must reach the interpreter."""
        from lumina.api import processing as proc

        captured: dict[str, Any] = {}

        def spy_interpreter(call_llm, input_text, task_context,
                            prompt_text, default_fields, tool_fns=None,
                            call_slm=None, nlp_pre_interpreter_fn=None):
            captured["nlp_pre_interpreter_fn"] = nlp_pre_interpreter_fn
            return {"query_type": "admin_command"}

        sentinel_nlp = lambda text, ctx: {"_nlp_anchors": []}  # noqa: E731
        session = self._make_session()
        runtime = self._make_runtime(interpreter_fn=spy_interpreter,
                                     nlp_fn=sentinel_nlp)

        with (
            patch.object(proc, "get_or_create_session", return_value=session),
            patch.object(proc._cfg.DOMAIN_REGISTRY, "get_runtime_context", return_value=runtime),
            patch.object(proc, "detect_glossary_query", return_value=None),
            patch.object(proc, "slm_available", return_value=True),
            patch.object(proc, "call_slm", return_value="ok"),
            patch.object(proc, "call_llm", return_value="Done."),
            patch.object(proc, "normalize_turn_data", side_effect=lambda d, _s: d),
            patch.object(proc, "apply_tool_call_policy", return_value=[]),
            patch.object(proc, "strip_latex_delimiters", side_effect=lambda s: s),
            patch("lumina.api.processing.time") as mock_time,
        ):
            mock_time.time.return_value = 1_000_000.0
            proc.process_message("sess-nlp", "Revoke root access for user Matt")

        assert captured.get("nlp_pre_interpreter_fn") is sentinel_nlp, (
            "nlp_pre_interpreter_fn was not forwarded to the local-only interpreter"
        )

    @pytest.mark.unit
    def test_no_nlp_fn_still_works(self) -> None:
        """When runtime has no nlp_pre_interpreter_fn the interpreter still runs."""
        from lumina.api import processing as proc

        captured: dict[str, Any] = {}

        def spy_interpreter(call_llm, input_text, task_context,
                            prompt_text, default_fields, tool_fns=None,
                            call_slm=None, nlp_pre_interpreter_fn=None):
            captured["nlp_pre_interpreter_fn"] = nlp_pre_interpreter_fn
            return {"query_type": "general"}

        session = self._make_session()
        runtime = self._make_runtime(interpreter_fn=spy_interpreter)

        with (
            patch.object(proc, "get_or_create_session", return_value=session),
            patch.object(proc._cfg.DOMAIN_REGISTRY, "get_runtime_context", return_value=runtime),
            patch.object(proc, "detect_glossary_query", return_value=None),
            patch.object(proc, "slm_available", return_value=True),
            patch.object(proc, "call_slm", return_value="ok"),
            patch.object(proc, "call_llm", return_value="Hello."),
            patch.object(proc, "normalize_turn_data", side_effect=lambda d, _s: d),
            patch.object(proc, "apply_tool_call_policy", return_value=[]),
            patch.object(proc, "strip_latex_delimiters", side_effect=lambda s: s),
            patch("lumina.api.processing.time") as mock_time,
        ):
            mock_time.time.return_value = 1_000_000.0
            proc.process_message("sess-nlp2", "hello")

        assert captured["nlp_pre_interpreter_fn"] is None, (
            "nlp_pre_interpreter_fn should be None when runtime has no NLP fn"
        )


# ===========================================================================
# processing.py — physics context for local-only domains
# ===========================================================================

class TestPhysicsContextLocalOnly:
    """Verify that local-only domains receive SLM physics context enrichment."""

    def _make_session(self) -> dict[str, Any]:
        mock_orch = MagicMock()
        mock_orch.state = MagicMock(world_sim_theme={}, mud_world_state={})
        mock_orch.last_domain_lib_decision = {}
        mock_orch.process_turn.return_value = (
            {
                "prompt_type": "admin_response",
                "domain_pack_id": "system",
                "domain_pack_version": "1",
                "task_id": "sys",
                "task_nominal_difficulty": 0.0,
                "skills_targeted": [],
                "theme": None,
                "standing_order_trigger": None,
                "references": [],
                "grounded": True,
            },
            "admin_response",
        )
        mock_orch.log_records = []
        mock_orch.get_standing_order_attempts.return_value = {}
        mock_orch.append_provenance_trace.return_value = None
        return {
            "orchestrator": mock_orch,
            "task_spec": {"task_id": "sys", "nominal_difficulty": 0.0, "skills_required": []},
            "current_problem": {},
            "turn_count": 0,
            "domain_id": "system",
            "problem_presented_at": None,
        }

    def _make_runtime(self, *, interpreter_fn) -> dict[str, Any]:
        return {
            "system_prompt": "sys",
            "domain": {"id": "system", "version": "1", "glossary": []},
            "runtime_provenance": {},
            "turn_input_schema": {},
            "turn_input_defaults": {"query_type": "general"},
            "slm_weight_overrides": {},
            "tool_fns": None,
            "action_prompt_type_map": {},
            "deterministic_templates": {},
            "local_only": True,
            "turn_interpreter_fn": interpreter_fn,
            "turn_interpretation_prompt": "classify this turn",
        }

    @pytest.mark.unit
    def test_local_only_domain_gets_physics_context(self) -> None:
        """Physics context enrichment must run even when local_only=True."""
        from lumina.api import processing as proc

        physics_called = {"called": False}

        def spy_interpreter(call_llm, input_text, task_context,
                            prompt_text, default_fields, tool_fns=None,
                            call_slm=None, nlp_pre_interpreter_fn=None):
            return {"query_type": "general"}

        original_interpret = proc.slm_interpret_physics_context

        def spy_physics(*args: Any, **kwargs: Any) -> dict[str, Any]:
            physics_called["called"] = True
            return {
                "matched_invariants": [],
                "applicable_standing_orders": [],
                "relevant_glossary_terms": [],
                "context_summary": "",
                "suggested_evidence_fields": {},
            }

        session = self._make_session()
        runtime = self._make_runtime(interpreter_fn=spy_interpreter)

        with (
            patch.object(proc, "get_or_create_session", return_value=session),
            patch.object(proc._cfg.DOMAIN_REGISTRY, "get_runtime_context", return_value=runtime),
            patch.object(proc, "detect_glossary_query", return_value=None),
            patch.object(proc, "slm_available", return_value=True),
            patch.object(proc, "slm_interpret_physics_context", side_effect=spy_physics),
            patch.object(proc, "call_slm", return_value="ok"),
            patch.object(proc, "call_llm", return_value="Hello."),
            patch.object(proc, "normalize_turn_data", side_effect=lambda d, _s: d),
            patch.object(proc, "apply_tool_call_policy", return_value=[]),
            patch.object(proc, "strip_latex_delimiters", side_effect=lambda s: s),
            patch("lumina.api.processing.time") as mock_time,
        ):
            mock_time.time.return_value = 1_000_000.0
            proc.process_message("sess-phys", "hello")

        assert physics_called["called"], (
            "slm_interpret_physics_context was NOT called for a local_only domain"
        )
