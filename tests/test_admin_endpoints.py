"""Tests for admin API endpoints — user management, domain pack lifecycle,
audit & escalation, CTL queries, and session close."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lumina.auth import auth
from lumina.persistence.adapter import NullPersistenceAdapter
from lumina.core.yaml_loader import load_yaml as _load_yaml

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_api_module():
    module_path = _REPO_ROOT / "src" / "lumina" / "api" / "server.py"
    module_name = "lumina_api_server_admin_test"
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
    mod.PERSISTENCE = NullPersistenceAdapter()
    mod.BOOTSTRAP_MODE = True
    mod._session_containers.clear()
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
            json={"role": "qa"},
            headers=_auth_header(root_token),
        )
        assert resp.status_code == 200
        assert resp.json()["role"] == "qa"

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
            json={"role": "qa"},
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
        # Login with new password
        login = client.post(
            "/api/auth/login",
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
    def test_query_ctl_records(self, client: TestClient) -> None:
        root_token = _register_root(client)
        resp = client.get("/api/ctl/records", headers=_auth_header(root_token))
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_list_ctl_sessions(self, client: TestClient) -> None:
        root_token = _register_root(client)
        resp = client.get("/api/ctl/sessions", headers=_auth_header(root_token))
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_get_ctl_record_not_found(self, client: TestClient) -> None:
        root_token = _register_root(client)
        resp = client.get(
            "/api/ctl/records/nonexistent-id",
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
        resp = client.get("/api/ctl/records", headers=_auth_header(user_token))
        assert resp.status_code == 403

    def test_user_cannot_list_ctl_sessions(self, client: TestClient) -> None:
        _register_root(client)
        _register_user(client, "bob")
        user_token = client.post(
            "/api/auth/login",
            json={"username": "bob", "password": "test-pass-123"},
        ).json()["access_token"]
        resp = client.get("/api/ctl/sessions", headers=_auth_header(user_token))
        assert resp.status_code == 403
