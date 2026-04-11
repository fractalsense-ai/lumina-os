"""Tests for panel route endpoints: GET and PATCH generic panels."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

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
    monkeypatch.setattr(auth, "JWT_SECRET", "test-secret-panels")
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


def _fake_layout_with_panels(panels: list[dict[str, Any]]):
    """Return a mock for _resolve_caller_layout returning the given panels."""
    layout = {"sidebar_panels": panels, "capabilities": []}

    def _resolver(user_data):
        return layout, panels

    return _resolver


# ─────────────────────────────────────────────────────────────
# GET /api/panels/{panel_id}
# ─────────────────────────────────────────────────────────────


@pytest.mark.integration
class TestGetPanelData:
    def test_self_profile_panel(self, client: TestClient) -> None:
        root_token = _register_root(client)
        panels = [{"id": "my_profile", "data_source": "self_profile"}]
        with patch(
            "lumina.api.routes.panels._resolve_caller_layout",
            _fake_layout_with_panels(panels),
        ):
            resp = client.get(
                "/api/panels/my_profile",
                headers=_auth_header(root_token),
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["panel"] == "my_profile"
        assert "user_id" in body

    def test_self_modules_panel(self, client: TestClient) -> None:
        root_token = _register_root(client)
        panels = [{"id": "modules", "data_source": "self_modules"}]
        with patch(
            "lumina.api.routes.panels._resolve_caller_layout",
            _fake_layout_with_panels(panels),
        ):
            resp = client.get(
                "/api/panels/modules",
                headers=_auth_header(root_token),
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["panel"] == "modules"
        assert "modules" in body

    def test_self_preferences_panel(self, client: TestClient) -> None:
        root_token = _register_root(client)
        panels = [{"id": "prefs", "data_source": "self_preferences"}]
        with patch(
            "lumina.api.routes.panels._resolve_caller_layout",
            _fake_layout_with_panels(panels),
        ):
            resp = client.get(
                "/api/panels/prefs",
                headers=_auth_header(root_token),
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["panel"] == "prefs"
        assert "preferences" in body

    def test_empty_queue_panel(self, client: TestClient) -> None:
        root_token = _register_root(client)
        panels = [{"id": "queue", "data_source": "empty_queue"}]
        with patch(
            "lumina.api.routes.panels._resolve_caller_layout",
            _fake_layout_with_panels(panels),
        ):
            resp = client.get(
                "/api/panels/queue",
                headers=_auth_header(root_token),
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["panel"] == "queue"
        assert body["items"] == []

    def test_panel_not_in_layout_returns_404(self, client: TestClient) -> None:
        root_token = _register_root(client)
        panels = [{"id": "other", "data_source": "self_profile"}]
        with patch(
            "lumina.api.routes.panels._resolve_caller_layout",
            _fake_layout_with_panels(panels),
        ):
            resp = client.get(
                "/api/panels/nonexistent",
                headers=_auth_header(root_token),
            )
        assert resp.status_code == 404

    def test_unknown_data_source_returns_404(self, client: TestClient) -> None:
        root_token = _register_root(client)
        panels = [{"id": "bad", "data_source": "totally_unknown"}]
        with patch(
            "lumina.api.routes.panels._resolve_caller_layout",
            _fake_layout_with_panels(panels),
        ):
            resp = client.get(
                "/api/panels/bad",
                headers=_auth_header(root_token),
            )
        assert resp.status_code == 404

    def test_unauthenticated_rejected(self, client: TestClient) -> None:
        resp = client.get("/api/panels/any")
        assert resp.status_code == 401

    def test_governed_modules_panel(self, client: TestClient) -> None:
        root_token = _register_root(client)
        panels = [{"id": "gov", "data_source": "governed_modules"}]
        with patch(
            "lumina.api.routes.panels._resolve_caller_layout",
            _fake_layout_with_panels(panels),
        ):
            resp = client.get(
                "/api/panels/gov",
                headers=_auth_header(root_token),
            )
        assert resp.status_code == 200
        assert "governed_modules" in resp.json()

    def test_notification_settings_panel(self, client: TestClient) -> None:
        root_token = _register_root(client)
        panels = [
            {"id": "notifs", "data_source": "notification_settings", "source_path": "notification_preferences"},
        ]
        with patch(
            "lumina.api.routes.panels._resolve_caller_layout",
            _fake_layout_with_panels(panels),
        ):
            resp = client.get(
                "/api/panels/notifs",
                headers=_auth_header(root_token),
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["panel"] == "notifs"
        assert "preferences" in body


# ─────────────────────────────────────────────────────────────
# PATCH /api/panels/{panel_id}
# ─────────────────────────────────────────────────────────────


@pytest.mark.integration
class TestUpdatePanelData:
    def test_update_self_preferences(self, client: TestClient) -> None:
        root_token = _register_root(client)
        panels = [{"id": "prefs", "data_source": "self_preferences"}]
        with patch(
            "lumina.api.routes.panels._resolve_caller_layout",
            _fake_layout_with_panels(panels),
        ):
            resp = client.patch(
                "/api/panels/prefs",
                json={"updates": {"theme": "dark"}},
                headers=_auth_header(root_token),
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "updated"
        assert "theme" in body["updated_fields"]

    def test_patch_non_preference_panel_rejected(self, client: TestClient) -> None:
        root_token = _register_root(client)
        panels = [{"id": "profile", "data_source": "self_profile"}]
        with patch(
            "lumina.api.routes.panels._resolve_caller_layout",
            _fake_layout_with_panels(panels),
        ):
            resp = client.patch(
                "/api/panels/profile",
                json={"updates": {"name": "test"}},
                headers=_auth_header(root_token),
            )
        assert resp.status_code == 405

    def test_patch_panel_not_in_layout(self, client: TestClient) -> None:
        root_token = _register_root(client)
        panels = [{"id": "other", "data_source": "self_preferences"}]
        with patch(
            "lumina.api.routes.panels._resolve_caller_layout",
            _fake_layout_with_panels(panels),
        ):
            resp = client.patch(
                "/api/panels/missing",
                json={"updates": {"key": "val"}},
                headers=_auth_header(root_token),
            )
        assert resp.status_code == 404

    def test_patch_empty_body_rejected(self, client: TestClient) -> None:
        root_token = _register_root(client)
        panels = [{"id": "prefs", "data_source": "self_preferences"}]
        with patch(
            "lumina.api.routes.panels._resolve_caller_layout",
            _fake_layout_with_panels(panels),
        ):
            resp = client.patch(
                "/api/panels/prefs",
                json={},
                headers=_auth_header(root_token),
            )
        assert resp.status_code == 422

    def test_unauthenticated_rejected(self, client: TestClient) -> None:
        resp = client.patch("/api/panels/any", json={"updates": {"x": 1}})
        assert resp.status_code == 401
