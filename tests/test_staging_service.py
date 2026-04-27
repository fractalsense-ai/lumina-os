"""Tests for StagingService — stage / list / approve / reject lifecycle."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from lumina.staging.staging_service import StagedFile, StagingService


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------

_PHYSICS_PAYLOAD: dict[str, Any] = {
    "id": "domain/test/demo/v1",
    "version": "1.0.0",
    "admin": {"name": "Test", "role": "admin", "pseudonymous_id": "da-1"},
    "meta_authority_id": "ma-1",
    "invariants": [],
    "standing_orders": [],
    "escalation_triggers": [],
    "artifacts": [],
}

_HINT_PAYLOAD: dict[str, Any] = {
    "hint_id": "hint-001",
    "domain_id": "domain/test/v1",
    "content": "Glossary reminder: variable ≠ constant.",
}


@pytest.fixture()
def svc(tmp_path: Path) -> StagingService:
    staging = tmp_path / "staging"
    return StagingService(staging_dir=staging, repo_root=tmp_path)


# ------------------------------------------------------------------
# Stage
# ------------------------------------------------------------------

class TestStageFile:
    def test_creates_envelope_json(self, svc: StagingService, tmp_path: Path):
        env = svc.stage_file(_PHYSICS_PAYLOAD, "domain-physics", "actor-1")
        path = tmp_path / "staging" / f"{env.staged_id}.json"
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["template_id"] == "domain-physics"
        assert data["approval_status"] == "pending"

    def test_returns_staged_file(self, svc: StagingService):
        env = svc.stage_file(_PHYSICS_PAYLOAD, "domain-physics", "actor-1")
        assert isinstance(env, StagedFile)
        assert env.staged_id
        assert env.approval_status == "pending"
        assert env.log_record_id  # System Log record was created

    def test_unknown_template_raises(self, svc: StagingService):
        with pytest.raises(ValueError, match="Unknown template_id"):
            svc.stage_file({}, "nonexistent", "actor-1")

    def test_missing_fields_raises(self, svc: StagingService):
        with pytest.raises(ValueError, match="missing required fields"):
            svc.stage_file({"id": "x"}, "domain-physics", "actor-1")

    def test_multiple_stages(self, svc: StagingService):
        e1 = svc.stage_file(_PHYSICS_PAYLOAD, "domain-physics", "actor-1")
        e2 = svc.stage_file(_HINT_PAYLOAD, "context-hint", "actor-2")
        assert e1.staged_id != e2.staged_id


# ------------------------------------------------------------------
# List / Get
# ------------------------------------------------------------------

class TestListAndGet:
    def test_list_empty(self, svc: StagingService):
        assert svc.list_staged() == []

    def test_list_returns_all(self, svc: StagingService):
        svc.stage_file(_PHYSICS_PAYLOAD, "domain-physics", "actor-1")
        svc.stage_file(_HINT_PAYLOAD, "context-hint", "actor-2")
        items = svc.list_staged()
        assert len(items) == 2

    def test_list_filters_by_actor(self, svc: StagingService):
        svc.stage_file(_PHYSICS_PAYLOAD, "domain-physics", "actor-1")
        svc.stage_file(_HINT_PAYLOAD, "context-hint", "actor-2")
        items = svc.list_staged(actor_id="actor-1")
        assert len(items) == 1
        assert items[0].actor_id == "actor-1"

    def test_get_staged(self, svc: StagingService):
        env = svc.stage_file(_PHYSICS_PAYLOAD, "domain-physics", "actor-1")
        loaded = svc.get_staged(env.staged_id)
        assert loaded is not None
        assert loaded.staged_id == env.staged_id

    def test_get_nonexistent(self, svc: StagingService):
        assert svc.get_staged("no-such-id") is None


# ------------------------------------------------------------------
# Approve
# ------------------------------------------------------------------

class TestApprove:
    def test_writes_file_to_target(self, svc: StagingService, tmp_path: Path):
        env = svc.stage_file(_PHYSICS_PAYLOAD, "domain-physics", "actor-1")
        final = svc.approve_staged(
            env.staged_id, "approver-1",
            target_overrides={"domain_short": "test"},
        )
        assert final.exists()
        data = json.loads(final.read_text(encoding="utf-8"))
        assert data["id"] == "domain/test/demo/v1"

    def test_updates_envelope_status(self, svc: StagingService):
        env = svc.stage_file(_PHYSICS_PAYLOAD, "domain-physics", "actor-1")
        svc.approve_staged(env.staged_id, "approver-1",
                           target_overrides={"domain_short": "test"})
        loaded = svc.get_staged(env.staged_id)
        assert loaded is not None
        assert loaded.approval_status == "approved"
        assert loaded.approver_id == "approver-1"
        assert loaded.final_path is not None
        assert loaded.resolved_at is not None

    def test_approve_nonexistent_raises(self, svc: StagingService):
        with pytest.raises(ValueError, match="not found"):
            svc.approve_staged("no-such-id", "approver-1")

    def test_approve_already_approved_raises(self, svc: StagingService):
        env = svc.stage_file(_PHYSICS_PAYLOAD, "domain-physics", "actor-1")
        svc.approve_staged(env.staged_id, "approver-1",
                           target_overrides={"domain_short": "test"})
        with pytest.raises(ValueError, match="already resolved"):
            svc.approve_staged(env.staged_id, "approver-1",
                               target_overrides={"domain_short": "test"})

    def test_context_hint_approve(self, svc: StagingService, tmp_path: Path):
        env = svc.stage_file(_HINT_PAYLOAD, "context-hint", "actor-1")
        final = svc.approve_staged(
            env.staged_id, "approver-1",
            target_overrides={"domain_short": "test"},
        )
        assert final.exists()
        data = json.loads(final.read_text(encoding="utf-8"))
        assert data["content"] == "Glossary reminder: variable ≠ constant."
        assert data["source_task"] == "context_crawler"


# ------------------------------------------------------------------
# Reject
# ------------------------------------------------------------------

class TestReject:
    def test_marks_rejected(self, svc: StagingService):
        env = svc.stage_file(_PHYSICS_PAYLOAD, "domain-physics", "actor-1")
        svc.reject_staged(env.staged_id, "approver-1", reason="Bad data")
        loaded = svc.get_staged(env.staged_id)
        assert loaded is not None
        assert loaded.approval_status == "rejected"
        assert loaded.approver_id == "approver-1"

    def test_reject_nonexistent_raises(self, svc: StagingService):
        with pytest.raises(ValueError, match="not found"):
            svc.reject_staged("no-such-id", "approver-1")

    def test_reject_already_rejected_raises(self, svc: StagingService):
        env = svc.stage_file(_PHYSICS_PAYLOAD, "domain-physics", "actor-1")
        svc.reject_staged(env.staged_id, "approver-1")
        with pytest.raises(ValueError, match="already resolved"):
            svc.reject_staged(env.staged_id, "approver-1")

    def test_no_file_written_on_reject(self, svc: StagingService, tmp_path: Path):
        env = svc.stage_file(_PHYSICS_PAYLOAD, "domain-physics", "actor-1")
        svc.reject_staged(env.staged_id, "approver-1")
        # No model-packs dir created under repo root
        assert not (tmp_path / "model-packs").exists()


# ------------------------------------------------------------------
# StagedFile.to_dict
# ------------------------------------------------------------------

class TestStagedFileModel:
    def test_to_dict_roundtrip(self, svc: StagingService):
        env = svc.stage_file(_PHYSICS_PAYLOAD, "domain-physics", "actor-1")
        d = env.to_dict()
        assert d["staged_id"] == env.staged_id
        assert isinstance(d["payload"], dict)
        assert d["approval_status"] == "pending"


# ------------------------------------------------------------------
# System Log records
# ------------------------------------------------------------------

class TestCTLIntegration:
    def test_stage_creates_ctl_record(self, svc: StagingService):
        env = svc.stage_file(_PHYSICS_PAYLOAD, "domain-physics", "actor-1")
        assert env.log_record_id is not None

    def test_approve_creates_ctl_record(self, svc: StagingService):
        env = svc.stage_file(_PHYSICS_PAYLOAD, "domain-physics", "actor-1")
        svc.approve_staged(env.staged_id, "approver-1",
                           target_overrides={"domain_short": "test"})
        loaded = svc.get_staged(env.staged_id)
        assert loaded is not None
        # The log_record_id gets updated to the approval record
        assert loaded.log_record_id is not None

    def test_reject_creates_ctl_record(self, svc: StagingService):
        env = svc.stage_file(_PHYSICS_PAYLOAD, "domain-physics", "actor-1")
        svc.reject_staged(env.staged_id, "approver-1", reason="test")
        loaded = svc.get_staged(env.staged_id)
        assert loaded is not None
        assert loaded.log_record_id is not None
