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
from lumina.api.models import DomainCommitRequest, DomainPhysicsUpdateRequest
from lumina.api.session import _close_session, _persist_session_container, _session_containers
from lumina.core.domain_registry import DomainNotFoundError
from lumina.ctl.admin_operations import (
    _canonical_sha256 as admin_canonical_sha256,
    build_commitment_record,
    can_govern_domain,
    map_role_to_actor_role,
)

log = logging.getLogger("lumina-api")

router = APIRouter()


@router.post("/api/domain-pack/commit")
async def domain_pack_commit(
    req: DomainCommitRequest,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict[str, Any]:
    current = await get_current_user(credentials)
    user_data = require_auth(current)

    if user_data["role"] not in ("root", "domain_authority"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    if user_data["role"] == "domain_authority" and not can_govern_domain(user_data, req.domain_id):
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

    _cfg.PERSISTENCE.append_ctl_record(
        "admin", record,
        ledger_path=_cfg.PERSISTENCE.get_ctl_ledger_path("admin", domain_id=resolved),
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

    allowed_roles = ("root", "qa", "auditor")
    if user_data["role"] not in allowed_roles:
        if user_data["role"] == "domain_authority" and can_govern_domain(user_data, domain_id):
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
async def update_domain_physics(
    domain_id: str,
    req: DomainPhysicsUpdateRequest,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict[str, Any]:
    current = await get_current_user(credentials)
    user_data = require_auth(current)

    if user_data["role"] not in ("root", "domain_authority"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    if user_data["role"] == "domain_authority" and not can_govern_domain(user_data, domain_id):
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
    _cfg.PERSISTENCE.append_ctl_record(
        "admin", record,
        ledger_path=_cfg.PERSISTENCE.get_ctl_ledger_path("admin", domain_id=resolved),
    )

    return {
        "subject_hash": subject_hash,
        "updated_fields": list(req.updates.keys()),
        "record_id": record["record_id"],
    }


@router.post("/api/session/{session_id}/close", status_code=200)
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
    is_privileged = user_data["role"] in ("root", "it_support")
    is_da = user_data["role"] == "domain_authority" and can_govern_domain(
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
