"""Tests for module-switch UX fixes:

1. _default_current_task receives module-specific domain physics
2. switch_active_module returns ui_overrides from runtime config
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]


# ── Load session module for _default_current_task ──────────

from lumina.api.session import _default_current_task


# ── Load education handlers via importlib ─────────────────────

_HELPERS_PATH = _REPO_ROOT / "domain-packs" / "education" / "controllers" / "ops" / "_helpers.py"
_helpers_spec = importlib.util.spec_from_file_location("edu_helpers_msu", str(_HELPERS_PATH))
_helpers_mod = importlib.util.module_from_spec(_helpers_spec)  # type: ignore[arg-type]
sys.modules["edu_helpers_msu"] = _helpers_mod
_helpers_spec.loader.exec_module(_helpers_mod)  # type: ignore[union-attr]

_OPS_PKG = "edu_ops_msu"
_ops_pkg = types.ModuleType(_OPS_PKG)
_ops_pkg.__path__ = [str(_HELPERS_PATH.parent)]  # type: ignore[attr-defined]
_ops_pkg.__package__ = _OPS_PKG
sys.modules[_OPS_PKG] = _ops_pkg
sys.modules[f"{_OPS_PKG}._helpers"] = _helpers_mod

_MODULES_PATH = _REPO_ROOT / "domain-packs" / "education" / "controllers" / "ops" / "modules.py"
_modules_spec = importlib.util.spec_from_file_location(
    f"{_OPS_PKG}.modules", str(_MODULES_PATH),
    submodule_search_locations=[],
)
_modules_mod = importlib.util.module_from_spec(_modules_spec)  # type: ignore[arg-type]
_modules_mod.__package__ = _OPS_PKG
sys.modules[f"{_OPS_PKG}.modules"] = _modules_mod
_modules_spec.loader.exec_module(_modules_mod)  # type: ignore[union-attr]

switch_active_module_handler = _modules_mod.switch_active_module


# ── Shared test data ──────────────────────────────────────────

_PRE_ALGEBRA_TIERS = [
    {"tier_id": "tier_1", "label": "Single operation", "operations": ["+", "-"]},
    {"tier_id": "tier_2", "label": "Single-step equations"},
    {"tier_id": "tier_3", "label": "Multi-step equations"},
]

_MODULE_MAP = {
    "domain/edu/general-education/v1": {
        "domain_physics_path": "dp/ge.json",
        "ui_overrides": {"subtitle": "Student Commons"},
    },
    "domain/edu/pre-algebra/v1": {
        "domain_physics_path": "dp/pa.json",
        "ui_overrides": {"subtitle": "Pre-Algebra"},
    },
    "domain/edu/algebra-intro/v1": {
        "domain_physics_path": "dp/ai.json",
        "ui_overrides": {"subtitle": "Algebra — Introduction"},
    },
}

_SAMPLE_MODULES = [
    {"module_id": k, "domain_physics_path": v["domain_physics_path"], "local_only": False}
    for k, v in _MODULE_MAP.items()
]


class _FakeHTTPException(Exception):
    def __init__(self, status_code: int, detail: str = ""):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


def _make_ctx() -> MagicMock:
    from unittest.mock import AsyncMock

    ctx = MagicMock()
    ctx.HTTPException = _FakeHTTPException
    ctx.domain_registry.list_modules_for_domain.return_value = _SAMPLE_MODULES
    ctx.domain_registry.get_runtime_context.return_value = {"module_map": _MODULE_MAP}
    ctx.domain_registry.resolve_default_for_user.return_value = "education"

    ctx.persistence.get_user = MagicMock(
        return_value={"user_id": "student1", "governed_modules": [
            "domain/edu/general-education/v1",
            "domain/edu/pre-algebra/v1",
        ]},
    )
    ctx.persistence.load_subject_profile = MagicMock(return_value={
        "modules": {"domain/edu/pre-algebra/v1": {}, "domain/edu/general-education/v1": {}},
    })
    ctx.persistence.save_subject_profile = MagicMock()
    ctx.persistence.append_log_record = MagicMock()

    ctx.run_in_threadpool = AsyncMock(side_effect=lambda fn, *a, **kw: fn(*a, **kw))
    ctx.build_commitment_record = MagicMock(return_value={"record_id": "rec-msu"})
    ctx.map_role_to_actor_role = MagicMock(return_value="student")
    ctx.has_domain_capability = MagicMock(return_value=True)
    ctx.can_govern_domain = MagicMock(return_value=True)

    return ctx


def _student_user(sub: str = "student1") -> dict[str, Any]:
    return {
        "sub": sub,
        "role": "user",
        "domain_roles": {"domain/edu/pre-algebra/v1": "student"},
    }


# ═════════════════════════════════════════════════════════════
# Phase 1: _default_current_task uses module domain physics
# ═════════════════════════════════════════════════════════════

@pytest.mark.unit
class TestDefaultCurrentProblemModuleDomain:
    """The problem generator must receive subsystem_configs from the active
    module's domain physics, not the top-level runtime domain."""

    def test_generator_receives_module_subsystem_configs(self) -> None:
        """When runtime["domain"] has the module's subsystem_configs, the
        task initializer should receive them via the runtime dict."""
        captured: dict[str, Any] = {}

        def fake_initializer(task_spec: dict, runtime: dict, *, domain_id: str | None = None) -> dict:
            difficulty = float(task_spec.get("nominal_difficulty", 0.5))
            subsystem_configs = (runtime.get("domain") or {}).get("subsystem_configs") or {}
            captured["difficulty"] = difficulty
            captured["subsystem_configs"] = subsystem_configs
            return {"problem_id": "p1", "tier": "tier_1", "expression": "2 + 3"}

        runtime = {
            "domain": {
                "subsystem_configs": {
                    "equation_difficulty_tiers": _PRE_ALGEBRA_TIERS,
                }
            },
        }
        task_spec = {"nominal_difficulty": 0.5}

        result = _default_current_task(task_spec, runtime, task_initializer_fn=fake_initializer)

        assert result["problem_id"] == "p1"
        assert "equation_difficulty_tiers" in captured["subsystem_configs"]
        assert len(captured["subsystem_configs"]["equation_difficulty_tiers"]) == 3

    def test_generator_fails_without_tiers(self) -> None:
        """When the task initializer fails (general-edu, no tiers),
        _default_current_task falls back to task_spec."""

        def failing_initializer(task_spec: dict, runtime: dict, *, domain_id: str | None = None) -> dict:
            tiers = (runtime.get("domain") or {}).get("subsystem_configs", {}).get("equation_difficulty_tiers") or []
            # Simulate the real problem generator crashing on empty tiers
            return tiers[0]  # IndexError when tiers is empty

        runtime = {
            "domain": {"subsystem_configs": {}},  # no tiers — general-edu
        }
        task_spec = {"task_id": "fallback-task", "nominal_difficulty": 0.5}

        result = _default_current_task(task_spec, runtime, task_initializer_fn=failing_initializer)

        # Should fall back to task_spec default, not crash
        assert result["task_id"] == "fallback-task"
        assert result["status"] == "in_progress"

    def test_overlayed_runtime_gets_module_tiers(self) -> None:
        """Simulates the fix in _build_domain_context: overlaying module
        domain onto runtime before calling _default_current_task."""
        captured_configs: list[dict] = []

        def capturing_initializer(task_spec: dict, runtime: dict, *, domain_id: str | None = None) -> dict:
            subsystem_configs = (runtime.get("domain") or {}).get("subsystem_configs") or {}
            captured_configs.append(subsystem_configs)
            return {"problem_id": "p2", "expression": "x + 1 = 5"}

        # Original runtime has general-education domain (no tiers)
        runtime = {
            "domain": {"subsystem_configs": {}},
        }
        # Module-specific domain with tiers
        module_domain = {
            "subsystem_configs": {
                "equation_difficulty_tiers": _PRE_ALGEBRA_TIERS,
            }
        }

        # Apply the fix: overlay module domain onto runtime
        gen_runtime = dict(runtime)
        gen_runtime["domain"] = module_domain

        task_spec = {"nominal_difficulty": 0.5}
        result = _default_current_task(task_spec, gen_runtime, task_initializer_fn=capturing_initializer)

        assert result["problem_id"] == "p2"
        assert captured_configs[0]["equation_difficulty_tiers"] == _PRE_ALGEBRA_TIERS


