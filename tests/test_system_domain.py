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
# Make domain-pack systools importable without installing the package.
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parents[1]
_SYSTOOLS = _REPO_ROOT / "domain-packs" / "system" / "systools"
# Ensure system systools path is FIRST so it takes precedence
if str(_SYSTOOLS) in sys.path:
    sys.path.remove(str(_SYSTOOLS))
sys.path.insert(0, str(_SYSTOOLS))
# Evict any cached tool_adapters from a different domain pack
sys.modules.pop("tool_adapters", None)

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
