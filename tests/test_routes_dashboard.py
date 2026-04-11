"""Tests for dashboard route endpoints: domain stats and telemetry."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lumina.auth import auth
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
    monkeypatch.setattr(auth, "JWT_SECRET", "test-secret-dashboard")
    mod.PERSISTENCE.load_subject_profile = _load_yaml
    return mod


@pytest.fixture
def client(api_module):
    return TestClient(api_module.app)


def _register_root(client: TestClient) -> str:
    resp = client.post(
        "/api/auth/register",
        json={"username": "admin", "password": "test-pass-123", "role": "user"},
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]


def _register_user(client: TestClient, username: str = "regular", role: str = "user") -> dict:
    resp = client.post(
        "/api/auth/register",
        json={"username": username, "password": "test-pass-123", "role": role},
    )
    assert resp.status_code == 200
    return resp.json()


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ─────────────────────────────────────────────────────────────
# GET /api/dashboard/domains
# ─────────────────────────────────────────────────────────────


@pytest.mark.integration
class TestDashboardDomains:
    def test_root_can_list_domains(self, client: TestClient) -> None:
        root_token = _register_root(client)
        resp = client.get(
            "/api/dashboard/domains",
            headers=_auth_header(root_token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)

    def test_regular_user_forbidden(self, client: TestClient) -> None:
        _register_root(client)
        _register_user(client, "student")
        user_token = client.post(
            "/api/auth/login",
            json={"username": "student", "password": "test-pass-123"},
        ).json()["access_token"]
        resp = client.get(
            "/api/dashboard/domains",
            headers=_auth_header(user_token),
        )
        assert resp.status_code == 403

    def test_unauthenticated_rejected(self, client: TestClient) -> None:
        resp = client.get("/api/dashboard/domains")
        assert resp.status_code == 401

    def test_response_contains_expected_fields(self, client: TestClient) -> None:
        root_token = _register_root(client)
        resp = client.get(
            "/api/dashboard/domains",
            headers=_auth_header(root_token),
        )
        assert resp.status_code == 200
        body = resp.json()
        if body:
            entry = body[0]
            assert "domain_id" in entry
            assert "name" in entry
            assert "pending_escalations" in entry
            assert "pending_ingestions" in entry
            assert "review_ingestions" in entry


# ─────────────────────────────────────────────────────────────
# GET /api/dashboard/telemetry
# ─────────────────────────────────────────────────────────────


@pytest.mark.integration
class TestDashboardTelemetry:
    def test_root_can_get_telemetry(self, client: TestClient) -> None:
        root_token = _register_root(client)
        resp = client.get(
            "/api/dashboard/telemetry",
            headers=_auth_header(root_token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "total_log_records" in body
        assert "record_type_counts" in body
        assert "escalation_summary" in body

    def test_telemetry_with_domain_filter(self, client: TestClient) -> None:
        root_token = _register_root(client)
        resp = client.get(
            "/api/dashboard/telemetry?domain_id=education",
            headers=_auth_header(root_token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["domain_filter"] == "education"

    def test_regular_user_forbidden(self, client: TestClient) -> None:
        _register_root(client)
        _register_user(client, "viewer")
        user_token = client.post(
            "/api/auth/login",
            json={"username": "viewer", "password": "test-pass-123"},
        ).json()["access_token"]
        resp = client.get(
            "/api/dashboard/telemetry",
            headers=_auth_header(user_token),
        )
        assert resp.status_code == 403

    def test_unauthenticated_rejected(self, client: TestClient) -> None:
        resp = client.get("/api/dashboard/telemetry")
        assert resp.status_code == 401

    def test_escalation_summary_structure(self, client: TestClient) -> None:
        root_token = _register_root(client)
        resp = client.get(
            "/api/dashboard/telemetry",
            headers=_auth_header(root_token),
        )
        assert resp.status_code == 200
        esc = resp.json()["escalation_summary"]
        assert "total" in esc
        assert "pending" in esc
        assert "resolved" in esc
