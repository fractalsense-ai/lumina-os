"""Integration tests for the HITL command gate.

Tests cover the two-step stage → resolve flow:
  POST /api/admin/command          → returns staged_id, nothing executed
  POST /api/admin/command/{id}/resolve → human Accept / Reject / Modify

Key scenarios:
  - Accept executes the operation
  - Reject discards the command (nothing executed)
  - Modify replaces the parsed schema, then executes modified version
  - Expired staged command returns 410
  - Wrong owner returns 403 (unless resolver is root)
  - Unknown staged_id returns 404
  - Already-resolved staged command returns 409
  - Invalid action returns 422
  - Modify without modified_schema returns 422
  - Modify with unknown operation in modified_schema returns 422
  - CTL records are written for staged, accepted, rejected, and modified paths
  - Root can resolve any user's staged command
"""
from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from lumina.auth import auth
from lumina.persistence.adapter import NullPersistenceAdapter
from lumina.core.yaml_loader import load_yaml as _load_yaml

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_api_module():
    module_path = _REPO_ROOT / "src" / "lumina" / "api" / "server.py"
    module_name = "lumina.api.server_hitl_test"
    if module_name in sys.modules:
        del sys.modules[module_name]
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
    mod._STAGED_COMMANDS.clear()
    monkeypatch.setattr(auth, "JWT_SECRET", "test-secret-hitl")
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


