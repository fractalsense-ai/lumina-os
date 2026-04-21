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
    mod.BOOTSTRAP_MODE = False
    mod.PERSISTENCE.load_subject_profile = _load_yaml

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

    # Route login to the correct track endpoint
    if role in ("root", "super_admin"):
        login_url = "/api/admin/auth/login"
    elif role == "admin":
        login_url = "/api/domain/auth/login"
    else:
        login_url = "/api/auth/login"

    login = client.post(
        login_url,
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
            "group": "admin",
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
def test_system_log_validate_role_gating(client: TestClient) -> None:
    user_token = _register_and_login(client, "regular_user", "user")
    root_token = _register_and_login(client, "root_user", "root")

    denied = client.get("/api/system-log/validate", headers={"Authorization": f"Bearer {user_token}"})
    assert denied.status_code == 403

    allowed = client.get("/api/system-log/validate", headers={"Authorization": f"Bearer {root_token}"})
    assert allowed.status_code == 200
    assert allowed.json()["result"]["intact"] is True


@pytest.mark.integration
def test_chat_glossary_lookup_returns_definition(client: TestClient, api_module) -> None:
    # Authenticated student whose profile routes to pre-algebra (has glossary).
    token = _register_and_login(client, "glossary_student", "user")

    # Patch load_subject_profile so the session picks up pre-algebra routing.
    _original_load = api_module.PERSISTENCE.load_subject_profile

    def _load_with_domain(path: str) -> dict:
        data = _original_load(path)
        data["domain_id"] = "domain/edu/pre-algebra/v1"
        return data

    api_module.PERSISTENCE.load_subject_profile = _load_with_domain
    # Bypass magic-circle consent gate for this test.
    api_module.PERSISTENCE.get_user_consent = lambda _uid: {"accepted": True}
    try:
        resp = client.post(
            "/api/chat",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "message": "what is a coefficient?",
                "deterministic_response": True,
            },
        )
    finally:
        api_module.PERSISTENCE.load_subject_profile = _original_load

    assert resp.status_code == 200
    body = resp.json()
    assert body["prompt_type"] == "definition_lookup"
    assert body["action"] == "definition_lookup"
    assert "coefficient" in body["response"].lower()
    assert not body["escalated"]


@pytest.mark.integration
def test_chat_glossary_no_match_falls_through(client: TestClient) -> None:
    resp = client.post(
        "/api/chat",
        json={
            "message": "what is a flurblesnork?",
            "deterministic_response": True,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    # Should NOT be definition_lookup — unknown term falls through to normal flow
    assert body["prompt_type"] != "definition_lookup"
