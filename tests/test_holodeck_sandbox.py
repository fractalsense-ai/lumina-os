"""Tests for Feature I — Holodeck Physics Sandbox.

Tests that domain authorities and root can simulate proposed physics changes
via POST /api/holodeck/simulate before approving them into the live system.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import threading
from pathlib import Path
from typing import Any
from unittest.mock import patch

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

def _load_api_module(module_name: str = "lumina_api_server_sandbox"):
    module_path = _REPO_ROOT / "src" / "lumina" / "api" / "server.py"
    spec = importlib.util.spec_from_file_location(module_name, str(module_path))
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load lumina-api-server module")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


def _make_token(role: str, governed_modules: list[str] | None = None) -> str:
    return auth.create_jwt(
        user_id=f"test_{role}_sandbox",
        role=role,
        governed_modules=governed_modules or [],
    )


def _auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# Correct evidence fields for the education algebra domain invariants:
#   solution_verifies → check: "substitution_check"
#   standard_method_preferred → check: "method_recognized"
#   no_illegal_operations → check: "illegal_operations == []"
_VALID_TURN_DATA = {
    "substitution_check": True,
    "method_recognized": True,
    "illegal_operations": [],
    "equivalence_preserved": True,
    "step_count": 3,
    "min_steps": 1,
    "problem_solved": True,
    "student_answer": "x = 5",
}


@pytest.fixture
def api_module(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LUMINA_RUNTIME_CONFIG_PATH", "domain-packs/education/cfg/runtime-config.yaml")
    monkeypatch.delenv("LUMINA_DOMAIN_REGISTRY_PATH", raising=False)
    mod = _load_api_module()
    mod.PERSISTENCE = NullPersistenceAdapter()
    mod.BOOTSTRAP_MODE = True
    mod.DOMAIN_REGISTRY = DomainRegistry(
        repo_root=_REPO_ROOT,
        single_config_path="domain-packs/education/cfg/runtime-config.yaml",
        load_runtime_context_fn=load_runtime_context,
    )
    mod._session_containers.clear()
    monkeypatch.setattr(auth, "JWT_SECRET", "test-secret-sandbox")
    mod.PERSISTENCE.load_subject_profile = _load_yaml
    _orig_load = mod.PERSISTENCE.load_domain_physics
    def _load_without_perms(path: str) -> dict:
        data = _orig_load(path)
        data.pop("permissions", None)
        return data
    mod.PERSISTENCE.load_domain_physics = _load_without_perms
    monkeypatch.setattr("lumina.api.processing.slm_available", lambda: False)
    return mod


@pytest.fixture
def client(api_module):
    return TestClient(api_module.app)


# ═══════════════════════════════════════════════════════════════════════
# Feature I — Holodeck Physics Sandbox
# ═══════════════════════════════════════════════════════════════════════


class TestHolodeckSandbox:
    """Feature I: Simulate proposed physics changes before they enter the live system."""

    @pytest.mark.integration
    def test_sandbox_with_physics_override_returns_holodeck_evidence(
        self, client: TestClient
    ) -> None:
        """Root user can simulate with inline physics_override and gets
        holodeck evidence, physics_diff, and hashes in response."""
        token = _make_token("root")
        override = {
            "invariants": [
                {
                    "id": "custom_sandbox_invariant",
                    "description": "Test invariant added via sandbox",
                    "severity": "warning",
                    "check": "sandbox_flag",
                }
            ],
        }
        resp = client.post(
            "/api/holodeck/simulate",
            json={
                "domain_id": "_default",
                "message": "solve x + 1 = 3",
                "physics_override": override,
                "turn_data_override": _VALID_TURN_DATA,
                "deterministic_response": True,
            },
            headers=_auth_header(token),
        )
        assert resp.status_code == 200
        body = resp.json()
        # Should have holodeck evidence
        sc = body.get("structured_content") or {}
        assert "holodeck" in sc, f"Expected holodeck key, got: {list(sc.keys())}"
        hd = sc["holodeck"]
        assert "state_snapshot" in hd
        assert "inspection_result" in hd
        assert "invariant_checks" in hd
        # Should have sandbox metadata
        assert body["sandbox_physics"] is not None
        assert body["physics_diff"] is not None
        assert body["live_physics_hash"] is not None
        assert body["sandbox_physics_hash"] is not None
        # The invariants in sandbox_physics should be the override
        assert body["sandbox_physics"]["invariants"] == override["invariants"]
        # Diff should show invariants changed
        diff = body["physics_diff"]
        assert "invariants" in diff.get("changed", {})
        # Session ID should be ephemeral (holodeck-prefixed)
        assert body["session_id"].startswith("holodeck-")

    @pytest.mark.integration
    def test_sandbox_user_forbidden(self, client: TestClient) -> None:
        """Regular user cannot access the sandbox — 403."""
        token = _make_token("user")
        resp = client.post(
            "/api/holodeck/simulate",
            json={
                "domain_id": "_default",
                "message": "hello",
                "physics_override": {"version": "0.99.0"},
            },
            headers=_auth_header(token),
        )
        assert resp.status_code == 403

    @pytest.mark.integration
    def test_sandbox_domain_authority_succeeds(self, client: TestClient) -> None:
        """admin can simulate physics changes for governed domains."""
        token = _make_token("admin", governed_modules=["_default"])
        resp = client.post(
            "/api/holodeck/simulate",
            json={
                "domain_id": "_default",
                "message": "solve x + 1 = 3",
                "physics_override": {"version": "0.99.0"},
                "turn_data_override": _VALID_TURN_DATA,
                "deterministic_response": True,
            },
            headers=_auth_header(token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["sandbox_physics"]["version"] == "0.99.0"

    @pytest.mark.integration
    def test_sandbox_requires_staged_id_or_override(self, client: TestClient) -> None:
        """Must provide exactly one of staged_id or physics_override."""
        token = _make_token("root")
        # Neither provided
        resp = client.post(
            "/api/holodeck/simulate",
            json={"domain_id": "_default", "message": "hello"},
            headers=_auth_header(token),
        )
        assert resp.status_code == 422

    @pytest.mark.integration
    def test_sandbox_both_staged_and_override_rejected(
        self, client: TestClient
    ) -> None:
        """Providing both staged_id AND physics_override is rejected."""
        token = _make_token("root")
        resp = client.post(
            "/api/holodeck/simulate",
            json={
                "domain_id": "_default",
                "message": "hello",
                "staged_id": "fake-id",
                "physics_override": {"version": "0.99.0"},
            },
            headers=_auth_header(token),
        )
        assert resp.status_code == 422

    @pytest.mark.integration
    def test_sandbox_staged_id_not_found_returns_404(
        self, client: TestClient
    ) -> None:
        """Referencing a non-existent staged_id returns 404."""
        token = _make_token("root")
        resp = client.post(
            "/api/holodeck/simulate",
            json={
                "domain_id": "_default",
                "message": "hello",
                "staged_id": "nonexistent-staged-id",
            },
            headers=_auth_header(token),
        )
        assert resp.status_code == 404

    @pytest.mark.integration
    def test_sandbox_with_staged_admin_command(
        self, client: TestClient, api_module
    ) -> None:
        """Simulate using a staged update_domain_physics command from the admin pipeline."""
        # Manually inject a staged command into the admin module's store
        from lumina.api.routes.admin import _STAGED_COMMANDS, _STAGED_COMMANDS_LOCK
        import time as _time

        staged_id = "test-staged-physics-001"
        with _STAGED_COMMANDS_LOCK:
            _STAGED_COMMANDS[staged_id] = {
                "staged_id": staged_id,
                "actor_id": "test_teacher",
                "actor_role": "user",
                "parsed_command": {
                    "operation": "update_domain_physics",
                    "params": {
                        "domain_id": "_default",
                        "updates": {
                            "description": "Modified by teacher proposal — pending review",
                        },
                    },
                },
                "original_instruction": "Update description for review",
                "staged_at": _time.time(),
                "expires_at": _time.time() + 300,
                "resolved": False,
            }

        try:
            token = _make_token("root")
            resp = client.post(
                "/api/holodeck/simulate",
                json={
                    "domain_id": "_default",
                    "message": "solve x + 1 = 3",
                    "staged_id": staged_id,
                    "turn_data_override": _VALID_TURN_DATA,
                    "deterministic_response": True,
                },
                headers=_auth_header(token),
            )
            assert resp.status_code == 200
            body = resp.json()

            # Sandbox physics should have the proposed description
            assert body["sandbox_physics"]["description"] == (
                "Modified by teacher proposal — pending review"
            )
            # staged_id echoed back
            assert body["staged_id"] == staged_id
            # Physics diff shows description changed
            diff = body["physics_diff"]
            assert "description" in diff.get("changed", {})
            # Holodeck evidence present
            sc = body.get("structured_content") or {}
            assert "holodeck" in sc
        finally:
            # Cleanup staged command
            with _STAGED_COMMANDS_LOCK:
                _STAGED_COMMANDS.pop(staged_id, None)

    @pytest.mark.integration
    def test_sandbox_ephemeral_session_cleaned_up(
        self, client: TestClient, api_module
    ) -> None:
        """After simulation, the sandbox session is removed from memory."""
        from lumina.api.session import _session_containers

        count_before = len(_session_containers)
        token = _make_token("root")
        resp = client.post(
            "/api/holodeck/simulate",
            json={
                "domain_id": "_default",
                "message": "hello",
                "physics_override": {"version": "0.99.0"},
                "turn_data_override": _VALID_TURN_DATA,
                "deterministic_response": True,
            },
            headers=_auth_header(token),
        )
        assert resp.status_code == 200
        body = resp.json()
        sandbox_sid = body["session_id"]
        assert sandbox_sid.startswith("holodeck-")
        # Session should have been cleaned up
        assert sandbox_sid not in _session_containers
        # Container count should be unchanged (sandbox was removed)
        assert len(_session_containers) == count_before

    @pytest.mark.integration
    def test_sandbox_does_not_pollute_live_physics(
        self, client: TestClient, api_module
    ) -> None:
        """Sandbox simulation does not modify the cached live runtime context."""
        runtime_before = api_module.DOMAIN_REGISTRY.get_runtime_context("_default")
        live_desc = runtime_before["domain"].get("description", "")

        token = _make_token("root")
        resp = client.post(
            "/api/holodeck/simulate",
            json={
                "domain_id": "_default",
                "message": "solve x + 1 = 3",
                "physics_override": {
                    "description": "SANDBOX POLLUTION TEST — should NOT appear in live"
                },
                "turn_data_override": _VALID_TURN_DATA,
                "deterministic_response": True,
            },
            headers=_auth_header(token),
        )
        assert resp.status_code == 200

        # Live runtime should be unchanged
        runtime_after = api_module.DOMAIN_REGISTRY.get_runtime_context("_default")
        assert runtime_after["domain"].get("description", "") == live_desc
        assert "SANDBOX POLLUTION TEST" not in runtime_after["domain"].get("description", "")

    @pytest.mark.integration
    def test_sandbox_resolved_staged_command_rejected(
        self, client: TestClient, api_module
    ) -> None:
        """Trying to simulate an already-resolved staged command returns 409."""
        from lumina.api.routes.admin import _STAGED_COMMANDS, _STAGED_COMMANDS_LOCK
        import time as _time

        staged_id = "test-resolved-staged-002"
        with _STAGED_COMMANDS_LOCK:
            _STAGED_COMMANDS[staged_id] = {
                "staged_id": staged_id,
                "actor_id": "test_teacher",
                "actor_role": "user",
                "parsed_command": {
                    "operation": "update_domain_physics",
                    "params": {
                        "domain_id": "_default",
                        "updates": {"version": "0.99.0"},
                    },
                },
                "original_instruction": "Already resolved",
                "staged_at": _time.time(),
                "expires_at": _time.time() + 300,
                "resolved": True,
            }

        try:
            token = _make_token("root")
            resp = client.post(
                "/api/holodeck/simulate",
                json={
                    "domain_id": "_default",
                    "message": "hello",
                    "staged_id": staged_id,
                },
                headers=_auth_header(token),
            )
            assert resp.status_code == 409
        finally:
            with _STAGED_COMMANDS_LOCK:
                _STAGED_COMMANDS.pop(staged_id, None)
