"""Tests for the Command Schema Registry — Default Deny admin command validation."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from lumina.middleware.command_schema_registry import (
    _validate_object,
    _validate_value,
    _type_matches,
    list_operations,
    reload,
    validate_command,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def real_schemas():
    """Load the real schema directory and return the count."""
    count = reload()
    yield count
    # Reset so other tests don't see stale state
    reload()


@pytest.fixture()
def tmp_schema_dir(tmp_path: Path):
    """Create a temporary schema directory with a couple of test schemas."""
    # Valid schema
    (tmp_path / "test-op.json").write_text(
        json.dumps(
            {
                "title": "test_op",
                "type": "object",
                "required": ["operation", "params"],
                "additionalProperties": False,
                "properties": {
                    "operation": {"const": "test_op"},
                    "target": {"type": "string"},
                    "params": {
                        "type": "object",
                        "required": ["name"],
                        "additionalProperties": False,
                        "properties": {
                            "name": {"type": "string", "minLength": 1},
                            "count": {"type": "integer"},
                            "tags": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "level": {
                                "type": "string",
                                "enum": ["low", "medium", "high"],
                            },
                        },
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    # Schema with no required params
    (tmp_path / "no-params.json").write_text(
        json.dumps(
            {
                "title": "no_params",
                "type": "object",
                "required": ["operation", "params"],
                "additionalProperties": False,
                "properties": {
                    "operation": {"const": "no_params"},
                    "params": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {},
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    return tmp_path


# ===================================================================
# Test: reload and list_operations
# ===================================================================


class TestReloadAndDiscovery:
    """Schema loading and operation discovery."""

    def test_reload_from_real_schemas(self, real_schemas: int):
        assert real_schemas >= 18, f"Expected ≥18 schemas, got {real_schemas}"

    def test_list_operations_returns_frozenset(self, real_schemas: int):
        ops = list_operations()
        assert isinstance(ops, frozenset)
        assert len(ops) >= 18

    def test_known_operations_present(self, real_schemas: int):
        ops = list_operations()
        expected = {
            "update_domain_physics",
            "commit_domain_physics",
            "update_user_role",
            "deactivate_user",
            "assign_domain_role",
            "revoke_domain_role",
            "resolve_escalation",
            "review_ingestion",
            "approve_interpretation",
            "reject_ingestion",
            "trigger_daemon_task",
            "review_proposals",
            "invite_user",
            "list_escalations",
            "list_ingestions",
            "module_status",
            "explain_reasoning",
            "daemon_status",
        }
        missing = expected - ops
        assert not missing, f"Missing schemas: {missing}"

    def test_reload_from_custom_dir(self, tmp_schema_dir: Path):
        count = reload(tmp_schema_dir)
        assert count == 2
        ops = list_operations()
        assert ops == frozenset({"test_op", "no_params"})

    def test_reload_from_empty_dir(self, tmp_path: Path):
        count = reload(tmp_path)
        assert count == 0
        assert list_operations() == frozenset()

    def test_reload_from_nonexistent_dir(self, tmp_path: Path):
        count = reload(tmp_path / "does-not-exist")
        assert count == 0

    def test_invalid_json_skipped(self, tmp_path: Path):
        (tmp_path / "bad.json").write_text("not json!", encoding="utf-8")
        (tmp_path / "good.json").write_text(
            json.dumps({"title": "good_op", "properties": {"params": {}}}),
            encoding="utf-8",
        )
        count = reload(tmp_path)
        assert count == 1
        assert "good_op" in list_operations()


# ===================================================================
# Test: validate_command — Default Deny
# ===================================================================


class TestDefaultDeny:
    """Unknown operations must be rejected."""

    def test_unknown_operation_denied(self, tmp_schema_dir: Path):
        reload(tmp_schema_dir)
        approved, violations = validate_command("totally_unknown", {})
        assert approved is False
        assert any("Unknown operation" in v for v in violations)

    def test_empty_operation_denied(self, tmp_schema_dir: Path):
        reload(tmp_schema_dir)
        approved, violations = validate_command("", {})
        assert approved is False

    def test_none_params_treated_as_empty(self, tmp_schema_dir: Path):
        reload(tmp_schema_dir)
        approved, violations = validate_command("no_params", None)
        assert approved is True
        assert violations == []


# ===================================================================
# Test: validate_command — Required params
# ===================================================================


class TestRequiredParams:
    """Required fields must be present."""

    def test_missing_required_param(self, tmp_schema_dir: Path):
        reload(tmp_schema_dir)
        approved, violations = validate_command("test_op", {})
        assert approved is False
        assert any("name" in v and "required" in v for v in violations)

    def test_required_param_present(self, tmp_schema_dir: Path):
        reload(tmp_schema_dir)
        approved, violations = validate_command("test_op", {"name": "hello"})
        assert approved is True
        assert violations == []


# ===================================================================
# Test: validate_command — Additional properties rejected
# ===================================================================


class TestAdditionalProperties:
    """Extra fields must be rejected."""

    def test_extra_field_rejected(self, tmp_schema_dir: Path):
        reload(tmp_schema_dir)
        approved, violations = validate_command(
            "test_op", {"name": "hello", "sneaky": True}
        )
        assert approved is False
        assert any("sneaky" in v and "unexpected" in v for v in violations)

    def test_no_extra_fields_passes(self, tmp_schema_dir: Path):
        reload(tmp_schema_dir)
        approved, violations = validate_command("test_op", {"name": "hello"})
        assert approved is True


# ===================================================================
# Test: validate_command — Type checking
# ===================================================================


class TestTypeChecking:
    """Values must match declared types."""

    def test_wrong_type_rejected(self, tmp_schema_dir: Path):
        reload(tmp_schema_dir)
        approved, violations = validate_command(
            "test_op", {"name": "hello", "count": "not-an-int"}
        )
        assert approved is False
        assert any("integer" in v for v in violations)

    def test_correct_type_passes(self, tmp_schema_dir: Path):
        reload(tmp_schema_dir)
        approved, violations = validate_command(
            "test_op", {"name": "hello", "count": 42}
        )
        assert approved is True

    def test_bool_not_treated_as_int(self, tmp_schema_dir: Path):
        reload(tmp_schema_dir)
        approved, violations = validate_command(
            "test_op", {"name": "hello", "count": True}
        )
        assert approved is False

    def test_bool_not_treated_as_number(self):
        assert _type_matches(True, "number") is False

    def test_array_type_validated(self, tmp_schema_dir: Path):
        reload(tmp_schema_dir)
        approved, violations = validate_command(
            "test_op", {"name": "hello", "tags": "not-a-list"}
        )
        assert approved is False
        assert any("array" in v for v in violations)

    def test_array_items_validated(self, tmp_schema_dir: Path):
        reload(tmp_schema_dir)
        approved, violations = validate_command(
            "test_op", {"name": "hello", "tags": ["ok", 123]}
        )
        assert approved is False
        assert any("string" in v for v in violations)

    def test_valid_array_passes(self, tmp_schema_dir: Path):
        reload(tmp_schema_dir)
        approved, violations = validate_command(
            "test_op", {"name": "hello", "tags": ["a", "b"]}
        )
        assert approved is True


# ===================================================================
# Test: validate_command — Enum enforcement
# ===================================================================


class TestEnumEnforcement:
    """Enum values must be one of the declared set."""

    def test_invalid_enum_rejected(self, tmp_schema_dir: Path):
        reload(tmp_schema_dir)
        approved, violations = validate_command(
            "test_op", {"name": "hello", "level": "extreme"}
        )
        assert approved is False
        assert any("must be one of" in v for v in violations)

    def test_valid_enum_passes(self, tmp_schema_dir: Path):
        reload(tmp_schema_dir)
        approved, violations = validate_command(
            "test_op", {"name": "hello", "level": "high"}
        )
        assert approved is True


# ===================================================================
# Test: validate_command — minLength enforcement
# ===================================================================


class TestMinLength:
    """String minLength must be enforced."""

    def test_empty_string_rejected_when_minlength(self, tmp_schema_dir: Path):
        reload(tmp_schema_dir)
        approved, violations = validate_command("test_op", {"name": ""})
        assert approved is False
        assert any("too short" in v for v in violations)

    def test_nonempty_string_passes(self, tmp_schema_dir: Path):
        reload(tmp_schema_dir)
        approved, violations = validate_command("test_op", {"name": "x"})
        assert approved is True


# ===================================================================
# Test: validate_command against real schemas
# ===================================================================


class TestRealSchemaValidation:
    """Validate against the actual production schemas."""

    def test_update_user_role_valid(self, real_schemas: int):
        approved, violations = validate_command(
            "update_user_role", {"user_id": "alice", "new_role": "operator"}
        )
        assert approved is True, violations

    def test_update_user_role_missing_user_id(self, real_schemas: int):
        approved, violations = validate_command(
            "update_user_role", {"new_role": "operator"}
        )
        assert approved is False
        assert any("user_id" in v for v in violations)

    def test_update_user_role_invalid_role(self, real_schemas: int):
        approved, violations = validate_command(
            "update_user_role", {"user_id": "alice", "new_role": "superadmin"}
        )
        assert approved is False
        assert any("must be one of" in v for v in violations)

    def test_update_user_role_extra_field(self, real_schemas: int):
        approved, violations = validate_command(
            "update_user_role", {"user_id": "alice", "new_role": "operator", "hack": 1}
        )
        assert approved is False
        assert any("unexpected" in v for v in violations)

    def test_deactivate_user_valid(self, real_schemas: int):
        approved, violations = validate_command(
            "deactivate_user", {"user_id": "bob"}
        )
        assert approved is True, violations

    def test_resolve_escalation_valid(self, real_schemas: int):
        approved, violations = validate_command(
            "resolve_escalation",
            {"escalation_id": "esc-1", "resolution": "approved", "rationale": "ok"},
        )
        assert approved is True, violations

    def test_resolve_escalation_bad_resolution(self, real_schemas: int):
        approved, violations = validate_command(
            "resolve_escalation",
            {"escalation_id": "esc-1", "resolution": "maybe", "rationale": "hmm"},
        )
        assert approved is False
        assert any("must be one of" in v for v in violations)

    def test_trigger_daemon_task_no_params(self, real_schemas: int):
        approved, violations = validate_command("trigger_daemon_task", {})
        assert approved is True, violations

    def test_invite_user_valid(self, real_schemas: int):
        approved, violations = validate_command(
            "invite_user", {"username": "charlie", "role": "user"}
        )
        assert approved is True, violations

    def test_module_status_valid(self, real_schemas: int):
        approved, violations = validate_command(
            "module_status", {"domain_id": "education"}
        )
        assert approved is True, violations

    def test_explain_reasoning_valid(self, real_schemas: int):
        approved, violations = validate_command(
            "explain_reasoning", {"event_id": "evt-42"}
        )
        assert approved is True, violations

    def test_daemon_status_empty_params(self, real_schemas: int):
        approved, violations = validate_command("daemon_status", {})
        assert approved is True, violations

    def test_commit_domain_physics_valid(self, real_schemas: int):
        approved, violations = validate_command(
            "commit_domain_physics", {"domain_id": "agriculture"}
        )
        assert approved is True, violations

    def test_assign_domain_role_valid(self, real_schemas: int):
        approved, violations = validate_command(
            "assign_domain_role",
            {"user_id": "u1", "module_id": "m1", "domain_role": "operator"},
        )
        assert approved is True, violations

    def test_list_escalations_empty_params(self, real_schemas: int):
        approved, violations = validate_command("list_escalations", {})
        assert approved is True, violations


# ===================================================================
# Test: _type_matches low-level
# ===================================================================


class TestTypeMatchesHelper:
    def test_string(self):
        assert _type_matches("hello", "string") is True
        assert _type_matches(42, "string") is False

    def test_integer(self):
        assert _type_matches(42, "integer") is True
        assert _type_matches(3.14, "integer") is False

    def test_number(self):
        assert _type_matches(42, "number") is True
        assert _type_matches(3.14, "number") is True
        assert _type_matches("42", "number") is False

    def test_boolean(self):
        assert _type_matches(True, "boolean") is True
        assert _type_matches(1, "boolean") is False

    def test_array(self):
        assert _type_matches([], "array") is True
        assert _type_matches({}, "array") is False

    def test_object(self):
        assert _type_matches({}, "object") is True
        assert _type_matches([], "object") is False

    def test_unknown_type_permissive(self):
        assert _type_matches("anything", "unknown_kind") is True


# ===================================================================
# Test: _validate_object / _validate_value low-level
# ===================================================================


class TestValidateObjectHelper:
    def test_non_object_value_for_object_schema(self):
        violations: list[str] = []
        _validate_object("not-a-dict", {"type": "object"}, "root", violations)
        assert len(violations) == 1
        assert "expected object" in violations[0]

    def test_nested_object_validated(self):
        schema = {
            "type": "object",
            "properties": {
                "inner": {
                    "type": "object",
                    "required": ["x"],
                    "properties": {"x": {"type": "integer"}},
                }
            },
        }
        violations: list[str] = []
        _validate_object({"inner": {}}, schema, "root", violations)
        assert any("x" in v and "required" in v for v in violations)
