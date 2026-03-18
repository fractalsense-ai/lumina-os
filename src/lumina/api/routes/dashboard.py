"""Dashboard endpoints: domain stats and telemetry."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from starlette.concurrency import run_in_threadpool

from lumina.api import config as _cfg
from lumina.api.middleware import _bearer_scheme, get_current_user, require_auth
from lumina.api.routes.ingestion import _get_ingest_service

log = logging.getLogger("lumina-api")

router = APIRouter()


@router.get("/api/dashboard/domains")
async def dashboard_domains(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> list[dict[str, Any]]:
    current = await get_current_user(credentials)
    user_data = require_auth(current)

    if user_data["role"] not in ("root", "domain_authority"):
        raise HTTPException(status_code=403, detail="Dashboard requires DA or root role")

    all_domains = _cfg.DOMAIN_REGISTRY.list_domains()

    if user_data["role"] == "domain_authority":
        governed = set(user_data.get("governed_modules") or [])
        all_domains = [d for d in all_domains if d.get("domain_id") in governed]

    results: list[dict[str, Any]] = []
    for domain in all_domains:
        domain_id = domain.get("domain_id", "")
        try:
            escalations = await run_in_threadpool(
                _cfg.PERSISTENCE.query_escalations, domain_id=domain_id, status="pending",
            )
            pending_escalations = len(escalations)
        except Exception:
            pending_escalations = 0

        svc = _get_ingest_service()
        pending_ingestions = len(svc.list_records(domain_id=domain_id, status="pending_extraction"))
        review_ingestions = len(svc.list_records(domain_id=domain_id, status="extraction_complete"))

        results.append({
            "domain_id": domain_id,
            "name": domain.get("name", domain_id),
            "version": domain.get("version", "0.0.0"),
            "pending_escalations": pending_escalations,
            "pending_ingestions": pending_ingestions,
            "review_ingestions": review_ingestions,
        })

    return results


@router.get("/api/dashboard/telemetry")
async def dashboard_telemetry(
    domain_id: str | None = None,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict[str, Any]:
    current = await get_current_user(credentials)
    user_data = require_auth(current)

    if user_data["role"] not in ("root", "domain_authority"):
        raise HTTPException(status_code=403, detail="Dashboard requires DA or root role")

    records = await run_in_threadpool(_cfg.PERSISTENCE.query_ctl_records, domain_id=domain_id)

    record_types: dict[str, int] = {}
    for r in records:
        rt = r.get("record_type", "unknown")
        record_types[rt] = record_types.get(rt, 0) + 1

    try:
        escalations = await run_in_threadpool(
            _cfg.PERSISTENCE.query_escalations, domain_id=domain_id,
        )
    except Exception:
        escalations = []

    pending = sum(1 for e in escalations if e.get("status") == "pending")
    resolved = sum(1 for e in escalations if e.get("status") == "resolved")

    return {
        "total_ctl_records": len(records),
        "record_type_counts": record_types,
        "escalation_summary": {
            "total": len(escalations),
            "pending": pending,
            "resolved": resolved,
        },
        "domain_filter": domain_id,
    }
