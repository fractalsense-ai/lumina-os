"""Staging endpoints: create, list, approve, reject staged files."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel

from lumina.api.middleware import _bearer_scheme, get_current_user, require_auth, require_role
from lumina.staging.staging_service import StagingService
from lumina.system_log.commit_guard import requires_log_commit

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/staging", tags=["staging"])

# Module-level service instance (lazily initialised on first use).
_service: StagingService | None = None


def _get_service() -> StagingService:
    global _service
    if _service is None:
        _service = StagingService()
    return _service


# ------------------------------------------------------------------
# Request / response models
# ------------------------------------------------------------------

class StageFileRequest(BaseModel):
    template_id: str
    payload: dict[str, Any]


class ApproveRequest(BaseModel):
    target_overrides: dict[str, str] | None = None


class RejectRequest(BaseModel):
    reason: str = ""


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------

@router.post("/create")
@requires_log_commit
async def create_staged_file(
    body: StageFileRequest,
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
    user: dict[str, Any] | None = Depends(get_current_user),
):
    """Stage a new file for review."""
    user_data = require_auth(user)
    require_role(user_data, "root", "admin")

    svc = _get_service()
    try:
        envelope = svc.stage_file(
            payload=body.payload,
            template_id=body.template_id,
            actor_id=user_data.get("sub", "unknown"),
            actor_role=user_data.get("role", "admin"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return {
        "staged_id": envelope.staged_id,
        "template_id": envelope.template_id,
        "staged_at": envelope.staged_at,
        "log_record_id": envelope.log_record_id,
    }


@router.get("/pending")
async def list_pending(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
    user: dict[str, Any] | None = Depends(get_current_user),
):
    """List all staged files (pending, approved, rejected)."""
    user_data = require_auth(user)
    require_role(user_data, "root", "admin", "operator")

    svc = _get_service()

    # Non-root users see only their own staged files
    actor_filter = None
    if user_data.get("role") not in ("root",):
        actor_filter = user_data.get("sub")

    items = svc.list_staged(actor_id=actor_filter)
    return {
        "count": len(items),
        "staged_files": [e.to_dict() for e in items],
    }


@router.get("/{staged_id}")
async def get_staged_file(
    staged_id: str,
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
    user: dict[str, Any] | None = Depends(get_current_user),
):
    """Retrieve a single staged file envelope."""
    user_data = require_auth(user)
    require_role(user_data, "root", "admin", "operator")

    svc = _get_service()
    envelope = svc.get_staged(staged_id)
    if envelope is None:
        raise HTTPException(status_code=404, detail="Staged file not found")

    return envelope.to_dict()


@router.post("/{staged_id}/approve")
@requires_log_commit
async def approve_staged_file(
    staged_id: str,
    body: ApproveRequest,
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
    user: dict[str, Any] | None = Depends(get_current_user),
):
    """Approve a staged file — writes to final destination."""
    user_data = require_auth(user)
    require_role(user_data, "root", "admin")

    svc = _get_service()
    try:
        final_path = svc.approve_staged(
            staged_id=staged_id,
            approver_id=user_data.get("sub", "unknown"),
            approver_role=user_data.get("role", "admin"),
            target_overrides=body.target_overrides,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return {
        "staged_id": staged_id,
        "approval_status": "approved",
        "final_path": str(final_path),
    }


@router.post("/{staged_id}/reject")
@requires_log_commit
async def reject_staged_file(
    staged_id: str,
    body: RejectRequest,
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
    user: dict[str, Any] | None = Depends(get_current_user),
):
    """Reject a staged file."""
    user_data = require_auth(user)
    require_role(user_data, "root", "admin")

    svc = _get_service()
    try:
        svc.reject_staged(
            staged_id=staged_id,
            approver_id=user_data.get("sub", "unknown"),
            approver_role=user_data.get("role", "admin"),
            reason=body.reason,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return {
        "staged_id": staged_id,
        "approval_status": "rejected",
    }
