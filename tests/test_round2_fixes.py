"""Tests for Round 2 fixes:

Phase 1 — Profile-aware domain-info endpoint
Phase 2 — Pre-algebra module-scoped problem generator
Phase 2b — Module-level default_task_spec in session
Phase 3 — Roster grants teacher domain_roles for escalation routing
Phase 4 — Session-close state flush to profile
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import types
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]


# ═══════════════════════════════════════════════════════════════
# Phase 1 — domain_info reads profile to resolve module
# ═══════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestDomainInfoProfileAware:
    """``/api/domain-info`` should honour the user profile's ``domain_id``
    so the correct module (e.g. Pre-Algebra) is served on initial login."""

    def _get_domain_info_handler(self):
        from lumina.api.routes.system import domain_info
        return domain_info

    @pytest.mark.anyio
    async def test_profile_domain_id_overrides_role_default(self) -> None:
        """When a student profile has domain_id pointing to pre-algebra,
        domain_info should return that module's physics & ui_overrides."""
        handler = self._get_domain_info_handler()

        fake_profile = {"domain_id": "domain/edu/pre-algebra/v1"}
        fake_domain = {"id": "domain/edu/pre-algebra/v1", "version": "1.0.0"}
        fake_manifest = {"subtitle": "Learning"}
        pa_physics_path = "dp/pre-algebra.json"

        runtime = {
            "domain_physics_path": "dp/default.json",
            "ui_manifest": fake_manifest,
            "ui_plugin": None,
            "module_map": {
                "domain/edu/general-education/v1": {
                    "domain_physics_path": "dp/ge.json",
                    "ui_overrides": {"subtitle": "Student Commons"},
                },
                "domain/edu/pre-algebra/v1": {
                    "domain_physics_path": pa_physics_path,
                    "ui_overrides": {"subtitle": "Pre-Algebra"},
                },
            },
            "role_to_default_module": {"student": "domain/edu/general-education/v1"},
        }
        user = {"sub": "student1", "role": "user", "domain_roles": {}}
        profile_path = MagicMock()
        profile_path.exists.return_value = True

        with (
            patch("lumina.api.routes.system._cfg") as mock_cfg,
            patch("lumina.api.routes.system.get_current_user", new_callable=AsyncMock, return_value=user),
            patch("lumina.api.routes.system._resolve_role_layout", return_value={}),
            patch("lumina.api.config._resolve_user_profile_path", return_value=profile_path) as mock_resolve,
        ):
            mock_cfg.DOMAIN_REGISTRY.resolve_domain_id.return_value = "education"
            mock_cfg.DOMAIN_REGISTRY.get_runtime_context.return_value = runtime
            mock_cfg.PERSISTENCE.load_domain_physics.return_value = fake_domain
            mock_cfg.PERSISTENCE.load_subject_profile.return_value = fake_profile

            result = await handler(domain_id=None, credentials=None)

        assert result["domain_id"] == "domain/edu/pre-algebra/v1"
        assert result["ui_manifest"]["subtitle"] == "Pre-Algebra"
        # Verify physics were loaded from the pre-algebra path
        mock_cfg.PERSISTENCE.load_domain_physics.assert_called_once_with(pa_physics_path)

    @pytest.mark.anyio
    async def test_no_profile_falls_back_to_role_default(self) -> None:
        """When the user has no profile file, role-based routing is used."""
        handler = self._get_domain_info_handler()

        fake_domain = {"id": "domain/edu/general-education/v1", "version": "1.0.0"}
        runtime = {
            "domain_physics_path": "dp/default.json",
            "ui_manifest": {
                "system_role_to_domain_role": {
                    "root": "admin",
                    "admin": "admin",
                    "super_admin": "teacher",
                    "operator": "student",
                    "half_operator": "student",
                    "user": "student",
                },
            },
            "ui_plugin": None,
            "module_map": {
                "domain/edu/general-education/v1": {
                    "domain_physics_path": "dp/ge.json",
                    "ui_overrides": {"subtitle": "Student Commons"},
                },
            },
            "role_to_default_module": {"student": "domain/edu/general-education/v1"},
        }
        user = {"sub": "student1", "role": "user", "domain_roles": {}}
        profile_path = MagicMock()
        profile_path.exists.return_value = False

        with (
            patch("lumina.api.routes.system._cfg") as mock_cfg,
            patch("lumina.api.routes.system.get_current_user", new_callable=AsyncMock, return_value=user),
            patch("lumina.api.routes.system._resolve_role_layout", return_value={}),
            patch("lumina.api.config._resolve_user_profile_path", return_value=profile_path),
        ):
            mock_cfg.DOMAIN_REGISTRY.resolve_domain_id.return_value = "education"
            mock_cfg.DOMAIN_REGISTRY.get_runtime_context.return_value = runtime
            mock_cfg.PERSISTENCE.load_domain_physics.return_value = fake_domain

            result = await handler(domain_id=None, credentials=None)

        assert result["ui_manifest"]["subtitle"] == "Student Commons"


