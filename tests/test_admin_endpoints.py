"""Tests for admin API endpoints — user management, domain pack lifecycle,
audit & escalation, System Log queries, and session close."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lumina.auth import auth
from lumina.persistence.adapter import NullPersistenceAdapter
from lumina.core.yaml_loader import load_yaml as _load_yaml

from lumina.core.domain_registry import DomainRegistry
from lumina.core.runtime_loader import load_runtime_context

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_api_module():
    module_path = _REPO_ROOT / "src" / "lumina" / "api" / "server.py"
    module_name = "lumina.api.server"
    spec = importlib.util.spec_from_file_location(module_name, str(module_path))
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load lumina-api-server module")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def api_module(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LUMINA_RUNTIME_CONFIG_PATH", "domain-packs/education/cfg/runtime-config.yaml")
    monkeypatch.delenv("LUMINA_DOMAIN_REGISTRY_PATH", raising=False)
    mod = _load_api_module()
    # Reset DOMAIN_REGISTRY to a clean single-domain instance so that
    # prior test modules that triggered config.py with a multi-domain
    # registry don't pollute the "_default" domain expected here.
    mod.DOMAIN_REGISTRY = DomainRegistry(
        repo_root=_REPO_ROOT,
        single_config_path="domain-packs/education/cfg/runtime-config.yaml",
        load_runtime_context_fn=load_runtime_context,
    )
    mod.PERSISTENCE = NullPersistenceAdapter()
    mod.BOOTSTRAP_MODE = True
    mod._session_containers.clear()
    mod._STAGED_COMMANDS.clear()
    monkeypatch.setattr(auth, "JWT_SECRET", "test-secret-admin")
    mod.PERSISTENCE.load_subject_profile = _load_yaml

    return mod


@pytest.fixture
def client(api_module):
    return TestClient(api_module.app)


def _register_root(client: TestClient) -> str:
    """Register first user (auto-promoted to root) and return token."""
    resp = client.post(
        "/api/auth/register",
        json={"username": "admin", "password": "test-pass-123", "role": "user"},
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]


def _register_user(client: TestClient, username: str = "regular", role: str = "user") -> dict:
    """Register a non-root user and return full response body."""
    resp = client.post(
        "/api/auth/register",
        json={"username": username, "password": "test-pass-123", "role": role},
    )
    assert resp.status_code == 200
    return resp.json()


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ─────────────────────────────────────────────────────────────
# Phase 1: User & Access Management
# ─────────────────────────────────────────────────────────────


@pytest.mark.integration
class TestUpdateUser:
    def test_root_can_update_user_role(self, client: TestClient) -> None:
        root_token = _register_root(client)
        user = _register_user(client, "bob")
        resp = client.patch(
            f"/api/auth/users/{user['user_id']}",
            json={"role": "operator"},
            headers=_auth_header(root_token),
        )
        assert resp.status_code == 200
        assert resp.json()["role"] == "operator"

    def test_non_root_cannot_update_user(self, client: TestClient) -> None:
        _register_root(client)
        user = _register_user(client, "bob")
        user_token = client.post(
            "/api/auth/login",
            json={"username": "bob", "password": "test-pass-123"},
        ).json()["access_token"]
        resp = client.patch(
            f"/api/auth/users/{user['user_id']}",
            json={"role": "root"},
            headers=_auth_header(user_token),
        )
        assert resp.status_code == 403

    def test_update_nonexistent_user(self, client: TestClient) -> None:
        root_token = _register_root(client)
        resp = client.patch(
            "/api/auth/users/nonexistent-id",
            json={"role": "operator"},
            headers=_auth_header(root_token),
        )
        assert resp.status_code == 404

    def test_invalid_role_rejected(self, client: TestClient) -> None:
        root_token = _register_root(client)
        user = _register_user(client, "bob")
        resp = client.patch(
            f"/api/auth/users/{user['user_id']}",
            json={"role": "superadmin"},
            headers=_auth_header(root_token),
        )
        assert resp.status_code == 400


@pytest.mark.integration
class TestDeleteUser:
    def test_root_can_deactivate_user(self, client: TestClient) -> None:
        root_token = _register_root(client)
        user = _register_user(client, "bob")
        resp = client.delete(
            f"/api/auth/users/{user['user_id']}",
            headers=_auth_header(root_token),
        )
        assert resp.status_code == 204

    def test_cannot_deactivate_self(self, client: TestClient) -> None:
        root_resp = client.post(
            "/api/auth/register",
            json={"username": "admin", "password": "test-pass-123", "role": "user"},
        )
        root_token = root_resp.json()["access_token"]
        root_id = root_resp.json()["user_id"]
        resp = client.delete(
            f"/api/auth/users/{root_id}",
            headers=_auth_header(root_token),
        )
        assert resp.status_code == 400

    def test_deactivated_user_cannot_login(self, client: TestClient) -> None:
        root_token = _register_root(client)
        _register_user(client, "bob")
        # Get bob's user_id
        users = client.get("/api/auth/users", headers=_auth_header(root_token)).json()
        bob = next(u for u in users if u["username"] == "bob")
        # Deactivate
        client.delete(f"/api/auth/users/{bob['user_id']}", headers=_auth_header(root_token))
        # Try login
        resp = client.post("/api/auth/login", json={"username": "bob", "password": "test-pass-123"})
        assert resp.status_code == 403


@pytest.mark.integration
class TestRevokeToken:
    def test_revoke_own_token(self, client: TestClient) -> None:
        root_token = _register_root(client)
        resp = client.post(
            "/api/auth/revoke",
            json={},
            headers=_auth_header(root_token),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "revoked"

    def test_revoked_token_rejected(self, client: TestClient) -> None:
        root_token = _register_root(client)
        client.post("/api/auth/revoke", json={}, headers=_auth_header(root_token))
        # Using the same token should now fail
        resp = client.get("/api/auth/me", headers=_auth_header(root_token))
        assert resp.status_code == 401


@pytest.mark.integration
class TestPasswordReset:
    def test_reset_own_password(self, client: TestClient) -> None:
        root_token = _register_root(client)
        resp = client.post(
            "/api/auth/password-reset",
            json={"new_password": "new-pass-12345"},
            headers=_auth_header(root_token),
        )
        assert resp.status_code == 200
        # Login with new password (root uses admin-track endpoint)
        login = client.post(
            "/api/admin/auth/login",
            json={"username": "admin", "password": "new-pass-12345"},
        )
        assert login.status_code == 200

    def test_short_password_rejected(self, client: TestClient) -> None:
        root_token = _register_root(client)
        resp = client.post(
            "/api/auth/password-reset",
            json={"new_password": "short"},
            headers=_auth_header(root_token),
        )
        assert resp.status_code == 400


# ─────────────────────────────────────────────────────────────
# Phase 2: Domain Pack Lifecycle
# ─────────────────────────────────────────────────────────────


@pytest.mark.integration
class TestDomainPackCommit:
    def test_commit_and_history(self, client: TestClient) -> None:
        root_token = _register_root(client)
        # Commit
        resp = client.post(
            "/api/domain-pack/commit",
            json={"domain_id": "_default", "summary": "test commit"},
            headers=_auth_header(root_token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["commitment_type"] == "domain_pack_activation"
        assert body["subject_hash"]
        assert body["record_id"]

    def test_non_root_non_da_rejected(self, client: TestClient) -> None:
        _register_root(client)
        user = _register_user(client, "bob")
        user_token = client.post(
            "/api/auth/login",
            json={"username": "bob", "password": "test-pass-123"},
        ).json()["access_token"]
        resp = client.post(
            "/api/domain-pack/commit",
            json={"domain_id": "_default", "summary": "test"},
            headers=_auth_header(user_token),
        )
        assert resp.status_code == 403


@pytest.mark.integration
class TestSessionClose:
    def test_close_own_session(self, client: TestClient, api_module) -> None:
        root_token = _register_root(client)
        # Create a session by sending a chat message
        chat_resp = client.post(
            "/api/chat",
            json={"message": "hello", "deterministic_response": True},
            headers=_auth_header(root_token),
        )
        assert chat_resp.status_code == 200
        session_id = chat_resp.json()["session_id"]

        # Close the session
        resp = client.post(
            f"/api/session/{session_id}/close",
            headers=_auth_header(root_token),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "closed"

        # Session should no longer be in memory
        assert session_id not in api_module._session_containers

    def test_close_nonexistent_session(self, client: TestClient) -> None:
        root_token = _register_root(client)
        resp = client.post(
            "/api/session/nonexistent/close",
            headers=_auth_header(root_token),
        )
        assert resp.status_code == 404


# ─────────────────────────────────────────────────────────────
# Phase 3: Audit & Escalation
# ─────────────────────────────────────────────────────────────


@pytest.mark.integration
class TestEscalations:
    def test_list_escalations_empty(self, client: TestClient) -> None:
        root_token = _register_root(client)
        resp = client.get("/api/escalations", headers=_auth_header(root_token))
        assert resp.status_code == 200
        assert resp.json() == []

    def test_user_role_cannot_list_escalations(self, client: TestClient) -> None:
        _register_root(client)
        _register_user(client, "bob")
        user_token = client.post(
            "/api/auth/login",
            json={"username": "bob", "password": "test-pass-123"},
        ).json()["access_token"]
        resp = client.get("/api/escalations", headers=_auth_header(user_token))
        assert resp.status_code == 403


@pytest.mark.integration
class TestAuditLog:
    def test_generate_audit_log(self, client: TestClient) -> None:
        root_token = _register_root(client)
        resp = client.get("/api/audit/log", headers=_auth_header(root_token))
        assert resp.status_code == 200
        body = resp.json()
        assert "total_records" in body
        assert "record_type_counts" in body

    def test_user_can_request_own_audit(self, client: TestClient) -> None:
        _register_root(client)
        _register_user(client, "bob")
        user_token = client.post(
            "/api/auth/login",
            json={"username": "bob", "password": "test-pass-123"},
        ).json()["access_token"]
        resp = client.get("/api/audit/log", headers=_auth_header(user_token))
        assert resp.status_code == 200


@pytest.mark.integration
class TestCtlQueries:
    def test_query_log_records(self, client: TestClient) -> None:
        root_token = _register_root(client)
        resp = client.get("/api/system-log/records", headers=_auth_header(root_token))
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_list_log_sessions(self, client: TestClient) -> None:
        root_token = _register_root(client)
        resp = client.get("/api/system-log/sessions", headers=_auth_header(root_token))
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_get_log_record_not_found(self, client: TestClient) -> None:
        root_token = _register_root(client)
        resp = client.get(
            "/api/system-log/records/nonexistent-id",
            headers=_auth_header(root_token),
        )
        assert resp.status_code == 404

    def test_user_cannot_query_ctl(self, client: TestClient) -> None:
        _register_root(client)
        _register_user(client, "bob")
        user_token = client.post(
            "/api/auth/login",
            json={"username": "bob", "password": "test-pass-123"},
        ).json()["access_token"]
        resp = client.get("/api/system-log/records", headers=_auth_header(user_token))
        assert resp.status_code == 403

    def test_user_cannot_list_log_sessions(self, client: TestClient) -> None:
        _register_root(client)
        _register_user(client, "bob")
        user_token = client.post(
            "/api/auth/login",
            json={"username": "bob", "password": "test-pass-123"},
        ).json()["access_token"]
        resp = client.get("/api/system-log/sessions", headers=_auth_header(user_token))
        assert resp.status_code == 403


# ─────────────────────────────────────────────────────────────
# Phase 4: Domain Roles on User Update
# ─────────────────────────────────────────────────────────────


@pytest.mark.integration
class TestUpdateUserDomainRoles:
    def test_root_can_assign_domain_roles(self, client: TestClient) -> None:
        root_token = _register_root(client)
        user = _register_user(client, "bob")
        resp = client.patch(
            f"/api/auth/users/{user['user_id']}",
            json={"domain_roles": {"education": "supervisor"}},
            headers=_auth_header(root_token),
        )
        assert resp.status_code == 200

    def test_domain_roles_persisted_after_update(self, client: TestClient, api_module) -> None:
        root_token = _register_root(client)
        user = _register_user(client, "carol")
        client.patch(
            f"/api/auth/users/{user['user_id']}",
            json={"domain_roles": {"education": "employee"}},
            headers=_auth_header(root_token),
        )
        stored = api_module.PERSISTENCE.get_user(user["user_id"])
        assert stored is not None
        assert stored.get("domain_roles", {}).get("education") == "employee"

    def test_domain_roles_merge_on_second_update(self, client: TestClient, api_module) -> None:
        root_token = _register_root(client)
        user = _register_user(client, "dave")
        client.patch(
            f"/api/auth/users/{user['user_id']}",
            json={"domain_roles": {"education": "supervisor"}},
            headers=_auth_header(root_token),
        )
        client.patch(
            f"/api/auth/users/{user['user_id']}",
            json={"domain_roles": {"agriculture": "employee"}},
            headers=_auth_header(root_token),
        )
        stored = api_module.PERSISTENCE.get_user(user["user_id"])
        assert stored is not None
        assert stored["domain_roles"].get("education") == "supervisor"
        assert stored["domain_roles"].get("agriculture") == "employee"

    def test_domain_roles_in_jwt_after_login(self, client: TestClient) -> None:
        from lumina.auth.auth import verify_jwt

        root_token = _register_root(client)
        user = _register_user(client, "eve")
        client.patch(
            f"/api/auth/users/{user['user_id']}",
            json={"domain_roles": {"education": "supervisor"}},
            headers=_auth_header(root_token),
        )
        login_resp = client.post(
            "/api/auth/login",
            json={"username": "eve", "password": "test-pass-123"},
        )
        assert login_resp.status_code == 200
        token = login_resp.json()["access_token"]
        claims = verify_jwt(token)
        assert claims is not None
        assert claims.get("domain_roles", {}).get("education") == "supervisor"


# ─────────────────────────────────────────────────────────────
# Phase 5: Audit Log Scoping
# ─────────────────────────────────────────────────────────────


@pytest.mark.integration
class TestAuditLogScoping:
    def test_da_without_governed_modules_gets_403(self, client: TestClient) -> None:
        root_token = _register_root(client)
        user = _register_user(client, "da-user")
        # Promote to admin with NO governed_modules
        client.patch(
            f"/api/auth/users/{user['user_id']}",
            json={"role": "admin"},
            headers=_auth_header(root_token),
        )
        da_token = client.post(
            "/api/domain/auth/login",
            json={"username": "da-user", "password": "test-pass-123"},
        ).json()["access_token"]
        resp = client.get("/api/audit/log", headers=_auth_header(da_token))
        assert resp.status_code == 403

    def test_guest_role_gets_403(self, client: TestClient) -> None:
        resp = client.get("/api/auth/guest-token")
        guest_token = resp.json()["access_token"]
        resp = client.get("/api/audit/log", headers=_auth_header(guest_token))
        assert resp.status_code == 403


# ─────────────────────────────────────────────────────────────
# Phase 6: Staged Commands List
# ─────────────────────────────────────────────────────────────


@pytest.mark.integration
class TestStagedCommandsList:
    def test_unauthenticated_returns_401(self, client: TestClient) -> None:
        resp = client.get("/api/admin/command/staged")
        assert resp.status_code == 401

    def test_user_role_returns_403(self, client: TestClient) -> None:
        _register_root(client)
        _register_user(client, "bob")
        user_token = client.post(
            "/api/auth/login",
            json={"username": "bob", "password": "test-pass-123"},
        ).json()["access_token"]
        resp = client.get("/api/admin/command/staged", headers=_auth_header(user_token))
        assert resp.status_code == 403

    def test_root_sees_empty_staged_list_initially(self, client: TestClient) -> None:
        root_token = _register_root(client)
        resp = client.get("/api/admin/command/staged", headers=_auth_header(root_token))
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 0
        assert body["staged_commands"] == []
        assert "limit" in body
        assert "offset" in body