def _register_user(client: TestClient, username: str, role: str = "it_support") -> str:
    resp = client.post(
        "/api/auth/register",
        json={"username": username, "password": "test-pass-123", "role": role},
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _stage(client: TestClient, token: str, parsed: dict, instruction: str = "do something") -> str:
    """Stage a command and return the staged_id."""
    with (
        patch.object(client.app.state, "_hitl_slm_available", create=True),
    ):
        pass  # context manager placeholder — actual patching is done at call site

    with (
        patch("lumina.api.server_hitl_test.slm_available", return_value=True),
        patch("lumina.api.server_hitl_test.slm_parse_admin_command", return_value=parsed),
    ):
        resp = client.post(
            "/api/admin/command",
            json={"instruction": instruction},
            headers=_auth(token),
        )
    assert resp.status_code == 200, resp.text
    return resp.json()["staged_id"]


def _stage_via_module(client: TestClient, api_module, token: str, parsed: dict, instruction: str = "test") -> str:
    """Stage a command using module-level patches (preferred in this test file)."""
    with (
        patch.object(api_module, "slm_available", return_value=True),
        patch.object(api_module, "slm_parse_admin_command", return_value=parsed),
    ):
        resp = client.post(
            "/api/admin/command",
            json={"instruction": instruction},
            headers=_auth(token),
        )
    assert resp.status_code == 200, resp.text
    return resp.json()["staged_id"]


# ── Stage endpoint ────────────────────────────────────────────────────────────


@pytest.mark.integration
def test_stage_returns_staged_id_and_no_execution(client: TestClient, api_module) -> None:
    """POST /api/admin/command must return a staged_id and NOT execute anything."""
    token = _register_root(client)
    deactivate_mock = MagicMock()
    api_module.PERSISTENCE.deactivate_user = deactivate_mock

    parsed = {"operation": "deactivate_user", "target": "user42", "params": {"user_id": "user42"}}
    with (
        patch.object(api_module, "slm_available", return_value=True),
        patch.object(api_module, "slm_parse_admin_command", return_value=parsed),
    ):
        resp = client.post(
            "/api/admin/command",
            json={"instruction": "deactivate user user42"},
            headers=_auth(token),
        )

    assert resp.status_code == 200
    body = resp.json()
    assert "staged_id" in body
    assert body["staged_command"]["operation"] == "deactivate_user"
    assert "expires_at" in body
    assert "ctl_stage_record_id" in body
    # Critical: execution must NOT have happened at stage time.
    deactivate_mock.assert_not_called()


@pytest.mark.integration
def test_stage_unknown_operation_rejected(client: TestClient, api_module) -> None:
    """An unknown operation in the parsed result must be rejected at stage time."""
    token = _register_root(client)
    parsed = {"operation": "summon_demons", "target": "chaos", "params": {}}
    with (
        patch.object(api_module, "slm_available", return_value=True),
        patch.object(api_module, "slm_parse_admin_command", return_value=parsed),
    ):
        resp = client.post(
            "/api/admin/command",
            json={"instruction": "summon demons"},
            headers=_auth(token),
        )
    assert resp.status_code == 422
    assert "Unknown operation" in resp.json()["detail"]


# ── Accept ────────────────────────────────────────────────────────────────────


@pytest.mark.integration
def test_accept_executes_and_returns_result(client: TestClient, api_module) -> None:
    """Accept path: operation is executed and result returned."""
    token = _register_root(client)
    deactivate_mock = MagicMock()
    api_module.PERSISTENCE.deactivate_user = deactivate_mock

    parsed = {"operation": "deactivate_user", "target": "user77", "params": {"user_id": "user77"}}
    staged_id = _stage_via_module(client, api_module, token, parsed, "deactivate user user77")

    resp = client.post(
        f"/api/admin/command/{staged_id}/resolve",
        json={"action": "accept"},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["action"] == "accept"
    assert body["staged_id"] == staged_id
    assert body["result"]["user_id"] == "user77"
    assert "ctl_record_id" in body
    deactivate_mock.assert_called_once_with("user77")


# ── Reject ────────────────────────────────────────────────────────────────────


@pytest.mark.integration
def test_reject_does_not_execute(client: TestClient, api_module) -> None:
    """Reject path: nothing is executed, action is recorded."""
    token = _register_root(client)
    deactivate_mock = MagicMock()
    api_module.PERSISTENCE.deactivate_user = deactivate_mock

    parsed = {"operation": "deactivate_user", "target": "user88", "params": {"user_id": "user88"}}
    staged_id = _stage_via_module(client, api_module, token, parsed, "deactivate user user88")

    resp = client.post(
        f"/api/admin/command/{staged_id}/resolve",
        json={"action": "reject"},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["action"] == "reject"
    assert body["staged_id"] == staged_id
    assert "ctl_record_id" in body
    # Execution must NOT have happened.
    deactivate_mock.assert_not_called()


# ── Modify ────────────────────────────────────────────────────────────────────


@pytest.mark.integration
def test_modify_executes_modified_schema(client: TestClient, api_module) -> None:
    """Modify path: modified_schema replaces the SLM-parsed schema before execution."""
    token = _register_root(client)
    deactivate_mock = MagicMock()
    api_module.PERSISTENCE.deactivate_user = deactivate_mock

    parsed = {"operation": "deactivate_user", "target": "user11", "params": {"user_id": "user11"}}
    staged_id = _stage_via_module(client, api_module, token, parsed, "deactivate user user11")

    # Modify: change the target user.
    modified = {"operation": "deactivate_user", "target": "user22", "params": {"user_id": "user22"}}
    resp = client.post(
        f"/api/admin/command/{staged_id}/resolve",
        json={"action": "modify", "modified_schema": modified},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["action"] == "modify"
    assert body["result"]["user_id"] == "user22"
    assert "ctl_record_id" in body
    deactivate_mock.assert_called_once_with("user22")


@pytest.mark.integration
def test_modify_without_schema_returns_422(client: TestClient, api_module) -> None:
    """Modify without providing modified_schema must return 422."""
    token = _register_root(client)
    parsed = {"operation": "deactivate_user", "target": "u1", "params": {"user_id": "u1"}}
    staged_id = _stage_via_module(client, api_module, token, parsed)

    resp = client.post(
        f"/api/admin/command/{staged_id}/resolve",
        json={"action": "modify"},
        headers=_auth(token),
    )
    assert resp.status_code == 422


@pytest.mark.integration
def test_modify_with_unknown_operation_returns_422(client: TestClient, api_module) -> None:
    """Modify with an unknown operation in the modified_schema must return 422."""
    token = _register_root(client)
    parsed = {"operation": "deactivate_user", "target": "u1", "params": {"user_id": "u1"}}
    staged_id = _stage_via_module(client, api_module, token, parsed)

    resp = client.post(
        f"/api/admin/command/{staged_id}/resolve",
        json={"action": "modify", "modified_schema": {"operation": "hack_the_planet", "target": "all", "params": {}}},
        headers=_auth(token),
    )
    assert resp.status_code == 422


# ── Expiry ────────────────────────────────────────────────────────────────────


@pytest.mark.integration
def test_expired_staged_command_returns_410(client: TestClient, api_module) -> None:
    """A staged command past its TTL must return 410."""
    token = _register_root(client)
    parsed = {"operation": "deactivate_user", "target": "u1", "params": {"user_id": "u1"}}

    with (
        patch.object(api_module, "slm_available", return_value=True),
        patch.object(api_module, "slm_parse_admin_command", return_value=parsed),
    ):
        resp = client.post(
            "/api/admin/command",
            json={"instruction": "deactivate user u1"},
            headers=_auth(token),
        )
    assert resp.status_code == 200
    staged_id = resp.json()["staged_id"]

    # Force-expire it.
    with api_module._STAGED_COMMANDS_LOCK:
        api_module._STAGED_COMMANDS[staged_id]["expires_at"] = time.time() - 1

    resp = client.post(
        f"/api/admin/command/{staged_id}/resolve",
        json={"action": "accept"},
        headers=_auth(token),
    )
    assert resp.status_code == 410


# ── Ownership ─────────────────────────────────────────────────────────────────


@pytest.mark.integration
def test_wrong_owner_cannot_resolve(client: TestClient, api_module) -> None:
    """A non-root actor cannot resolve another user's staged command."""
    token1 = _register_root(client)           # root (first registered → root)
    token2 = _register_user(client, "it_user", "it_support")

    # it_support stages a command.
    parsed = {"operation": "deactivate_user", "target": "u99", "params": {"user_id": "u99"}}
    staged_id = _stage_via_module(client, api_module, token2, parsed)

    # A different it_support user tries to resolve it.
    token3 = _register_user(client, "it_user2", "it_support")
    resp = client.post(
        f"/api/admin/command/{staged_id}/resolve",
        json={"action": "accept"},
        headers=_auth(token3),
    )
    assert resp.status_code == 403


@pytest.mark.integration
def test_root_can_resolve_any_staged_command(client: TestClient, api_module) -> None:
    """Root can resolve a staged command that was created by a different actor."""
    root_token = _register_root(client)
    it_token = _register_user(client, "it_user", "it_support")

    deactivate_mock = MagicMock()
    api_module.PERSISTENCE.deactivate_user = deactivate_mock

    parsed = {"operation": "deactivate_user", "target": "u50", "params": {"user_id": "u50"}}
    staged_id = _stage_via_module(client, api_module, it_token, parsed, "deactivate user u50")

    # Root resolves it.
    resp = client.post(
        f"/api/admin/command/{staged_id}/resolve",
        json={"action": "accept"},
        headers=_auth(root_token),
    )
    assert resp.status_code == 200
    assert resp.json()["result"]["user_id"] == "u50"
    deactivate_mock.assert_called_once_with("u50")


# ── Edge cases ────────────────────────────────────────────────────────────────


@pytest.mark.integration
def test_unknown_staged_id_returns_404(client: TestClient, api_module) -> None:
    token = _register_root(client)
    resp = client.post(
        "/api/admin/command/does-not-exist/resolve",
        json={"action": "accept"},
        headers=_auth(token),
    )
    assert resp.status_code == 404


@pytest.mark.integration
def test_double_resolve_returns_409(client: TestClient, api_module) -> None:
    """A staged command can only be resolved once."""
    token = _register_root(client)
    deactivate_mock = MagicMock()
    api_module.PERSISTENCE.deactivate_user = deactivate_mock

    parsed = {"operation": "deactivate_user", "target": "u55", "params": {"user_id": "u55"}}
    staged_id = _stage_via_module(client, api_module, token, parsed)

    resp1 = client.post(
        f"/api/admin/command/{staged_id}/resolve",
        json={"action": "accept"},
        headers=_auth(token),
    )
    assert resp1.status_code == 200

    resp2 = client.post(
        f"/api/admin/command/{staged_id}/resolve",
        json={"action": "accept"},
        headers=_auth(token),
    )
    assert resp2.status_code == 409


@pytest.mark.integration
def test_invalid_action_returns_422(client: TestClient, api_module) -> None:
    token = _register_root(client)
    parsed = {"operation": "deactivate_user", "target": "u1", "params": {"user_id": "u1"}}
    staged_id = _stage_via_module(client, api_module, token, parsed)

    resp = client.post(
        f"/api/admin/command/{staged_id}/resolve",
        json={"action": "obliterate"},
        headers=_auth(token),
    )
    assert resp.status_code == 422


# ── CTL record assertions ─────────────────────────────────────────────────────


@pytest.mark.integration
def test_ctl_staged_record_written_on_stage(client: TestClient, api_module) -> None:
    """A hitl_command_staged CTL record must be written when a command is staged."""
    token = _register_root(client)
    ctl_records: list[dict] = []

    orig_append = api_module.PERSISTENCE.append_ctl_record

    def _capture(record_type, record, **kwargs):
        ctl_records.append(record)
        return orig_append(record_type, record, **kwargs)

    api_module.PERSISTENCE.append_ctl_record = _capture

    parsed = {"operation": "deactivate_user", "target": "u1", "params": {"user_id": "u1"}}
    with (
        patch.object(api_module, "slm_available", return_value=True),
        patch.object(api_module, "slm_parse_admin_command", return_value=parsed),
    ):
        resp = client.post(
            "/api/admin/command",
            json={"instruction": "deactivate user u1"},
            headers=_auth(token),
        )
    assert resp.status_code == 200

    staged_types = [r.get("commitment_type") for r in ctl_records]
    assert "hitl_command_staged" in staged_types


@pytest.mark.integration
def test_ctl_accepted_record_written_on_accept(client: TestClient, api_module) -> None:
    """A hitl_command_accepted CTL record must be written when a command is accepted."""
    token = _register_root(client)
    ctl_records: list[dict] = []

    orig_append = api_module.PERSISTENCE.append_ctl_record

    def _capture(record_type, record, **kwargs):
        ctl_records.append(record)
        return orig_append(record_type, record, **kwargs)

    api_module.PERSISTENCE.append_ctl_record = _capture

    parsed = {"operation": "deactivate_user", "target": "u2", "params": {"user_id": "u2"}}
    staged_id = _stage_via_module(client, api_module, token, parsed)

    resp = client.post(
        f"/api/admin/command/{staged_id}/resolve",
        json={"action": "accept"},
        headers=_auth(token),
    )
    assert resp.status_code == 200

    commit_types = [r.get("commitment_type") for r in ctl_records]
    assert "hitl_command_accepted" in commit_types


@pytest.mark.integration
def test_ctl_rejected_record_written_on_reject(client: TestClient, api_module) -> None:
    """A hitl_command_rejected CTL record must be written when a command is rejected."""
    token = _register_root(client)
    ctl_records: list[dict] = []

    orig_append = api_module.PERSISTENCE.append_ctl_record

    def _capture(record_type, record, **kwargs):
        ctl_records.append(record)
        return orig_append(record_type, record, **kwargs)

    api_module.PERSISTENCE.append_ctl_record = _capture

    parsed = {"operation": "deactivate_user", "target": "u3", "params": {"user_id": "u3"}}
    staged_id = _stage_via_module(client, api_module, token, parsed)

    resp = client.post(
        f"/api/admin/command/{staged_id}/resolve",
        json={"action": "reject"},
        headers=_auth(token),
    )
    assert resp.status_code == 200

    commit_types = [r.get("commitment_type") for r in ctl_records]
    assert "hitl_command_rejected" in commit_types