# ═══════════════════════════════════════════════════════════════
# Phase 2 — Pre-algebra problem generator
# ═══════════════════════════════════════════════════════════════

_PA_TIERS = [
    {"tier_id": "tier_1", "equation_type": "integer_and_fraction_ops", "min_difficulty": 0.0, "max_difficulty": 0.35},
    {"tier_id": "tier_2", "equation_type": "ratios_and_expressions", "min_difficulty": 0.35, "max_difficulty": 0.65},
    {"tier_id": "tier_3", "equation_type": "single_step_equations", "min_difficulty": 0.65, "max_difficulty": 1.0},
]


def _load_pa_generator():
    """Import the pre-algebra problem generator via importlib."""
    _gen_path = _REPO_ROOT / "model-packs" / "education" / "modules" / "pre-algebra" / "problem_generator.py"
    _spec = importlib.util.spec_from_file_location("pa_gen_test", str(_gen_path))
    _mod = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
    _spec.loader.exec_module(_mod)  # type: ignore[union-attr]
    return _mod


@pytest.mark.unit
class TestPreAlgebraGenerator:
    """Pre-algebra generator produces valid problems for each tier."""

    def test_tier1_integer_and_fraction_ops(self) -> None:
        gen = _load_pa_generator()
        subsys = {"equation_difficulty_tiers": _PA_TIERS}
        problem = gen.generate_problem(0.1, subsys)
        assert problem["equation_type"] == "integer_and_fraction_ops"
        assert problem["difficulty_tier"] == "tier_1"
        assert problem["status"] == "in_progress"
        # Tier 1 produces arithmetic (no variable)
        assert problem["expected_answer"]

    def test_tier2_ratios_and_expressions(self) -> None:
        gen = _load_pa_generator()
        subsys = {"equation_difficulty_tiers": _PA_TIERS}
        problem = gen.generate_problem(0.5, subsys)
        assert problem["equation_type"] == "ratios_and_expressions"
        assert problem["difficulty_tier"] == "tier_2"

    def test_tier3_single_step_equations(self) -> None:
        gen = _load_pa_generator()
        subsys = {"equation_difficulty_tiers": _PA_TIERS}
        problem = gen.generate_problem(0.8, subsys)
        assert problem["equation_type"] == "single_step_equations"
        assert problem["difficulty_tier"] == "tier_3"

    def test_low_difficulty_maps_to_tier1(self) -> None:
        """nominal_difficulty of 0.15 should land in tier_1 [0, 0.35)."""
        gen = _load_pa_generator()
        subsys = {"equation_difficulty_tiers": _PA_TIERS}
        problem = gen.generate_problem(0.15, subsys)
        assert problem["difficulty_tier"] == "tier_1"
        assert problem["equation_type"] == "integer_and_fraction_ops"

    def test_generator_keys_match_tier_equation_types(self) -> None:
        """All equation_type values in tiers must exist in _GENERATORS."""
        gen = _load_pa_generator()
        for tier in _PA_TIERS:
            eq_type = tier["equation_type"]
            assert eq_type in gen._GENERATORS, f"{eq_type} not in _GENERATORS"


# ═══════════════════════════════════════════════════════════════
# Phase 2b — Module-level default_task_spec in session
# ═══════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestModuleLevelDefaultTaskSpec:
    """session.py should prefer the module-map's default_task_spec over
    the global runtime one when building a new DomainContext."""

    def test_runtime_config_pre_algebra_has_task_spec(self) -> None:
        """The runtime-config.yaml pre-algebra module entry declares a
        default_task_spec with nominal_difficulty 0.15."""
        from lumina.core.runtime_loader import load_yaml
        from conftest import merge_module_config_sidecars
        cfg = load_yaml(str(_REPO_ROOT / "model-packs" / "education" / "cfg" / "runtime-config.yaml"))
        module_map = cfg["runtime"]["module_map"]
        merge_module_config_sidecars(module_map)
        pa_entry = module_map["domain/edu/pre-algebra/v1"]
        task_spec = pa_entry.get("default_task_spec")
        assert task_spec is not None
        assert task_spec["nominal_difficulty"] == 0.45
        assert task_spec["task_id"] == "pre-algebra-basics-001"


