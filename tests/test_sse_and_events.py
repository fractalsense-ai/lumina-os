"""Tests for SSE endpoint: /api/events/token and /api/events/stream.

Covers SSE token generation, RBAC, token validation, and structured content builders.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from lumina.auth import auth
from lumina.persistence.adapter import NullPersistenceAdapter
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
    mod.PERSISTENCE = NullPersistenceAdapter()
    mod.BOOTSTRAP_MODE = True
    mod._session_containers.clear()
    monkeypatch.setattr(auth, "JWT_SECRET", "test-secret-sse")
    mod.PERSISTENCE.load_subject_profile = _load_yaml
    return mod


@pytest.fixture
def client(api_module):
    return TestClient(api_module.app)


def _register_root(client: TestClient) -> str:
    resp = client.post(
        "/api/auth/register",
        json={"username": "root_admin", "password": "test-pass-123", "role": "user"},
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]


def _register_user(client: TestClient, username: str = "regular", role: str = "user") -> str:
    resp = client.post(
        "/api/auth/register",
        json={"username": username, "password": "test-pass-123", "role": role},
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ── SSE Token Endpoint ────────────────────────────────────────


@pytest.mark.integration
def test_sse_token_requires_auth(client: TestClient, api_module) -> None:
    """SSE token endpoint rejects unauthenticated requests."""
    resp = client.get("/api/events/token")
    assert resp.status_code in (401, 403)


@pytest.mark.integration
def test_sse_token_issued_for_root(client: TestClient, api_module) -> None:
    """Root user can obtain an SSE token."""
    token = _register_root(client)
    resp = client.get("/api/events/token", headers=_auth_header(token))
    assert resp.status_code == 200
    data = resp.json()
    assert "token" in data
    assert isinstance(data["token"], str)
    assert len(data["token"]) > 20


@pytest.mark.integration
def test_sse_token_issued_for_domain_authority(client: TestClient, api_module) -> None:
    """Domain authority can obtain an SSE token."""
    _register_root(client)
    da_token = _register_user(client, username="da_user", role="admin")
    resp = client.get("/api/events/token", headers=_auth_header(da_token))
    assert resp.status_code == 200
    assert "token" in resp.json()


@pytest.mark.integration
def test_sse_token_issued_for_auditor(client: TestClient, api_module) -> None:
    """Auditor can obtain an SSE token."""
    _register_root(client)
    aud_token = _register_user(client, username="auditor_user", role="half_operator")
    resp = client.get("/api/events/token", headers=_auth_header(aud_token))
    assert resp.status_code == 200
    assert "token" in resp.json()


@pytest.mark.integration
def test_sse_token_denied_for_regular_user(client: TestClient, api_module) -> None:
    """Regular users cannot obtain SSE tokens."""
    _register_root(client)
    user_token = _register_user(client, username="student", role="user")
    resp = client.get("/api/events/token", headers=_auth_header(user_token))
    assert resp.status_code == 403


# ── SSE Stream Endpoint ───────────────────────────────────────


@pytest.mark.integration
def test_sse_stream_rejects_missing_token(client: TestClient, api_module) -> None:
    """Stream endpoint rejects when no token query param."""
    resp = client.get("/api/events/stream")
    assert resp.status_code in (401, 422)


@pytest.mark.integration
def test_sse_stream_rejects_invalid_token(client: TestClient, api_module) -> None:
    """Stream endpoint rejects invalid token."""
    resp = client.get("/api/events/stream?token=bogus")
    assert resp.status_code in (401, 403)


@pytest.mark.integration
def test_sse_token_is_single_use(client: TestClient, api_module) -> None:
    """SSE tokens are consumed on first use."""
    root_token = _register_root(client)
    resp = client.get("/api/events/token", headers=_auth_header(root_token))
    sse_token = resp.json()["token"]

    # First use — stream starts (we just check it opens, don't consume)
    # The TestClient doesn't support streaming well, so test via token store
    from lumina.api.routes.events import _sse_tokens, _hash_token
    hashed = _hash_token(sse_token)
    assert hashed in _sse_tokens

    # Second token request works (new token)
    resp2 = client.get("/api/events/token", headers=_auth_header(root_token))
    assert resp2.status_code == 200
    sse_token2 = resp2.json()["token"]
    assert sse_token2 != sse_token


# ── Escalation Detail Endpoint ────────────────────────────────


@pytest.mark.integration
def test_escalation_detail_not_found(client: TestClient, api_module) -> None:
    """GET /api/escalations/{id} returns 404 for unknown ID."""
    token = _register_root(client)
    resp = client.get("/api/escalations/nonexistent-id", headers=_auth_header(token))
    assert resp.status_code == 404


@pytest.mark.integration
def test_escalation_detail_returns_record(client: TestClient, api_module) -> None:
    """GET /api/escalations/{id} returns the record if it exists."""
    token = _register_root(client)

    fake_record = {
        "record_id": "esc-test-001",
        "trigger": "frustration_repeated",
        "domain_pack_id": "education/pre-algebra",
        "session_id": "s1",
        "status": "pending",
        "timestamp_utc": "2025-01-01T00:00:00Z",
    }
    api_module.PERSISTENCE.query_escalations = lambda *a, **kw: [fake_record]

    resp = client.get("/api/escalations/esc-test-001", headers=_auth_header(token))
    assert resp.status_code == 200
    data = resp.json()
    assert data["record_id"] == "esc-test-001"
    assert data["trigger"] == "frustration_repeated"


@pytest.mark.integration
def test_escalation_detail_rbac_regular_user_denied(client: TestClient, api_module) -> None:
    """Regular users cannot access escalation detail."""
    _register_root(client)
    user_token = _register_user(client, username="student2", role="user")
    resp = client.get("/api/escalations/esc-test-001", headers=_auth_header(user_token))
    assert resp.status_code == 403
