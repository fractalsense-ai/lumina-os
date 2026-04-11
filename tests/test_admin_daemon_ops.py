"""Tests for daemon admin operations (admin_daemon.execute).

Covers trigger_daemon_task, daemon_status, review_proposals,
resolve_proposal, and daemon_report operations.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from lumina.api.admin_context import AdminOperationContext
from lumina.api.routes.ops import admin_daemon


def _make_ctx() -> AdminOperationContext:
    """Build a minimal AdminOperationContext with mocked services."""
    return AdminOperationContext(
        persistence=MagicMock(),
        domain_registry=MagicMock(),
        can_govern_domain=MagicMock(return_value=True),
        build_commitment_record=MagicMock(return_value={}),
        map_role_to_actor_role=MagicMock(return_value="root"),
        build_trace_event=MagicMock(return_value={}),
        build_domain_role_assignment=MagicMock(return_value={}),
        build_domain_role_revocation=MagicMock(return_value={}),
        canonical_sha256=MagicMock(return_value="abc123"),
        resolve_user_profile_path=MagicMock(),
        has_domain_capability=MagicMock(return_value=False),
        has_escalation_capability=MagicMock(return_value=False),
    )


def _root_user() -> dict[str, Any]:
    return {"sub": "root-001", "role": "root"}


def _da_user() -> dict[str, Any]:
    return {"sub": "da-001", "role": "domain_authority"}


def _regular_user() -> dict[str, Any]:
    return {"sub": "user-001", "role": "user"}


def _mock_scheduler() -> MagicMock:
    sched = MagicMock()
    sched.trigger_async.return_value = "run-001"
    sched.get_status.return_value = {"active": False, "last_run_id": "run-001"}
    sched.get_report.return_value = {"run_id": "run-001", "tasks": [], "completed": True}
    sched.get_pending_proposals.return_value = [
        {"proposal_id": "prop-1", "type": "physics_edit", "domain_id": "education"}
    ]
    sched.resolve_proposal.return_value = True
    return sched


def _run(coro):
    return asyncio.run(coro)


# ─────────────────────────────────────────────────────────────
# Unknown operations
# ─────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestUnknownOperation:
    def test_unknown_operation_returns_none(self) -> None:
        result = _run(admin_daemon.execute(
            "totally_unknown_op", {}, _root_user(), _make_ctx(),
            get_daemon_scheduler=_mock_scheduler,
        ))
        assert result is None


# ─────────────────────────────────────────────────────────────
# trigger_daemon_task
# ─────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestTriggerDaemonTask:
    def test_root_can_trigger(self) -> None:
        sched = _mock_scheduler()
        result = _run(admin_daemon.execute(
            "trigger_daemon_task", {}, _root_user(), _make_ctx(),
            get_daemon_scheduler=lambda: sched,
        ))
        assert result is not None
        assert result["run_id"] == "run-001"
        assert result["status"] == "started"
        sched.trigger_async.assert_called_once()

    def test_da_can_trigger(self) -> None:
        sched = _mock_scheduler()
        result = _run(admin_daemon.execute(
            "trigger_daemon_task", {}, _da_user(), _make_ctx(),
            get_daemon_scheduler=lambda: sched,
        ))
        assert result is not None
        assert result["run_id"] == "run-001"

    def test_trigger_with_tasks_and_domains(self) -> None:
        sched = _mock_scheduler()
        result = _run(admin_daemon.execute(
            "trigger_daemon_task",
            {"tasks": ["cleanup"], "domain_ids": ["education"]},
            _root_user(),
            _make_ctx(),
            get_daemon_scheduler=lambda: sched,
        ))
        assert result is not None
        call_kwargs = sched.trigger_async.call_args
        assert call_kwargs.kwargs.get("task_names") == ["cleanup"]
        assert call_kwargs.kwargs.get("domain_ids") == ["education"]

    def test_regular_user_forbidden(self) -> None:
        sched = _mock_scheduler()
        with pytest.raises(HTTPException) as exc_info:
            _run(admin_daemon.execute(
                "trigger_daemon_task", {}, _regular_user(), _make_ctx(),
                get_daemon_scheduler=lambda: sched,
            ))
        assert exc_info.value.status_code == 403


# ─────────────────────────────────────────────────────────────
# daemon_status
# ─────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestDaemonStatus:
    def test_returns_status(self) -> None:
        sched = _mock_scheduler()
        result = _run(admin_daemon.execute(
            "daemon_status", {}, _root_user(), _make_ctx(),
            get_daemon_scheduler=lambda: sched,
        ))
        assert result is not None
        assert result["operation"] == "daemon_status"
        assert result["active"] is False
        sched.get_status.assert_called_once()

    def test_any_role_can_view(self) -> None:
        sched = _mock_scheduler()
        result = _run(admin_daemon.execute(
            "daemon_status", {}, _regular_user(), _make_ctx(),
            get_daemon_scheduler=lambda: sched,
        ))
        assert result is not None
        assert "active" in result


# ─────────────────────────────────────────────────────────────
# daemon_report
# ─────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestDaemonReport:
    def test_root_can_get_report(self) -> None:
        sched = _mock_scheduler()
        result = _run(admin_daemon.execute(
            "daemon_report", {"run_id": "run-001"}, _root_user(), _make_ctx(),
            get_daemon_scheduler=lambda: sched,
        ))
        assert result is not None
        assert result["run_id"] == "run-001"
        assert result["operation"] == "daemon_report"

    def test_report_not_found(self) -> None:
        sched = _mock_scheduler()
        sched.get_report.return_value = None
        with pytest.raises(HTTPException) as exc_info:
            _run(admin_daemon.execute(
                "daemon_report", {"run_id": "nonexistent"}, _root_user(), _make_ctx(),
                get_daemon_scheduler=lambda: sched,
            ))
        assert exc_info.value.status_code == 404

    def test_regular_user_forbidden(self) -> None:
        sched = _mock_scheduler()
        with pytest.raises(HTTPException) as exc_info:
            _run(admin_daemon.execute(
                "daemon_report", {"run_id": "run-001"}, _regular_user(), _make_ctx(),
                get_daemon_scheduler=lambda: sched,
            ))
        assert exc_info.value.status_code == 403


# ─────────────────────────────────────────────────────────────
# review_proposals
# ─────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestReviewProposals:
    def test_root_can_list_proposals(self) -> None:
        sched = _mock_scheduler()
        result = _run(admin_daemon.execute(
            "review_proposals", {}, _root_user(), _make_ctx(),
            get_daemon_scheduler=lambda: sched,
        ))
        assert result is not None
        assert result["count"] == 1
        assert result["proposals"][0]["proposal_id"] == "prop-1"

    def test_proposals_with_domain_filter(self) -> None:
        sched = _mock_scheduler()
        result = _run(admin_daemon.execute(
            "review_proposals",
            {"domain_id": "education"},
            _root_user(),
            _make_ctx(),
            get_daemon_scheduler=lambda: sched,
        ))
        assert result is not None
        sched.get_pending_proposals.assert_called_once_with(domain_id="education")


# ─────────────────────────────────────────────────────────────
# resolve_proposal
# ─────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestResolveProposal:
    def test_root_can_approve(self) -> None:
        sched = _mock_scheduler()
        result = _run(admin_daemon.execute(
            "resolve_proposal",
            {"proposal_id": "prop-1", "action": "approved"},
            _root_user(),
            _make_ctx(),
            get_daemon_scheduler=lambda: sched,
        ))
        assert result is not None
        assert result["proposal_id"] == "prop-1"
        assert result["status"] == "approved"

    def test_root_can_reject(self) -> None:
        sched = _mock_scheduler()
        result = _run(admin_daemon.execute(
            "resolve_proposal",
            {"proposal_id": "prop-1", "action": "rejected"},
            _root_user(),
            _make_ctx(),
            get_daemon_scheduler=lambda: sched,
        ))
        assert result is not None
        assert result["status"] == "rejected"

    def test_invalid_action_rejected(self) -> None:
        sched = _mock_scheduler()
        with pytest.raises(HTTPException) as exc_info:
            _run(admin_daemon.execute(
                "resolve_proposal",
                {"proposal_id": "prop-1", "action": "maybe"},
                _root_user(),
                _make_ctx(),
                get_daemon_scheduler=lambda: sched,
            ))
        assert exc_info.value.status_code == 400

    def test_proposal_not_found(self) -> None:
        sched = _mock_scheduler()
        sched.resolve_proposal.return_value = False
        with pytest.raises(HTTPException) as exc_info:
            _run(admin_daemon.execute(
                "resolve_proposal",
                {"proposal_id": "nonexistent", "action": "approved"},
                _root_user(),
                _make_ctx(),
                get_daemon_scheduler=lambda: sched,
            ))
        assert exc_info.value.status_code == 404

    def test_regular_user_forbidden(self) -> None:
        sched = _mock_scheduler()
        with pytest.raises(HTTPException) as exc_info:
            _run(admin_daemon.execute(
                "resolve_proposal",
                {"proposal_id": "prop-1", "action": "approved"},
                _regular_user(),
                _make_ctx(),
                get_daemon_scheduler=lambda: sched,
            ))
        assert exc_info.value.status_code == 403
