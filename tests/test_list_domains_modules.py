"""Tests for list_domains and list_modules HITL-exempt admin operations.

These operations bypass HITL staging and execute immediately, returning
results inline with hitl_exempt=True.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from lumina.auth import auth
from lumina.persistence.adapter import NullPersistenceAdapter
from lumina.core.domain_registry import DomainRegistry

_REPO_ROOT = Path(__file__).resolve().parents[1]


# ── Helpers ───────────────────────────────────────────────────────────────────

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
    monkeypatch.setattr(auth, "JWT_SECRET", "test-secret-discovery")

    # Wire up the real domain registry so list_domains / list_modules work
    from lumina.api import config as _cfg
    registry = DomainRegistry(
        repo_root=_REPO_ROOT,
        registry_path=str(_REPO_ROOT / "cfg" / "domain-registry.yaml"),
    )
    monkeypatch.setattr(_cfg, "DOMAIN_REGISTRY", registry)

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


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ── list_domains ──────────────────────────────────────────────────────────────


@pytest.mark.integration
def test_list_domains_hitl_exempt(client: TestClient, api_module) -> None:
    """list_domains should execute immediately without HITL staging."""
    token = _register_root(client)
    parsed = {"operation": "list_domains", "target": "", "params": {}}
    with (
        patch.object(api_module, "slm_available", return_value=True),
        patch.object(api_module, "slm_parse_admin_command", return_value=parsed),
    ):
        resp = client.post(
            "/api/admin/command",
            json={"instruction": "list domains"},
            headers=_auth_header(token),
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["staged_id"] is None
    assert body["hitl_exempt"] is True
    assert "domains" in body["result"]
    assert isinstance(body["result"]["domains"], list)
    assert len(body["result"]["domains"]) > 0


# ── list_modules ──────────────────────────────────────────────────────────────


@pytest.mark.integration
def test_list_modules_hitl_exempt(client: TestClient, api_module) -> None:
    """list_modules should execute immediately for a valid domain."""
    token = _register_root(client)
    parsed = {
        "operation": "list_modules",
        "target": "education",
        "params": {"domain_id": "education"},
    }
    with (
        patch.object(api_module, "slm_available", return_value=True),
        patch.object(api_module, "slm_parse_admin_command", return_value=parsed),
    ):
        resp = client.post(
            "/api/admin/command",
            json={"instruction": "list modules for education"},
            headers=_auth_header(token),
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["staged_id"] is None
    assert body["hitl_exempt"] is True
    assert body["result"]["domain_id"] == "education"
    assert isinstance(body["result"]["modules"], list)


@pytest.mark.integration
def test_list_modules_unknown_domain_400(client: TestClient, api_module) -> None:
    """list_modules for a nonexistent domain should return 400."""
    token = _register_root(client)
    parsed = {
        "operation": "list_modules",
        "target": "nonexistent",
        "params": {"domain_id": "nonexistent"},
    }
    with (
        patch.object(api_module, "slm_available", return_value=True),
        patch.object(api_module, "slm_parse_admin_command", return_value=parsed),
    ):
        resp = client.post(
            "/api/admin/command",
            json={"instruction": "list modules for nonexistent"},
            headers=_auth_header(token),
        )
    assert resp.status_code == 400
