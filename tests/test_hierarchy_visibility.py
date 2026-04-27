"""Tests for hierarchy-based visibility in list_users.

Covers:
- Students see teachers + TAs only (not DA, not other students)
- TAs see teachers + students (not DA)
- Teachers see everyone (DA + teachers + TAs + students)
- DA sees everyone in governed modules (unchanged)
- Root sees everyone in domain (unchanged)
- user_id stripped for low-privilege callers (students/guardians)
- Auto-injection of domain_id from session context
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]


# ── Fixtures ──────────────────────────────────────────────────

def _mock_cfg(users: list[dict[str, Any]] | None = None) -> MagicMock:
    """Return a mock _cfg with PERSISTENCE and DOMAIN_REGISTRY."""
    cfg = MagicMock()
    cfg.PERSISTENCE.list_users.return_value = users or []
    cfg.PERSISTENCE.get_log_ledger_path.return_value = "/tmp/ledger.json"
    cfg.PERSISTENCE.append_log_record.return_value = None
    cfg.DOMAIN_REGISTRY.resolve_domain_id.return_value = "education"

    # Include both governance modules and a subject module (algebra-1)
    # so that "student" role_id can be resolved via domain-physics.json.
    edu_modules = []
    module_names = [
        "domain-authority", "teacher", "teaching-assistant", "guardian", "algebra-1",
    ]
    for mod_name in module_names:
        dp_path = f"model-packs/education/modules/{mod_name}/domain-physics.json"
        full = _REPO_ROOT / dp_path
        if full.exists():
            edu_modules.append({
                "module_id": mod_name,
                "domain_id": "education",
                "domain_physics_path": dp_path,
            })
    cfg.DOMAIN_REGISTRY.list_modules_for_domain.return_value = edu_modules
    cfg.DOMAIN_REGISTRY._repo_root = str(_REPO_ROOT)
    cfg.DOMAIN_REGISTRY._domains = {
        "education": {
            "runtime_config_path": "model-packs/education/cfg/runtime-config.yaml",
        },
    }

    return cfg


def _make_user(
    user_id: str,
    role: str = "user",
    domain_roles: dict[str, str] | None = None,
    governed_modules: list[str] | None = None,
    active: bool = True,
) -> dict[str, Any]:
    return {
        "user_id": user_id,
        "username": user_id,
        "role": role,
        "domain_roles": domain_roles or {},
        "governed_modules": governed_modules or [],
        "active": active,
    }


# Sample users — role_ids match actual domain-physics.json definitions:
#   domain_authority (level 0), teacher (level 1),
#   teaching_assistant (level 2), student (level 3 — from algebra-1)
_DA = _make_user(
    "da1", role="admin",
    governed_modules=["domain-authority", "teacher", "teaching-assistant", "guardian", "algebra-1"],
)
_TEACHER = _make_user("teacher1", domain_roles={"teacher": "teacher"})
_TA = _make_user("ta1", domain_roles={"teaching-assistant": "teaching_assistant"})
_STUDENT = _make_user("student1", domain_roles={"algebra-1": "student"})
_STUDENT2 = _make_user("student2", domain_roles={"algebra-1": "student"})
_ROOT = _make_user("root1", role="root")
_ALL_USERS = [_DA, _TEACHER, _TA, _STUDENT, _STUDENT2, _ROOT]

# Users with education domain presence (root has no domain_roles/governed_modules)
_DOMAIN_USERS = [_DA, _TEACHER, _TA, _STUDENT, _STUDENT2]


def _caller(
    sub: str,
    role: str,
    domain_roles: dict[str, str] | None = None,
    governed_modules: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "sub": sub,
        "role": role,
        "domain_roles": domain_roles or {},
        "governed_modules": governed_modules or [],
    }


def _exec_list_users(
    user_data: dict[str, Any],
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from lumina.api.routes.admin import _execute_admin_operation
    parsed = {
        "operation": "list_users",
        "target": "",
        "params": params if params is not None else {"domain_id": "education"},
    }
    return asyncio.run(_execute_admin_operation(user_data, parsed, "list users"))


# ─────────────────────────────────────────────────────────────
# Hierarchy visibility tests
# ─────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestHierarchyVisibility:
    """Hierarchy-level filtering for list_users in education domain."""

    def test_student_sees_teacher_and_ta_only(self) -> None:
        cfg = _mock_cfg(_ALL_USERS)
        caller = _caller("student1", "user", domain_roles={"algebra-1": "student"})
        with patch("lumina.api.routes.admin._cfg", cfg), \
             patch("lumina.api.governance._cfg", cfg):
            result = _exec_list_users(caller)
        usernames = {u["username"] for u in result["users"]}
        # Student (level 3) should see teacher (level 1) and TA (level 2) only
        assert "teacher1" in usernames
        assert "ta1" in usernames
        assert "da1" not in usernames
        assert "student2" not in usernames
        assert "student1" not in usernames  # own record excluded
        assert "root1" not in usernames

    def test_student_user_id_stripped(self) -> None:
        cfg = _mock_cfg(_ALL_USERS)
        caller = _caller("student1", "user", domain_roles={"algebra-1": "student"})
        with patch("lumina.api.routes.admin._cfg", cfg), \
             patch("lumina.api.governance._cfg", cfg):
            result = _exec_list_users(caller)
        for u in result["users"]:
            assert "user_id" not in u, f"user_id should be stripped for students, found in {u}"

    def test_ta_sees_teachers_and_students(self) -> None:
        cfg = _mock_cfg(_ALL_USERS)
        caller = _caller("ta1", "user", domain_roles={"teaching-assistant": "teaching_assistant"})
        with patch("lumina.api.routes.admin._cfg", cfg), \
             patch("lumina.api.governance._cfg", cfg):
            result = _exec_list_users(caller)
        usernames = {u["username"] for u in result["users"]}
        # TA (level 2) should see teacher (level 1) and students (level 3)
        assert "teacher1" in usernames
        assert "student1" in usernames
        assert "student2" in usernames
        assert "da1" not in usernames
        assert "ta1" not in usernames  # own record excluded

    def test_teacher_sees_everyone_in_domain(self) -> None:
        cfg = _mock_cfg(_ALL_USERS)
        caller = _caller("teacher1", "user", domain_roles={"teacher": "teacher"})
        with patch("lumina.api.routes.admin._cfg", cfg), \
             patch("lumina.api.governance._cfg", cfg):
            result = _exec_list_users(caller)
        usernames = {u["username"] for u in result["users"]}
        # Teacher (level 1) should see DA, TAs, and students
        assert "da1" in usernames
        assert "ta1" in usernames
        assert "student1" in usernames
        assert "student2" in usernames
        assert "teacher1" not in usernames  # own record excluded

    def test_da_sees_all_governed(self) -> None:
        cfg = _mock_cfg(_ALL_USERS)
        caller = _caller(
            "da1", "admin",
            governed_modules=["domain-authority", "teacher", "teaching-assistant", "guardian", "algebra-1"],
        )
        with patch("lumina.api.routes.admin._cfg", cfg), \
             patch("lumina.api.governance._cfg", cfg), \
             patch("lumina.api.routes.admin.can_govern_domain", return_value=True):
            result = _exec_list_users(caller)
        # DA should see everyone in governed modules (hierarchy filter doesn't apply)
        assert result["count"] >= 4  # at least teacher, TA, student1, student2

    def test_root_sees_all_domain_users(self) -> None:
        """Root sees all users with education domain presence (root user record
        itself has no domain_roles, so it's excluded by the domain filter)."""
        cfg = _mock_cfg(_ALL_USERS)
        caller = _caller("root1", "root")
        with patch("lumina.api.routes.admin._cfg", cfg), \
             patch("lumina.api.governance._cfg", cfg):
            result = _exec_list_users(caller)
        assert result["count"] == len(_DOMAIN_USERS)

    def test_teacher_user_id_not_stripped(self) -> None:
        cfg = _mock_cfg(_ALL_USERS)
        caller = _caller("teacher1", "user", domain_roles={"teacher": "teacher"})
        with patch("lumina.api.routes.admin._cfg", cfg), \
             patch("lumina.api.governance._cfg", cfg):
            result = _exec_list_users(caller)
        # Teachers should see user_id (not stripped)
        for u in result["users"]:
            assert "user_id" in u

    def test_no_domain_id_skips_hierarchy_filter(self) -> None:
        """When no domain_id is provided and caller is a regular user,
        hierarchy filter does not activate — all users are returned."""
        cfg = _mock_cfg(_ALL_USERS)
        caller = _caller("student1", "user", domain_roles={"algebra-1": "student"})
        with patch("lumina.api.routes.admin._cfg", cfg), \
             patch("lumina.api.governance._cfg", cfg):
            result = _exec_list_users(caller, params={"role": ""})
        # No domain_id → hierarchy filter doesn't activate → sees all users
        assert result["count"] == len(_ALL_USERS)
