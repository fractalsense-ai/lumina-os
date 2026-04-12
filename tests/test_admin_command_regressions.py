"""Regression tests for admin command normalisation bug fixes.

Covers:
- Empty governed_modules no longer triggers IndexError
- Domain-role aliases (student, teacher) normalised to system role "user"
- Domain-prefix stripping (education_user → user)
- governed_modules "all" expansion via DomainRegistry
- String governed_modules coerced to list
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
from lumina.core.runtime_loader import load_runtime_context

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
    monkeypatch.setattr(auth, "JWT_SECRET", "test-secret-regressions")
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


# ── Unit tests for _normalize_slm_command ─────────────────────────────────────


@pytest.mark.integration
def test_empty_governed_modules_no_index_error(client: TestClient, api_module) -> None:
    """Empty governed_modules: [] must not IndexError."""
    token = _register_root(client)
    parsed = {
        "operation": "invite_user",
        "target": "alice",
        "params": {
            "username": "alice",
            "role": "user",
            "governed_modules": [],
        },
    }
    with (
        patch.object(api_module, "slm_available", return_value=True),
        patch.object(api_module, "slm_parse_admin_command", return_value=parsed),
    ):
        resp = client.post(
            "/api/admin/command",
            json={"instruction": "invite user alice"},
            headers=_auth_header(token),
        )
    # Should succeed — no IndexError on empty list
    # invite_user now goes through HITL staging (action card)
    assert resp.status_code == 200
    body = resp.json()
    assert body["staged_id"] is not None
    assert body["structured_content"]["type"] == "action_card"


@pytest.mark.integration
def test_domain_role_student_normalised_to_user(api_module) -> None:
    """SLM returning new_role='student' should normalise to 'user' with intended_domain_role."""
    from lumina.api.routes.admin import _normalize_slm_command

    cmd = {
        "operation": "update_user_role",
        "target": "bob",
        "params": {"user_id": "bob", "new_role": "student"},
    }
    result = _normalize_slm_command(cmd)
    assert result["params"]["new_role"] == "user"
    assert result["params"]["intended_domain_role"] == "student"


@pytest.mark.integration
def test_domain_role_teacher_normalised_to_user(api_module) -> None:
    """SLM returning new_role='teacher' should normalise to 'user' with intended_domain_role."""
    from lumina.api.routes.admin import _normalize_slm_command

    cmd = {
        "operation": "update_user_role",
        "target": "carol",
        "params": {"user_id": "carol", "new_role": "teacher"},
    }
    result = _normalize_slm_command(cmd)
    assert result["params"]["new_role"] == "user"
    assert result["params"]["intended_domain_role"] == "teacher"


@pytest.mark.integration
def test_domain_prefix_stripped(api_module) -> None:
    """SLM returning 'education_user' should strip the domain prefix → 'user'."""
    from lumina.api.routes.admin import _normalize_slm_command

    cmd = {
        "operation": "update_user_role",
        "target": "dave",
        "params": {"user_id": "dave", "new_role": "education_user"},
    }
    result = _normalize_slm_command(cmd)
    assert result["params"]["new_role"] == "user"
    assert result["params"]["intended_domain_role"] == "education_user"


@pytest.mark.integration
def test_governed_modules_all_expansion(api_module, monkeypatch: pytest.MonkeyPatch) -> None:
    """governed_modules: 'all' should expand to actual module IDs from the registry.

    Only domain_authority may carry governed_modules; non-DA roles have it
    stripped by _normalize_slm_command (Phase 6).
    """
    from lumina.api import config as _cfg
    from lumina.api.routes.admin import _normalize_slm_command

    mock_registry = MagicMock()
    mock_registry.resolve_domain_id.return_value = "education"
    mock_registry._prefix_to_domain = {}
    mock_registry.list_modules_for_domain.return_value = [
        {"module_id": "algebra-1", "domain_physics_path": "..."},
        {"module_id": "pre-algebra", "domain_physics_path": "..."},
    ]
    monkeypatch.setattr(_cfg, "DOMAIN_REGISTRY", mock_registry)

    cmd = {
        "operation": "invite_user",
        "target": "education",
        "params": {
            "username": "eve",
            "role": "domain_authority",
            "governed_modules": "all",
        },
    }
    result = _normalize_slm_command(cmd)
    assert result["params"]["governed_modules"] == ["algebra-1", "pre-algebra"]


@pytest.mark.integration
def test_governed_modules_all_string_coerced_to_list(api_module) -> None:
    """governed_modules: 'some_module' (string) should become ['some_module']."""
    from lumina.api.routes.admin import _normalize_slm_command

    cmd = {
        "operation": "invite_user",
        "target": "frank",
        "params": {
            "username": "frank",
            "role": "domain_authority",
            "governed_modules": "some_module",
        },
    }
    result = _normalize_slm_command(cmd)
    assert result["params"]["governed_modules"] == ["some_module"]


# ── domain_id resolution from session module path ─────────────────────────────


@pytest.fixture
def multi_domain_module(monkeypatch: pytest.MonkeyPatch):
    """Fixture with multi-domain registry for domain_id resolution tests."""
    monkeypatch.setenv("LUMINA_RUNTIME_CONFIG_PATH", "domain-packs/education/cfg/runtime-config.yaml")
    monkeypatch.delenv("LUMINA_DOMAIN_REGISTRY_PATH", raising=False)
    mod = _load_api_module()
    mod.PERSISTENCE = NullPersistenceAdapter()
    mod.BOOTSTRAP_MODE = True
    mod._session_containers.clear()
    monkeypatch.setattr(auth, "JWT_SECRET", "test-secret-regressions-md")

    from lumina.api import config as _cfg
    registry = DomainRegistry(
        repo_root=_REPO_ROOT,
        registry_path=str(_REPO_ROOT / "domain-packs" / "system" / "cfg" / "domain-registry.yaml"),
        load_runtime_context_fn=load_runtime_context,
    )
    monkeypatch.setattr(_cfg, "DOMAIN_REGISTRY", registry)
    return mod


@pytest.fixture
def md_client(multi_domain_module):
    return TestClient(multi_domain_module.app)


@pytest.mark.integration
def test_invite_domain_id_resolved_from_module_path(md_client: TestClient, multi_domain_module) -> None:
    """When domain_id is a module path like 'domain/edu/domain-authority/v1',
    it should be resolved to the registry domain_id 'education'."""
    # First register to consume bootstrap slot (gets promoted to root)
    root_resp = md_client.post(
        "/api/auth/register",
        json={"username": "root_admin", "password": "test-pass-123", "role": "user"},
    )
    assert root_resp.status_code == 200
    root_token = root_resp.json()["access_token"]

    resp = md_client.post(
        "/api/admin/command",
        json={
            "operation": "invite_user",
            "params": {"username": "NewStudent", "role": "user", "intended_domain_role": "student"},
            "domain_id": "domain/edu/domain-authority/v1",
        },
        headers={"Authorization": f"Bearer {root_token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    staged = body["staged_command"]
    # domain_id must be resolved to the registry domain ID, not the raw module path
    assert staged["params"]["domain_id"] == "education"
