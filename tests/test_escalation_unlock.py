"""Tests for the education escalation-unlock feature set (Phase 3).

Covers:
  - Unit tests for ``lumina.core.session_unlock`` PIN OTP functions.
  - Integration tests for ``POST /api/escalations/{id}/resolve`` with
    ``generate_pin=True`` / ``intervention_notes``.
  - Integration tests for ``POST /api/sessions/{id}/unlock`` (OTP endpoint).
  - Integration tests for the frozen-session gate in ``process_message()``.
"""

from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from lumina.auth import auth
from lumina.core import session_unlock as _su
from lumina.persistence.adapter import NullPersistenceAdapter
from lumina.core.yaml_loader import load_yaml as _load_yaml

_REPO_ROOT = Path(__file__).resolve().parents[1]


# ─────────────────────────────────────────────────────────────
# Module loader helpers
# ─────────────────────────────────────────────────────────────

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


@pytest.fixture(autouse=True)
def clear_pin_store():
    """Ensure the in-memory PIN store is empty before and after each test."""
    _su._UNLOCK_PINS.clear()
    yield
    _su._UNLOCK_PINS.clear()


@pytest.fixture
def api_module(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LUMINA_RUNTIME_CONFIG_PATH", "domain-packs/education/cfg/runtime-config.yaml")
    monkeypatch.delenv("LUMINA_DOMAIN_REGISTRY_PATH", raising=False)
    mod = _load_api_module()
    mod.PERSISTENCE = NullPersistenceAdapter()
    mod.BOOTSTRAP_MODE = True
    mod._session_containers.clear()
    monkeypatch.setattr(auth, "JWT_SECRET", "test-secret-unlock")
    mod.PERSISTENCE.load_subject_profile = _load_yaml
    return mod


@pytest.fixture
def client(api_module) -> TestClient:
    return TestClient(api_module.app)


# ─────────────────────────────────────────────────────────────
# Auth helpers
# ─────────────────────────────────────────────────────────────

def _register_root(client: TestClient) -> str:
    resp = client.post(
        "/api/auth/register",
        json={"username": "root-u", "password": "pass-123", "role": "user"},
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]


def _register_student(client: TestClient) -> dict[str, Any]:
    resp = client.post(
        "/api/auth/register",
        json={"username": "student-u", "password": "pass-123", "role": "user"},
    )
    assert resp.status_code == 200
    return resp.json()


def _login(client: TestClient, username: str) -> str:
    resp = client.post(
        "/api/auth/login",
        json={"username": username, "password": "pass-123"},
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ─────────────────────────────────────────────────────────────
# Fake escalation record helper
# ─────────────────────────────────────────────────────────────

def _make_esc_record(
    record_id: str = "esc-test-001",
    session_id: str = "session-abc",
    actor_id: str = "student-123",
    domain_pack_id: str = "education",
) -> dict[str, Any]:
    return {
        "record_type": "EscalationRecord",
        "record_id": record_id,
        "session_id": session_id,
        "actor_id": actor_id,
        "actor_role": "subject",
        "status": "open",
        "trigger": "frustration_threshold",
        "domain_pack_id": domain_pack_id,
        "target_role": "admin",
    }


def _inject_escalation(mod, record: dict[str, Any]) -> None:
    """Monkeypatch NullPersistenceAdapter to return *record* from query_escalations."""
    mod.PERSISTENCE.query_escalations = lambda *a, **kw: [record]


# ─────────────────────────────────────────────────────────────
# § 1 — Unit tests: session_unlock module
# ─────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestSessionUnlockCore:
    def test_generate_returns_six_digit_string(self) -> None:
        pin = _su.generate_unlock_pin("sess-1", "esc-1")
        assert len(pin) == 6
        assert pin.isdigit()

    def test_generate_zero_padded(self) -> None:
        # Run enough times to confirm we never get a non-padded string
        pins = {_su.generate_unlock_pin("sess-pad", "esc-1") for _ in range(20)}
        _su._UNLOCK_PINS.clear()  # clean up extras
        for p in pins:
            assert len(p) == 6, f"PIN {p!r} is not 6 chars"

    def test_valid_pin_returns_true_and_removes_entry(self) -> None:
        pin = _su.generate_unlock_pin("sess-2", "esc-2")
        assert _su.validate_unlock_pin("sess-2", pin) is True
        assert "sess-2" not in _su._UNLOCK_PINS

    def test_wrong_pin_returns_false_and_keeps_entry(self) -> None:
        pin = _su.generate_unlock_pin("sess-3", "esc-3")
        bad_pin = "000000" if pin != "000000" else "111111"
        assert _su.validate_unlock_pin("sess-3", bad_pin) is False
        assert "sess-3" in _su._UNLOCK_PINS

    def test_unknown_session_returns_false(self) -> None:
        assert _su.validate_unlock_pin("no-such-session", "123456") is False

    def test_has_pending_pin_true_before_validation(self) -> None:
        _su.generate_unlock_pin("sess-5", "esc-5")
        assert _su.has_pending_pin("sess-5") is True

    def test_has_pending_pin_false_after_correct_validation(self) -> None:
        pin = _su.generate_unlock_pin("sess-6", "esc-6")
        _su.validate_unlock_pin("sess-6", pin)
        assert _su.has_pending_pin("sess-6") is False

    def test_has_pending_pin_false_before_any_generate(self) -> None:
        assert _su.has_pending_pin("sess-never") is False

    def test_expired_pin_returns_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        pin = _su.generate_unlock_pin("sess-exp", "esc-exp")
        # Force TTL to appear elapsed by moving "now" far into the future
        future = time.time() + 99999
        monkeypatch.setattr("lumina.core.session_unlock.time.time", lambda: future)
        assert _su.validate_unlock_pin("sess-exp", pin) is False

    def test_expired_pin_purged_from_store(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _su.generate_unlock_pin("sess-purge", "esc-purge")
        future = time.time() + 99999
        monkeypatch.setattr("lumina.core.session_unlock.time.time", lambda: future)
        _su.has_pending_pin("sess-purge")  # triggers _purge_expired
        assert "sess-purge" not in _su._UNLOCK_PINS

    def test_second_generate_overwrites_first_pin(self) -> None:
        _su.generate_unlock_pin("sess-ow", "esc-1")
        pin2 = _su.generate_unlock_pin("sess-ow", "esc-2")
        # Only the second PIN is valid now
        assert _su.validate_unlock_pin("sess-ow", pin2) is True


# ─────────────────────────────────────────────────────────────
# § 2 — Integration: resolve escalation with generate_pin
# ─────────────────────────────────────────────────────────────


@pytest.mark.integration
class TestResolveEscalationWithPin:
    def test_generate_pin_true_returns_unlock_pin(
        self, client: TestClient, api_module
    ) -> None:
        root_token = _register_root(client)
        esc = _make_esc_record()
        _inject_escalation(api_module, esc)
        resp = client.post(
            f"/api/escalations/{esc['record_id']}/resolve",
            json={"decision": "approve", "reasoning": "Teacher reviewed.", "generate_pin": True},
            headers=_auth(root_token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "unlock_pin" in body
        assert len(body["unlock_pin"]) == 6
        assert body["unlock_pin"].isdigit()

    def test_generate_pin_false_no_unlock_pin_in_body(
        self, client: TestClient, api_module
    ) -> None:
        root_token = _register_root(client)
        esc = _make_esc_record()
        _inject_escalation(api_module, esc)
        resp = client.post(
            f"/api/escalations/{esc['record_id']}/resolve",
            json={"decision": "reject", "reasoning": "Not now.", "generate_pin": False},
            headers=_auth(root_token),
        )
        assert resp.status_code == 200
        assert "unlock_pin" not in resp.json()

    def test_generate_pin_freezes_session_container(
        self, client: TestClient, api_module
    ) -> None:
        from lumina.api.session import SessionContainer, _session_containers
        root_token = _register_root(client)
        esc = _make_esc_record(session_id="sess-to-freeze")
        _inject_escalation(api_module, esc)

        # Pre-create a container for the session so we can check frozen state
        container = SessionContainer(active_domain_id="education")
        _session_containers["sess-to-freeze"] = container

        client.post(
            f"/api/escalations/{esc['record_id']}/resolve",
            json={"decision": "defer", "reasoning": "Pending.", "generate_pin": True},
            headers=_auth(root_token),
        )
        assert container.frozen is True

    def test_resolve_stores_pin_in_unlock_pins(
        self, client: TestClient, api_module
    ) -> None:
        root_token = _register_root(client)
        esc = _make_esc_record(session_id="sess-pin-store")
        _inject_escalation(api_module, esc)
        resp = client.post(
            f"/api/escalations/{esc['record_id']}/resolve",
            json={"decision": "approve", "reasoning": "ok", "generate_pin": True},
            headers=_auth(root_token),
        )
        assert resp.status_code == 200
        assert _su.has_pending_pin("sess-pin-store") is True
        pin_from_body = resp.json()["unlock_pin"]
        assert _su.validate_unlock_pin("sess-pin-store", pin_from_body) is True

    def test_intervention_notes_does_not_crash_when_session_not_in_memory(
        self, client: TestClient, api_module
    ) -> None:
        """Resolve with intervention_notes when session is not in memory should succeed."""
        root_token = _register_root(client)
        esc = _make_esc_record(session_id="sess-absent")
        _inject_escalation(api_module, esc)
        resp = client.post(
            f"/api/escalations/{esc['record_id']}/resolve",
            json={
                "decision": "approve",
                "reasoning": "Teacher helped.",
                "intervention_notes": "Worked on multiplication table with student.",
            },
            headers=_auth(root_token),
        )
        assert resp.status_code == 200
        assert resp.json()["decision"] == "approve"

    def test_escalation_not_found_returns_404(
        self, client: TestClient, api_module
    ) -> None:
        root_token = _register_root(client)
        resp = client.post(
            "/api/escalations/nonexistent-esc/resolve",
            json={"decision": "approve", "reasoning": "ok"},
            headers=_auth(root_token),
        )
        assert resp.status_code == 404

    def test_unauthenticated_resolve_returns_401(
        self, client: TestClient, api_module
    ) -> None:
        resp = client.post(
            "/api/escalations/esc-123/resolve",
            json={"decision": "approve", "reasoning": "ok"},
        )
        assert resp.status_code == 401

    def test_invalid_decision_returns_400(
        self, client: TestClient, api_module
    ) -> None:
        root_token = _register_root(client)
        esc = _make_esc_record()
        _inject_escalation(api_module, esc)
        resp = client.post(
            f"/api/escalations/{esc['record_id']}/resolve",
            json={"decision": "maybe", "reasoning": "dunno"},
            headers=_auth(root_token),
        )
        assert resp.status_code == 400


# ─────────────────────────────────────────────────────────────
# § 3 — Integration: POST /api/sessions/{id}/unlock
# ─────────────────────────────────────────────────────────────


@pytest.mark.integration
class TestSessionUnlockEndpoint:
    def _setup_frozen_session(
        self,
        client: TestClient,
        api_module,
        root_token: str,
    ) -> tuple[str, str]:
        """Create a frozen session with a live PIN; return (session_id, pin)."""
        from lumina.api.session import SessionContainer, _session_containers
        esc = _make_esc_record(session_id="sess-unlock-ep")
        _inject_escalation(api_module, esc)

        container = SessionContainer(active_domain_id="education")
        _session_containers["sess-unlock-ep"] = container

        resp = client.post(
            f"/api/escalations/{esc['record_id']}/resolve",
            json={"decision": "approve", "reasoning": "ok", "generate_pin": True},
            headers=_auth(root_token),
        )
        assert resp.status_code == 200
        pin = resp.json()["unlock_pin"]
        return "sess-unlock-ep", pin

    def test_correct_pin_returns_200_unlocked(
        self, client: TestClient, api_module
    ) -> None:
        root_token = _register_root(client)          # first → auto-promoted to root
        _register_student(client)                     # second → stays "user"
        student_token = _login(client, "student-u")
        session_id, pin = self._setup_frozen_session(client, api_module, root_token)
        resp = client.post(
            f"/api/sessions/{session_id}/unlock",
            json={"pin": pin},
            headers=_auth(student_token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["unlocked"] is True
        assert body["session_id"] == session_id

    def test_wrong_pin_returns_403(
        self, client: TestClient, api_module
    ) -> None:
        root_token = _register_root(client)
        _register_student(client)
        student_token = _login(client, "student-u")
        session_id, pin = self._setup_frozen_session(client, api_module, root_token)
        bad_pin = "000000" if pin != "000000" else "111111"
        resp = client.post(
            f"/api/sessions/{session_id}/unlock",
            json={"pin": bad_pin},
            headers=_auth(student_token),
        )
        assert resp.status_code == 403

    def test_session_container_unfrozen_after_correct_pin(
        self, client: TestClient, api_module
    ) -> None:
        from lumina.api.session import _session_containers
        root_token = _register_root(client)
        _register_student(client)
        student_token = _login(client, "student-u")
        session_id, pin = self._setup_frozen_session(client, api_module, root_token)
        assert _session_containers[session_id].frozen is True
        client.post(
            f"/api/sessions/{session_id}/unlock",
            json={"pin": pin},
            headers=_auth(student_token),
        )
        assert _session_containers[session_id].frozen is False

    def test_wrong_pin_leaves_session_frozen(
        self, client: TestClient, api_module
    ) -> None:
        from lumina.api.session import _session_containers
        root_token = _register_root(client)
        _register_student(client)
        student_token = _login(client, "student-u")
        session_id, pin = self._setup_frozen_session(client, api_module, root_token)
        bad_pin = "000000" if pin != "000000" else "111111"
        client.post(
            f"/api/sessions/{session_id}/unlock",
            json={"pin": bad_pin},
            headers=_auth(student_token),
        )
        assert _session_containers[session_id].frozen is True

    def test_unauthenticated_unlock_returns_401(
        self, client: TestClient, api_module
    ) -> None:
        resp = client.post(
            "/api/sessions/some-session/unlock",
            json={"pin": "123456"},
        )
        assert resp.status_code == 401


# ─────────────────────────────────────────────────────────────
# § 4 — Integration: frozen-session gate in process_message()
# ─────────────────────────────────────────────────────────────


_CHAT_TURN_OVERRIDE = {
    "correctness": "correct",
    "frustration_marker_count": 0,
    "step_count": 2,
    "hint_used": False,
    "repeated_error": False,
    "off_task_ratio": 0.0,
    "response_latency_sec": 5,
}


@pytest.mark.integration
class TestFrozenSessionChatFlow:
    """Verify the frozen-session gate blocks processing and honours PIN unlock."""

    def _create_live_session(
        self, client: TestClient, session_id: str = "sess-freeze-chat"
    ) -> None:
        """Create a real session by sending one deterministic chat message."""
        resp = client.post(
            "/api/chat",
            json={
                "session_id": session_id,
                "message": "I checked by substitution.",
                "deterministic_response": True,
                "turn_data_override": _CHAT_TURN_OVERRIDE,
            },
        )
        assert resp.status_code == 200

    def test_frozen_session_blocks_normal_input(
        self, client: TestClient, api_module
    ) -> None:
        sid = "sess-freeze-block"
        self._create_live_session(client, sid)
        api_module._session_containers[sid].frozen = True

        resp = client.post(
            "/api/chat",
            json={
                "session_id": sid,
                "message": "hello there",
                "deterministic_response": True,
                "turn_data_override": _CHAT_TURN_OVERRIDE,
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["action"] == "session_frozen"
        assert body["escalated"] is True

    def test_frozen_session_random_digits_do_not_unlock(
        self, client: TestClient, api_module
    ) -> None:
        sid = "sess-freeze-wrongpin"
        self._create_live_session(client, sid)
        api_module._session_containers[sid].frozen = True

        resp = client.post(
            "/api/chat",
            json={
                "session_id": sid,
                "message": "999999",  # valid 6-digit format but no matching PIN stored
                "deterministic_response": True,
                "turn_data_override": _CHAT_TURN_OVERRIDE,
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["action"] == "session_frozen"

    def test_correct_pin_in_chat_unfreezes_and_returns_unlocked(
        self, client: TestClient, api_module
    ) -> None:
        sid = "sess-freeze-unlock-chat"
        self._create_live_session(client, sid)
        api_module._session_containers[sid].frozen = True

        # Generate a PIN for this session directly via the module
        pin = _su.generate_unlock_pin(sid, "esc-chat-test")

        resp = client.post(
            "/api/chat",
            json={
                "session_id": sid,
                "message": pin,
                "deterministic_response": True,
                "turn_data_override": _CHAT_TURN_OVERRIDE,
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["action"] == "session_unlocked"
        assert body["escalated"] is False

    def test_session_container_unfrozen_after_pin_in_chat(
        self, client: TestClient, api_module
    ) -> None:
        sid = "sess-freeze-container"
        self._create_live_session(client, sid)
        api_module._session_containers[sid].frozen = True
        pin = _su.generate_unlock_pin(sid, "esc-container-check")

        client.post(
            "/api/chat",
            json={
                "session_id": sid,
                "message": pin,
                "deterministic_response": True,
                "turn_data_override": _CHAT_TURN_OVERRIDE,
            },
        )
        assert api_module._session_containers[sid].frozen is False

    def test_non_frozen_session_processes_normally(
        self, client: TestClient
    ) -> None:
        resp = client.post(
            "/api/chat",
            json={
                "message": "I checked by substitution.",
                "deterministic_response": True,
                "turn_data_override": _CHAT_TURN_OVERRIDE,
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["action"] not in ("session_frozen", "session_unlocked")
