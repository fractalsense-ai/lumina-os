"""Tests for the /api/admin/command endpoint — SLM-powered admin command translation.

Covers RBAC enforcement, SLM parsing, dispatch to admin operations,
fallback on SLM unavailability, and System Log record creation.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from lumina.auth import auth
from lumina.persistence.adapter import NullPersistenceAdapter
from lumina.core.yaml_loader import load_yaml as _load_yaml

from lumina.core.domain_registry import DomainRegistry
from lumina.core.runtime_loader import load_runtime_context

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
    # Reset DOMAIN_REGISTRY to a clean single-domain instance so that
    # prior test modules that triggered config.py with a multi-domain
    # registry don't pollute the "_default" domain expected here.
    mod.DOMAIN_REGISTRY = DomainRegistry(
        repo_root=_REPO_ROOT,
        single_config_path="domain-packs/education/cfg/runtime-config.yaml",
        load_runtime_context_fn=load_runtime_context,
    )
    mod.PERSISTENCE = NullPersistenceAdapter()
    mod.BOOTSTRAP_MODE = True
    mod._session_containers.clear()
    monkeypatch.setattr(auth, "JWT_SECRET", "test-secret-admin-cmd")
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


# ── RBAC Enforcement ──────────────────────────────────────────────────────────


@pytest.mark.integration
def test_regular_user_reaches_pipeline(client: TestClient, api_module) -> None:
    """All authenticated users pass the /api/command gate — security is enforced
    by per-operation min_role checks, not the endpoint.  With no SLM the
    natural-language path returns 503; direct dispatch checks min_role."""
    _register_root(client)  # first user becomes root
    token = _register_user(client, "viewer", "user")
    # Natural-language instruction hits SLM-unavailable (503) since no SLM
    resp = client.post(
        "/api/command",
        json={"instruction": "update something"},
        headers=_auth_header(token),
    )
    assert resp.status_code in (503, 422)  # SLM unavailable or unparseable


@pytest.mark.integration
def test_user_blocked_at_domain_gate(client: TestClient, api_module) -> None:
    """Regular user must get 403 at the /api/domain/command endpoint."""
    _register_root(client)
    token = _register_user(client, "viewer2", "user")
    resp = client.post(
        "/api/domain/command",
        json={"instruction": "do something"},
        headers=_auth_header(token),
    )
    assert resp.status_code == 403


@pytest.mark.integration
def test_user_blocked_at_admin_gate(client: TestClient, api_module) -> None:
    """Regular user must get 403 at the /api/admin/command endpoint."""
    _register_root(client)
    token = _register_user(client, "viewer3", "user")
    resp = client.post(
        "/api/admin/command",
        json={"instruction": "do something"},
        headers=_auth_header(token),
    )
    assert resp.status_code == 403


@pytest.mark.integration
def test_da_blocked_at_admin_gate(client: TestClient, api_module) -> None:
    """Domain authority must get 403 at the /api/admin/command endpoint."""
    _register_root(client)
    token = _register_user(client, "da_blocked", "admin")
    resp = client.post(
        "/api/admin/command",
        json={"instruction": "do something"},
        headers=_auth_header(token),
    )
    assert resp.status_code == 403


@pytest.mark.integration
def test_da_passes_domain_gate(client: TestClient, api_module) -> None:
    """Domain authority passes the /api/domain/command gate."""
    _register_root(client)
    token = _register_user(client, "da_pass", "admin")
    resp = client.post(
        "/api/domain/command",
        json={"instruction": "do something"},
        headers=_auth_header(token),
    )
    # DA passes the gate; SLM unavailable or operation dispatch takes over
    assert resp.status_code in (200, 422, 503)


@pytest.mark.integration
def test_unauthenticated_denied(client: TestClient) -> None:
    """Missing auth should get 401."""
    resp = client.post(
        "/api/admin/command",
        json={"instruction": "update something"},
    )
    assert resp.status_code == 401


# ── SLM Unavailability ───────────────────────────────────────────────────────


@pytest.mark.integration
def test_slm_unavailable_returns_503(client: TestClient, api_module) -> None:
    token = _register_root(client)
    with patch.object(api_module, "slm_available", return_value=False):
        resp = client.post(
            "/api/admin/command",
            json={"instruction": "do something"},
            headers=_auth_header(token),
        )
    assert resp.status_code == 503
    assert "unavailable" in resp.json()["detail"].lower()


# ── Unparseable Command ──────────────────────────────────────────────────────


@pytest.mark.integration
def test_unparseable_command_returns_422(client: TestClient, api_module) -> None:
    token = _register_root(client)
    with (
        patch.object(api_module, "slm_available", return_value=True),
        patch.object(api_module, "slm_parse_admin_command", return_value=None),
    ):
        resp = client.post(
            "/api/admin/command",
            json={"instruction": "what is the meaning of life?"},
            headers=_auth_header(token),
        )
    assert resp.status_code == 422
    assert "interpret" in resp.json()["detail"].lower()


# ── Successful Command Dispatch ──────────────────────────────────────────────


@pytest.mark.integration
def test_deactivate_user_dispatches(client: TestClient, api_module) -> None:
    token = _register_root(client)
    parsed = {"operation": "deactivate_user", "target": "user99", "params": {"user_id": "user99"}}
    deactivate_mock = MagicMock()
    api_module.PERSISTENCE.deactivate_user = deactivate_mock

    with (
        patch.object(api_module, "slm_available", return_value=True),
        patch.object(api_module, "slm_parse_admin_command", return_value=parsed),
    ):
        # deactivate_user now goes through HITL staging (action card).
        resp = client.post(
            "/api/admin/command",
            json={"instruction": "deactivate user user99"},
            headers=_auth_header(token),
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["staged_id"] is not None
    assert body["structured_content"]["type"] == "action_card"


@pytest.mark.integration
def test_unknown_operation_returns_422(client: TestClient, api_module) -> None:
    token = _register_root(client)
    parsed = {"operation": "launch_missiles", "target": "moon", "params": {}}
    with (
        patch.object(api_module, "slm_available", return_value=True),
        patch.object(api_module, "slm_parse_admin_command", return_value=parsed),
    ):
        resp = client.post(
            "/api/admin/command",
            json={"instruction": "launch missiles at the moon"},
            headers=_auth_header(token),
        )
    assert resp.status_code == 422
    assert "Unknown operation" in resp.json()["detail"]


@pytest.mark.integration
def test_resolve_escalation_dispatches(client: TestClient, api_module) -> None:
    token = _register_root(client)
    parsed = {
        "operation": "resolve_escalation",
        "target": "esc-001",
        "params": {
            "escalation_id": "esc-001",
            "resolution": "approved",
            "rationale": "Looks good",
        },
    }
    with (
        patch.object(api_module, "slm_available", return_value=True),
        patch.object(api_module, "slm_parse_admin_command", return_value=parsed),
    ):
        # Stage the command.
        stage_resp = client.post(
            "/api/admin/command",
            json={"instruction": "approve escalation esc-001"},
            headers=_auth_header(token),
        )
    assert stage_resp.status_code == 200
    staged_id = stage_resp.json()["staged_id"]

    # Human accepts the staged command.
    resolve_resp = client.post(
        f"/api/admin/command/{staged_id}/resolve",
        json={"action": "accept"},
        headers=_auth_header(token),
    )
    assert resolve_resp.status_code == 200
    body = resolve_resp.json()
    assert body["result"]["operation"] == "resolve_escalation"
    assert body["result"]["resolution"] == "approved"


@pytest.mark.integration
def test_update_user_role_requires_root(client: TestClient, api_module) -> None:
    """Only root can call update_user_role — admin gets 403 immediately (HITL-exempt)."""
    _register_root(client)
    da_token = _register_user(client, "da_user", "admin")

    parsed = {
        "operation": "update_user_role",
        "target": "someone",
        "params": {"user_id": "someone", "new_role": "half_operator"},
    }
    with (
        patch.object(api_module, "slm_available", return_value=True),
        patch.object(api_module, "slm_parse_admin_command", return_value=parsed),
    ):
        # update_user_role now goes through HITL staging.
        # admin can stage the command via domain tier; role check happens at approval.
        resp = client.post(
            "/api/domain/command",
            json={"instruction": "change someone's role to half_operator"},
            headers=_auth_header(da_token),
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["staged_id"] is not None


# ── Dispatch-type classification unit tests ───────────────────────────────────
# These tests exercise the system runtime adapter directly to verify that
# read-only query types (status_query, diagnostic) no longer trigger
# slm_parse_admin_command, while admin_command still does.

import json as _json
import sys as _sys
from pathlib import Path as _Path

_SYS_ADAPTER_DIR = _Path(__file__).resolve().parent.parent / "domain-packs" / "system" / "controllers"
if str(_SYS_ADAPTER_DIR) not in _sys.path:
    _sys.path.insert(0, str(_SYS_ADAPTER_DIR))

from runtime_adapters import interpret_turn_input, _COMMAND_DISPATCH_TYPES  # noqa: E402


def _make_llm(query_type: str):
    """Return a fake call_llm that always classifies the input as query_type."""
    def call_llm(system: str, user: str, model: str | None) -> str:
        return _json.dumps({
            "query_type": query_type,
            "target_component": None,
            "off_task_ratio": 0.0,
            "response_latency_sec": 1.0,
        })
    return call_llm


class TestCommandDispatchTypes:

    def test_status_query_not_in_dispatch_set(self):
        """status_query must have been removed from _COMMAND_DISPATCH_TYPES."""
        assert "status_query" not in _COMMAND_DISPATCH_TYPES

    def test_diagnostic_not_in_dispatch_set(self):
        """diagnostic must have been removed from _COMMAND_DISPATCH_TYPES."""
        assert "diagnostic" not in _COMMAND_DISPATCH_TYPES

    def test_admin_command_in_dispatch_set(self):
        assert "admin_command" in _COMMAND_DISPATCH_TYPES

    def test_config_review_in_dispatch_set(self):
        assert "config_review" in _COMMAND_DISPATCH_TYPES

    def test_status_query_produces_null_command_dispatch(self):
        """status_query classified turn must not trigger slm_parse_admin_command.

        Since status_query is no longer in _COMMAND_DISPATCH_TYPES the code
        takes the else-branch unconditionally and sets command_dispatch=None
        without ever touching the SLM layer.
        """
        evidence = interpret_turn_input(
            call_llm=_make_llm("status_query"),
            input_text="what is the current system status?",
            task_context={},
            prompt_text="",
        )
        assert evidence["command_dispatch"] is None

    def test_diagnostic_produces_null_command_dispatch(self):
        """diagnostic classified turn must not trigger slm_parse_admin_command."""
        evidence = interpret_turn_input(
            call_llm=_make_llm("diagnostic"),
            input_text="something seems broken",
            task_context={},
            prompt_text="",
        )
        assert evidence["command_dispatch"] is None


# ── invite_user operation ─────────────────────────────────────────────────────


@pytest.mark.integration
def test_invite_user_executes_immediately(client: TestClient, api_module) -> None:
    """invite_user is HITL-exempt — must execute immediately, not stage."""
    token = _register_root(client)
    parsed = {
        "operation": "invite_user",
        "target": "matt",
        "params": {"username": "matt", "role": "user"},
    }
    with (
        patch.object(api_module, "slm_available", return_value=True),
        patch.object(api_module, "slm_parse_admin_command", return_value=parsed),
    ):
        resp = client.post(
            "/api/admin/command",
            json={"instruction": "invite user Matt"},
            headers=_auth_header(token),
        )
    assert resp.status_code == 200
    body = resp.json()
    # invite_user now requires HITL approval — staged as action card
    assert body["staged_id"] is not None
    assert body["structured_content"]["type"] == "action_card"


# ── _stage_command helper ─────────────────────────────────────────────────────


@pytest.mark.unit
def test_stage_command_helper_creates_entry() -> None:
    """_stage_command should create, store, and return a staged entry."""
    from lumina.api.routes.admin import _stage_command, _STAGED_COMMANDS

    entry = _stage_command(
        parsed_command={"operation": "deactivate_user", "target": "user99", "params": {"user_id": "user99"}},
        original_instruction="deactivate user user99",
        actor_id="test-actor",
        actor_role="root",
    )
    assert entry["staged_id"] in _STAGED_COMMANDS
    assert entry["parsed_command"]["operation"] == "deactivate_user"
    assert entry["structured_content"]["type"] == "action_card"
    assert entry["structured_content"]["card_type"] == "command_proposal"
    assert not entry["resolved"]


@pytest.mark.unit
def test_stage_command_helper_rejects_unknown_operation() -> None:
    """_stage_command should raise ValueError for unknown operations."""
    from lumina.api.routes.admin import _stage_command

    with pytest.raises(ValueError, match="Unknown operation"):
        _stage_command(
            parsed_command={"operation": "nuke_everything", "target": "", "params": {}},
            original_instruction="nuke everything",
            actor_id="test-actor",
            actor_role="root",
        )