# ═════════════════════════════════════════════════════════════
# Phase 2: switch_active_module returns ui_overrides
# ═════════════════════════════════════════════════════════════

@pytest.mark.unit
class TestSwitchModuleUiOverrides:
    """switch_active_module must include ui_overrides from the runtime
    config so the frontend can update the header subtitle."""

    def test_switch_returns_ui_overrides_for_pre_algebra(self) -> None:
        ctx = _make_ctx()
        student = _student_user()

        result = asyncio.run(
            switch_active_module_handler(
                "switch_active_module",
                {"module_id": "pre-algebra"},
                student, ctx,
            )
        )

        assert result["status"] == "switched"
        assert result["module_id"] == "domain/edu/pre-algebra/v1"
        assert "ui_overrides" in result
        assert result["ui_overrides"]["subtitle"] == "Pre-Algebra"

    def test_switch_returns_ui_overrides_for_student_commons(self) -> None:
        ctx = _make_ctx()
        student = _student_user()

        result = asyncio.run(
            switch_active_module_handler(
                "switch_active_module",
                {"module_id": "general-education"},
                student, ctx,
            )
        )

        assert result["status"] == "switched"
        assert result["ui_overrides"]["subtitle"] == "Student Commons"

    def test_switch_returns_empty_overrides_when_registry_missing(self) -> None:
        ctx = _make_ctx()
        ctx.domain_registry.get_runtime_context.side_effect = Exception("unavailable")
        student = _student_user()

        result = asyncio.run(
            switch_active_module_handler(
                "switch_active_module",
                {"module_id": "pre-algebra"},
                student, ctx,
            )
        )

        assert result["status"] == "switched"
        assert result["ui_overrides"] == {}

    def test_switch_returns_ui_overrides_for_algebra_intro(self) -> None:
        ctx = _make_ctx()
        ctx.persistence.get_user = MagicMock(
            return_value={"user_id": "student1", "governed_modules": [
                "domain/edu/algebra-intro/v1",
            ]},
        )
        ctx.persistence.load_subject_profile = MagicMock(return_value={
            "modules": {"domain/edu/algebra-intro/v1": {}},
        })
        student = _student_user()

        result = asyncio.run(
            switch_active_module_handler(
                "switch_active_module",
                {"module_id": "algebra-intro"},
                student, ctx,
            )
        )

        assert result["ui_overrides"]["subtitle"] == "Algebra — Introduction"


