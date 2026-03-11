from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lumina.auth import auth
from lumina.persistence.adapter import NullPersistenceAdapter

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_api_module():
    module_path = _REPO_ROOT / "src" / "lumina" / "api" / "server.py"
    module_name = "lumina_api_server_test"

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
    monkeypatch.setattr(auth, "JWT_SECRET", "test-secret")
    return mod


@pytest.fixture
def client(api_module):
    return TestClient(api_module.app)


@pytest.mark.integration
def test_register_first_user_bootstrap_promotes_root(client: TestClient) -> None:
    resp = client.post(
        "/api/auth/register",
        json={"username": "alice", "password": "test-pass-123", "role": "user"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["role"] == "root"
    assert body["access_token"]


@pytest.mark.integration
def test_login_and_me_flow(client: TestClient) -> None:
    reg = client.post(
        "/api/auth/register",
        json={"username": "bob", "password": "test-pass-123", "role": "user"},
    )
    assert reg.status_code == 200

    login = client.post(
        "/api/auth/login",
        json={"username": "bob", "password": "test-pass-123"},
    )
    assert login.status_code == 200
    token = login.json()["access_token"]

    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    me_body = me.json()
    assert me_body["username"] == "bob"
    # First registered user in this isolated fixture is root.
    assert me_body["role"] == "root"


@pytest.mark.integration
def test_users_endpoint_role_gating(client: TestClient) -> None:
    root_reg = client.post(
        "/api/auth/register",
        json={"username": "rootuser", "password": "test-pass-123", "role": "user"},
    )
    assert root_reg.status_code == 200
    root_token = root_reg.json()["access_token"]

    user_reg = client.post(
        "/api/auth/register",
        json={"username": "regular", "password": "test-pass-123", "role": "user"},
    )
    assert user_reg.status_code == 200

    users_as_root = client.get("/api/auth/users", headers={"Authorization": f"Bearer {root_token}"})
    assert users_as_root.status_code == 200
    assert len(users_as_root.json()) >= 2

    user_login = client.post(
        "/api/auth/login",
        json={"username": "regular", "password": "test-pass-123"},
    )
    assert user_login.status_code == 200
    user_token = user_login.json()["access_token"]

    users_as_regular = client.get("/api/auth/users", headers={"Authorization": f"Bearer {user_token}"})
    assert users_as_regular.status_code == 403
