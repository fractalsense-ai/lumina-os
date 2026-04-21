"""POST /api/holodeck/simulate — physics sandbox for staged changes.

Allows domain authorities and root to run test messages through the full
D.S.A. pipeline using *proposed* physics (from a HITL staged command or
an inline override) without affecting the live system.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from starlette.concurrency import run_in_threadpool

from lumina.api import config as _cfg
from lumina.api.middleware import _bearer_scheme, get_current_user
from lumina.api.models import HolodeckSimulateRequest, HolodeckSimulateResponse
from lumina.api.processing import process_message
from lumina.api.session import _session_containers
from lumina.core.domain_registry import DomainNotFoundError
from lumina.system_log.admin_operations import can_govern_domain

log = logging.getLogger("lumina-api")

router = APIRouter()

_HOLODECK_ROLES = frozenset({"root", "admin"})


def _canonical_hash(obj: dict[str, Any]) -> str:
    payload = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _compute_physics_diff(
    live: dict[str, Any],
    sandbox: dict[str, Any],
) -> dict[str, Any]:
    """Shallow diff: keys added, removed, or changed between live and sandbox."""
    added: dict[str, Any] = {}
    removed: list[str] = []
    changed: dict[str, Any] = {}

    for key in sandbox:
        if key not in live:
            added[key] = sandbox[key]
        elif sandbox[key] != live[key]:
            changed[key] = {"live": live[key], "sandbox": sandbox[key]}

    for key in live:
        if key not in sandbox:
            removed.append(key)

    return {"added": added, "removed": removed, "changed": changed}


def _resolve_staged_physics_updates(staged_id: str) -> dict[str, Any]:
    """Look up a HITL staged command and extract the proposed physics updates.

    Searches both the in-memory admin staged commands and the on-disk
    StagingService envelopes.
    """
    # 1. Check admin staged commands (from /api/admin/command pipeline)
    from lumina.api.routes.admin import _STAGED_COMMANDS, _STAGED_COMMANDS_LOCK

    with _STAGED_COMMANDS_LOCK:
        entry = _STAGED_COMMANDS.get(staged_id)

    if entry is not None:
        if entry.get("resolved"):
            raise HTTPException(
                status_code=409,
                detail=f"Staged command {staged_id} has already been resolved.",
            )
        parsed = entry.get("parsed_command") or {}
        if parsed.get("operation") != "update_domain_physics":
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Staged command {staged_id} is operation "
                    f"'{parsed.get('operation')}', not 'update_domain_physics'."
                ),
            )
        return (parsed.get("params") or {}).get("updates") or {}

    # 2. Check StagingService (on-disk domain-physics envelopes)
    from lumina.staging.staging_service import StagingService

    svc = StagingService(repo_root=_cfg._REPO_ROOT)
    staged_file = svc.get_staged(staged_id)
    if staged_file is not None:
        if staged_file.approval_status != "pending":
            raise HTTPException(
                status_code=409,
                detail=f"Staged file {staged_id} is already {staged_file.approval_status}.",
            )
        if staged_file.template_id != "domain-physics":
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Staged file {staged_id} has template "
                    f"'{staged_file.template_id}', not 'domain-physics'."
                ),
            )
        return staged_file.payload

    raise HTTPException(status_code=404, detail=f"Staged entry not found: {staged_id}")


@router.post("/api/holodeck/simulate", response_model=HolodeckSimulateResponse)
async def holodeck_simulate(
    req: HolodeckSimulateRequest,
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
) -> HolodeckSimulateResponse:
    """Run a test message through the pipeline with proposed physics changes."""

    # ── Auth ──
    user = await get_current_user(credentials)
    if user is None or user.get("role") not in _HOLODECK_ROLES:
        raise HTTPException(
            status_code=403,
            detail="Holodeck simulation is restricted to root and admin roles.",
        )

    # ── Domain authority scope check ──
    if user["role"] == "admin" and not can_govern_domain(user, req.domain_id):
        raise HTTPException(
            status_code=403,
            detail="Not authorized to simulate physics for this domain.",
        )

    # ── Validate: exactly one of staged_id or physics_override ──
    if req.staged_id and req.physics_override:
        raise HTTPException(
            status_code=422,
            detail="Provide either staged_id or physics_override, not both.",
        )
    if not req.staged_id and not req.physics_override:
        raise HTTPException(
            status_code=422,
            detail="Provide staged_id or physics_override.",
        )

    # ── Resolve domain ──
    try:
        resolved_domain_id = _cfg.DOMAIN_REGISTRY.resolve_domain_id(req.domain_id)
    except DomainNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # ── Load live physics ──
    runtime = _cfg.DOMAIN_REGISTRY.get_runtime_context(resolved_domain_id)
    live_physics = runtime.get("domain") or {}

    # ── Build sandbox physics ──
    if req.staged_id:
        updates = await run_in_threadpool(_resolve_staged_physics_updates, req.staged_id)
        sandbox_physics = copy.deepcopy(live_physics)
        for k, v in updates.items():
            sandbox_physics[k] = v
    else:
        sandbox_physics = copy.deepcopy(live_physics)
        for k, v in (req.physics_override or {}).items():
            sandbox_physics[k] = v

    live_hash = _canonical_hash(live_physics)
    sandbox_hash = _canonical_hash(sandbox_physics)
    physics_diff = _compute_physics_diff(live_physics, sandbox_physics)

    # ── Ephemeral sandbox session ──
    sandbox_session_id = f"holodeck-{uuid.uuid4()}"

    try:
        result = await run_in_threadpool(
            process_message,
            sandbox_session_id,
            req.message,
            req.turn_data_override,
            req.deterministic_response,
            resolved_domain_id,
            user,
            None,   # model_id
            None,   # model_version
            True,   # holodeck
            sandbox_physics,
        )
    except DomainNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        # Tear down ephemeral session — no persistence needed
        _session_containers.pop(sandbox_session_id, None)

    return HolodeckSimulateResponse(
        session_id=sandbox_session_id,
        response=result.get("response", ""),
        action=result.get("action", ""),
        prompt_type=result.get("prompt_type", ""),
        escalated=result.get("escalated", False),
        tool_results=result.get("tool_results"),
        domain_id=result.get("domain_id"),
        structured_content=result.get("structured_content"),
        sandbox_physics=sandbox_physics,
        physics_diff=physics_diff,
        live_physics_hash=live_hash,
        sandbox_physics_hash=sandbox_hash,
        staged_id=req.staged_id,
    )
