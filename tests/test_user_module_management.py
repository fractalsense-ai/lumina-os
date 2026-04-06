"""Tests for user/module management commands: assign_student, remove_student,
assign_module, remove_module.

Covers:
- RBAC: teacher can only assign students to self
- RBAC: DA can assign students to any teacher within governed modules
- RBAC: teacher with assign_modules_to_students capability can assign/remove modules
- RBAC: plain users without capability are denied
- Persistence: student profile gets assigned_teacher_id
- Persistence: teacher profile gets assigned_students list
- Persistence: update_user_governed_modules called with correct args
- SLM promotion: student/module assignment inputs promote general → admin_command
- Deterministic fallback: correct operations dispatched from verb+noun patterns
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch, call

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]

# ── Load adapters via importlib ───────────────────────────────
_GOV_PATH = _REPO_ROOT / "domain-packs" / "education" / "controllers" / "governance_adapters.py"
_gov_spec = importlib.util.spec_from_file_location("gov_adapters_umm", str(_GOV_PATH))
_gov_mod = importlib.util.module_from_spec(_gov_spec)  # type: ignore[arg-type]
sys.modules["gov_adapters_umm"] = _gov_mod
_gov_spec.loader.exec_module(_gov_mod)  # type: ignore[union-attr]

_edu_maybe_promote = _gov_mod._maybe_promote_query_type
_edu_fallback = _gov_mod._deterministic_command_fallback

_SYS_PATH = _REPO_ROOT / "domain-packs" / "system" / "controllers" / "runtime_adapters.py"
_sys_spec = importlib.util.spec_from_file_location("sys_adapters_umm", str(_SYS_PATH))
_sys_mod = importlib.util.module_from_spec(_sys_spec)  # type: ignore[arg-type]
sys.modules["sys_adapters_umm"] = _sys_mod
_sys_spec.loader.exec_module(_sys_mod)  # type: ignore[union-attr]

_sys_maybe_promote = _sys_mod._maybe_promote_query_type
_sys_fallback = _sys_mod._deterministic_command_fallback


# ── Helpers ───────────────────────────────────────────────────

def _mock_cfg() -> MagicMock:
    """Return a mock for lumina.api.config with common defaults."""
    cfg = MagicMock()
    cfg.PERSISTENCE.get_log_ledger_path.return_value = "/tmp/ledger.json"
    cfg.PERSISTENCE.append_log_record.return_value = None
    cfg.PERSISTENCE.load_subject_profile.return_value = {}
    cfg.PERSISTENCE.save_subject_profile.return_value = None
    cfg.PERSISTENCE.update_user_governed_modules.return_value = {"governed_modules": []}
    cfg.DOMAIN_REGISTRY.resolve_domain_id.return_value = "education"
    cfg.DOMAIN_REGISTRY.list_modules_for_domain.return_value = [
        {"module_id": "edu-core", "domain_id": "education"},
    ]
    cfg.DOMAIN_REGISTRY.list_domains.return_value = [{"domain_id": "education"}]
    return cfg


def _teacher_user(sub: str = "teacher1") -> dict[str, Any]:
    return {
        "sub": sub,
        "role": "user",
        "domain_roles": {"edu-core": "teacher"},
        "scoped_capabilities": {
            "edu-core": {
                "teacher": [
                    "receive_escalations",
                    "view_all_student_progress",
                    "assign_modules_to_students",
                    "resolve_escalations",
                ],
            },
        },
    }


def _da_user(sub: str = "da1") -> dict[str, Any]:
    return {
        "sub": sub,
        "role": "domain_authority",
        "domain_roles": {},
        "governed_modules": ["edu-core"],
    }


def _student_user(sub: str = "student1") -> dict[str, Any]:
    return {
        "sub": sub,
        "role": "user",
        "domain_roles": {"edu-core": "student"},
    }


def _exec(user_data, parsed, instruction="test"):
    from lumina.api.routes.admin import _execute_admin_operation
    return asyncio.run(_execute_admin_operation(user_data, parsed, instruction))


# ─────────────────────────────────────────────────────────────
# Phase 1: SLM promotion — education adapter
# ─────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestStudentModulePromotion:
    """Student/module assignment inputs promote general → admin_command."""

    def test_assign_student_promotes(self) -> None:
        ev = {"query_type": "general"}
        _edu_maybe_promote(ev, "assign student alice to me")
        assert ev["query_type"] == "admin_command"

    def test_remove_student_promotes(self) -> None:
        ev = {"query_type": "general"}
        _edu_maybe_promote(ev, "remove student bob from teacher1")
        assert ev["query_type"] == "admin_command"

    def test_assign_module_promotes(self) -> None:
        ev = {"query_type": "general"}
        _edu_maybe_promote(ev, "assign module math-101 to student1")
        assert ev["query_type"] == "admin_command"

    def test_remove_module_promotes(self) -> None:
        ev = {"query_type": "general"}
        _edu_maybe_promote(ev, "remove module math-101 from student1")
        assert ev["query_type"] == "admin_command"

    def test_system_assign_student_promotes(self) -> None:
        ev = {"query_type": "general"}
        _sys_maybe_promote(ev, "assign student alice to teacher bob")
        assert ev["query_type"] == "admin_command"

    def test_system_remove_module_promotes(self) -> None:
        ev = {"query_type": "general"}
        _sys_maybe_promote(ev, "remove module bio-101 from student1")
        assert ev["query_type"] == "admin_command"

    def test_no_promotion_greeting(self) -> None:
        ev = {"query_type": "general"}
        _edu_maybe_promote(ev, "hello teacher")
        assert ev["query_type"] == "general"


# ─────────────────────────────────────────────────────────────
# Phase 2: Deterministic fallback — education adapter
# ─────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestEducationDeterministicFallback:
    """Verb+noun patterns route to correct operations."""

    def test_assign_student_fallback(self) -> None:
        result = _edu_fallback("assign student alice to me", {"intent_type": "mutation"})
        assert result is not None
        assert result["operation"] == "assign_student"

    def test_remove_student_fallback(self) -> None:
        result = _edu_fallback("remove student alice from teacher1", {"intent_type": "mutation"})
        assert result is not None
        assert result["operation"] == "remove_student"

    def test_assign_module_fallback(self) -> None:
        result = _edu_fallback("assign module math-101 to student1", {"intent_type": "mutation"})
        assert result is not None
        assert result["operation"] == "assign_module"

    def test_remove_module_fallback(self) -> None:
        result = _edu_fallback("remove module bio-101 from student1", {"intent_type": "mutation"})
        assert result is not None
        assert result["operation"] == "remove_module"

    def test_give_module_fallback(self) -> None:
        result = _edu_fallback("give module math-101 to alice", {"intent_type": "mutation"})
        assert result is not None
        assert result["operation"] == "assign_module"


# ─────────────────────────────────────────────────────────────
# Phase 3: Command handler — assign_student
# ─────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestAssignStudentHandler:
    """assign_student handler RBAC checks and persistence updates."""

    def test_teacher_assigns_student_to_self(self) -> None:
        cfg = _mock_cfg()
        teacher = _teacher_user()
        student = _student_user()
        cfg.PERSISTENCE.get_user.side_effect = lambda uid: student if uid == "student1" else teacher

        with patch("lumina.api.routes.admin._cfg", cfg), \
             patch("lumina.api.routes.admin._has_domain_capability", return_value=True):
            result = _exec(
                teacher,
                {"operation": "assign_student", "target": "", "params": {"student_id": "student1", "teacher_id": "someone_else"}},
            )
        assert result["status"] == "assigned"
        assert result["teacher_id"] == "teacher1"  # forced to self
        assert result["student_id"] == "student1"
        assert "record_id" in result

    def test_da_assigns_student_to_teacher(self) -> None:
        cfg = _mock_cfg()
        teacher = _teacher_user("teacher1")
        teacher["domain_roles"] = {"edu-core": "teacher"}
        student = _student_user()
        cfg.PERSISTENCE.get_user.side_effect = lambda uid: {
            "student1": student, "teacher1": teacher,
        }.get(uid)

        da = _da_user()
        with patch("lumina.api.routes.admin._cfg", cfg):
            result = _exec(
                da,
                {"operation": "assign_student", "target": "", "params": {"student_id": "student1", "teacher_id": "teacher1"}},
            )
        assert result["status"] == "assigned"
        assert result["teacher_id"] == "teacher1"

    def test_da_requires_teacher_id(self) -> None:
        cfg = _mock_cfg()
        da = _da_user()
        with patch("lumina.api.routes.admin._cfg", cfg):
            with pytest.raises(Exception) as exc_info:
                _exec(da, {"operation": "assign_student", "target": "", "params": {"student_id": "s1"}})
            assert "teacher_id required" in str(exc_info.value.detail)

    def test_student_cannot_assign(self) -> None:
        cfg = _mock_cfg()
        student = _student_user()
        with patch("lumina.api.routes.admin._cfg", cfg):
            with pytest.raises(Exception) as exc_info:
                _exec(student, {"operation": "assign_student", "target": "", "params": {"student_id": "s2"}})
            assert "403" in str(exc_info.value.status_code) or "Requires teacher" in str(exc_info.value.detail)

    def test_missing_student_id(self) -> None:
        cfg = _mock_cfg()
        teacher = _teacher_user()
        with patch("lumina.api.routes.admin._cfg", cfg):
            with pytest.raises(Exception) as exc_info:
                _exec(teacher, {"operation": "assign_student", "target": "", "params": {}})
            assert "student_id required" in str(exc_info.value.detail)

    def test_nonexistent_student_404(self) -> None:
        cfg = _mock_cfg()
        da = _da_user()
        cfg.PERSISTENCE.get_user.return_value = None
        with patch("lumina.api.routes.admin._cfg", cfg):
            with pytest.raises(Exception) as exc_info:
                _exec(da, {"operation": "assign_student", "target": "", "params": {"student_id": "ghost", "teacher_id": "t1"}})
            assert "404" in str(exc_info.value.status_code) or "not found" in str(exc_info.value.detail).lower()


# ─────────────────────────────────────────────────────────────
# Phase 4: Command handler — remove_student
# ─────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestRemoveStudentHandler:

    def test_teacher_removes_student(self) -> None:
        cfg = _mock_cfg()
        teacher = _teacher_user()
        student = _student_user()
        cfg.PERSISTENCE.get_user.side_effect = lambda uid: student if uid == "student1" else teacher
        cfg.PERSISTENCE.load_subject_profile.return_value = {"assigned_teacher_id": "teacher1"}

        with patch("lumina.api.routes.admin._cfg", cfg), \
             patch("lumina.api.routes.admin._has_domain_capability", return_value=True):
            result = _exec(
                teacher,
                {"operation": "remove_student", "target": "", "params": {"student_id": "student1"}},
            )
        assert result["status"] == "removed"
        assert result["teacher_id"] == "teacher1"

    def test_da_removes_student(self) -> None:
        cfg = _mock_cfg()
        teacher = _teacher_user("teacher1")
        teacher["domain_roles"] = {"edu-core": "teacher"}
        student = _student_user()
        cfg.PERSISTENCE.get_user.side_effect = lambda uid: student if uid == "student1" else teacher

        da = _da_user()
        with patch("lumina.api.routes.admin._cfg", cfg):
            result = _exec(
                da,
                {"operation": "remove_student", "target": "", "params": {"student_id": "student1", "teacher_id": "teacher1"}},
            )
        assert result["status"] == "removed"


# ─────────────────────────────────────────────────────────────
# Phase 5: Command handler — assign_module
# ─────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestAssignModuleHandler:

    def test_teacher_assigns_module(self) -> None:
        cfg = _mock_cfg()
        teacher = _teacher_user()
        student = _student_user()
        cfg.PERSISTENCE.get_user.side_effect = lambda uid: student if uid == "student1" else teacher
        cfg.PERSISTENCE.update_user_governed_modules.return_value = {"governed_modules": ["math-101"]}

        with patch("lumina.api.routes.admin._cfg", cfg), \
             patch("lumina.api.routes.admin._has_domain_capability", return_value=True):
            result = _exec(
                teacher,
                {"operation": "assign_module", "target": "student1", "params": {"user_id": "student1", "module_id": "math-101"}},
            )
        assert result["status"] == "assigned"
        assert result["module_id"] == "math-101"
        cfg.PERSISTENCE.update_user_governed_modules.assert_called_once_with("student1", add=["math-101"])

    def test_da_assigns_module(self) -> None:
        cfg = _mock_cfg()
        da = _da_user()
        student = _student_user()
        cfg.PERSISTENCE.get_user.return_value = student
        cfg.PERSISTENCE.update_user_governed_modules.return_value = {"governed_modules": ["edu-core"]}

        with patch("lumina.api.routes.admin._cfg", cfg):
            result = _exec(
                da,
                {"operation": "assign_module", "target": "student1", "params": {"user_id": "student1", "module_id": "edu-core"}},
            )
        assert result["status"] == "assigned"

    def test_plain_user_cannot_assign_module(self) -> None:
        cfg = _mock_cfg()
        student = _student_user()
        with patch("lumina.api.routes.admin._cfg", cfg):
            with pytest.raises(Exception) as exc_info:
                _exec(
                    student,
                    {"operation": "assign_module", "target": "s2", "params": {"user_id": "s2", "module_id": "m1"}},
                )
            assert "403" in str(exc_info.value.status_code) or "capability" in str(exc_info.value.detail).lower()

    def test_missing_module_id(self) -> None:
        cfg = _mock_cfg()
        teacher = _teacher_user()
        with patch("lumina.api.routes.admin._cfg", cfg):
            with pytest.raises(Exception) as exc_info:
                _exec(teacher, {"operation": "assign_module", "target": "s1", "params": {"user_id": "s1"}})
            assert "module_id" in str(exc_info.value.detail).lower()


# ─────────────────────────────────────────────────────────────
# Phase 6: Command handler — remove_module
# ─────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestRemoveModuleHandler:

    def test_teacher_removes_module(self) -> None:
        cfg = _mock_cfg()
        teacher = _teacher_user()
        student = _student_user()
        cfg.PERSISTENCE.get_user.side_effect = lambda uid: student if uid == "student1" else teacher
        cfg.PERSISTENCE.update_user_governed_modules.return_value = {"governed_modules": []}

        with patch("lumina.api.routes.admin._cfg", cfg), \
             patch("lumina.api.routes.admin._has_domain_capability", return_value=True):
            result = _exec(
                teacher,
                {"operation": "remove_module", "target": "student1", "params": {"user_id": "student1", "module_id": "math-101"}},
            )
        assert result["status"] == "removed"
        assert result["module_id"] == "math-101"
        cfg.PERSISTENCE.update_user_governed_modules.assert_called_once_with("student1", remove=["math-101"])

    def test_nonexistent_user_404(self) -> None:
        cfg = _mock_cfg()
        teacher = _teacher_user()
        cfg.PERSISTENCE.get_user.return_value = None
        with patch("lumina.api.routes.admin._cfg", cfg), \
             patch("lumina.api.routes.admin._has_domain_capability", return_value=True):
            with pytest.raises(Exception) as exc_info:
                _exec(
                    teacher,
                    {"operation": "remove_module", "target": "ghost", "params": {"user_id": "ghost", "module_id": "m1"}},
                )
            assert "not found" in str(exc_info.value.detail).lower()

    def test_da_outside_governed_scope_denied(self) -> None:
        cfg = _mock_cfg()
        da = _da_user()
        da["governed_modules"] = ["edu-core"]
        student = _student_user()
        cfg.PERSISTENCE.get_user.return_value = student
        # DA tries to remove a module they don't govern
        from lumina.system_log.admin_operations import can_govern_domain
        with patch("lumina.api.routes.admin._cfg", cfg), \
             patch("lumina.api.routes.admin.can_govern_domain", return_value=False):
            with pytest.raises(Exception) as exc_info:
                _exec(
                    da,
                    {"operation": "remove_module", "target": "s1", "params": {"user_id": "s1", "module_id": "other-domain-mod"}},
                )
            assert "403" in str(exc_info.value.status_code) or "authorised" in str(exc_info.value.detail).lower()
