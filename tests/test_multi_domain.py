"""Tests for multi-domain runtime routing."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lumina.auth import auth
from lumina.persistence.adapter import NullPersistenceAdapter
from lumina.core.yaml_loader import load_yaml as _load_yaml

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_api_module(module_name: str = "lumina_api_server_multidomain_test"):
    module_path = _REPO_ROOT / "src" / "lumina" / "api" / "server.py"
    spec = importlib.util.spec_from_file_location(module_name, str(module_path))
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load lumina-api-server module")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def multi_domain_module(monkeypatch: pytest.MonkeyPatch):
    """Load API module in multi-domain mode with the domain registry."""
    monkeypatch.setenv("LUMINA_DOMAIN_REGISTRY_PATH", "cfg/domain-registry.yaml")
    # Ensure single-domain var is unset so registry takes precedence
    monkeypatch.delenv("LUMINA_RUNTIME_CONFIG_PATH", raising=False)

    mod = _load_api_module("lumina_api_server_multidomain_test")
    mod.PERSISTENCE = NullPersistenceAdapter()
    mod.BOOTSTRAP_MODE = False
    mod.PERSISTENCE.load_subject_profile = _load_yaml

    monkeypatch.setattr(auth, "JWT_SECRET", "test-secret")
    return mod


@pytest.fixture
def multi_client(multi_domain_module):
    return TestClient(multi_domain_module.app)


# ── Domain catalog ───────────────────────────────────────────


@pytest.mark.integration
def test_domains_endpoint_lists_available_domains(multi_client: TestClient) -> None:
    resp = multi_client.get("/api/domains")
    assert resp.status_code == 200
    domains = resp.json()
    domain_ids = [d["domain_id"] for d in domains]
    assert "education" in domain_ids
    assert "agriculture" in domain_ids


@pytest.mark.integration
def test_domain_info_with_explicit_domain(multi_client: TestClient) -> None:
    resp = multi_client.get("/api/domain-info", params={"domain_id": "education"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["domain_id"]


@pytest.mark.integration
def test_domain_info_invalid_domain_returns_400(multi_client: TestClient) -> None:
    resp = multi_client.get("/api/domain-info", params={"domain_id": "nonexistent"})
    assert resp.status_code == 400


# ── Per-session domain binding ───────────────────────────────


@pytest.mark.integration
def test_chat_with_explicit_domain_id(multi_client: TestClient) -> None:
    resp = multi_client.post(
        "/api/chat",
        json={
            "message": "Hello from education domain",
            "deterministic_response": True,
            "domain_id": "education",
            "turn_data_override": {
                "correctness": "correct",
                "frustration_marker_count": 0,
                "step_count": 1,
                "hint_used": False,
                "repeated_error": False,
                "off_task_ratio": 0.0,
                "response_latency_sec": 5,
            },
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["domain_id"] == "education"


@pytest.mark.integration
def test_chat_uses_default_domain_when_omitted(multi_client: TestClient) -> None:
    resp = multi_client.post(
        "/api/chat",
        json={
            "message": "Hello with no domain specified",
            "deterministic_response": True,
            "turn_data_override": {
                "correctness": "correct",
                "frustration_marker_count": 0,
                "step_count": 1,
                "hint_used": False,
                "repeated_error": False,
                "off_task_ratio": 0.0,
                "response_latency_sec": 5,
            },
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    # default_domain in domain-registry.yaml is "education"
    assert body["domain_id"] == "education"


@pytest.mark.integration
def test_chat_invalid_domain_returns_400(multi_client: TestClient) -> None:
    resp = multi_client.post(
        "/api/chat",
        json={
            "message": "Hello",
            "deterministic_response": True,
            "domain_id": "nonexistent_domain",
        },
    )
    assert resp.status_code == 400
    assert "nonexistent_domain" in resp.text


@pytest.mark.integration
def test_session_domain_switch(multi_client: TestClient) -> None:
    """A session can switch domain_id to a different domain mid-session."""
    # First turn: start in education domain
    resp1 = multi_client.post(
        "/api/chat",
        json={
            "session_id": "domain-switch-test",
            "message": "First turn in education",
            "deterministic_response": True,
            "domain_id": "education",
            "turn_data_override": {
                "correctness": "correct",
                "frustration_marker_count": 0,
                "step_count": 1,
                "hint_used": False,
                "repeated_error": False,
                "off_task_ratio": 0.0,
                "response_latency_sec": 5,
            },
        },
    )
    assert resp1.status_code == 200
    assert resp1.json()["domain_id"] == "education"

    # Second turn: switch to agriculture — should succeed
    resp2 = multi_client.post(
        "/api/chat",
        json={
            "session_id": "domain-switch-test",
            "message": "Switching to agriculture",
            "deterministic_response": True,
            "domain_id": "agriculture",
            "turn_data_override": {
                "within_tolerance": True,
                "response_latency_sec": 5,
                "off_task_ratio": 0.0,
                "step_count": 1,
            },
        },
    )
    assert resp2.status_code == 200
    assert resp2.json()["domain_id"] == "agriculture"

    # Third turn: switch back to education — should resume
    resp3 = multi_client.post(
        "/api/chat",
        json={
            "session_id": "domain-switch-test",
            "message": "Back to education",
            "deterministic_response": True,
            "domain_id": "education",
            "turn_data_override": {
                "correctness": "correct",
                "frustration_marker_count": 0,
                "step_count": 1,
                "hint_used": False,
                "repeated_error": False,
                "off_task_ratio": 0.0,
                "response_latency_sec": 5,
            },
        },
    )
    assert resp3.status_code == 200
    assert resp3.json()["domain_id"] == "education"


@pytest.mark.integration
def test_parallel_sessions_different_domains(multi_client: TestClient) -> None:
    """Two sessions can run concurrently on different domains."""
    edu_resp = multi_client.post(
        "/api/chat",
        json={
            "session_id": "parallel-edu",
            "message": "Education turn",
            "deterministic_response": True,
            "domain_id": "education",
            "turn_data_override": {
                "correctness": "correct",
                "frustration_marker_count": 0,
                "step_count": 1,
                "hint_used": False,
                "repeated_error": False,
                "off_task_ratio": 0.0,
                "response_latency_sec": 5,
            },
        },
    )
    assert edu_resp.status_code == 200
    assert edu_resp.json()["domain_id"] == "education"

    agri_resp = multi_client.post(
        "/api/chat",
        json={
            "session_id": "parallel-agri",
            "message": "Agriculture turn",
            "deterministic_response": True,
            "domain_id": "agriculture",
            "turn_data_override": {
                "within_tolerance": True,
                "response_latency_sec": 5,
                "off_task_ratio": 0.0,
                "step_count": 1,
            },
        },
    )
    assert agri_resp.status_code == 200
    assert agri_resp.json()["domain_id"] == "agriculture"

    # Confirm each session is isolated (second turn still works on own domain)
    edu_resp2 = multi_client.post(
        "/api/chat",
        json={
            "session_id": "parallel-edu",
            "message": "Education turn 2",
            "deterministic_response": True,
            "domain_id": "education",
            "turn_data_override": {
                "correctness": "partial",
                "frustration_marker_count": 0,
                "step_count": 1,
                "hint_used": False,
                "repeated_error": False,
                "off_task_ratio": 0.0,
                "response_latency_sec": 5,
            },
        },
    )
    assert edu_resp2.status_code == 200
    assert edu_resp2.json()["domain_id"] == "education"
