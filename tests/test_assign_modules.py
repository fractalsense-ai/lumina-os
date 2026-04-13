"""Tests for /assignmodules command, short-name resolution helpers,
and multi-module assignment to individual students and classrooms.

Covers:
- extract_short_name: full module_id → short name
- resolve_module_shortname: short name → full module_id (pass-through + resolution + 422)
- list_learning_modules: filters out local_only role modules
- assign_modules handler: single student, classroom, RBAC, missing params
- NLP promotion: "assign modules" promotes general → admin_command
- Deterministic fallback: multi-module routes to assign_modules
- switch_active_module short-name resolution
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]

# ── Load education helpers via importlib ──────────────────────
# _helpers.py has no relative imports so it loads standalone.
_HELPERS_PATH = _REPO_ROOT / "domain-packs" / "education" / "controllers" / "ops" / "_helpers.py"
_helpers_spec = importlib.util.spec_from_file_location("edu_helpers_am", str(_HELPERS_PATH))
_helpers_mod = importlib.util.module_from_spec(_helpers_spec)  # type: ignore[arg-type]
sys.modules["edu_helpers_am"] = _helpers_mod
_helpers_spec.loader.exec_module(_helpers_mod)  # type: ignore[union-attr]

extract_short_name = _helpers_mod.extract_short_name
resolve_module_shortname = _helpers_mod.resolve_module_shortname
list_learning_modules = _helpers_mod.list_learning_modules

# ── Load modules handler ──────────────────────────────────────
# modules.py uses `from ._helpers import ...` — we must make the
# relative import resolve by registering a fake parent package.
_OPS_PKG_NAME = "edu_ops_am"
_ops_pkg = types.ModuleType(_OPS_PKG_NAME)
_ops_pkg.__path__ = [str(_HELPERS_PATH.parent)]  # type: ignore[attr-defined]
_ops_pkg.__package__ = _OPS_PKG_NAME
sys.modules[_OPS_PKG_NAME] = _ops_pkg

# Register _helpers under the fake package so relative import works
sys.modules[f"{_OPS_PKG_NAME}._helpers"] = _helpers_mod

_MODULES_PATH = _REPO_ROOT / "domain-packs" / "education" / "controllers" / "ops" / "modules.py"
_modules_spec = importlib.util.spec_from_file_location(
    f"{_OPS_PKG_NAME}.modules", str(_MODULES_PATH),
    submodule_search_locations=[],
)
_modules_mod = importlib.util.module_from_spec(_modules_spec)  # type: ignore[arg-type]
_modules_mod.__package__ = _OPS_PKG_NAME
sys.modules[f"{_OPS_PKG_NAME}.modules"] = _modules_mod
_modules_spec.loader.exec_module(_modules_mod)  # type: ignore[union-attr]

assign_modules_handler = _modules_mod.assign_modules
switch_active_module_handler = _modules_mod.switch_active_module

# ── Load governance adapters for NLP tests ────────────────────
_GOV_PATH = _REPO_ROOT / "domain-packs" / "education" / "controllers" / "governance_adapters.py"
_gov_spec = importlib.util.spec_from_file_location("gov_adapters_am", str(_GOV_PATH))
_gov_mod = importlib.util.module_from_spec(_gov_spec)  # type: ignore[arg-type]
sys.modules["gov_adapters_am"] = _gov_mod
_gov_spec.loader.exec_module(_gov_mod)  # type: ignore[union-attr]

_edu_maybe_promote = _gov_mod._maybe_promote_query_type
_edu_fallback = _gov_mod._deterministic_command_fallback


# ── Test data ─────────────────────────────────────────────────

_SAMPLE_MODULES = [
    {"module_id": "domain/edu/general-education/v1", "domain_physics_path": "dp/ge.json", "local_only": False},
    {"module_id": "domain/edu/pre-algebra/v1", "domain_physics_path": "dp/pa.json", "local_only": False},
    {"module_id": "domain/edu/algebra-intro/v1", "domain_physics_path": "dp/ai.json", "local_only": False},
    {"module_id": "domain/edu/teacher/v1", "domain_physics_path": "dp/t.json", "local_only": True},
    {"module_id": "domain/edu/domain-authority/v1", "domain_physics_path": "dp/da.json", "local_only": True},
]


class _FakeHTTPException(Exception):
    def __init__(self, status_code: int, detail: str = ""):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


def _make_ctx(
    modules: list[dict] | None = None,
    user_lookup: dict[str, dict] | None = None,
    teacher_profile: dict | None = None,
) -> MagicMock:
    """Build a minimal mock ctx for handler tests."""
    ctx = MagicMock()
    ctx.HTTPException = _FakeHTTPException
    ctx.domain_registry.list_modules_for_domain.return_value = modules or _SAMPLE_MODULES

    def _get_user(uid: str) -> dict | None:
        if user_lookup:
            return user_lookup.get(uid)
        return {"user_id": uid, "sub": uid, "role": "user"}

    ctx.persistence.get_user = _get_user
    ctx.persistence.get_user_by_username = lambda u: None
    ctx.persistence.update_user_governed_modules = MagicMock(return_value={"governed_modules": []})
    ctx.persistence.load_subject_profile = MagicMock(return_value=teacher_profile or {})
    ctx.persistence.save_subject_profile = MagicMock()
    ctx.persistence.append_log_record = MagicMock()

    ctx.run_in_threadpool = AsyncMock(side_effect=lambda fn, *a, **kw: fn(*a, **kw))
    ctx.resolve_user_profile_path = MagicMock(return_value=Path("/tmp/profile.json"))
    ctx.build_commitment_record = MagicMock(return_value={"record_id": "rec-001"})
    ctx.map_role_to_actor_role = MagicMock(return_value="teacher")
    ctx.has_domain_capability = MagicMock(return_value=True)
    ctx.can_govern_domain = MagicMock(return_value=True)

    return ctx


def _teacher_user(sub: str = "teacher1") -> dict[str, Any]:
    return {
        "sub": sub,
        "role": "user",
        "domain_roles": {"domain/edu/teacher/v1": "teacher"},
        "scoped_capabilities": {},
    }


def _da_user(sub: str = "da1") -> dict[str, Any]:
    return {
        "sub": sub,
        "role": "domain_authority",
        "domain_roles": {},
        "governed_modules": ["domain/edu/general-education/v1"],
    }


def _student_user(sub: str = "student1") -> dict[str, Any]:
    return {
        "sub": sub,
        "role": "user",
        "domain_roles": {"domain/edu/pre-algebra/v1": "student"},
    }


# ═════════════════════════════════════════════════════════════
# Phase 1: Short-name resolution helpers
# ═════════════════════════════════════════════════════════════

@pytest.mark.unit
class TestExtractShortName:

    def test_standard_module_id(self) -> None:
        assert extract_short_name("domain/edu/pre-algebra/v1") == "pre-algebra"

    def test_general_education(self) -> None:
        assert extract_short_name("domain/edu/general-education/v1") == "general-education"

    def test_role_module(self) -> None:
        assert extract_short_name("domain/edu/teacher/v1") == "teacher"

    def test_short_id_passthrough(self) -> None:
        assert extract_short_name("pre-algebra") == "pre-algebra"

    def test_two_part_id(self) -> None:
        assert extract_short_name("edu/pre-algebra") == "edu/pre-algebra"


@pytest.mark.unit
class TestResolveModuleShortname:

    def test_short_name_resolved(self) -> None:
        ctx = _make_ctx()
        assert resolve_module_shortname(ctx, "pre-algebra") == "domain/edu/pre-algebra/v1"

    def test_full_path_passthrough(self) -> None:
        ctx = _make_ctx()
        assert resolve_module_shortname(ctx, "domain/edu/pre-algebra/v1") == "domain/edu/pre-algebra/v1"

    def test_unknown_name_raises_422(self) -> None:
        ctx = _make_ctx()
        with pytest.raises(_FakeHTTPException) as exc_info:
            resolve_module_shortname(ctx, "nonexistent")
        assert exc_info.value.status_code == 422
        assert "Unknown module" in exc_info.value.detail

    def test_role_module_resolvable(self) -> None:
        ctx = _make_ctx()
        assert resolve_module_shortname(ctx, "teacher") == "domain/edu/teacher/v1"


@pytest.mark.unit
class TestListLearningModules:

    def test_filters_local_only(self) -> None:
        ctx = _make_ctx()
        result = list_learning_modules(ctx)
        ids = [m["module_id"] for m in result]
        assert "domain/edu/pre-algebra/v1" in ids
        assert "domain/edu/teacher/v1" not in ids
        assert "domain/edu/domain-authority/v1" not in ids

    def test_includes_short_names(self) -> None:
        ctx = _make_ctx()
        result = list_learning_modules(ctx)
        shorts = {m["short_name"] for m in result}
        assert "pre-algebra" in shorts
        assert "general-education" in shorts

    def test_count(self) -> None:
        ctx = _make_ctx()
        result = list_learning_modules(ctx)
        assert len(result) == 3  # ge, pre-algebra, algebra-intro


# ═════════════════════════════════════════════════════════════
# Phase 2: assign_modules handler
# ═════════════════════════════════════════════════════════════

@pytest.mark.unit
class TestAssignModulesHandler:

    def test_single_module_single_student(self) -> None:
        ctx = _make_ctx()
        teacher = _teacher_user()
        result = asyncio.run(
            assign_modules_handler(
                "assign_modules",
                {"module_ids": "pre-algebra", "target": "student1"},
                teacher, ctx,
            )
        )
        assert result["status"] == "assigned"
        assert result["count"] == 1
        assert result["assignments"][0]["user_id"] == "student1"
        assert "domain/edu/pre-algebra/v1" in result["assignments"][0]["module_ids"]

    def test_multi_module_single_student(self) -> None:
        ctx = _make_ctx()
        teacher = _teacher_user()
        result = asyncio.run(
            assign_modules_handler(
                "assign_modules",
                {"module_ids": "pre-algebra,algebra-intro", "target": "student1"},
                teacher, ctx,
            )
        )
        assert result["count"] == 1
        mods = result["assignments"][0]["module_ids"]
        assert "domain/edu/pre-algebra/v1" in mods
        assert "domain/edu/algebra-intro/v1" in mods

    def test_classroom_target(self) -> None:
        ctx = _make_ctx(
            teacher_profile={
                "educator_state": {"assigned_students": ["s1", "s2", "s3"]},
            },
        )
        teacher = _teacher_user()
        result = asyncio.run(
            assign_modules_handler(
                "assign_modules",
                {"module_ids": "pre-algebra", "target": "classroom"},
                teacher, ctx,
            )
        )
        assert result["count"] == 3
        assigned_users = [a["user_id"] for a in result["assignments"]]
        assert set(assigned_users) == {"s1", "s2", "s3"}

    def test_empty_classroom_raises_422(self) -> None:
        ctx = _make_ctx(teacher_profile={"educator_state": {"assigned_students": []}})
        teacher = _teacher_user()
        with pytest.raises(_FakeHTTPException) as exc_info:
            asyncio.run(
                assign_modules_handler(
                    "assign_modules",
                    {"module_ids": "pre-algebra", "target": "classroom"},
                    teacher, ctx,
                )
            )
        assert exc_info.value.status_code == 422
        assert "No students" in exc_info.value.detail

    def test_missing_params_raises_422(self) -> None:
        ctx = _make_ctx()
        teacher = _teacher_user()
        with pytest.raises(_FakeHTTPException) as exc_info:
            asyncio.run(
                assign_modules_handler(
                    "assign_modules",
                    {"module_ids": "", "target": ""},
                    teacher, ctx,
                )
            )
        assert exc_info.value.status_code == 422

    def test_unknown_module_raises_422(self) -> None:
        ctx = _make_ctx()
        teacher = _teacher_user()
        with pytest.raises(_FakeHTTPException) as exc_info:
            asyncio.run(
                assign_modules_handler(
                    "assign_modules",
                    {"module_ids": "nonexistent-module", "target": "student1"},
                    teacher, ctx,
                )
            )
        assert exc_info.value.status_code == 422

    def test_student_cannot_assign(self) -> None:
        ctx = _make_ctx()
        ctx.has_domain_capability = MagicMock(return_value=False)
        student = _student_user()
        with pytest.raises(_FakeHTTPException) as exc_info:
            asyncio.run(
                assign_modules_handler(
                    "assign_modules",
                    {"module_ids": "pre-algebra", "target": "s2"},
                    student, ctx,
                )
            )
        assert exc_info.value.status_code == 403

    def test_da_can_assign(self) -> None:
        ctx = _make_ctx()
        da = _da_user()
        result = asyncio.run(
            assign_modules_handler(
                "assign_modules",
                {"module_ids": "pre-algebra", "target": "student1"},
                da, ctx,
            )
        )
        assert result["status"] == "assigned"

    def test_full_path_accepted(self) -> None:
        ctx = _make_ctx()
        teacher = _teacher_user()
        result = asyncio.run(
            assign_modules_handler(
                "assign_modules",
                {"module_ids": "domain/edu/pre-algebra/v1", "target": "student1"},
                teacher, ctx,
            )
        )
        assert result["status"] == "assigned"
        assert "domain/edu/pre-algebra/v1" in result["assignments"][0]["module_ids"]


# ═════════════════════════════════════════════════════════════
# Phase 3: NLP promotion and deterministic fallback
# ═════════════════════════════════════════════════════════════

@pytest.mark.unit
class TestMultiModuleNLP:

    def test_assign_modules_promotes(self) -> None:
        ev = {"query_type": "general"}
        _edu_maybe_promote(ev, "assign modules pre-algebra,algebra-intro to classroom")
        assert ev["query_type"] == "admin_command"

    def test_assignmodules_keyword_promotes(self) -> None:
        ev = {"query_type": "general"}
        _edu_maybe_promote(ev, "assignmodules pre-algebra student1")
        assert ev["query_type"] == "admin_command"

    def test_fallback_assign_modules_plural(self) -> None:
        result = _edu_fallback(
            "assign modules pre-algebra,algebra-intro to student1",
            {"intent_type": "mutation"},
        )
        assert result is not None
        assert result["operation"] == "assign_modules"
        assert "module_ids" in result["params"]

    def test_fallback_assign_modules_classroom(self) -> None:
        result = _edu_fallback(
            "assign modules pre-algebra to classroom",
            {"intent_type": "mutation"},
        )
        assert result is not None
        assert result["operation"] == "assign_modules"
        assert result["params"].get("target") == "classroom"

    def test_fallback_single_module_still_singular(self) -> None:
        """'assign module X to Y' (singular) still routes to assign_module."""
        result = _edu_fallback(
            "assign module pre-algebra to student1",
            {"intent_type": "mutation"},
        )
        assert result is not None
        assert result["operation"] == "assign_module"


# ═════════════════════════════════════════════════════════════
# Phase 4: switch_active_module short-name resolution
# ═════════════════════════════════════════════════════════════

@pytest.mark.unit
class TestSwitchModuleShortName:

    def test_switch_with_short_name(self) -> None:
        ctx = _make_ctx()
        student = _student_user()
        # Set up profile with governed modules using full path
        ctx.persistence.get_user = MagicMock(
            return_value={"user_id": "student1", "governed_modules": ["domain/edu/pre-algebra/v1"]},
        )
        ctx.persistence.load_subject_profile = MagicMock(return_value={
            "modules": {"domain/edu/pre-algebra/v1": {}},
        })
        result = asyncio.run(
            switch_active_module_handler(
                "switch_active_module",
                {"module_id": "pre-algebra"},
                student, ctx,
            )
        )
        assert result["status"] == "switched"
        assert result["module_id"] == "domain/edu/pre-algebra/v1"

    def test_switch_with_full_path(self) -> None:
        ctx = _make_ctx()
        student = _student_user()
        ctx.persistence.get_user = MagicMock(
            return_value={"user_id": "student1", "governed_modules": ["domain/edu/pre-algebra/v1"]},
        )
        ctx.persistence.load_subject_profile = MagicMock(return_value={
            "modules": {"domain/edu/pre-algebra/v1": {}},
        })
        result = asyncio.run(
            switch_active_module_handler(
                "switch_active_module",
                {"module_id": "domain/edu/pre-algebra/v1"},
                student, ctx,
            )
        )
        assert result["status"] == "switched"
        assert result["module_id"] == "domain/edu/pre-algebra/v1"
