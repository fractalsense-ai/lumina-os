"""Domain pack lifecycle endpoints and session close."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from starlette.concurrency import run_in_threadpool

from lumina.api import config as _cfg
from lumina.api.middleware import _bearer_scheme, get_current_user, require_auth
from lumina.api.models import DomainCommitRequest, DomainPhysicsUpdateRequest, SessionResumeRequest
from lumina.api.session import _close_session, _persist_session_container, _session_containers
from lumina.core.domain_registry import DomainNotFoundError
from lumina.system_log.admin_operations import (
    _canonical_sha256 as admin_canonical_sha256,
    build_commitment_record,
    can_govern_domain,
    map_role_to_actor_role,
)
from lumina.system_log.commit_guard import requires_log_commit

log = logging.getLogger("lumina-api")

router = APIRouter()


@router.post("/api/domain-pack/commit")
@requires_log_commit
async def domain_pack_commit(
    req: DomainCommitRequest,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict[str, Any]:
    current = await get_current_user(credentials)
    user_data = require_auth(current)

    if user_data["role"] not in ("root", "admin"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    if user_data["role"] == "admin" and not can_govern_domain(user_data, req.domain_id):
        raise HTTPException(status_code=403, detail="Not authorized for this domain")

    try:
        resolved = _cfg.DOMAIN_REGISTRY.resolve_domain_id(req.domain_id)
    except DomainNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    runtime = _cfg.DOMAIN_REGISTRY.get_runtime_context(resolved)
    domain_physics_path = runtime["domain_physics_path"]
    domain = await run_in_threadpool(_cfg.PERSISTENCE.load_domain_physics, str(domain_physics_path))

    subject_hash = admin_canonical_sha256(domain)
    subject_version = str(domain.get("version", ""))
    subject_id = str(domain.get("id", resolved))

    record = build_commitment_record(
        actor_id=req.actor_id or user_data["sub"],
        actor_role=map_role_to_actor_role(user_data["role"]),
        commitment_type="domain_pack_activation",
        subject_id=subject_id,
        summary=req.summary or f"Domain pack activation: {resolved}",
        subject_version=subject_version,
        subject_hash=subject_hash,
    )

    _cfg.PERSISTENCE.append_log_record(
        "admin", record,
        ledger_path=_cfg.PERSISTENCE.get_domain_ledger_path(resolved),
    )

    return {
        "record_id": record["record_id"],
        "subject_hash": subject_hash,
        "subject_version": subject_version,
        "commitment_type": "domain_pack_activation",
    }


@router.get("/api/domain-pack/{domain_id}/history")
async def domain_pack_history(
    domain_id: str,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> list[dict[str, Any]]:
    current = await get_current_user(credentials)
    user_data = require_auth(current)

    allowed_roles = ("root", "operator", "half_operator")
    if user_data["role"] not in allowed_roles:
        if user_data["role"] == "admin" and can_govern_domain(user_data, domain_id):
            pass
        else:
            raise HTTPException(status_code=403, detail="Insufficient permissions")

    records = await run_in_threadpool(_cfg.PERSISTENCE.query_commitments, domain_id)
    return [
        {
            "record_id": r.get("record_id"),
            "commitment_type": r.get("commitment_type"),
            "timestamp": r.get("timestamp_utc"),
            "subject_version": r.get("subject_version"),
            "subject_hash": r.get("subject_hash"),
            "summary": r.get("summary"),
        }
        for r in records
    ]


@router.patch("/api/domain-pack/{domain_id}/physics")
@requires_log_commit
async def update_domain_physics(
    domain_id: str,
    req: DomainPhysicsUpdateRequest,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict[str, Any]:
    current = await get_current_user(credentials)
    user_data = require_auth(current)

    if user_data["role"] not in ("root", "admin"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    if user_data["role"] == "admin" and not can_govern_domain(user_data, domain_id):
        raise HTTPException(status_code=403, detail="Not authorized for this domain")

    try:
        resolved = _cfg.DOMAIN_REGISTRY.resolve_domain_id(domain_id)
    except DomainNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    runtime = _cfg.DOMAIN_REGISTRY.get_runtime_context(resolved)
    domain_physics_path = Path(runtime["domain_physics_path"])

    domain = await run_in_threadpool(_cfg.PERSISTENCE.load_domain_physics, str(domain_physics_path))
    for key, value in req.updates.items():
        domain[key] = value

    def _write_physics() -> None:
        tmp = domain_physics_path.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(domain, fh, indent=2, ensure_ascii=False)
        tmp.replace(domain_physics_path)

    await run_in_threadpool(_write_physics)

    subject_hash = admin_canonical_sha256(domain)
    subject_id = str(domain.get("id", resolved))

    record = build_commitment_record(
        actor_id=user_data["sub"],
        actor_role=map_role_to_actor_role(user_data["role"]),
        commitment_type="domain_pack_activation",
        subject_id=subject_id,
        summary=req.summary,
        subject_version=str(domain.get("version", "")),
        subject_hash=subject_hash,
        metadata={"updated_fields": list(req.updates.keys())},
    )
    _cfg.PERSISTENCE.append_log_record(
        "admin", record,
        ledger_path=_cfg.PERSISTENCE.get_domain_ledger_path(resolved),
    )

    return {
        "subject_hash": subject_hash,
        "updated_fields": list(req.updates.keys()),
        "record_id": record["record_id"],
    }


@router.post("/api/session/{session_id}/close", status_code=200)
@requires_log_commit
async def close_session(
    session_id: str,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict[str, str]:
    current = await get_current_user(credentials)
    user_data = require_auth(current)

    container = _session_containers.get(session_id)
    if container is None:
        raise HTTPException(status_code=404, detail="Session not found or already closed")

    is_owner = container.user is not None and container.user.get("sub") == user_data["sub"]
    is_privileged = user_data["role"] in ("root", "super_admin")
    is_da = user_data["role"] == "admin" and can_govern_domain(
        user_data, container.active_domain_id
    )
    if not (is_owner or is_privileged or is_da):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    await run_in_threadpool(
        _close_session,
        session_id,
        user_data["sub"],
        map_role_to_actor_role(user_data["role"]),
        "normal",
    )
    return {"status": "closed", "session_id": session_id}


# ─────────────────────────────────────────────────────────────
# Session handoff / resume — client-side transcript sealing
# ─────────────────────────────────────────────────────────────


@router.post("/api/session/{session_id}/handoff", status_code=200)
async def session_handoff(
    session_id: str,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict[str, Any]:
    """Return a sealed transcript snapshot for client-side persistence."""
    import time as _time

    from lumina.auth.auth import sign_transcript

    current = await get_current_user(credentials)
    user_data = require_auth(current)

    container = _session_containers.get(session_id)
    if container is None:
        raise HTTPException(status_code=404, detail="Session not found or already closed")

    is_owner = container.user is not None and container.user.get("sub") == user_data["sub"]
    if not is_owner:
        raise HTTPException(status_code=403, detail="Not session owner")

    user_id: str = user_data["sub"]

    # Build transcript from ring buffer snapshot
    turns = container.ring_buffer.snapshot()
    transcript = [
        {
            "turn": t.turn_number,
            "user": t.user_message,
            "assistant": t.llm_response,
            "ts": t.timestamp,
            "domain_id": t.domain_id,
        }
        for t in turns
    ]

    # Metadata — compressed state proof
    active_ctx = container.contexts.get(container.active_domain_id)
    turn_count = active_ctx.turn_count if active_ctx else 0

    metadata: dict[str, Any] = {
        "domain_id": container.active_domain_id,
        "turn_count": turn_count,
        "last_activity_utc": container.last_activity,
    }

    seal_payload = {"transcript": transcript, "metadata": metadata}
    seal = sign_transcript(user_id, seal_payload)

    return {
        "session_id": session_id,
        "transcript": transcript,
        "metadata": metadata,
        "seal": seal,
        "sealed_at_utc": _time.time(),
    }


@router.post("/api/session/{session_id}/resume", status_code=200)
async def session_resume(
    session_id: str,
    req: SessionResumeRequest,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict[str, Any]:
    """Verify a sealed transcript and re-hydrate the session ring buffer."""
    from lumina.auth.auth import verify_transcript

    current = await get_current_user(credentials)
    user_data = require_auth(current)

    user_id: str = user_data["sub"]

    # Verify HMAC seal
    seal_payload = {"transcript": req.transcript, "metadata": req.metadata}
    if not verify_transcript(user_id, seal_payload, req.seal):
        raise HTTPException(status_code=403, detail="Transcript integrity verification failed")

    # Re-hydrate the ring buffer into an existing or new session
    from lumina.api.session import get_or_create_session
    from lumina.core.domain_registry import DomainNotFoundError

    domain_id = req.metadata.get("domain_id")
    try:
        get_or_create_session(session_id, domain_id=domain_id, user=user_data)
    except DomainNotFoundError:
        # Sealed domain may no longer be registered; fall back to default
        get_or_create_session(session_id, domain_id=None, user=user_data)

    container = _session_containers.get(session_id)
    if container is None:
        raise HTTPException(status_code=500, detail="Session creation failed")

    # Hydrate ring buffer with verified transcript turns
    records = [
        {
            "turn_number": entry.get("turn", 0),
            "user_message": entry.get("user", ""),
            "llm_response": entry.get("assistant", ""),
            "timestamp": entry.get("ts", 0.0),
            "domain_id": entry.get("domain_id", domain_id or ""),
        }
        for entry in req.transcript
    ]
    container.ring_buffer.hydrate(records)

    # Restore turn_count so the processing pipeline knows this isn't turn 0
    _resumed_turn_count = len(req.transcript)
    ctx = container.active_context
    if ctx is not None:
        ctx.turn_count = _resumed_turn_count

    return {
        "status": "resumed",
        "session_id": session_id,
        "turn_count": _resumed_turn_count,
    }
