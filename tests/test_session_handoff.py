"""Tests for session handoff/resume — HMAC-sealed client-side transcripts."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("LUMINA_JWT_SECRET", "test-secret-for-handoff-012345678901234567890")

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
    monkeypatch.setenv("LUMINA_RUNTIME_CONFIG_PATH", "model-packs/education/cfg/runtime-config.yaml")
    monkeypatch.delenv("LUMINA_DOMAIN_REGISTRY_PATH", raising=False)
    mod = _load_api_module()
    mod.PERSISTENCE = NullPersistenceAdapter()
    mod.BOOTSTRAP_MODE = True
    mod._session_containers.clear()
    monkeypatch.setattr(auth, "JWT_SECRET", "test-secret-handoff")
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


def _register_user(client: TestClient, username: str = "regular") -> dict:
    resp = client.post(
        "/api/auth/register",
        json={"username": username, "password": "test-pass-123", "role": "user"},
    )
    assert resp.status_code == 200
    return resp.json()


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _seed_session(client: TestClient, token: str, session_id: str):
    """Create a session container with ring-buffer content.

    Directly inserts a ``SessionContainer`` into the global store,
    avoiding the full ``/api/chat`` pipeline which may block on LLM.
    Uses ``/api/auth/me`` to resolve the JWT into a user dict so
    the container's ``.user`` matches the owner check in handoff.
    """
    from lumina.api.session import SessionContainer, _session_containers

    me = client.get("/api/auth/me", headers=_auth_header(token)).json()
    user = {"sub": me["user_id"], "role": me.get("role", "user")}

    container = SessionContainer(active_domain_id="_default", user=user)
    container.ring_buffer.push(
        user_message="hello",
        llm_response="Hi there — deterministic stub.",
        turn_number=1,
        domain_id="_default",
    )
    _session_containers[session_id] = container


# ─────────────────────────────────────────────────────────────
# Handoff endpoint
# ─────────────────────────────────────────────────────────────


class TestHandoff:
    def test_handoff_returns_sealed_transcript(self, client, api_module):
        token = _register_root(client)
        me = client.get("/api/auth/me", headers=_auth_header(token)).json()
        session_id = f"user_{me['user_id']}"

        _seed_session(client, token, session_id)


        resp = client.post(
            f"/api/session/{session_id}/handoff",
            headers=_auth_header(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "seal" in data
        assert "transcript" in data
        assert "metadata" in data
        assert "sealed_at_utc" in data
        assert data["session_id"] == session_id
        assert isinstance(data["transcript"], list)
        assert len(data["seal"]) == 64  # hex SHA-256

    def test_handoff_requires_auth(self, client, api_module):
        resp = client.post("/api/session/fake-session/handoff")
        assert resp.status_code in (401, 403)

    def test_handoff_rejects_non_owner(self, client, api_module):
        root_token = _register_root(client)
        me = client.get("/api/auth/me", headers=_auth_header(root_token)).json()
        session_id = f"user_{me['user_id']}"

        _seed_session(client, root_token, session_id)


        # Register a second user
        other = _register_user(client, "other-user")
        other_token = other["access_token"]

        resp = client.post(
            f"/api/session/{session_id}/handoff",
            headers=_auth_header(other_token),
        )
        assert resp.status_code == 403

    def test_handoff_returns_404_for_missing_session(self, client, api_module):
        token = _register_root(client)
        resp = client.post(
            "/api/session/nonexistent/handoff",
            headers=_auth_header(token),
        )
        assert resp.status_code == 404


# ─────────────────────────────────────────────────────────────
# Resume endpoint
# ─────────────────────────────────────────────────────────────


class TestResume:
    def test_resume_accepts_valid_seal(self, client, api_module):
        token = _register_root(client)
        me = client.get("/api/auth/me", headers=_auth_header(token)).json()
        session_id = f"user_{me['user_id']}"

        _seed_session(client, token, session_id)


        # Handoff to get a sealed transcript
        handoff_resp = client.post(
            f"/api/session/{session_id}/handoff",
            headers=_auth_header(token),
        )
        assert handoff_resp.status_code == 200
        handoff = handoff_resp.json()

        # Close the session so ring buffer is cleared
        client.post(
            f"/api/session/{session_id}/close",
            headers=_auth_header(token),
        )

        # Resume with the sealed transcript
        resume_resp = client.post(
            f"/api/session/{session_id}/resume",
            json={
                "transcript": handoff["transcript"],
                "metadata": handoff["metadata"],
                "seal": handoff["seal"],
            },
            headers=_auth_header(token),
        )
        assert resume_resp.status_code == 200
        data = resume_resp.json()
        assert data["status"] == "resumed"
        assert data["turn_count"] == len(handoff["transcript"])

    def test_resume_rejects_tampered_transcript(self, client, api_module):
        token = _register_root(client)
        me = client.get("/api/auth/me", headers=_auth_header(token)).json()
        session_id = f"user_{me['user_id']}"

        _seed_session(client, token, session_id)


        handoff = client.post(
            f"/api/session/{session_id}/handoff",
            headers=_auth_header(token),
        ).json()

        # Tamper with the transcript
        if handoff["transcript"]:
            handoff["transcript"][0]["assistant"] = "TAMPERED RESPONSE"

        resume_resp = client.post(
            f"/api/session/{session_id}/resume",
            json={
                "transcript": handoff["transcript"],
                "metadata": handoff["metadata"],
                "seal": handoff["seal"],
            },
            headers=_auth_header(token),
        )
        assert resume_resp.status_code == 403
        assert "integrity" in resume_resp.json()["detail"].lower()

    def test_resume_rejects_seal_from_different_user(self, client, api_module):
        root_token = _register_root(client)
        me = client.get("/api/auth/me", headers=_auth_header(root_token)).json()
        session_id = f"user_{me['user_id']}"

        _seed_session(client, root_token, session_id)


        handoff = client.post(
            f"/api/session/{session_id}/handoff",
            headers=_auth_header(root_token),
        ).json()

        # Another user tries to resume with root's seal
        other = _register_user(client, "other-user2")
        other_token = other["access_token"]
        other_session = f"user_{other['user_id']}"

        resume_resp = client.post(
            f"/api/session/{other_session}/resume",
            json={
                "transcript": handoff["transcript"],
                "metadata": handoff["metadata"],
                "seal": handoff["seal"],
            },
            headers=_auth_header(other_token),
        )
        assert resume_resp.status_code == 403

    def test_resume_rejects_garbage_seal(self, client, api_module):
        token = _register_root(client)
        me = client.get("/api/auth/me", headers=_auth_header(token)).json()
        session_id = f"user_{me['user_id']}"

        resume_resp = client.post(
            f"/api/session/{session_id}/resume",
            json={
                "transcript": [{"turn": 1, "user": "hi", "assistant": "hey", "ts": 1.0, "domain_id": "d"}],
                "metadata": {"domain_id": "d", "turn_count": 1, "last_activity_utc": 1.0},
                "seal": "0" * 64,
            },
            headers=_auth_header(token),
        )
        assert resume_resp.status_code == 403

    def test_resume_rehydrates_ring_buffer(self, client, api_module):
        """After resume, the session's ring buffer should contain the restored turns."""
        from lumina.api.session import _session_containers

        token = _register_root(client)
        me = client.get("/api/auth/me", headers=_auth_header(token)).json()
        session_id = f"user_{me['user_id']}"

        _seed_session(client, token, session_id)


        handoff = client.post(
            f"/api/session/{session_id}/handoff",
            headers=_auth_header(token),
        ).json()

        # Close then resume
        client.post(f"/api/session/{session_id}/close", headers=_auth_header(token))

        client.post(
            f"/api/session/{session_id}/resume",
            json={
                "transcript": handoff["transcript"],
                "metadata": handoff["metadata"],
                "seal": handoff["seal"],
            },
            headers=_auth_header(token),
        )

        container = _session_containers.get(session_id)
        assert container is not None
        turns = container.ring_buffer.snapshot()
        assert len(turns) == len(handoff["transcript"])
