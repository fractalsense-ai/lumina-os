"""Tests for escalation routing to assigned teachers.

Covers:
- list_escalations: teacher sees only own + unassigned escalations
- list_escalations: DA sees all governed escalations regardless of target
- resolve_escalation: teacher cannot resolve another teacher's escalation
- resolve_escalation: teacher can resolve unassigned escalations
- education_escalation_context: returns assigned_teacher_id and assigned_room_id
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]

# ── Load escalation_handlers via importlib ────────────────────
_ESC_PATH = _REPO_ROOT / "domain-packs" / "education" / "controllers" / "escalation_handlers.py"
_esc_spec = importlib.util.spec_from_file_location("edu_esc_handlers", str(_ESC_PATH))
_esc_mod = importlib.util.module_from_spec(_esc_spec)  # type: ignore[arg-type]
sys.modules["edu_esc_handlers"] = _esc_mod
_esc_spec.loader.exec_module(_esc_mod)  # type: ignore[union-attr]

list_escalations = _esc_mod.list_escalations
resolve_escalation = _esc_mod.resolve_escalation

# ── Load education_escalation_context ─────────────────────────
_CTX_PATH = _REPO_ROOT / "domain-packs" / "education" / "controllers" / "education_escalation_context.py"
_ctx_spec = importlib.util.spec_from_file_location("edu_esc_ctx", str(_CTX_PATH))
_ctx_mod = importlib.util.module_from_spec(_ctx_spec)  # type: ignore[arg-type]
sys.modules["edu_esc_ctx"] = _ctx_mod
_ctx_spec.loader.exec_module(_ctx_mod)  # type: ignore[union-attr]

education_escalation_context = _ctx_mod.education_escalation_context


# ── Test helpers ──────────────────────────────────────────────

_MODULE_ID = "domain/edu/algebra-level-1/v1"


def _make_physics_file(role_id: str = "teacher", receive_escalations: bool = True) -> str:
    """Create a temporary physics JSON file with role capabilities."""
    physics = {
        "domain_roles": {
            "roles": [
                {
                    "role_id": role_id,
                    "scoped_capabilities": {
                        "receive_escalations": receive_escalations,
                    },
                }
            ]
        }
    }
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    json.dump(physics, tmp)
    tmp.close()
    return tmp.name


def _mock_registry(physics_path: str) -> MagicMock:
    reg = MagicMock()
    reg.list_domains.return_value = [
        {"domain_id": "education"},
    ]
    reg.list_modules_for_domain.return_value = [
        {
            "module_id": _MODULE_ID,
            "domain_physics_path": physics_path,
        },
    ]
    return reg


def _mock_persistence(escalations: list[dict]) -> MagicMock:
    p = MagicMock()
    p.query_escalations = MagicMock(return_value=list(escalations))
    p.append_log_record = MagicMock()
    p.get_system_ledger_path = MagicMock(return_value="test.jsonl")
    p.load_subject_profile = MagicMock(return_value={})
    p.save_subject_profile = MagicMock()
    return p


def _teacher_user(sub: str = "teacher1") -> dict[str, Any]:
    return {
        "sub": sub,
        "role": "user",
        "domain_roles": {_MODULE_ID: "teacher"},
    }


def _da_user(sub: str = "da1") -> dict[str, Any]:
    return {
        "sub": sub,
        "role": "domain_authority",
        "governed_modules": [_MODULE_ID],
    }


def _root_user() -> dict[str, Any]:
    return {"sub": "root", "role": "root"}


def _esc_record(
    record_id: str,
    target_id: str | None = None,
    domain_pack_id: str = _MODULE_ID,
    status: str = "open",
) -> dict[str, Any]:
    rec = {
        "record_type": "EscalationRecord",
        "record_id": record_id,
        "domain_pack_id": domain_pack_id,
        "status": status,
        "trigger": "test-trigger",
        "session_id": "sess-1",
        "timestamp_utc": "2025-01-01T00:00:00+00:00",
    }
    if target_id is not None:
        rec["escalation_target_id"] = target_id
    return rec


# ═════════════════════════════════════════════════════════════
# Phase 1: list_escalations teacher scoping
# ═════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestListEscalationsTeacherScoping:
    """Teacher with receive_escalations sees own + unassigned only."""

    @pytest.fixture(autouse=True)
    def _physics(self):
        self.physics_path = _make_physics_file("teacher", receive_escalations=True)

    def test_teacher_sees_own_escalations(self) -> None:
        esc = [
            _esc_record("e1", target_id="teacher1"),
            _esc_record("e2", target_id="teacher2"),
        ]
        result = asyncio.run(list_escalations(
            user_data=_teacher_user("teacher1"),
            persistence=_mock_persistence(esc),
            domain_registry=_mock_registry(self.physics_path),
        ))
        assert isinstance(result, list)
        ids = [r["record_id"] for r in result]
        assert "e1" in ids
        assert "e2" not in ids

    def test_teacher_sees_unassigned_escalations(self) -> None:
        esc = [
            _esc_record("e1", target_id="teacher1"),
            _esc_record("e2", target_id=None),  # no target
            _esc_record("e3"),  # key absent
        ]
        result = asyncio.run(list_escalations(
            user_data=_teacher_user("teacher1"),
            persistence=_mock_persistence(esc),
            domain_registry=_mock_registry(self.physics_path),
        ))
        ids = [r["record_id"] for r in result]
        assert set(ids) == {"e1", "e2", "e3"}

    def test_teacher_does_not_see_other_teachers_escalations(self) -> None:
        esc = [
            _esc_record("e1", target_id="teacher2"),
            _esc_record("e2", target_id="teacher3"),
        ]
        result = asyncio.run(list_escalations(
            user_data=_teacher_user("teacher1"),
            persistence=_mock_persistence(esc),
            domain_registry=_mock_registry(self.physics_path),
        ))
        assert result == []

    def test_teacher_empty_target_id_falls_through(self) -> None:
        """Empty string target_id is treated as unassigned."""
        esc = [_esc_record("e1")]
        esc[0]["escalation_target_id"] = ""
        result = asyncio.run(list_escalations(
            user_data=_teacher_user("teacher1"),
            persistence=_mock_persistence(esc),
            domain_registry=_mock_registry(self.physics_path),
        ))
        assert len(result) == 1


@pytest.mark.unit
class TestListEscalationsDAScope:
    """DA sees all governed escalations regardless of escalation_target_id."""

    @pytest.fixture(autouse=True)
    def _physics(self):
        self.physics_path = _make_physics_file("teacher", receive_escalations=True)

    def test_da_sees_all_governed(self) -> None:
        esc = [
            _esc_record("e1", target_id="teacher1"),
            _esc_record("e2", target_id="teacher2"),
            _esc_record("e3", target_id=None),
        ]
        result = asyncio.run(list_escalations(
            user_data=_da_user("da1"),
            persistence=_mock_persistence(esc),
            domain_registry=_mock_registry(self.physics_path),
        ))
        assert len(result) == 3

    def test_da_filtered_by_governed_modules(self) -> None:
        other_module = "domain/edu/other/v1"
        esc = [
            _esc_record("e1", target_id="teacher1", domain_pack_id=_MODULE_ID),
            _esc_record("e2", target_id="teacher1", domain_pack_id=other_module),
        ]
        result = asyncio.run(list_escalations(
            user_data=_da_user("da1"),
            persistence=_mock_persistence(esc),
            domain_registry=_mock_registry(self.physics_path),
        ))
        ids = [r["record_id"] for r in result]
        assert "e1" in ids
        assert "e2" not in ids


@pytest.mark.unit
class TestListEscalationsRootScope:
    """Root sees all escalations, no scoping."""

    def test_root_sees_all(self) -> None:
        esc = [
            _esc_record("e1", target_id="teacher1"),
            _esc_record("e2", target_id="teacher2"),
            _esc_record("e3"),
        ]
        result = asyncio.run(list_escalations(
            user_data=_root_user(),
            persistence=_mock_persistence(esc),
        ))
        assert len(result) == 3


# ═════════════════════════════════════════════════════════════
# Phase 2: resolve_escalation teacher scoping
# ═════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestResolveEscalationTeacherScope:
    """Teacher can only resolve own or unassigned escalations."""

    @pytest.fixture(autouse=True)
    def _physics(self):
        self.physics_path = _make_physics_file("teacher", receive_escalations=True)

    def test_teacher_cannot_resolve_other_teachers_escalation(self) -> None:
        esc = [_esc_record("e1", target_id="teacher2")]
        result = asyncio.run(resolve_escalation(
            user_data=_teacher_user("teacher1"),
            persistence=_mock_persistence(esc),
            domain_registry=_mock_registry(self.physics_path),
            path_params={"escalation_id": "e1"},
            body={"decision": "approve", "reasoning": "ok"},
        ))
        assert result.get("__status") == 403
        assert "Not authorized for this escalation" in result.get("detail", "")

    def test_teacher_can_resolve_own_escalation(self) -> None:
        esc = [_esc_record("e1", target_id="teacher1")]
        result = asyncio.run(resolve_escalation(
            user_data=_teacher_user("teacher1"),
            persistence=_mock_persistence(esc),
            domain_registry=_mock_registry(self.physics_path),
            path_params={"escalation_id": "e1"},
            body={"decision": "approve", "reasoning": "good work"},
        ))
        assert "__status" not in result
        assert result.get("decision") == "approve"

    def test_teacher_can_resolve_unassigned_escalation(self) -> None:
        esc = [_esc_record("e1")]  # no escalation_target_id key
        result = asyncio.run(resolve_escalation(
            user_data=_teacher_user("teacher1"),
            persistence=_mock_persistence(esc),
            domain_registry=_mock_registry(self.physics_path),
            path_params={"escalation_id": "e1"},
            body={"decision": "reject", "reasoning": "not needed"},
        ))
        assert "__status" not in result
        assert result.get("decision") == "reject"

    def test_da_can_resolve_any_governed_escalation(self) -> None:
        esc = [_esc_record("e1", target_id="teacher2")]
        result = asyncio.run(resolve_escalation(
            user_data=_da_user("da1"),
            persistence=_mock_persistence(esc),
            domain_registry=_mock_registry(self.physics_path),
            path_params={"escalation_id": "e1"},
            body={"decision": "defer", "reasoning": "needs review"},
        ))
        assert "__status" not in result
        assert result.get("decision") == "defer"


# ═════════════════════════════════════════════════════════════
# Phase 3: education_escalation_context enrichment
# ═════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestEscalationContextEnrichment:
    """education_escalation_context returns routing fields from profile."""

    def test_returns_assigned_teacher_id(self) -> None:
        writer = MagicMock()
        writer._profile = {
            "subject_id": "student1",
            "assigned_teacher_id": "teacher1",
            "assigned_room_id": "room-42",
        }
        orch = MagicMock()
        orch._writer = writer

        ctx = education_escalation_context(orchestrator=orch, domain_id="education")
        assert ctx["actor_pseudonym"] == "student1"
        assert ctx["assigned_teacher_id"] == "teacher1"
        assert ctx["assigned_room_id"] == "room-42"

    def test_returns_empty_when_no_fields(self) -> None:
        writer = MagicMock()
        writer._profile = {"subject_id": "student2"}
        orch = MagicMock()
        orch._writer = writer

        ctx = education_escalation_context(orchestrator=orch, domain_id="education")
        assert ctx["assigned_teacher_id"] == ""
        assert ctx["assigned_room_id"] == ""

    def test_returns_defaults_without_writer(self) -> None:
        orch = MagicMock(spec=[])  # no _writer attribute

        ctx = education_escalation_context(orchestrator=orch, domain_id="education")
        assert ctx["actor_pseudonym"] == ""
        assert ctx["assigned_teacher_id"] == ""
        assert ctx["assigned_room_id"] == ""
        assert ctx["domain_id"] == "education"
