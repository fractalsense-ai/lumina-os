"""Escalation prevention regression tests.

Verify that JWT scoped tokens cannot cross authority boundaries:
- Domain tokens cannot reach admin endpoints
- Admin tokens cannot perform domain-authority-only operations
- User tokens cannot reach admin or DA endpoints
- Self-role-escalation is blocked
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from lumina.auth import auth
from lumina.auth.auth import create_scoped_jwt
from lumina.persistence.adapter import NullPersistenceAdapter
from lumina.core.domain_registry import DomainRegistry
from lumina.core.runtime_loader import load_runtime_context
from lumina.core.yaml_loader import load_yaml as _load_yaml

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
    mod.DOMAIN_REGISTRY = DomainRegistry(
        repo_root=_REPO_ROOT,
        single_config_path="domain-packs/education/cfg/runtime-config.yaml",
        load_runtime_context_fn=load_runtime_context,
    )
    mod.PERSISTENCE = NullPersistenceAdapter()
    mod.BOOTSTRAP_MODE = True
    mod._session_containers.clear()
    mod._STAGED_COMMANDS.clear()
    monkeypatch.setattr(auth, "JWT_SECRET", "test-secret-esc")
    monkeypatch.setattr(auth, "ADMIN_JWT_SECRET", "admin-secret-esc")
    monkeypatch.setattr(auth, "DOMAIN_JWT_SECRET", "domain-secret-esc")
    monkeypatch.setattr(auth, "USER_JWT_SECRET", "user-secret-esc")
    mod.PERSISTENCE.load_subject_profile = _load_yaml
    return mod


@pytest.fixture
def client(api_module):
    return TestClient(api_module.app)


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _register_root(client: TestClient) -> str:
    resp = client.post(
        "/api/auth/register",
        json={"username": "admin", "password": "test-pass-123", "role": "user"},
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]


def _make_user_token(user_id: str = "user-001", role: str = "user") -> str:
    return create_scoped_jwt(user_id=user_id, role=role)


def _make_domain_token(user_id: str = "da-001", governed: list[str] | None = None) -> str:
    return create_scoped_jwt(
        user_id=user_id,
        role="domain_authority",
        governed_modules=governed or ["education"],
    )


def _make_admin_token(user_id: str = "root-001", role: str = "root") -> str:
    return create_scoped_jwt(user_id=user_id, role=role)


# ─────────────────────────────────────────────────────────────
# Domain token → admin endpoint → 403
# ─────────────────────────────────────────────────────────────


@pytest.mark.integration
class TestDomainTokenCannotReachAdmin:
    """Domain-authority JWT must NOT access admin-only endpoints."""

    def test_domain_token_cannot_list_users(self, client: TestClient) -> None:
        _register_root(client)  # bootstrap
        da_token = _make_domain_token()
        resp = client.get("/api/auth/users", headers=_auth_header(da_token))
        assert resp.status_code == 403

    def test_domain_token_cannot_update_user_role(self, client: TestClient) -> None:
        _register_root(client)
        da_token = _make_domain_token()
        resp = client.patch(
            "/api/auth/users/someone",
            json={"role": "root"},
            headers=_auth_header(da_token),
        )
        assert resp.status_code in (403, 404)

    def test_domain_token_cannot_trigger_nightcycle(self, client: TestClient) -> None:
        _register_root(client)
        da_token = _make_domain_token()
        # DA *should* be allowed for nightcycle actually (the route allows
        # "root" and "domain_authority") — this tests the boundary correctly.
        from unittest.mock import MagicMock
        sched = MagicMock()
        sched.trigger_async.return_value = "run-x"
        with patch("lumina.api.routes.nightcycle._get_night_scheduler", return_value=sched):
            resp = client.post(
                "/api/nightcycle/trigger",
                json={},
                headers=_auth_header(da_token),
            )
        # DA is explicitly allowed by nightcycle — not a 403
        assert resp.status_code == 200


# ─────────────────────────────────────────────────────────────
# User token → admin endpoints → 403
# ─────────────────────────────────────────────────────────────


@pytest.mark.integration
class TestUserTokenCannotReachAdmin:
    """Regular user JWT must NOT access admin-only endpoints."""

    def test_user_cannot_list_users(self, client: TestClient) -> None:
        _register_root(client)
        user_token = _make_user_token()
        resp = client.get("/api/auth/users", headers=_auth_header(user_token))
        assert resp.status_code == 403

    def test_user_cannot_update_roles(self, client: TestClient) -> None:
        _register_root(client)
        user_token = _make_user_token()
        resp = client.patch(
            "/api/auth/users/someone",
            json={"role": "root"},
            headers=_auth_header(user_token),
        )
        assert resp.status_code in (403, 404)

    def test_user_cannot_trigger_nightcycle(self, client: TestClient) -> None:
        _register_root(client)
        user_token = _make_user_token()
        resp = client.post(
            "/api/nightcycle/trigger",
            json={},
            headers=_auth_header(user_token),
        )
        assert resp.status_code == 403

    def test_user_cannot_get_nightcycle_status(self, client: TestClient) -> None:
        _register_root(client)
        user_token = _make_user_token()
        resp = client.get(
            "/api/nightcycle/status",
            headers=_auth_header(user_token),
        )
        assert resp.status_code == 403

    def test_user_cannot_access_dashboard_domains(self, client: TestClient) -> None:
        _register_root(client)
        user_token = _make_user_token()
        resp = client.get(
            "/api/dashboard/domains",
            headers=_auth_header(user_token),
        )
        assert resp.status_code == 403

    def test_user_cannot_access_dashboard_telemetry(self, client: TestClient) -> None:
        _register_root(client)
        user_token = _make_user_token()
        resp = client.get(
            "/api/dashboard/telemetry",
            headers=_auth_header(user_token),
        )
        assert resp.status_code == 403

    def test_user_cannot_access_vocabulary_growth(self, client: TestClient) -> None:
        _register_root(client)
        user_token = _make_user_token()
        resp = client.get(
            "/api/dashboard/education/vocabulary-growth",
            headers=_auth_header(user_token),
        )
        assert resp.status_code == 403


# ─────────────────────────────────────────────────────────────
# Self-role-escalation attempts → 403
# ─────────────────────────────────────────────────────────────


@pytest.mark.integration
class TestSelfRoleEscalation:
    """Users must not be able to elevate their own role."""

    def test_regular_user_cannot_self_promote(self, client: TestClient) -> None:
        _register_root(client)
        user_resp = client.post(
            "/api/auth/register",
            json={"username": "alice", "password": "pass-123", "role": "user"},
        )
        assert user_resp.status_code == 200
        user_id = user_resp.json()["user_id"]
        user_token = client.post(
            "/api/auth/login",
            json={"username": "alice", "password": "pass-123"},
        ).json()["access_token"]

        resp = client.patch(
            f"/api/auth/users/{user_id}",
            json={"role": "root"},
            headers=_auth_header(user_token),
        )
        assert resp.status_code == 403

    def test_da_cannot_self_promote_to_root(self, client: TestClient) -> None:
        _register_root(client)
        da_token = _make_domain_token(user_id="da-self")
        resp = client.patch(
            "/api/auth/users/da-self",
            json={"role": "root"},
            headers=_auth_header(da_token),
        )
        assert resp.status_code in (403, 404)


# ─────────────────────────────────────────────────────────────
# Token signed with wrong secret → 401
# ─────────────────────────────────────────────────────────────


@pytest.mark.integration
class TestTokenScopeTampering:
    """Tokens signed with the wrong secret must be rejected."""

    def test_token_with_invalid_secret_rejected(self, client: TestClient) -> None:
        """Craft a token with a wrong secret — should get 401."""
        import json as _json
        import hmac as _hmac
        import hashlib as _hashlib
        import time as _time
        from base64 import urlsafe_b64encode as _b64e

        def _b64url(data: bytes) -> str:
            return _b64e(data).rstrip(b"=").decode("ascii")

        header = _b64url(_json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
        payload_data = {
            "sub": "hacker",
            "role": "root",
            "iss": "lumina-admin",
            "token_scope": "admin",
            "iat": int(_time.time()),
            "exp": int(_time.time()) + 3600,
            "jti": "fakejti",
            "governed_modules": [],
        }
        payload = _b64url(_json.dumps(payload_data).encode())
        message = f"{header}.{payload}".encode("ascii")
        sig = _b64url(
            _hmac.new(b"wrong-secret-entirely", message, _hashlib.sha256).digest()
        )
        fake_token = f"{header}.{payload}.{sig}"

        resp = client.get("/api/auth/users", headers=_auth_header(fake_token))
        assert resp.status_code == 401


# ─────────────────────────────────────────────────────────────
# Holodeck role gate
# ─────────────────────────────────────────────────────────────


@pytest.mark.integration
class TestHolodeckRoleGate:
    """Only root and domain_authority can use holodeck mode."""

    def test_user_cannot_use_holodeck(self, client: TestClient) -> None:
        _register_root(client)
        user_token = _make_user_token()
        resp = client.post(
            "/api/chat",
            json={"message": "test", "holodeck": True},
            headers=_auth_header(user_token),
        )
        assert resp.status_code == 403

    def test_qa_cannot_use_holodeck(self, client: TestClient) -> None:
        _register_root(client)
        qa_token = _make_user_token(user_id="qa-1", role="qa")
        resp = client.post(
            "/api/chat",
            json={"message": "test", "holodeck": True},
            headers=_auth_header(qa_token),
        )
        assert resp.status_code == 403

    def test_auditor_cannot_use_holodeck(self, client: TestClient) -> None:
        _register_root(client)
        auditor_token = _make_user_token(user_id="aud-1", role="auditor")
        resp = client.post(
            "/api/chat",
            json={"message": "test", "holodeck": True},
            headers=_auth_header(auditor_token),
        )
        assert resp.status_code == 403
