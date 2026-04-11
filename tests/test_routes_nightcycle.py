"""Tests for nightcycle route endpoints: trigger, status, report, proposals, resolve."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

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
    monkeypatch.setattr(auth, "JWT_SECRET", "test-secret-nightcycle")
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


def _mock_scheduler() -> MagicMock:
    sched = MagicMock()
    sched.trigger_async.return_value = "run-001"
    sched.get_status.return_value = {"active": False, "last_run_id": "run-001"}
    sched.get_report.return_value = {"run_id": "run-001", "tasks": [], "completed": True}
    sched.get_pending_proposals.return_value = [
        {"proposal_id": "prop-1", "type": "physics_edit", "domain_id": "education"}
    ]
    sched.resolve_proposal.return_value = True
    return sched


@pytest.mark.integration
class TestNightcycleTrigger:
    def test_root_can_trigger(self, client: TestClient) -> None:
        root_token = _register_root(client)
        sched = _mock_scheduler()
        with patch("lumina.api.routes.nightcycle._get_night_scheduler", return_value=sched):
            resp = client.post(
                "/api/nightcycle/trigger",
                json={},
                headers=_auth_header(root_token),
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["run_id"] == "run-001"
        assert body["status"] == "started"
        sched.trigger_async.assert_called_once()

    def test_trigger_with_tasks_and_domains(self, client: TestClient) -> None:
        root_token = _register_root(client)
        sched = _mock_scheduler()
        with patch("lumina.api.routes.nightcycle._get_night_scheduler", return_value=sched):
            resp = client.post(
                "/api/nightcycle/trigger",
                json={"tasks": ["cleanup"], "domain_ids": ["education"]},
                headers=_auth_header(root_token),
            )
        assert resp.status_code == 200
        call_kwargs = sched.trigger_async.call_args
        assert call_kwargs.kwargs.get("task_names") == ["cleanup"]
        assert call_kwargs.kwargs.get("domain_ids") == ["education"]

    def test_regular_user_forbidden(self, client: TestClient) -> None:
        _register_root(client)
        user = _register_user(client, "student")
        user_token = client.post(
            "/api/auth/login",
            json={"username": "student", "password": "test-pass-123"},
        ).json()["access_token"]
        resp = client.post(
            "/api/nightcycle/trigger",
            json={},
            headers=_auth_header(user_token),
        )
        assert resp.status_code == 403

    def test_unauthenticated_rejected(self, client: TestClient) -> None:
        resp = client.post("/api/nightcycle/trigger", json={})
        assert resp.status_code == 401


@pytest.mark.integration
class TestNightcycleStatus:
    def test_root_can_get_status(self, client: TestClient) -> None:
        root_token = _register_root(client)
        sched = _mock_scheduler()
        with patch("lumina.api.routes.nightcycle._get_night_scheduler", return_value=sched):
            resp = client.get(
                "/api/nightcycle/status",
                headers=_auth_header(root_token),
            )
        assert resp.status_code == 200
        assert "active" in resp.json()

    def test_regular_user_forbidden(self, client: TestClient) -> None:
        _register_root(client)
        user = _register_user(client, "viewer")
        user_token = client.post(
            "/api/auth/login",
            json={"username": "viewer", "password": "test-pass-123"},
        ).json()["access_token"]
        resp = client.get(
            "/api/nightcycle/status",
            headers=_auth_header(user_token),
        )
        assert resp.status_code == 403


@pytest.mark.integration
class TestNightcycleReport:
    def test_root_can_get_report(self, client: TestClient) -> None:
        root_token = _register_root(client)
        sched = _mock_scheduler()
        with patch("lumina.api.routes.nightcycle._get_night_scheduler", return_value=sched):
            resp = client.get(
                "/api/nightcycle/report/run-001",
                headers=_auth_header(root_token),
            )
        assert resp.status_code == 200
        assert resp.json()["run_id"] == "run-001"

    def test_report_not_found(self, client: TestClient) -> None:
        root_token = _register_root(client)
        sched = _mock_scheduler()
        sched.get_report.return_value = None
        with patch("lumina.api.routes.nightcycle._get_night_scheduler", return_value=sched):
            resp = client.get(
                "/api/nightcycle/report/nonexistent",
                headers=_auth_header(root_token),
            )
        assert resp.status_code == 404

    def test_regular_user_forbidden(self, client: TestClient) -> None:
        _register_root(client)
        user = _register_user(client, "viewer2")
        user_token = client.post(
            "/api/auth/login",
            json={"username": "viewer2", "password": "test-pass-123"},
        ).json()["access_token"]
        resp = client.get(
            "/api/nightcycle/report/run-001",
            headers=_auth_header(user_token),
        )
        assert resp.status_code == 403


@pytest.mark.integration
class TestNightcycleProposals:
    def test_root_can_list_proposals(self, client: TestClient) -> None:
        root_token = _register_root(client)
        sched = _mock_scheduler()
        with patch("lumina.api.routes.nightcycle._get_night_scheduler", return_value=sched):
            resp = client.get(
                "/api/nightcycle/proposals",
                headers=_auth_header(root_token),
            )
        assert resp.status_code == 200
        proposals = resp.json()
        assert isinstance(proposals, list)
        assert len(proposals) == 1
        assert proposals[0]["proposal_id"] == "prop-1"

    def test_proposals_with_domain_filter(self, client: TestClient) -> None:
        root_token = _register_root(client)
        sched = _mock_scheduler()
        with patch("lumina.api.routes.nightcycle._get_night_scheduler", return_value=sched):
            resp = client.get(
                "/api/nightcycle/proposals?domain_id=education",
                headers=_auth_header(root_token),
            )
        assert resp.status_code == 200
        sched.get_pending_proposals.assert_called_once_with(domain_id="education")

    def test_regular_user_forbidden(self, client: TestClient) -> None:
        _register_root(client)
        user = _register_user(client, "student2")
        user_token = client.post(
            "/api/auth/login",
            json={"username": "student2", "password": "test-pass-123"},
        ).json()["access_token"]
        resp = client.get(
            "/api/nightcycle/proposals",
            headers=_auth_header(user_token),
        )
        assert resp.status_code == 403


@pytest.mark.integration
class TestNightcycleResolveProposal:
    def test_root_can_approve_proposal(self, client: TestClient) -> None:
        root_token = _register_root(client)
        sched = _mock_scheduler()
        with patch("lumina.api.routes.nightcycle._get_night_scheduler", return_value=sched):
            resp = client.post(
                "/api/nightcycle/proposals/prop-1/resolve",
                json={"action": "approved"},
                headers=_auth_header(root_token),
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["proposal_id"] == "prop-1"
        assert body["status"] == "approved"

    def test_root_can_reject_proposal(self, client: TestClient) -> None:
        root_token = _register_root(client)
        sched = _mock_scheduler()
        with patch("lumina.api.routes.nightcycle._get_night_scheduler", return_value=sched):
            resp = client.post(
                "/api/nightcycle/proposals/prop-1/resolve",
                json={"action": "rejected"},
                headers=_auth_header(root_token),
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "rejected"

    def test_invalid_action_rejected(self, client: TestClient) -> None:
        root_token = _register_root(client)
        sched = _mock_scheduler()
        with patch("lumina.api.routes.nightcycle._get_night_scheduler", return_value=sched):
            resp = client.post(
                "/api/nightcycle/proposals/prop-1/resolve",
                json={"action": "maybe"},
                headers=_auth_header(root_token),
            )
        assert resp.status_code == 400

    def test_proposal_not_found(self, client: TestClient) -> None:
        root_token = _register_root(client)
        sched = _mock_scheduler()
        sched.resolve_proposal.return_value = False
        with patch("lumina.api.routes.nightcycle._get_night_scheduler", return_value=sched):
            resp = client.post(
                "/api/nightcycle/proposals/nonexistent/resolve",
                json={"action": "approved"},
                headers=_auth_header(root_token),
            )
        assert resp.status_code == 404

    def test_regular_user_forbidden(self, client: TestClient) -> None:
        _register_root(client)
        user = _register_user(client, "student3")
        user_token = client.post(
            "/api/auth/login",
            json={"username": "student3", "password": "test-pass-123"},
        ).json()["access_token"]
        resp = client.post(
            "/api/nightcycle/proposals/prop-1/resolve",
            json={"action": "approved"},
            headers=_auth_header(user_token),
        )
        assert resp.status_code == 403