# ═════════════════════════════════════════════════════════════
# Phase 3: switch rebuilds cached session context
# ═════════════════════════════════════════════════════════════

@pytest.mark.unit
class TestSwitchModuleRebuildsDomainContext:
    """After switching modules the handler must call
    rebuild_domain_context so the in-memory session picks up
    the new module's physics on the next chat turn."""

    def test_rebuild_called_with_user_and_domain(self) -> None:
        ctx = _make_ctx()
        ctx.rebuild_domain_context = MagicMock()
        student = _student_user()

        asyncio.run(
            switch_active_module_handler(
                "switch_active_module",
                {"module_id": "pre-algebra"},
                student, ctx,
            )
        )

        ctx.rebuild_domain_context.assert_called_once_with("student1", "education")

    def test_rebuild_not_called_when_absent(self) -> None:
        """If ctx has no rebuild_domain_context (older framework),
        the switch must still succeed without errors."""
        ctx = _make_ctx()
        # Ensure attribute is absent (default MagicMock would auto-create it)
        if hasattr(ctx, "rebuild_domain_context"):
            del ctx.rebuild_domain_context
        student = _student_user()

        result = asyncio.run(
            switch_active_module_handler(
                "switch_active_module",
                {"module_id": "pre-algebra"},
                student, ctx,
            )
        )

        assert result["status"] == "switched"

    def test_rebuild_failure_does_not_block_switch(self) -> None:
        """If rebuild_domain_context raises, the switch should still
        succeed — the context will be rebuilt on the next chat request."""
        ctx = _make_ctx()
        ctx.rebuild_domain_context = MagicMock(side_effect=RuntimeError("boom"))
        student = _student_user()

        result = asyncio.run(
            switch_active_module_handler(
                "switch_active_module",
                {"module_id": "pre-algebra"},
                student, ctx,
            )
        )

        assert result["status"] == "switched"
        ctx.rebuild_domain_context.assert_called_once()
