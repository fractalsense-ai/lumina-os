from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import auth
from persistence_adapter import NullPersistenceAdapter


def _load_api_module():
    repo_root = Path(__file__).resolve().parents[1]
    module_path = repo_root / "reference-implementations" / "lumina-api-server.py"
    module_name = "lumina_api_server_chat_tool_ctl_test"

    spec = importlib.util.spec_from_file_location(module_name, str(module_path))
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load lumina-api-server module")

    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def api_module(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LUMINA_RUNTIME_CONFIG_PATH", "domain-packs/education/runtime-config.yaml")
    monkeypatch.delenv("LUMINA_DOMAIN_REGISTRY_PATH", raising=False)

    mod = _load_api_module()
    mod.PERSISTENCE = NullPersistenceAdapter()
    mod.BOOTSTRAP_MODE = False

    repo_root = Path(__file__).resolve().parents[1]
    yaml_loader_path = repo_root / "reference-implementations" / "yaml-loader.py"
    yaml_spec = importlib.util.spec_from_file_location("test_yaml_loader", str(yaml_loader_path))
    if yaml_spec is None or yaml_spec.loader is None:
        raise RuntimeError("Could not load yaml-loader.py")
    yaml_mod = importlib.util.module_from_spec(yaml_spec)
    yaml_spec.loader.exec_module(yaml_mod)
    mod.PERSISTENCE.load_subject_profile = lambda path: yaml_mod.load_yaml(path)

    monkeypatch.setattr(auth, "JWT_SECRET", "test-secret")
    return mod


@pytest.fixture
def client(api_module):
    return TestClient(api_module.app)


def _register_and_login(client: TestClient, username: str, role: str) -> str:
    reg = client.post(
        "/api/auth/register",
        json={"username": username, "password": "test-pass-123", "role": role},
    )
    assert reg.status_code == 200

    login = client.post(
        "/api/auth/login",
        json={"username": username, "password": "test-pass-123"},
    )
    assert login.status_code == 200
    return login.json()["access_token"]


@pytest.mark.integration
def test_chat_rejects_empty_message(client: TestClient) -> None:
    resp = client.post("/api/chat", json={"message": "   "})
    assert resp.status_code == 400


@pytest.mark.integration
def test_chat_deterministic_success(client: TestClient) -> None:
    resp = client.post(
        "/api/chat",
        json={
            "message": "I checked by substitution.",
            "deterministic_response": True,
            "turn_data_override": {
                "correctness": "correct",
                "frustration_marker_count": 0,
                "step_count": 2,
                "hint_used": False,
                "repeated_error": False,
                "off_task_ratio": 0.0,
                "response_latency_sec": 5,
            },
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["response"]
    assert body["action"]


@pytest.mark.integration
def test_chat_permission_denied_with_token(client: TestClient, api_module) -> None:
    token = _register_and_login(client, "student_user", "user")

    # Deny execute access for non-owner/non-group users.
    api_module.PERSISTENCE.load_domain_physics = lambda _path: {
        "permissions": {
            "mode": "700",
            "owner": "domain_owner_only",
            "group": "domain_authority",
        }
    }

    resp = client.post(
        "/api/chat",
        headers={"Authorization": f"Bearer {token}"},
        json={"message": "hello", "deterministic_response": True},
    )
    assert resp.status_code == 403
    assert "Module access denied" in resp.text


@pytest.mark.integration
def test_tool_invalid_tool_id_returns_400(client: TestClient) -> None:
    resp = client.post("/api/tool/not-a-real-tool", json={"payload": {}})
    assert resp.status_code == 400


@pytest.mark.integration
def test_ctl_validate_role_gating(client: TestClient) -> None:
    user_token = _register_and_login(client, "regular_user", "user")
    root_token = _register_and_login(client, "root_user", "root")

    denied = client.get("/api/ctl/validate", headers={"Authorization": f"Bearer {user_token}"})
    assert denied.status_code == 403

    allowed = client.get("/api/ctl/validate", headers={"Authorization": f"Bearer {root_token}"})
    assert allowed.status_code == 200
    assert allowed.json()["result"]["intact"] is True
