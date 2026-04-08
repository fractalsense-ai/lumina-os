"""Tests for structured content builders — action card factories.

Verifies that escalation and command proposal cards conform to the
action-card-schema-v1 JSON Schema.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from lumina.api.structured_content import (
    build_escalation_card,
    build_command_proposal_card,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_schema() -> dict:
    schema_path = _REPO_ROOT / "standards" / "action-card-schema-v1.json"
    return json.loads(schema_path.read_text(encoding="utf-8"))


# ── Escalation Card ──────────────────────────────────────────


@pytest.mark.unit
def test_escalation_card_has_required_fields() -> None:
    record = {
        "record_id": "esc-001",
        "trigger": "frustration_repeated",
        "sla_minutes": 30,
        "domain_lib_decision": {"tier": "yellow", "domain_alert_flag": "confused"},
        "target_role": "teacher",
        "session_id": "sess-1",
        "actor_id": "student-abc",
        "timestamp_utc": "2025-01-01T00:00:00Z",
        "task_id": "task-1",
    }
    card = build_escalation_card(record)

    assert card["type"] == "action_card"
    assert card["card_type"] == "escalation"
    assert card["id"] == "esc-001"
    assert card["title"] == "Escalation Alert"
    assert "frustration_repeated" in card["body"]
    assert "SLA: 30 min" in card["body"]
    assert len(card["actions"]) == 3
    assert card["resolve_endpoint"] == "/api/escalations/esc-001/resolve"


@pytest.mark.unit
def test_escalation_card_includes_session_context() -> None:
    record = {
        "record_id": "esc-002",
        "trigger": "off_topic",
        "target_role": "domain_authority",
    }
    ctx = {
        "domain_id": "education/pre-algebra",
        "turn_count": 12,
        "actor_pseudonym": "Student A",
    }
    card = build_escalation_card(record, session_context=ctx)
    assert card["context"]["domain_id"] == "education/pre-algebra"
    assert card["context"]["turn_count"] == 12
    assert card["context"]["actor_pseudonym"] == "Student A"


@pytest.mark.unit
def test_escalation_card_action_ids() -> None:
    card = build_escalation_card({"record_id": "esc-003"})
    action_ids = [a["id"] for a in card["actions"]]
    assert action_ids == ["approve", "reject", "defer"]


@pytest.mark.unit
def test_escalation_card_action_styles() -> None:
    card = build_escalation_card({"record_id": "esc-004"})
    styles = {a["id"]: a["style"] for a in card["actions"]}
    assert styles["approve"] == "primary"
    assert styles["reject"] == "destructive"
    assert styles["defer"] == "ghost"


@pytest.mark.unit
def test_escalation_card_domain_alert_in_body() -> None:
    record = {
        "record_id": "esc-005",
        "trigger": "harm_risk",
        "domain_lib_decision": {"domain_alert_flag": "safety_concern"},
    }
    card = build_escalation_card(record)
    assert "safety_concern" in card["body"]


# ── Command Proposal Card ────────────────────────────────────


@pytest.mark.unit
def test_command_card_has_required_fields() -> None:
    staged = {
        "staged_id": "cmd-001",
        "parsed_command": {
            "operation": "update_physics",
            "params": {"key": "value"},
            "target": "education/pre-algebra",
        },
        "original_instruction": "Update the physics config",
        "actor_id": "admin-user",
        "staged_at": "2025-01-01T10:00:00Z",
        "expires_at": "2025-01-01T10:05:00Z",
    }
    card = build_command_proposal_card(staged)

    assert card["type"] == "action_card"
    assert card["card_type"] == "command_proposal"
    assert card["id"] == "cmd-001"
    assert card["title"] == "Command Proposal"
    assert "update_physics" in card["body"]
    assert len(card["actions"]) == 3
    assert card["resolve_endpoint"] == "/api/admin/command/cmd-001/resolve"


@pytest.mark.unit
def test_command_card_action_ids() -> None:
    card = build_command_proposal_card({"staged_id": "cmd-002"})
    action_ids = [a["id"] for a in card["actions"]]
    assert action_ids == ["accept", "reject", "modify"]


@pytest.mark.unit
def test_command_card_includes_original_instruction() -> None:
    staged = {
        "staged_id": "cmd-003",
        "original_instruction": "Set max_turns to 50",
        "parsed_command": {"operation": "set_param"},
    }
    card = build_command_proposal_card(staged)
    assert "Set max_turns to 50" in card["body"]


@pytest.mark.unit
def test_command_card_context_fields() -> None:
    staged = {
        "staged_id": "cmd-004",
        "parsed_command": {
            "operation": "register_domain",
            "params": {"domain_id": "agriculture/wheat"},
            "target": "system",
        },
        "original_instruction": "Register wheat domain",
        "actor_id": "root_admin",
        "expires_at": "2025-01-01T10:05:00Z",
    }
    card = build_command_proposal_card(staged)
    assert card["context"]["operation"] == "register_domain"
    assert card["context"]["target"] == "system"
    assert card["context"]["actor_id"] == "root_admin"


@pytest.mark.unit
def test_command_card_params_in_body() -> None:
    staged = {
        "staged_id": "cmd-005",
        "parsed_command": {
            "operation": "update",
            "params": {"threshold": 0.8, "mode": "strict"},
        },
    }
    card = build_command_proposal_card(staged)
    assert "threshold=0.8" in card["body"]
    assert "mode=strict" in card["body"]


# ── Schema Conformance ───────────────────────────────────────


@pytest.mark.unit
def test_escalation_card_schema_keys() -> None:
    """Card has exactly the fields defined in the schema."""
    schema = _load_schema()
    required = set(schema["required"])
    card = build_escalation_card({"record_id": "esc-schema"})
    card_keys = set(card.keys())
    assert required.issubset(card_keys), f"Missing: {required - card_keys}"


@pytest.mark.unit
def test_command_card_schema_keys() -> None:
    schema = _load_schema()
    required = set(schema["required"])
    card = build_command_proposal_card({"staged_id": "cmd-schema"})
    card_keys = set(card.keys())
    assert required.issubset(card_keys), f"Missing: {required - card_keys}"


@pytest.mark.unit
def test_action_has_required_schema_fields() -> None:
    schema = _load_schema()
    action_required = set(schema["$defs"]["action"]["required"])
    card = build_escalation_card({"record_id": "esc-action"})
    for action in card["actions"]:
        assert action_required.issubset(set(action.keys()))


@pytest.mark.unit
def test_action_styles_in_schema() -> None:
    schema = _load_schema()
    valid_styles = set(schema["$defs"]["action"]["properties"]["style"]["enum"])
    for builder, arg in [
        (build_escalation_card, {"record_id": "e"}),
        (build_command_proposal_card, {"staged_id": "c"}),
    ]:
        card = builder(arg)
        for action in card["actions"]:
            assert action["style"] in valid_styles, f"Bad style: {action['style']}"


@pytest.mark.unit
def test_card_types_in_schema() -> None:
    schema = _load_schema()
    valid_types = set(schema["properties"]["card_type"]["enum"])
    e = build_escalation_card({"record_id": "e"})
    c = build_command_proposal_card({"staged_id": "c"})
    assert e["card_type"] in valid_types
    assert c["card_type"] in valid_types
