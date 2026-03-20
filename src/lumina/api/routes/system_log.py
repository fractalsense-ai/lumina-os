"""System Log query endpoints: records, sessions, single record lookup."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from starlette.concurrency import run_in_threadpool

from lumina.api import config as _cfg
from lumina.api.middleware import _bearer_scheme, get_current_user, require_auth, require_role

log = logging.getLogger("lumina-api")

router = APIRouter()


@router.get("/api/system-log/records")
async def query_log_records(
    session_id: str | None = None,
    record_type: str | None = None,
    event_type: str | None = None,
    domain_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> list[dict[str, Any]]:
    current = await get_current_user(credentials)
    user_data = require_auth(current)

    allowed_roles = ("root", "qa", "auditor")
    if user_data["role"] not in allowed_roles:
        if user_data["role"] == "domain_authority":
            pass
        else:
            raise HTTPException(status_code=403, detail="Insufficient permissions")

    records = await run_in_threadpool(
        _cfg.PERSISTENCE.query_log_records,
        session_id=session_id,
        record_type=record_type,
        event_type=event_type,
        domain_id=domain_id,
        limit=limit,
        offset=offset,
    )
    return records


@router.get("/api/system-log/sessions")
async def list_log_sessions(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> list[dict[str, Any]]:
    current = await get_current_user(credentials)
    user_data = require_auth(current)

    allowed_roles = ("root", "domain_authority", "it_support", "qa", "auditor")
    if user_data["role"] not in allowed_roles:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    summaries = await run_in_threadpool(_cfg.PERSISTENCE.list_log_sessions_summary)
    return summaries


@router.get("/api/system-log/records/{record_id}")
async def get_log_record(
    record_id: str,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict[str, Any]:
    current = await get_current_user(credentials)
    user_data = require_auth(current)

    allowed_roles = ("root", "qa", "auditor")
    if user_data["role"] not in allowed_roles:
        if user_data["role"] == "domain_authority":
            pass
        else:
            raise HTTPException(status_code=403, detail="Insufficient permissions")

    all_records = await run_in_threadpool(_cfg.PERSISTENCE.query_log_records, limit=10000)
    for r in all_records:
        if r.get("record_id") == record_id:
            return r

    raise HTTPException(status_code=404, detail="Record not found")
