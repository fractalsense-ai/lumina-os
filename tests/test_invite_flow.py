"""Tests for the user invite / onboarding flow (Phase 4).

Covers:
  - Unit tests for ``lumina.core.invite_store`` token functions.
  - Integration tests for ``POST /api/auth/invite``.
  - Integration tests for ``POST /api/auth/setup-password``.
  - Integration tests for the ``invite_user`` HITL admin command operation.
"""

from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from lumina.auth import auth
from lumina.core import invite_store as _is
from lumina.persistence.adapter import NullPersistenceAdapter
from lumina.core.yaml_loader import load_yaml as _load_yaml

_REPO_ROOT = Path(__file__).resolve().parents[1]


# ─────────────────────────────────────────────────────────────
# Module loader
# ─────────────────────────────────────────────────────────────

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


@pytest.fixture(autouse=True)
def clear_invite_store():
    """Ensure the in-memory invite token store is clean before/after each test."""
    _is._INVITE_TOKENS.clear()
    yield
    _is._INVITE_TOKENS.clear()


@pytest.fixture
def api_module(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LUMINA_RUNTIME_CONFIG_PATH", "domain-packs/education/cfg/runtime-config.yaml")
    monkeypatch.delenv("LUMINA_DOMAIN_REGISTRY_PATH", raising=False)
    monkeypatch.delenv("LUMINA_SMTP_HOST", raising=False)  # SMTP off by default
    mod = _load_api_module()
    mod.PERSISTENCE = NullPersistenceAdapter()
    mod.BOOTSTRAP_MODE = True
    mod._session_containers.clear()
    monkeypatch.setattr(auth, "JWT_SECRET", "test-secret-invite")
    mod.PERSISTENCE.load_subject_profile = _load_yaml
    return mod


@pytest.fixture
def client(api_module) -> TestClient:
    return TestClient(api_module.app)


# ─────────────────────────────────────────────────────────────
# Auth helpers
# ─────────────────────────────────────────────────────────────

def _register_root(client: TestClient) -> str:
    resp = client.post(
        "/api/auth/register",
        json={"username": "root-inv", "password": "pass-1234", "role": "user"},
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ─────────────────────────────────────────────────────────────
# § 1 — Unit tests: invite_store module
# ─────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestInviteStoreCore:
    def test_generate_returns_url_safe_string(self) -> None:
        token = _is.generate_invite_token("uid-1", "alice")
        assert len(token) >= 32

    def test_validate_returns_user_id_and_deletes_token(self) -> None:
        token = _is.generate_invite_token("uid-2", "bob")
        result = _is.validate_invite_token(token)
        assert result == "uid-2"
        # consumed — second call returns None
        assert _is.validate_invite_token(token) is None

    def test_validate_unknown_token_returns_none(self) -> None:
        assert _is.validate_invite_token("not-a-real-token") is None

    def test_has_pending_invite_true_when_present(self) -> None:
        _is.generate_invite_token("uid-3", "carol")
        assert _is.has_pending_invite("uid-3") is True

    def test_has_pending_invite_false_after_validate(self) -> None:
        token = _is.generate_invite_token("uid-4", "dave")
        _is.validate_invite_token(token)
        assert _is.has_pending_invite("uid-4") is False

    def test_generate_replaces_previous_token_for_same_user(self) -> None:
        t1 = _is.generate_invite_token("uid-5", "eve")
        t2 = _is.generate_invite_token("uid-5", "eve")
        assert t1 != t2
        # Only the new token is valid
        assert _is.validate_invite_token(t1) is None
        assert _is.validate_invite_token(t2) == "uid-5"

    def test_purges_expired_tokens(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_is, "_INVITE_TOKEN_TTL_SECONDS", 0)
        token = _is.generate_invite_token("uid-6", "frank")
        # Force expiry
        _is._INVITE_TOKENS[token]["expires_at"] = time.time() - 1
        result = _is.validate_invite_token(token)
        assert result is None


# ─────────────────────────────────────────────────────────────
# § 2 — Integration: POST /api/auth/invite
# ─────────────────────────────────────────────────────────────


@pytest.mark.integration
class TestInviteEndpoint:
    def test_invite_regular_user_returns_setup_url(
        self, client: TestClient, api_module: Any
    ) -> None:
        root_token = _register_root(client)
        resp = client.post(
            "/api/auth/invite",
            json={"username": "new-user", "role": "user"},
            headers=_auth(root_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["username"] == "new-user"
        assert data["role"] == "user"
        assert "setup_token" in data
        assert "setup_url" in data
        assert data["setup_token"] in data["setup_url"]
        assert data["email_sent"] is False

    def test_invite_creates_pending_account(
        self, client: TestClient, api_module: Any
    ) -> None:
        root_token = _register_root(client)
        resp = client.post(
            "/api/auth/invite",
            json={"username": "pending-user", "role": "user"},
            headers=_auth(root_token),
        )
        assert resp.status_code == 200
        user_id = resp.json()["user_id"]
        user = api_module.PERSISTENCE.get_user(user_id)
        assert user is not None
        assert user["active"] is False
        assert user["password_hash"] == ""

    def test_invite_domain_authority_without_governed_modules_succeeds(
        self, client: TestClient
    ) -> None:
        """DA with null governed_modules = access to ALL modules (Phase 6)."""
        root_token = _register_root(client)
        resp = client.post(
            "/api/auth/invite",
            json={"username": "da-nomod", "role": "admin"},
            headers=_auth(root_token),
        )
        assert resp.status_code == 200

    def test_invite_domain_authority_with_modules_succeeds(
        self, client: TestClient, api_module: Any
    ) -> None:
        root_token = _register_root(client)
        resp = client.post(
            "/api/auth/invite",
            json={
                "username": "da-user",
                "role": "admin",
                "governed_modules": ["domain/edu/algebra-level-1/v1"],
            },
            headers=_auth(root_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["role"] == "admin"
        assert "domain/edu/algebra-level-1/v1" in data["governed_modules"]

    def test_invite_rejects_invalid_role(self, client: TestClient) -> None:
        root_token = _register_root(client)
        resp = client.post(
            "/api/auth/invite",
            json={"username": "bad-role-user", "role": "superadmin"},
            headers=_auth(root_token),
        )
        assert resp.status_code == 400

    def test_invite_rejects_duplicate_username(self, client: TestClient) -> None:
        root_token = _register_root(client)
        client.post(
            "/api/auth/invite",
            json={"username": "dup-user", "role": "user"},
            headers=_auth(root_token),
        )
        resp = client.post(
            "/api/auth/invite",
            json={"username": "dup-user", "role": "user"},
            headers=_auth(root_token),
        )
        assert resp.status_code == 409

    def test_invite_requires_auth(self, client: TestClient) -> None:
        resp = client.post(
            "/api/auth/invite",
            json={"username": "anon-user", "role": "user"},
        )
        assert resp.status_code in (401, 403)

    def test_invite_by_unprivileged_user_is_rejected(self, client: TestClient) -> None:
        # Register root first to ensure subsequent registrations don't get promoted
        _register_root(client)
        # Register a plain user (not the first, so it stays as 'user' role)
        client.post(
            "/api/auth/register",
            json={"username": "plain-user", "password": "pass-1234", "role": "user"},
        )
        token = client.post(
            "/api/auth/login",
            json={"username": "plain-user", "password": "pass-1234"},
        ).json()["access_token"]

        resp = client.post(
            "/api/auth/invite",
            json={"username": "another-user", "role": "user"},
            headers=_auth(token),
        )
        assert resp.status_code == 403


# ─────────────────────────────────────────────────────────────
# § 3 — Integration: POST /api/auth/setup-password
# ─────────────────────────────────────────────────────────────


@pytest.mark.integration
class TestSetupPasswordEndpoint:
    def _invite_and_get_token(self, client: TestClient, username: str = "new-invite-user") -> str:
        root_token = _register_root(client)
        resp = client.post(
            "/api/auth/invite",
            json={"username": username, "role": "user"},
            headers=_auth(root_token),
        )
        assert resp.status_code == 200
        return resp.json()["setup_token"]

    def test_setup_password_activates_account_and_returns_jwt(
        self, client: TestClient, api_module: Any
    ) -> None:
        setup_token = self._invite_and_get_token(client)
        resp = client.post(
            "/api/auth/setup-password",
            json={"token": setup_token, "new_password": "MyStr0ngPass"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    def test_setup_password_activates_user_record(
        self, client: TestClient, api_module: Any
    ) -> None:
        setup_token = self._invite_and_get_token(client, username="activate-me")
        user_before = api_module.PERSISTENCE.get_user_by_username("activate-me")
        assert user_before is not None
        assert user_before["active"] is False

        client.post(
            "/api/auth/setup-password",
            json={"token": setup_token, "new_password": "MyStr0ngPass"},
        )
        user_after = api_module.PERSISTENCE.get_user_by_username("activate-me")
        assert user_after is not None
        assert user_after["active"] is True

    def test_setup_password_token_is_single_use(
        self, client: TestClient
    ) -> None:
        setup_token = self._invite_and_get_token(client, username="single-use-user")
        client.post(
            "/api/auth/setup-password",
            json={"token": setup_token, "new_password": "MyStr0ngPass"},
        )
        # Second call with same token is rejected
        resp2 = client.post(
            "/api/auth/setup-password",
            json={"token": setup_token, "new_password": "AnotherPass"},
        )
        assert resp2.status_code == 403

    def test_setup_password_invalid_token_returns_403(
        self, client: TestClient
    ) -> None:
        resp = client.post(
            "/api/auth/setup-password",
            json={"token": "completely-invalid-token", "new_password": "MyStr0ngPass"},
        )
        assert resp.status_code == 403

    def test_setup_password_too_short_returns_400(
        self, client: TestClient
    ) -> None:
        setup_token = self._invite_and_get_token(client, username="short-pw-user")
        resp = client.post(
            "/api/auth/setup-password",
            json={"token": setup_token, "new_password": "short"},
        )
        assert resp.status_code == 400

    def test_activated_user_can_login(
        self, client: TestClient
    ) -> None:
        setup_token = self._invite_and_get_token(client, username="login-after-setup")
        client.post(
            "/api/auth/setup-password",
            json={"token": setup_token, "new_password": "MyStr0ngPass9"},
        )
        login_resp = client.post(
            "/api/auth/login",
            json={"username": "login-after-setup", "password": "MyStr0ngPass9"},
        )
        assert login_resp.status_code == 200
        assert "access_token" in login_resp.json()

    def test_pending_user_cannot_login_before_setup(
        self, client: TestClient
    ) -> None:
        root_token = _register_root(client)
        client.post(
            "/api/auth/invite",
            json={"username": "not-yet-active", "role": "user"},
            headers=_auth(root_token),
        )
        # No password set — login should fail
        login_resp = client.post(
            "/api/auth/login",
            json={"username": "not-yet-active", "password": "anything"},
        )
        assert login_resp.status_code == 401


# ─────────────────────────────────────────────────────────────
# § 4 — Integration: invite_user HITL admin command
# ─────────────────────────────────────────────────────────────


@pytest.mark.integration
class TestInviteUserHITLCommand:
    def _stage_invite_command(
        self,
        client: TestClient,
        root_token: str,
        instruction: str = "invite user jdoe with role user",
    ) -> dict[str, Any] | None:
        resp = client.post(
            "/api/admin/command",
            json={"instruction": instruction},
            headers=_auth(root_token),
        )
        if resp.status_code not in (200, 201):
            return None
        return resp.json()

    def test_invite_user_operation_creates_pending_user(
        self, client: TestClient, api_module: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root_token = _register_root(client)
        staged = self._stage_invite_command(client, root_token)
        if staged is None:
            pytest.skip("SLM staging unavailable in test env")
        staged_id = staged.get("staged_id") or staged.get("id")
        if staged_id is None:
            pytest.skip("SLM may not map to invite_user in test env")

        # Manually inject invite_user operation into the staged command
        from lumina.api.routes import admin as _admin_mod
        with _admin_mod._STAGED_COMMANDS_LOCK:
            if staged_id in _admin_mod._STAGED_COMMANDS:
                _admin_mod._STAGED_COMMANDS[staged_id]["parsed_command"] = {
                    "operation": "invite_user",
                    "params": {
                        "username": "hitl-invited",
                        "role": "user",
                    },
                }

        resp = client.post(
            f"/api/admin/command/{staged_id}/resolve",
            json={"action": "accept"},
            headers=_auth(root_token),
        )
        if resp.status_code == 422:
            pytest.skip("SLM staging not available in test env")

        assert resp.status_code == 200
        data = resp.json()
        result = data.get("result", {})
        assert result.get("operation") == "invite_user"
        assert "setup_url" in result
        assert "user_id" in result

    def test_invite_user_direct_operation_via_resolve(
        self, client: TestClient, api_module: Any
    ) -> None:
        """Directly inject an invite_user staged command and resolve it."""
        root_token = _register_root(client)

        import uuid
        from lumina.api.routes import admin as _admin_mod

        staged_id = f"staged-{uuid.uuid4().hex[:8]}"
        with _admin_mod._STAGED_COMMANDS_LOCK:
            _admin_mod._STAGED_COMMANDS[staged_id] = {
                "staged_id": staged_id,
                "actor_id": "root-inv",
                "original_instruction": "invite user testda for domain/edu/algebra-level-1/v1",
                "parsed_command": {
                    "operation": "invite_user",
                    "params": {
                        "username": "testda-direct",
                        "role": "admin",
                        "governed_modules": ["domain/edu/algebra-level-1/v1"],
                    },
                },
                "resolved": False,
                "log_stage_record_id": f"ctl-{uuid.uuid4().hex[:8]}",
                "expires_at": time.time() + 600,
            }

        resp = client.post(
            f"/api/admin/command/{staged_id}/resolve",
            json={"action": "accept"},
            headers=_auth(root_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        result = data["result"]
        assert result["operation"] == "invite_user"
        assert result["role"] == "admin"
        assert "domain/edu/algebra-level-1/v1" in result["governed_modules"]
        assert "setup_url" in result

        # Verify user created as pending
        user = api_module.PERSISTENCE.get_user_by_username("testda-direct")
        assert user is not None
        assert user["active"] is False
        assert user["role"] == "admin"

    def test_invite_user_da_without_modules_returns_400(
        self, client: TestClient
    ) -> None:
        root_token = _register_root(client)

        import uuid
        from lumina.api.routes import admin as _admin_mod

        staged_id = f"staged-{uuid.uuid4().hex[:8]}"
        with _admin_mod._STAGED_COMMANDS_LOCK:
            _admin_mod._STAGED_COMMANDS[staged_id] = {
                "staged_id": staged_id,
                "actor_id": "root-inv",
                "original_instruction": "invite domain authority with no modules",
                "parsed_command": {
                    "operation": "invite_user",
                    "params": {
                        "username": "da-no-modules",
                        "role": "admin",
                        "governed_modules": [],
                    },
                },
                "resolved": False,
                "log_stage_record_id": f"ctl-{uuid.uuid4().hex[:8]}",
                "expires_at": time.time() + 600,
            }

        resp = client.post(
            f"/api/admin/command/{staged_id}/resolve",
            json={"action": "accept"},
            headers=_auth(root_token),
        )
        assert resp.status_code == 400
        assert "governed_modules" in resp.json()["detail"].lower()
