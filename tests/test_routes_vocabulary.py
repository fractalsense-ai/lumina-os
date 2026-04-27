"""Tests for vocabulary route endpoints: metric submission and dashboard growth."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

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
    monkeypatch.setenv("LUMINA_RUNTIME_CONFIG_PATH", "model-packs/education/cfg/runtime-config.yaml")
    monkeypatch.delenv("LUMINA_DOMAIN_REGISTRY_PATH", raising=False)
    mod = _load_api_module()
    mod.DOMAIN_REGISTRY = DomainRegistry(
        repo_root=_REPO_ROOT,
        single_config_path="model-packs/education/cfg/runtime-config.yaml",
        load_runtime_context_fn=load_runtime_context,
    )
    mod.PERSISTENCE = NullPersistenceAdapter()
    mod.BOOTSTRAP_MODE = True
    mod._session_containers.clear()
    mod._STAGED_COMMANDS.clear()
    monkeypatch.setattr(auth, "JWT_SECRET", "test-secret-vocab")
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


# ─────────────────────────────────────────────────────────────
# POST /api/user/{user_id}/vocabulary-metric
# ─────────────────────────────────────────────────────────────


@pytest.mark.integration
class TestPostVocabularyMetric:
    def _post_metric(self, client, token, user_id, **overrides):
        payload = {
            "vocabulary_complexity_score": 0.75,
            "lexical_diversity": 0.6,
            "avg_word_length": 5.2,
            "embedding_spread": 0.8,
            "domain_terms_detected": ["photosynthesis"],
            "buffer_turns": 3,
            "measurement_valid": True,
        }
        payload.update(overrides)
        return client.post(
            f"/api/user/{user_id}/vocabulary-metric",
            json=payload,
            headers=_auth_header(token),
        )

    def test_student_can_submit_own_metric(self, client: TestClient, api_module) -> None:
        _register_root(client)
        user = _register_user(client, "student1")
        user_id = user["user_id"]
        user_token = client.post(
            "/api/auth/login",
            json={"username": "student1", "password": "test-pass-123"},
        ).json()["access_token"]

        # Ensure the profile directory exists for the persistence stub
        profile_path = _REPO_ROOT / "data" / "profiles" / user_id
        profile_path.mkdir(parents=True, exist_ok=True)
        edu_file = profile_path / "education.yaml"
        edu_file.write_text("learning_state: {}\n", encoding="utf-8")

        try:
            resp = self._post_metric(client, user_token, user_id)
            assert resp.status_code == 200
            body = resp.json()
            assert body["status"] == "ok"
            assert body["score"] == 0.75
        finally:
            edu_file.unlink(missing_ok=True)
            profile_path.rmdir()

    def test_root_can_submit_for_other_user(self, client: TestClient, api_module) -> None:
        root_token = _register_root(client)
        user = _register_user(client, "student2")
        user_id = user["user_id"]

        profile_path = _REPO_ROOT / "data" / "profiles" / user_id
        profile_path.mkdir(parents=True, exist_ok=True)
        edu_file = profile_path / "education.yaml"
        edu_file.write_text("learning_state: {}\n", encoding="utf-8")

        try:
            resp = self._post_metric(client, root_token, user_id)
            assert resp.status_code == 200
        finally:
            edu_file.unlink(missing_ok=True)
            profile_path.rmdir()

    def test_user_cannot_submit_for_other_user(self, client: TestClient) -> None:
        _register_root(client)
        user_a = _register_user(client, "alice")
        _register_user(client, "bob")
        alice_token = client.post(
            "/api/auth/login",
            json={"username": "alice", "password": "test-pass-123"},
        ).json()["access_token"]

        resp = self._post_metric(client, alice_token, "some-other-id")
        assert resp.status_code == 403

    def test_profile_not_found(self, client: TestClient) -> None:
        root_token = _register_root(client)
        resp = self._post_metric(client, root_token, "nonexistent-user")
        assert resp.status_code == 404

    def test_unauthenticated_rejected(self, client: TestClient) -> None:
        resp = client.post(
            "/api/user/any/vocabulary-metric",
            json={"vocabulary_complexity_score": 0.5},
        )
        assert resp.status_code == 401

    def test_invalid_score_rejected(self, client: TestClient) -> None:
        root_token = _register_root(client)
        resp = client.post(
            "/api/user/any/vocabulary-metric",
            json={"vocabulary_complexity_score": 2.0},
            headers=_auth_header(root_token),
        )
        assert resp.status_code == 422


# ─────────────────────────────────────────────────────────────
# GET /api/dashboard/education/vocabulary-growth
# ─────────────────────────────────────────────────────────────


@pytest.mark.integration
class TestDashboardVocabularyGrowth:
    def test_root_can_access(self, client: TestClient) -> None:
        root_token = _register_root(client)
        resp = client.get(
            "/api/dashboard/education/vocabulary-growth",
            headers=_auth_header(root_token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "students" in body
        assert "summary" in body

    def test_regular_user_forbidden(self, client: TestClient) -> None:
        _register_root(client)
        _register_user(client, "student3")
        user_token = client.post(
            "/api/auth/login",
            json={"username": "student3", "password": "test-pass-123"},
        ).json()["access_token"]
        resp = client.get(
            "/api/dashboard/education/vocabulary-growth",
            headers=_auth_header(user_token),
        )
        assert resp.status_code == 403

    def test_unauthenticated_rejected(self, client: TestClient) -> None:
        resp = client.get("/api/dashboard/education/vocabulary-growth")
        assert resp.status_code == 401

    def test_empty_profiles_dir(self, client: TestClient) -> None:
        root_token = _register_root(client)
        resp = client.get(
            "/api/dashboard/education/vocabulary-growth",
            headers=_auth_header(root_token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["students"] == []
        assert body["summary"]["total_students_tracked"] == 0
