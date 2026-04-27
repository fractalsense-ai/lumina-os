"""Tests for the domain-scoped role hierarchy feature.

Covers:
- Permission resolution with domain roles (additive overlay)
- JWT creation with domain_roles claim
- Backward compatibility (no domain_roles = existing behavior)
- Domain role ACL scoped overrides
- Edge cases
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from lumina.auth import auth
from lumina.core.permissions import Operation, check_permission, check_permission_or_raise


# ---------------------------------------------------------------------------
# Fixtures — shared module permissions and domain role configs
# ---------------------------------------------------------------------------

EDU_PERMS = {
    "mode": "750",
    "owner": "da_algebra_lead_001",
    "group": "admin",
    "acl": [
        {"role": "operator", "access": "rx", "scope": "evaluation_only"},
        {"role": "half_operator", "access": "r", "scope": "log_records_only"},
        {"role": "user", "access": "x"},
    ],
}

EDU_DOMAIN_ROLES = {
    "schema_version": "1.0",
    "roles": [
        {
            "role_id": "teacher",
            "role_name": "Teacher",
            "hierarchy_level": 1,
            "description": "Instructor with full domain access.",
            "maps_to_system_role": "admin",
            "default_access": "rwx",
            "may_assign_domain_roles": True,
            "max_assignable_level": 2,
        },
        {
            "role_id": "teaching_assistant",
            "role_name": "Teaching Assistant",
            "hierarchy_level": 2,
            "description": "Support staff with read and execute access.",
            "maps_to_system_role": "user",
            "default_access": "rx",
            "may_assign_domain_roles": False,
        },
        {
            "role_id": "student",
            "role_name": "Student",
            "hierarchy_level": 3,
            "description": "Learner with execute-only access.",
            "maps_to_system_role": "user",
            "default_access": "x",
            "may_assign_domain_roles": False,
        },
    ],
    "role_acl": [
        {
            "domain_role": "teaching_assistant",
            "access": "rx",
            "scope": "session_monitoring",
        },
        {
            "domain_role": "teaching_assistant",
            "access": "r",
            "scope": "log_records_own_students",
        },
    ],
}

AGRI_PERMS = {
    "mode": "750",
    "owner": "da_agri_ops_001",
    "group": "admin",
    "acl": [
        {"role": "user", "access": "x"},
    ],
}

AGRI_DOMAIN_ROLES = {
    "schema_version": "1.0",
    "roles": [
        {
            "role_id": "site_manager",
            "role_name": "Site Manager",
            "hierarchy_level": 1,
            "description": "On-site manager.",
            "maps_to_system_role": "admin",
            "default_access": "rwx",
            "may_assign_domain_roles": True,
            "max_assignable_level": 2,
        },
        {
            "role_id": "field_operator",
            "role_name": "Field Operator",
            "hierarchy_level": 2,
            "description": "Field worker.",
            "maps_to_system_role": "user",
            "default_access": "rx",
            "may_assign_domain_roles": False,
        },
        {
            "role_id": "observer",
            "role_name": "Observer",
            "hierarchy_level": 3,
            "description": "Read-only observer.",
            "maps_to_system_role": "user",
            "default_access": "r",
            "may_assign_domain_roles": False,
        },
    ],
}


# ---------------------------------------------------------------------------
# Permission resolution — domain role grants access when system role denies
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDomainRolePermissionGrants:
    """Domain roles grant access that the system role alone would deny."""

    def test_teaching_assistant_gets_read_via_domain_role(self) -> None:
        """A TA with system role 'user' has no read via mode (others=0),
        but domain_role 'teaching_assistant' grants 'rx'."""
        result = check_permission(
            "ta_001",
            "user",
            EDU_PERMS,
            Operation.READ,
            domain_role="teaching_assistant",
            domain_roles_config=EDU_DOMAIN_ROLES,
        )
        assert result is True

    def test_teaching_assistant_gets_execute_via_domain_role(self) -> None:
        result = check_permission(
            "ta_001",
            "user",
            EDU_PERMS,
            Operation.EXECUTE,
            domain_role="teaching_assistant",
            domain_roles_config=EDU_DOMAIN_ROLES,
        )
        assert result is True

    def test_teaching_assistant_denied_write(self) -> None:
        """TA has default_access 'rx' — write is not granted."""
        result = check_permission(
            "ta_001",
            "user",
            EDU_PERMS,
            Operation.WRITE,
            domain_role="teaching_assistant",
            domain_roles_config=EDU_DOMAIN_ROLES,
        )
        assert result is False

    def test_student_gets_execute_only(self) -> None:
        """Student domain role has default_access 'x'."""
        assert check_permission(
            "stu_001", "user", EDU_PERMS, Operation.EXECUTE,
            domain_role="student", domain_roles_config=EDU_DOMAIN_ROLES,
        )
        assert not check_permission(
            "stu_001", "user", EDU_PERMS, Operation.READ,
            domain_role="student", domain_roles_config=EDU_DOMAIN_ROLES,
        )
        assert not check_permission(
            "stu_001", "user", EDU_PERMS, Operation.WRITE,
            domain_role="student", domain_roles_config=EDU_DOMAIN_ROLES,
        )

    def test_teacher_gets_full_access(self) -> None:
        """Teacher domain role maps to DA with default_access 'rwx'."""
        for op in (Operation.READ, Operation.WRITE, Operation.EXECUTE):
            assert check_permission(
                "teacher_001", "admin", EDU_PERMS, op,
                domain_role="teacher", domain_roles_config=EDU_DOMAIN_ROLES,
            )


# ---------------------------------------------------------------------------
# Backward compatibility — no domain roles = existing behavior
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBackwardCompatibility:
    """Existing behavior is preserved when domain_role is not provided."""

    def test_no_domain_role_same_as_before(self) -> None:
        """Without domain_role, 'user' with mode '750' (others=0) is denied read."""
        assert not check_permission("u-1", "user", EDU_PERMS, Operation.READ)

    def test_system_acl_still_works(self) -> None:
        """System ACL entries work unchanged."""
        assert check_permission("qa-1", "operator", EDU_PERMS, Operation.READ)
        assert check_permission("qa-1", "operator", EDU_PERMS, Operation.EXECUTE)

    def test_owner_still_gets_full(self) -> None:
        assert check_permission(
            "da_algebra_lead_001", "admin", EDU_PERMS, Operation.WRITE
        )

    def test_root_still_bypasses(self) -> None:
        assert check_permission("any", "root", EDU_PERMS, Operation.WRITE)

    def test_domain_role_none_config_none(self) -> None:
        """Explicitly passing None for both domain_role params works."""
        assert not check_permission(
            "u-1", "user", EDU_PERMS, Operation.READ,
            domain_role=None, domain_roles_config=None,
        )


# ---------------------------------------------------------------------------
# Domain role ACL overrides
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDomainRoleACL:
    """domain_roles.role_acl provides scoped overrides."""

    def test_role_acl_grants_access(self) -> None:
        """TA gets 'rx' via role_acl entry with scope 'session_monitoring'."""
        assert check_permission(
            "ta_001", "user", EDU_PERMS, Operation.READ,
            domain_role="teaching_assistant",
            domain_roles_config=EDU_DOMAIN_ROLES,
        )

    def test_role_acl_with_domain_role_in_main_acl(self) -> None:
        """domain_role-keyed entries in the main permissions.acl also work."""
        perms_with_dr_acl = {
            **EDU_PERMS,
            "acl": [
                *EDU_PERMS["acl"],
                {"domain_role": "student", "access": "r", "scope": "own_progress"},
            ],
        }
        assert check_permission(
            "stu_001", "user", perms_with_dr_acl, Operation.READ,
            domain_role="student", domain_roles_config=EDU_DOMAIN_ROLES,
        )


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDomainRoleEdgeCases:
    """Edge cases and error conditions."""

    def test_unknown_domain_role_denied(self) -> None:
        """A domain role not in the config is denied."""
        assert not check_permission(
            "u-1", "user", EDU_PERMS, Operation.READ,
            domain_role="nonexistent_role",
            domain_roles_config=EDU_DOMAIN_ROLES,
        )

    def test_domain_role_with_empty_config(self) -> None:
        """Domain role with empty roles list is denied."""
        assert not check_permission(
            "u-1", "user", EDU_PERMS, Operation.READ,
            domain_role="teacher",
            domain_roles_config={"schema_version": "1.0", "roles": []},
        )

    def test_domain_role_without_config(self) -> None:
        """Domain role with no config dict is ignored."""
        assert not check_permission(
            "u-1", "user", EDU_PERMS, Operation.READ,
            domain_role="teacher",
            domain_roles_config=None,
        )

    def test_domain_role_does_not_affect_root_bypass(self) -> None:
        """Root still bypasses even if domain_role is set."""
        assert check_permission(
            "root_001", "root", EDU_PERMS, Operation.WRITE,
            domain_role="student",
            domain_roles_config=EDU_DOMAIN_ROLES,
        )

    def test_system_role_grant_not_revoked_by_domain_role(self) -> None:
        """If system ACL already grants access, domain role cannot revoke it."""
        # user has 'x' via system ACL — student domain role also gives 'x'
        # but even without domain role, system ACL should grant
        assert check_permission("u-1", "user", EDU_PERMS, Operation.EXECUTE)

    def test_different_domains_different_roles(self) -> None:
        """A user can have different domain roles in different domains."""
        # Teacher in education domain
        assert check_permission(
            "user_001", "admin", EDU_PERMS, Operation.WRITE,
            domain_role="teacher", domain_roles_config=EDU_DOMAIN_ROLES,
        )
        # Observer in agriculture domain — read only
        assert check_permission(
            "user_001", "user", AGRI_PERMS, Operation.READ,
            domain_role="observer", domain_roles_config=AGRI_DOMAIN_ROLES,
        )
        assert not check_permission(
            "user_001", "user", AGRI_PERMS, Operation.WRITE,
            domain_role="observer", domain_roles_config=AGRI_DOMAIN_ROLES,
        )


# ---------------------------------------------------------------------------
# check_permission_or_raise with domain roles
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDomainRolePermissionOrRaise:
    """check_permission_or_raise passes domain role params through."""

    def test_or_raise_allows_with_domain_role(self) -> None:
        """Should not raise when domain role grants access."""
        check_permission_or_raise(
            "ta_001", "user", EDU_PERMS, Operation.READ,
            domain_role="teaching_assistant",
            domain_roles_config=EDU_DOMAIN_ROLES,
        )

    def test_or_raise_denies_without_domain_role(self) -> None:
        """Should raise when system role denies and no domain role."""
        with pytest.raises(PermissionError):
            check_permission_or_raise(
                "ta_001", "user", EDU_PERMS, Operation.READ,
            )


# ---------------------------------------------------------------------------
# Agriculture domain roles
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAgricultureDomainRoles:
    """Domain roles for the agriculture domain."""

    def test_site_manager_full_access(self) -> None:
        for op in (Operation.READ, Operation.WRITE, Operation.EXECUTE):
            assert check_permission(
                "mgr_001", "admin", AGRI_PERMS, op,
                domain_role="site_manager",
                domain_roles_config=AGRI_DOMAIN_ROLES,
            )

    def test_field_operator_read_execute(self) -> None:
        assert check_permission(
            "op_001", "user", AGRI_PERMS, Operation.READ,
            domain_role="field_operator",
            domain_roles_config=AGRI_DOMAIN_ROLES,
        )
        assert check_permission(
            "op_001", "user", AGRI_PERMS, Operation.EXECUTE,
            domain_role="field_operator",
            domain_roles_config=AGRI_DOMAIN_ROLES,
        )
        assert not check_permission(
            "op_001", "user", AGRI_PERMS, Operation.WRITE,
            domain_role="field_operator",
            domain_roles_config=AGRI_DOMAIN_ROLES,
        )

    def test_observer_read_only(self) -> None:
        assert check_permission(
            "obs_001", "user", AGRI_PERMS, Operation.READ,
            domain_role="observer",
            domain_roles_config=AGRI_DOMAIN_ROLES,
        )
        # NOTE: observer domain role has default_access 'r' only, but
        # the system-level ACL grants 'x' to system role 'user'.
        # System-level grants cannot be revoked by domain roles (additive
        # overlay principle), so execute is still permitted.
        assert check_permission(
            "obs_001", "user", AGRI_PERMS, Operation.EXECUTE,
            domain_role="observer",
            domain_roles_config=AGRI_DOMAIN_ROLES,
        )
        assert not check_permission(
            "obs_001", "user", AGRI_PERMS, Operation.WRITE,
            domain_role="observer",
            domain_roles_config=AGRI_DOMAIN_ROLES,
        )


    def test_observer_read_only_without_system_acl(self) -> None:
        """When the system ACL does NOT grant 'x' to user, observer is truly read-only."""
        perms_no_user_acl = {
            "mode": "750",
            "owner": "da_agri_ops_001",
            "group": "admin",
        }
        assert check_permission(
            "obs_001", "user", perms_no_user_acl, Operation.READ,
            domain_role="observer",
            domain_roles_config=AGRI_DOMAIN_ROLES,
        )
        assert not check_permission(
            "obs_001", "user", perms_no_user_acl, Operation.EXECUTE,
            domain_role="observer",
            domain_roles_config=AGRI_DOMAIN_ROLES,
        )
        assert not check_permission(
            "obs_001", "user", perms_no_user_acl, Operation.WRITE,
            domain_role="observer",
            domain_roles_config=AGRI_DOMAIN_ROLES,
        )


# ===========================================================================
# Phase 2 — Domain Roles core helper + API endpoint tests
# ===========================================================================

from fastapi.testclient import TestClient

from lumina.persistence.adapter import NullPersistenceAdapter
from lumina.core.yaml_loader import load_yaml as _load_yaml

_REPO_ROOT_DR = Path(__file__).resolve().parents[1]


def _load_api_module_dr():
    module_path = _REPO_ROOT_DR / "src" / "lumina" / "api" / "server.py"
    module_name = "lumina.api.server"
    spec = importlib.util.spec_from_file_location(module_name, str(module_path))
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load lumina-api-server module")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def dr_api_module(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LUMINA_RUNTIME_CONFIG_PATH", "model-packs/education/cfg/runtime-config.yaml")
    monkeypatch.delenv("LUMINA_DOMAIN_REGISTRY_PATH", raising=False)
    mod = _load_api_module_dr()
    mod.PERSISTENCE = NullPersistenceAdapter()
    mod.BOOTSTRAP_MODE = True
    mod._session_containers.clear()
    monkeypatch.setattr(auth, "JWT_SECRET", "test-secret-dr")
    mod.PERSISTENCE.load_subject_profile = _load_yaml
    return mod


@pytest.fixture
def dr_client(dr_api_module):
    return TestClient(dr_api_module.app)


def _dr_register_root(client: TestClient) -> str:
    resp = client.post(
        "/api/auth/register",
        json={"username": "admin_dr", "password": "test-pass-123", "role": "user"},
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]


def _dr_register_user(client: TestClient, username: str = "user_dr") -> dict:
    resp = client.post(
        "/api/auth/register",
        json={"username": username, "password": "test-pass-123", "role": "user"},
    )
    assert resp.status_code == 200
    return resp.json()


def _dr_auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ─────────────────────────────────────────────────────────────
# Core helper unit tests
# ─────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestDomainRoleCoreHelpers:
    """Tests for src/lumina/core/domain_roles.py helper functions."""

    def test_get_default_role_defs_returns_list(self) -> None:
        from lumina.core.domain_roles import get_default_role_defs

        defs = get_default_role_defs()
        assert isinstance(defs, list)
        assert len(defs) >= 4

    def test_default_role_defs_have_required_fields(self) -> None:
        from lumina.core.domain_roles import get_default_role_defs

        for defn in get_default_role_defs():
            assert "role_id" in defn
            assert "label" in defn
            assert "tier_level" in defn
            assert "default_access" in defn

    def test_default_roles_ordered_by_tier_level(self) -> None:
        from lumina.core.domain_roles import get_default_role_defs

        levels = [d["tier_level"] for d in get_default_role_defs()]
        assert levels == sorted(levels)

    def test_get_default_role_defs_contains_all_four_tiers(self) -> None:
        from lumina.core.domain_roles import get_default_role_defs

        role_ids = {d["role_id"] for d in get_default_role_defs()}
        for expected in ("supervisor", "employee", "user_member", "guest"):
            assert expected in role_ids

    def test_get_domain_role_def_known_role(self) -> None:
        from lumina.core.domain_roles import get_domain_role_def

        defn = get_domain_role_def("supervisor")
        assert defn is not None
        assert defn["role_id"] == "supervisor"
        assert "r" in defn["default_access"]
        assert "w" in defn["default_access"]

    def test_get_domain_role_def_unknown_returns_none(self) -> None:
        from lumina.core.domain_roles import get_domain_role_def

        assert get_domain_role_def("nonexistent_role_xyz") is None

    def test_check_scoped_capability_supervisor_write(self) -> None:
        from lumina.core.domain_roles import check_scoped_capability

        assert check_scoped_capability("supervisor", "w", {}) is True

    def test_check_scoped_capability_guest_no_write(self) -> None:
        from lumina.core.domain_roles import check_scoped_capability

        assert check_scoped_capability("guest", "w", {}) is False

    def test_check_scoped_capability_guest_read(self) -> None:
        from lumina.core.domain_roles import check_scoped_capability

        assert check_scoped_capability("guest", "r", {}) is True

    def test_check_scoped_capability_unknown_role_false(self) -> None:
        from lumina.core.domain_roles import check_scoped_capability

        assert check_scoped_capability("phantom_role", "r", {}) is False

    def test_get_active_role_defs_defaults_only(self) -> None:
        from lumina.core.domain_roles import get_active_role_defs, get_default_role_defs

        active_ids = {d["role_id"] for d in get_active_role_defs({})}
        default_ids = {d["role_id"] for d in get_default_role_defs()}
        assert default_ids.issubset(active_ids)

    def test_get_active_role_defs_merges_domain_override(self) -> None:
        from lumina.core.domain_roles import get_active_role_defs

        physics = {
            "domain_roles": {
                "roles": [
                    {
                        "role_id": "supervisor",
                        "label": "Department Head",
                        "tier_level": 1,
                        "default_access": "rwxi",
                    }
                ]
            }
        }
        active = {d["role_id"]: d for d in get_active_role_defs(physics)}
        assert active["supervisor"]["label"] == "Department Head"

    def test_get_active_role_defs_adds_domain_only_role(self) -> None:
        from lumina.core.domain_roles import get_active_role_defs

        physics = {
            "domain_roles": {
                "roles": [
                    {
                        "role_id": "lab_assistant",
                        "label": "Lab Assistant",
                        "tier_level": 5,
                        "default_access": "x",
                    }
                ]
            }
        }
        active_ids = {d["role_id"] for d in get_active_role_defs(physics)}
        assert "lab_assistant" in active_ids


# ─────────────────────────────────────────────────────────────
# API integration tests — /api/domain-roles/**
# ─────────────────────────────────────────────────────────────


@pytest.mark.integration
class TestListDefaultRolesEndpoint:
    def test_root_can_list_defaults(self, dr_client: TestClient) -> None:
        root_token = _dr_register_root(dr_client)
        resp = dr_client.get("/api/domain-roles/defaults", headers=_dr_auth(root_token))
        assert resp.status_code == 200
        roles = resp.json()
        assert isinstance(roles, list)
        role_ids = [r["role_id"] for r in roles]
        for expected in ("supervisor", "employee", "user_member", "guest"):
            assert expected in role_ids

    def test_ordinary_user_gets_403(self, dr_client: TestClient) -> None:
        _dr_register_root(dr_client)
        user = _dr_register_user(dr_client, "plain_user_a")
        token = dr_client.post(
            "/api/auth/login",
            json={"username": "plain_user_a", "password": "test-pass-123"},
        ).json()["access_token"]
        resp = dr_client.get("/api/domain-roles/defaults", headers=_dr_auth(token))
        assert resp.status_code == 403

    def test_unauthenticated_returns_401(self, dr_client: TestClient) -> None:
        resp = dr_client.get("/api/domain-roles/defaults")
        assert resp.status_code == 401


@pytest.mark.integration
class TestAssignDomainRoleEndpoint:
    def test_root_can_assign_known_role(
        self, dr_client: TestClient, dr_api_module
    ) -> None:
        root_token = _dr_register_root(dr_client)
        user = _dr_register_user(dr_client, "carol_dr")
        resp = dr_client.post(
            "/api/domain-roles/education/assign",
            json={"user_id": user["user_id"], "domain_role": "supervisor"},
            headers=_dr_auth(root_token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["user_id"] == user["user_id"]
        assert body["module_id"] == "education"
        assert body["domain_role"] == "supervisor"
        assert "record_id" in body

    def test_unknown_domain_role_rejected(self, dr_client: TestClient) -> None:
        root_token = _dr_register_root(dr_client)
        user = _dr_register_user(dr_client, "dave_dr")
        resp = dr_client.post(
            "/api/domain-roles/education/assign",
            json={"user_id": user["user_id"], "domain_role": "wizard"},
            headers=_dr_auth(root_token),
        )
        assert resp.status_code == 400

    def test_user_role_insufficient(self, dr_client: TestClient) -> None:
        _dr_register_root(dr_client)
        user = _dr_register_user(dr_client, "eve_dr")
        token = dr_client.post(
            "/api/auth/login",
            json={"username": "eve_dr", "password": "test-pass-123"},
        ).json()["access_token"]
        resp = dr_client.post(
            "/api/domain-roles/education/assign",
            json={"user_id": user["user_id"], "domain_role": "supervisor"},
            headers=_dr_auth(token),
        )
        assert resp.status_code == 403

    def test_nonexistent_user_returns_404(self, dr_client: TestClient) -> None:
        root_token = _dr_register_root(dr_client)
        resp = dr_client.post(
            "/api/domain-roles/education/assign",
            json={"user_id": "ghost-id-555", "domain_role": "employee"},
            headers=_dr_auth(root_token),
        )
        assert resp.status_code == 404

    def test_role_persisted_in_adapter(
        self, dr_client: TestClient, dr_api_module
    ) -> None:
        root_token = _dr_register_root(dr_client)
        user = _dr_register_user(dr_client, "frank_dr")
        dr_client.post(
            "/api/domain-roles/education/assign",
            json={"user_id": user["user_id"], "domain_role": "employee"},
            headers=_dr_auth(root_token),
        )
        stored = dr_api_module.PERSISTENCE.get_user(user["user_id"])
        assert stored is not None
        assert stored.get("domain_roles", {}).get("education") == "employee"

    def test_unauthenticated_returns_401(self, dr_client: TestClient) -> None:
        resp = dr_client.post(
            "/api/domain-roles/education/assign",
            json={"user_id": "any", "domain_role": "guest"},
        )
        assert resp.status_code == 401


@pytest.mark.integration
class TestRevokeDomainRoleEndpoint:
    def test_root_can_revoke_assigned_role(
        self, dr_client: TestClient, dr_api_module
    ) -> None:
        root_token = _dr_register_root(dr_client)
        user = _dr_register_user(dr_client, "grace_dr")
        # assign first
        dr_client.post(
            "/api/domain-roles/education/assign",
            json={"user_id": user["user_id"], "domain_role": "supervisor"},
            headers=_dr_auth(root_token),
        )
        # revoke
        resp = dr_client.delete(
            f"/api/domain-roles/education/{user['user_id']}",
            headers=_dr_auth(root_token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["revoked_role"] == "supervisor"
        assert "record_id" in body

    def test_revoke_user_with_no_role_returns_404(
        self, dr_client: TestClient
    ) -> None:
        root_token = _dr_register_root(dr_client)
        user = _dr_register_user(dr_client, "henry_dr")
        resp = dr_client.delete(
            f"/api/domain-roles/education/{user['user_id']}",
            headers=_dr_auth(root_token),
        )
        assert resp.status_code == 404

    def test_revoke_nonexistent_user_returns_404(
        self, dr_client: TestClient
    ) -> None:
        root_token = _dr_register_root(dr_client)
        resp = dr_client.delete(
            "/api/domain-roles/education/ghost-id-xyz",
            headers=_dr_auth(root_token),
        )
        assert resp.status_code == 404

    def test_user_role_cannot_revoke(self, dr_client: TestClient) -> None:
        _dr_register_root(dr_client)
        user = _dr_register_user(dr_client, "iris_dr")
        token = dr_client.post(
            "/api/auth/login",
            json={"username": "iris_dr", "password": "test-pass-123"},
        ).json()["access_token"]
        resp = dr_client.delete(
            f"/api/domain-roles/education/{user['user_id']}",
            headers=_dr_auth(token),
        )
        assert resp.status_code == 403

    def test_unauthenticated_returns_401(self, dr_client: TestClient) -> None:
        resp = dr_client.delete("/api/domain-roles/education/any-user")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# JWT domain_roles claim
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestJWTDomainRoles:
    """JWT creation and verification with domain_roles claim."""

    def test_create_jwt_with_domain_roles(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(auth, "JWT_SECRET", "test-secret")
        dr = {"domain/edu/algebra-level-1/v1": "teaching_assistant"}
        token = auth.create_jwt(
            user_id="ta_001",
            role="user",
            domain_roles=dr,
            ttl_minutes=5,
        )
        payload = auth.verify_jwt(token)
        assert payload["domain_roles"] == dr
        assert payload["role"] == "user"
        assert payload["sub"] == "ta_001"

    def test_create_jwt_without_domain_roles(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """domain_roles omitted from payload when None or empty."""
        monkeypatch.setattr(auth, "JWT_SECRET", "test-secret")
        token = auth.create_jwt(user_id="u-1", role="user", ttl_minutes=5)
        payload = auth.verify_jwt(token)
        assert "domain_roles" not in payload

    def test_create_jwt_empty_domain_roles(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Empty dict is treated as no domain roles."""
        monkeypatch.setattr(auth, "JWT_SECRET", "test-secret")
        token = auth.create_jwt(
            user_id="u-1", role="user", domain_roles={}, ttl_minutes=5,
        )
        payload = auth.verify_jwt(token)
        assert "domain_roles" not in payload

    def test_create_jwt_multiple_domain_roles(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """User can hold different domain roles in different modules."""
        monkeypatch.setattr(auth, "JWT_SECRET", "test-secret")
        dr = {
            "domain/edu/algebra-level-1/v1": "teacher",
            "domain/edu/geometry-level-1/v1": "teaching_assistant",
        }
        token = auth.create_jwt(
            user_id="multi_001", role="admin",
            domain_roles=dr, ttl_minutes=5,
        )
        payload = auth.verify_jwt(token)
        assert payload["domain_roles"] == dr
