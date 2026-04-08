"""Tests for Features F, G, H:

Feature F — Magic-circle consent gate (server-side enforcement)
Feature G — MUD narrative in deterministic mode
Feature H — Physics holodeck mode
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from lumina.auth import auth
from lumina.persistence.adapter import NullPersistenceAdapter
from lumina.core.yaml_loader import load_yaml as _load_yaml
from lumina.core.domain_registry import DomainRegistry
from lumina.core.runtime_loader import load_runtime_context
from lumina.core.domain_registry import DomainRegistry
from lumina.core.runtime_loader import load_runtime_context

_REPO_ROOT = Path(__file__).resolve().parents[1]


# ═══════════════════════════════════════════════════════════════════════
# Shared fixtures
# ═══════════════════════════════════════════════════════════════════════

def _load_api_module(module_name: str = "lumina_api_server_fgh"):
    module_path = _REPO_ROOT / "src" / "lumina" / "api" / "server.py"
    spec = importlib.util.spec_from_file_location(module_name, str(module_path))
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load lumina-api-server module")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


def _make_token(role: str, governed_modules: list[str] | None = None) -> str:
    """Create a signed JWT for the given role using the test JWT_SECRET."""
    return auth.create_jwt(
        user_id=f"test_{role}_fgh",
        role=role,
        governed_modules=governed_modules or [],
    )


def _auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def api_module(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LUMINA_RUNTIME_CONFIG_PATH", "domain-packs/education/cfg/runtime-config.yaml")
    monkeypatch.delenv("LUMINA_DOMAIN_REGISTRY_PATH", raising=False)
    mod = _load_api_module()
    mod.PERSISTENCE = NullPersistenceAdapter()
    mod.BOOTSTRAP_MODE = True
    # Ensure a fresh single-domain DomainRegistry (prevents stale cache
    # from multi-domain test modules loaded earlier in the suite).
    mod.DOMAIN_REGISTRY = DomainRegistry(
        repo_root=_REPO_ROOT,
        single_config_path="domain-packs/education/cfg/runtime-config.yaml",
        load_runtime_context_fn=load_runtime_context,
    )
    mod._session_containers.clear()
    monkeypatch.setattr(auth, "JWT_SECRET", "test-secret-fgh")
    mod.PERSISTENCE.load_subject_profile = _load_yaml
    # Strip RBAC permissions from domain physics so consent tests can focus
    # on consent gating rather than module-level RBAC.
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


@pytest.fixture
def multi_api_module(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LUMINA_DOMAIN_REGISTRY_PATH", "domain-packs/system/cfg/domain-registry.yaml")
    monkeypatch.delenv("LUMINA_RUNTIME_CONFIG_PATH", raising=False)
    mod = _load_api_module("lumina_api_server_fgh_multi")
    mod.PERSISTENCE = NullPersistenceAdapter()
    mod.BOOTSTRAP_MODE = False
    mod._session_containers.clear()
    mod.PERSISTENCE.load_subject_profile = _load_yaml
    mod.DOMAIN_REGISTRY = DomainRegistry(
        repo_root=_REPO_ROOT,
        registry_path="domain-packs/system/cfg/domain-registry.yaml",
        load_runtime_context_fn=load_runtime_context,
    )
    monkeypatch.setattr(auth, "JWT_SECRET", "test-secret-fgh-multi")
    monkeypatch.setattr("lumina.api.processing.slm_available", lambda: False)
    return mod


@pytest.fixture
def multi_client(multi_api_module):
    return TestClient(multi_api_module.app)


# ═══════════════════════════════════════════════════════════════════════
# Feature F — Magic-circle consent gate
# ═══════════════════════════════════════════════════════════════════════


class TestConsentGate:
    """Feature F: Only user role is blocked without consent; governance roles bypass."""

    @pytest.mark.integration
    def test_user_without_consent_gets_consent_required(self, client: TestClient) -> None:
        """A 'user' role sending a chat message without prior consent acceptance
        receives a consent_required action instead of a normal response."""
        token = _make_token("user")
        resp = client.post(
            "/api/chat",
            json={"message": "solve x + 1 = 3", "deterministic_response": True},
            headers=_auth_header(token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["action"] == "consent_required"
        assert "consent" in body["response"].lower()

    @pytest.mark.integration
    def test_user_with_consent_processes_normally(self, client: TestClient) -> None:
        """After POSTing to /api/consent/accept, the same user can chat normally."""
        token = _make_token("user")
        # First: send a message to create the session
        resp1 = client.post(
            "/api/chat",
            json={"message": "hello", "deterministic_response": True},
            headers=_auth_header(token),
        )
        assert resp1.json()["action"] == "consent_required"
        session_id = resp1.json()["session_id"]

        # Accept consent
        consent_resp = client.post(
            "/api/consent/accept",
            headers=_auth_header(token),
        )
        assert consent_resp.status_code == 200
        assert consent_resp.json()["status"] == "accepted"

        # Now chat should work
        resp2 = client.post(
            "/api/chat",
            json={"message": "solve x + 1 = 3", "deterministic_response": True, "session_id": session_id},
            headers=_auth_header(token),
        )
        assert resp2.status_code == 200
        body = resp2.json()
        assert body["action"] != "consent_required"

    @pytest.mark.integration
    def test_root_bypasses_consent(self, client: TestClient) -> None:
        """Root role should never see consent_required — governance roles bypass."""
        token = _make_token("root")
        resp = client.post(
            "/api/chat",
            json={"message": "hello", "deterministic_response": True},
            headers=_auth_header(token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["action"] != "consent_required"

    @pytest.mark.integration
    def test_domain_authority_bypasses_consent(self, client: TestClient) -> None:
        """domain_authority role should bypass consent gate."""
        token = _make_token("domain_authority")
        resp = client.post(
            "/api/chat",
            json={"message": "hello", "deterministic_response": True},
            headers=_auth_header(token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["action"] != "consent_required"

    @pytest.mark.integration
    def test_consent_persists_across_turns(self, client: TestClient) -> None:
        """Once consent is accepted, subsequent turns in the same session work."""
        token = _make_token("user")
        # Create session
        resp1 = client.post(
            "/api/chat",
            json={"message": "hello", "deterministic_response": True},
            headers=_auth_header(token),
        )
        session_id = resp1.json()["session_id"]
        assert resp1.json()["action"] == "consent_required"

        # Accept consent
        client.post("/api/consent/accept", headers=_auth_header(token))

        # Turn 2
        resp2 = client.post(
            "/api/chat",
            json={"message": "what is 2+2", "deterministic_response": True, "session_id": session_id},
            headers=_auth_header(token),
        )
        assert resp2.json()["action"] != "consent_required"

        # Turn 3
        resp3 = client.post(
            "/api/chat",
            json={"message": "what is 3+3", "deterministic_response": True, "session_id": session_id},
            headers=_auth_header(token),
        )
        assert resp3.json()["action"] != "consent_required"

    @pytest.mark.integration
    def test_consent_accept_endpoint_requires_auth(self, client: TestClient) -> None:
        """The /api/consent/accept endpoint must require authentication."""
        resp = client.post("/api/consent/accept")
        assert resp.status_code == 401


# ═══════════════════════════════════════════════════════════════════════
# Feature G — MUD narrative in deterministic mode
# ═══════════════════════════════════════════════════════════════════════


class TestMUDDeterministic:
    """Feature G: Deterministic responses include MUD narrative when world-sim is active."""

    @pytest.mark.integration
    def test_deterministic_with_mud_has_narrative(self, client: TestClient, api_module) -> None:
        """When MUD state is present on the orchestrator, deterministic mode
        should produce narrative-flavored output (guide_npc, zone, etc.)."""
        # Route to algebra module (MUD features need LearningState dataclass)
        _orig_load_profile = api_module.PERSISTENCE.load_subject_profile
        def _load_with_algebra(path: str) -> dict:
            data = _orig_load_profile(path)
            data["domain_id"] = "domain/edu/algebra-level-1/v1"
            return data
        api_module.PERSISTENCE.load_subject_profile = _load_with_algebra

        token = _make_token("qa")  # bypass consent; qa→student→learning adapters
        # Valid turn data that satisfies domain invariants.
        # Evidence field names must match the check expressions in
        # domain-physics.json, NOT the invariant IDs.  e.g. the
        # "solution_verifies" invariant checks field "substitution_check".
        valid_turn = {
            "correctness": "correct",
            "hint_used": False,
            "response_latency_sec": 10.0,
            "frustration_marker_count": 0,
            "repeated_error": False,
            "off_task_ratio": 0.0,
            "step_count": 1,
            "problem_solved": True,
            "equivalence_preserved": True,
            "substitution_check": True,
            "method_recognized": True,
            "illegal_operations": [],
        }
        resp = client.post(
            "/api/chat",
            json={"message": "hello", "deterministic_response": True, "turn_data_override": valid_turn},
            headers=_auth_header(token),
        )
        assert resp.status_code == 200
        session_id = resp.json()["session_id"]

        # Inject MUD state directly onto the orchestrator
        from lumina.api.session import _session_containers
        container = _session_containers.get(session_id)
        assert container is not None
        orch = container.active_context.orchestrator
        orch.state.world_sim_theme = {"label": "Dark Fantasy"}
        orch.state.mud_world_state = {
            "zone": "Shadow Keep",
            "protagonist": "Scholar",
            "guide_npc": "Merlin",
            "antagonist": "Dark Sorcerer",
            "macguffin": "Arcane Tome",
            "obstacle_theme": "riddle",
            "variable_skin": "arcane",
            "failure_state": "The shadows consume all",
        }

        # Send a deterministic turn — should include narrative
        resp2 = client.post(
            "/api/chat",
            json={
                "message": "solve x + 1 = 3",
                "deterministic_response": True,
                "session_id": session_id,
                "turn_data_override": valid_turn,
            },
            headers=_auth_header(token),
        )
        assert resp2.status_code == 200
        body = resp2.json()
        response_lower = body["response"].lower()
        # Response should contain at least some MUD narrative elements
        assert any(word in response_lower for word in ["merlin", "shadow keep", "scholar", "riddle"]), \
            f"Expected MUD narrative in response, got: {body['response']}"

    @pytest.mark.integration
    def test_deterministic_without_mud_is_flat(self, client: TestClient) -> None:
        """Without MUD state, deterministic mode uses flat templates (backward compat)."""
        token = _make_token("root")
        resp = client.post(
            "/api/chat",
            json={"message": "hello", "deterministic_response": True},
            headers=_auth_header(token),
        )
        assert resp.status_code == 200
        body = resp.json()
        # Should have a normal response, no MUD narrative
        assert body["action"] != "consent_required"
        # The response should be a plain template output
        assert body["response"]  # non-empty


# ═══════════════════════════════════════════════════════════════════════
# Feature H — Physics holodeck mode
# ═══════════════════════════════════════════════════════════════════════


class TestPhysicsHolodeck:
    """Feature H: Holodeck mode returns structured evidence for builders."""

    @pytest.mark.integration
    def test_holodeck_as_root_returns_evidence(self, client: TestClient) -> None:
        """Root user with holodeck=True gets structured evidence in response."""
        token = _make_token("root")
        resp = client.post(
            "/api/chat",
            json={"message": "hello", "deterministic_response": True, "holodeck": True},
            headers=_auth_header(token),
        )
        assert resp.status_code == 200
        body = resp.json()
        sc = body.get("structured_content") or {}
        assert "holodeck" in sc, f"Expected holodeck key in structured_content, got: {list(sc.keys())}"
        holodeck_data = sc["holodeck"]
        assert "state_snapshot" in holodeck_data
        assert "world_sim_active" in holodeck_data

    @pytest.mark.integration
    def test_holodeck_as_user_forbidden(self, client: TestClient) -> None:
        """Regular user cannot use holodeck mode — 403."""
        token = _make_token("user")
        resp = client.post(
            "/api/chat",
            json={"message": "hello", "deterministic_response": True, "holodeck": True},
            headers=_auth_header(token),
        )
        assert resp.status_code == 403

    @pytest.mark.integration
    def test_holodeck_as_domain_authority_returns_evidence(self, client: TestClient) -> None:
        """domain_authority can also use holodeck mode."""
        token = _make_token("domain_authority")
        resp = client.post(
            "/api/chat",
            json={"message": "hello", "deterministic_response": True, "holodeck": True},
            headers=_auth_header(token),
        )
        assert resp.status_code == 200
        body = resp.json()
        sc = body.get("structured_content") or {}
        assert "holodeck" in sc