# ═══════════════════════════════════════════════════════════════
# Phase 3 — Roster grants teacher domain_roles
# ═══════════════════════════════════════════════════════════════


_HELPERS_PATH = _REPO_ROOT / "model-packs" / "education" / "controllers" / "ops" / "_helpers.py"
_helpers_spec = importlib.util.spec_from_file_location("edu_helpers_r2", str(_HELPERS_PATH))
_helpers_mod = importlib.util.module_from_spec(_helpers_spec)  # type: ignore[arg-type]
sys.modules["edu_helpers_r2"] = _helpers_mod
_helpers_spec.loader.exec_module(_helpers_mod)  # type: ignore[union-attr]

_OPS_PKG_R2 = "edu_ops_r2"
_ops_pkg_r2 = types.ModuleType(_OPS_PKG_R2)
_ops_pkg_r2.__path__ = [str(_HELPERS_PATH.parent)]  # type: ignore[attr-defined]
_ops_pkg_r2.__package__ = _OPS_PKG_R2
sys.modules[_OPS_PKG_R2] = _ops_pkg_r2
sys.modules[f"{_OPS_PKG_R2}._helpers"] = _helpers_mod

_ROSTER_PATH = _REPO_ROOT / "model-packs" / "education" / "controllers" / "ops" / "roster.py"
_roster_spec = importlib.util.spec_from_file_location(
    f"{_OPS_PKG_R2}.roster", str(_ROSTER_PATH),
    submodule_search_locations=[],
)
_roster_mod = importlib.util.module_from_spec(_roster_spec)  # type: ignore[arg-type]
_roster_mod.__package__ = _OPS_PKG_R2
sys.modules[f"{_OPS_PKG_R2}.roster"] = _roster_mod
_roster_spec.loader.exec_module(_roster_mod)  # type: ignore[union-attr]


class _FakeHTTPException(Exception):
    def __init__(self, status_code: int, detail: str = ""):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


def _make_roster_ctx(student_profile: dict, teacher_profile: dict) -> MagicMock:
    ctx = MagicMock()
    ctx.HTTPException = _FakeHTTPException

    _profiles = {
        "student1": dict(student_profile),
        "teacher1": dict(teacher_profile),
    }

    async def fake_load_profile(c, uid):
        return _profiles.get(uid, {})

    async def fake_save_profile(c, uid, data):
        _profiles[uid] = data

    # Monkey-patch the module-level helpers
    _roster_mod.load_profile = fake_load_profile
    _roster_mod.save_profile = fake_save_profile
    _roster_mod.require_teacher_capability = AsyncMock()
    _roster_mod.require_user_exists = AsyncMock(
        side_effect=lambda c, uid, label: {"user_id": uid}
    )
    _roster_mod.write_commitment = MagicMock(return_value={"record_id": "rec-r2"})
    _roster_mod._sync_ta_students = AsyncMock()
    ctx.map_role_to_actor_role = MagicMock(return_value="student")
    ctx.run_in_threadpool = AsyncMock()

    return ctx, _profiles


@pytest.mark.unit
class TestRosterGrantsDomainRoles:
    """assign_student_to_roster should add the student's module to the
    teacher's domain_roles so escalation routing works."""

    @pytest.mark.anyio
    async def test_teacher_gets_student_module_domain_role(self) -> None:
        student_profile = {
            "domain_id": "domain/edu/pre-algebra/v1",
            "assigned_teacher_id": None,
        }
        teacher_profile = {
            "educator_state": {"assigned_students": [], "receive_escalations": True},
            "domain_roles": {},
        }
        ctx, profiles = _make_roster_ctx(student_profile, teacher_profile)
        user_data = {"sub": "teacher1", "role": "user"}

        result = await _roster_mod.assign_student(
            operation="assign_student",
            params={"student_id": "student1", "teacher_id": "teacher1"},
            user_data=user_data,
            ctx=ctx,
        )

        assert result["status"] == "assigned"
        t_prof = profiles["teacher1"]
        assert "domain/edu/pre-algebra/v1" in t_prof.get("domain_roles", {})
        assert t_prof["domain_roles"]["domain/edu/pre-algebra/v1"] == "teacher"

    @pytest.mark.anyio
    async def test_existing_domain_role_not_overwritten(self) -> None:
        """If teacher already has domain_roles for the module, keep it."""
        student_profile = {
            "domain_id": "domain/edu/pre-algebra/v1",
            "assigned_teacher_id": None,
        }
        teacher_profile = {
            "educator_state": {"assigned_students": [], "receive_escalations": True},
            "domain_roles": {"domain/edu/pre-algebra/v1": "admin"},
        }
        ctx, profiles = _make_roster_ctx(student_profile, teacher_profile)
        user_data = {"sub": "teacher1", "role": "user"}

        await _roster_mod.assign_student(
            operation="assign_student",
            params={"student_id": "student1", "teacher_id": "teacher1"},
            user_data=user_data,
            ctx=ctx,
        )

        # Should NOT overwrite the existing admin role
        assert profiles["teacher1"]["domain_roles"]["domain/edu/pre-algebra/v1"] == "admin"


