"""Tests for the three operational-gap features:

Feature A — ``list_commands`` admin operation
Feature B — System identity grounding (Project Lumina in UNIVERSAL_BASE_IDENTITY)
Feature C — Graceful degradation (policy commitment RuntimeError → 422/503)
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from lumina.auth import auth
from lumina.persistence.adapter import NullPersistenceAdapter
from lumina.core.yaml_loader import load_yaml as _load_yaml
from lumina.core.domain_registry import DomainRegistry
from lumina.core.runtime_loader import load_runtime_context

_REPO_ROOT = Path(__file__).resolve().parents[1]


# ═══════════════════════════════════════════════════════════════════════
# Shared fixtures
# ═══════════════════════════════════════════════════════════════════════

def _load_api_module(module_name: str = "lumina.api.server"):
    module_path = _REPO_ROOT / "src" / "lumina" / "api" / "server.py"
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
    monkeypatch.setattr(auth, "JWT_SECRET", "test-secret-three-features")
    mod.PERSISTENCE.load_subject_profile = _load_yaml
    return mod


@pytest.fixture
def multi_api_module(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LUMINA_DOMAIN_REGISTRY_PATH", "cfg/domain-registry.yaml")
    monkeypatch.delenv("LUMINA_RUNTIME_CONFIG_PATH", raising=False)
    mod = _load_api_module("lumina_api_server_threefeat_multi")
    mod.PERSISTENCE = NullPersistenceAdapter()
    mod.BOOTSTRAP_MODE = False
    mod._session_containers.clear()
    mod.PERSISTENCE.load_subject_profile = _load_yaml
    mod.DOMAIN_REGISTRY = DomainRegistry(
        repo_root=_REPO_ROOT,
        registry_path="cfg/domain-registry.yaml",
        load_runtime_context_fn=load_runtime_context,
    )
    monkeypatch.setattr(auth, "JWT_SECRET", "test-secret-three-features-multi")
    return mod


@pytest.fixture
def multi_client(multi_api_module):
    return TestClient(multi_api_module.app)


@pytest.fixture
def client(api_module):
    return TestClient(api_module.app)


def _register_root(client: TestClient) -> str:
    resp = client.post(
        "/api/auth/register",
        json={"username": "root_feat", "password": "test-pass-123", "role": "user"},
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]


def _auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ═══════════════════════════════════════════════════════════════════════
# Feature A — list_commands
# ═══════════════════════════════════════════════════════════════════════


class TestListCommandsSchemaRegistered:
    """list_commands schema is discoverable by the command-schema registry."""

    @pytest.mark.unit
    def test_list_commands_schema_file_exists(self) -> None:
        path = _REPO_ROOT / "standards" / "admin-command-schemas" / "list-commands.json"
        assert path.exists(), "list-commands.json schema file missing"

    @pytest.mark.unit
    def test_list_commands_schema_valid_json(self) -> None:
        path = _REPO_ROOT / "standards" / "admin-command-schemas" / "list-commands.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["title"] == "list_commands"
        assert data["description"]

    @pytest.mark.unit
    def test_list_commands_in_registry(self) -> None:
        from lumina.middleware.command_schema_registry import list_operations, reload
        reload()
        assert "list_commands" in list_operations()

    @pytest.mark.unit
    def test_get_schema_returns_dict(self) -> None:
        from lumina.middleware.command_schema_registry import get_schema, reload
        reload()
        schema = get_schema("list_commands")
        assert schema is not None
        assert schema["title"] == "list_commands"


class TestListCommandsOperation:
    """list_commands is HITL-exempt and returns the full command catalog."""

    @pytest.mark.unit
    def test_list_commands_in_known_ops(self) -> None:
        from lumina.api.routes.admin import _KNOWN_OPERATIONS
        assert "list_commands" in _KNOWN_OPERATIONS

    @pytest.mark.unit
    def test_list_commands_is_hitl_exempt(self) -> None:
        from lumina.api.routes.admin import _HITL_EXEMPT_OPS
        assert "list_commands" in _HITL_EXEMPT_OPS

    @pytest.mark.integration
    def test_list_commands_via_api(self, client: TestClient, api_module) -> None:
        token = _register_root(client)
        with patch("lumina.core.slm.slm_parse_admin_command") as mock_parse:
            mock_parse.return_value = {"operation": "list_commands", "params": {}}
            resp = client.post(
                "/api/admin/command",
                json={"instruction": "list commands"},
                headers=_auth_header(token),
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["hitl_exempt"] is True
        result = body["result"]
        assert result["operation"] == "list_commands"
        assert result["count"] >= 21
        # Every entry should have the rich catalog fields
        for cmd in result["commands"]:
            assert "name" in cmd
            assert "description" in cmd
            assert "hitl_exempt" in cmd
            assert "min_role" in cmd

    @pytest.mark.integration
    def test_list_commands_names_only(self, client: TestClient, api_module) -> None:
        token = _register_root(client)
        with patch("lumina.core.slm.slm_parse_admin_command") as mock_parse:
            mock_parse.return_value = {
                "operation": "list_commands",
                "params": {"include_details": False},
            }
            resp = client.post(
                "/api/admin/command",
                json={"instruction": "list commands brief"},
                headers=_auth_header(token),
            )
        assert resp.status_code == 200
        commands = resp.json()["result"]["commands"]
        # No detail fields when include_details=false
        for cmd in commands:
            assert "name" in cmd
            assert "description" not in cmd

    @pytest.mark.integration
    def test_list_commands_sorted(self, client: TestClient, api_module) -> None:
        token = _register_root(client)
        with patch("lumina.core.slm.slm_parse_admin_command") as mock_parse:
            mock_parse.return_value = {"operation": "list_commands", "params": {}}
            resp = client.post(
                "/api/admin/command",
                json={"instruction": "list commands"},
                headers=_auth_header(token),
            )
        names = [c["name"] for c in resp.json()["result"]["commands"]]
        assert names == sorted(names), "Commands should be alphabetically sorted"


# ═══════════════════════════════════════════════════════════════════════
# Feature B — System Identity Grounding
# ═══════════════════════════════════════════════════════════════════════


class TestSystemIdentityPersonaBuilder:
    """UNIVERSAL_BASE_IDENTITY contains 'Project Lumina'."""

    @pytest.mark.unit
    def test_identity_contains_project_lumina(self) -> None:
        from lumina.core.persona_builder import UNIVERSAL_BASE_IDENTITY
        assert "Project Lumina" in UNIVERSAL_BASE_IDENTITY

    @pytest.mark.unit
    def test_identity_still_references_library_system(self) -> None:
        from lumina.core.persona_builder import UNIVERSAL_BASE_IDENTITY
        assert "library computer" in UNIVERSAL_BASE_IDENTITY.lower()

    @pytest.mark.unit
    def test_all_contexts_contain_project_lumina(self) -> None:
        from lumina.core.persona_builder import PersonaContext, build_system_prompt
        for ctx in PersonaContext:
            prompt = build_system_prompt(ctx)
            assert "Project Lumina" in prompt, f"Context {ctx.value} missing Project Lumina"


class TestSystemIdentitySchema:
    """system_identity is defined in the system-physics schema."""

    @pytest.mark.unit
    def test_system_identity_in_schema(self) -> None:
        path = _REPO_ROOT / "standards" / "system-physics-schema-v1.json"
        schema = json.loads(path.read_text(encoding="utf-8"))
        props = schema["properties"]
        assert "system_identity" in props
        identity_props = props["system_identity"]["properties"]
        assert "system_name" in identity_props
        assert "description" in identity_props
        assert "disambiguation_note" in identity_props

    @pytest.mark.unit
    def test_system_name_required_within_block(self) -> None:
        path = _REPO_ROOT / "standards" / "system-physics-schema-v1.json"
        schema = json.loads(path.read_text(encoding="utf-8"))
        required = schema["properties"]["system_identity"]["required"]
        assert "system_name" in required


class TestSystemIdentityConfig:
    """system_identity is populated in the compiled system-physics.json."""

    @pytest.mark.unit
    def test_system_physics_json_has_identity(self) -> None:
        path = _REPO_ROOT / "cfg" / "system-physics.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "system_identity" in data
        assert data["system_identity"]["system_name"] == "Project Lumina"

    @pytest.mark.unit
    def test_universal_base_identity_contains_name(self) -> None:
        path = _REPO_ROOT / "cfg" / "system-physics.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "Project Lumina" in data["universal_base_identity"]

    @pytest.mark.unit
    def test_disambiguation_note_present(self) -> None:
        path = _REPO_ROOT / "cfg" / "system-physics.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        note = data["system_identity"]["disambiguation_note"]
        assert "immersion" in note.lower()


class TestDepartmentTag:
    """department property is in the domain-physics schema and tagged modules."""

    @pytest.mark.unit
    def test_department_in_domain_schema(self) -> None:
        path = _REPO_ROOT / "standards" / "domain-physics-schema-v1.json"
        schema = json.loads(path.read_text(encoding="utf-8"))
        assert "department" in schema["properties"]

    @pytest.mark.unit
    def test_algebra1_department(self) -> None:
        path = _REPO_ROOT / "domain-packs" / "education" / "modules" / "algebra-1" / "domain-physics.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["department"] == "Mathematics"

    @pytest.mark.unit
    def test_agriculture_department(self) -> None:
        path = _REPO_ROOT / "domain-packs" / "agriculture" / "modules" / "operations-level-1" / "domain-physics.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["department"] == "Field Operations"


# ═══════════════════════════════════════════════════════════════════════
# Feature C — Graceful Degradation
# ═══════════════════════════════════════════════════════════════════════


class TestGracefulDegradationChat:
    """RuntimeError from policy commitment → 422, not 500."""

    @pytest.mark.integration
    def test_policy_commitment_returns_422(self, multi_client: TestClient) -> None:
        with patch(
            "lumina.api.session._assert_policy_commitment",
            side_effect=RuntimeError(
                "Policy commitment mismatch: active module domain-physics hash is not log-committed."
            ),
        ):
            resp = multi_client.post(
                "/api/chat",
                json={"message": "hello", "domain_id": "education"},
            )
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert "committed" in detail.lower()
        assert "administrator" in detail.lower()

    @pytest.mark.integration
    def test_system_physics_commitment_returns_503(self, multi_client: TestClient) -> None:
        with patch(
            "lumina.api.routes.chat.process_message",
            side_effect=RuntimeError(
                "system_physics commitment not found for current hash"
            ),
        ):
            resp = multi_client.post(
                "/api/chat",
                json={"message": "hello", "domain_id": "education"},
            )
        assert resp.status_code == 503
        detail = resp.json()["detail"]
        assert "system physics" in detail.lower()

    @pytest.mark.integration
    def test_unrelated_runtime_error_still_500(self, multi_client: TestClient) -> None:
        with patch(
            "lumina.api.routes.chat.process_message",
            side_effect=RuntimeError("something totally unexpected"),
        ):
            resp = multi_client.post(
                "/api/chat",
                json={"message": "hello", "domain_id": "education"},
            )
        assert resp.status_code == 500


class TestGracefulDegradationAdmin:
    """RuntimeError from policy commitment in admin route → 422."""

    @pytest.mark.integration
    def test_admin_hitl_exempt_policy_error_422(self, client: TestClient, api_module) -> None:
        token = _register_root(client)
        with patch("lumina.core.slm.slm_parse_admin_command") as mock_parse, \
             patch(
                 "lumina.api.routes.admin._execute_admin_operation",
                 side_effect=RuntimeError("policy commitment mismatch"),
             ):
            mock_parse.return_value = {"operation": "list_domains", "params": {}}
            resp = client.post(
                "/api/admin/command",
                json={"instruction": "list domains"},
                headers=_auth_header(token),
            )
        assert resp.status_code == 422
        assert "committed" in resp.json()["detail"].lower()