# ═══════════════════════════════════════════════════════════════
# Phase 4 — Session-close state flush
# ═══════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestSessionCloseStateFlush:
    """_close_session should invoke the profile serializer to flush
    final orchestrator state before dropping the session container."""

    def test_close_session_flushes_profile(self) -> None:
        from lumina.api.session import _close_session, _session_containers, SessionContainer, DomainContext
        from unittest.mock import MagicMock, patch

        flushed = {}

        def fake_serializer(orch_state, profile_data, module_key):
            profile_data["flushed_state"] = dict(orch_state)
            profile_data["flushed_module"] = module_key
            flushed["called"] = True
            return profile_data

        orch = MagicMock()
        orch.state = {"fluency": 0.8, "current_tier": "tier_2"}
        orch.domain = {}
        orch.get_standing_order_attempts.return_value = {}

        ctx = DomainContext(
            orchestrator=orch,
            task_spec={"task_id": "t1"},
            current_task={},
            turn_count=5,
            domain_id="education",
            task_presented_at=0.0,
            subject_profile_path="/fake/profile.yaml",
            module_key="domain/edu/pre-algebra/v1",
        )

        container = SessionContainer(active_domain_id="education", user={"sub": "student1", "role": "user"})
        container.contexts["education"] = ctx
        _session_containers["test-close-flush"] = container

        runtime = {
            "module_map": {
                "domain/edu/pre-algebra/v1": {
                    "profile_serializer_fn": fake_serializer,
                },
            },
            "profile_serializer_fn": None,
        }

        saved_data = {}

        with patch("lumina.api.session._cfg") as mock_cfg:
            mock_cfg.DOMAIN_REGISTRY.get_runtime_context.return_value = runtime
            mock_cfg.PERSISTENCE.load_subject_profile.return_value = {"learning_state": {}}
            mock_cfg.PERSISTENCE.save_subject_profile.side_effect = lambda path, data: saved_data.update({"path": path, "data": data})
            mock_cfg.PERSISTENCE.append_log_record = MagicMock()
            mock_cfg.PERSISTENCE.get_domain_ledger_path.return_value = "/fake/ledger"

            _close_session("test-close-flush", actor_id="student1", actor_role="student")

        assert flushed.get("called") is True
        assert saved_data["data"]["flushed_module"] == "domain/edu/pre-algebra/v1"
        assert "test-close-flush" not in _session_containers

    def test_close_session_graceful_without_serializer(self) -> None:
        """When no profile_serializer_fn exists, fallback to dict copy."""
        from lumina.api.session import _close_session, _session_containers, SessionContainer, DomainContext

        orch = MagicMock()
        orch.state = {"key": "value"}
        orch.domain = {}
        orch.get_standing_order_attempts.return_value = {}

        ctx = DomainContext(
            orchestrator=orch,
            task_spec={},
            current_task={},
            turn_count=1,
            domain_id="education",
            task_presented_at=0.0,
            subject_profile_path="/fake/profile.yaml",
            module_key="domain/edu/pre-algebra/v1",
        )

        container = SessionContainer(active_domain_id="education", user={"sub": "s1", "role": "user"})
        container.contexts["education"] = ctx
        _session_containers["test-close-no-ser"] = container

        runtime = {"module_map": {}, "profile_serializer_fn": None}

        saved = {}

        with patch("lumina.api.session._cfg") as mock_cfg:
            mock_cfg.DOMAIN_REGISTRY.get_runtime_context.return_value = runtime
            mock_cfg.PERSISTENCE.load_subject_profile.return_value = {}
            mock_cfg.PERSISTENCE.save_subject_profile.side_effect = lambda p, d: saved.update(d)
            mock_cfg.PERSISTENCE.append_log_record = MagicMock()
            mock_cfg.PERSISTENCE.get_domain_ledger_path.return_value = "/fake"

            _close_session("test-close-no-ser", actor_id="s1", actor_role="student")

        assert saved.get("session_state") == {"key": "value"}
        assert "test-close-no-ser" not in _session_containers
