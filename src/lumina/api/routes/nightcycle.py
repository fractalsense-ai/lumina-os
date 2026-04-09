"""Night cycle endpoints: trigger, status, report, proposals."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from starlette.concurrency import run_in_threadpool

from lumina.api import config as _cfg
from lumina.api.middleware import _bearer_scheme, get_current_user, require_auth
from lumina.core.yaml_loader import load_yaml
from lumina.system_log.admin_operations import build_commitment_record, map_role_to_actor_role
from lumina.system_log.commit_guard import requires_log_commit

log = logging.getLogger("lumina-api")

router = APIRouter()

_NIGHT_SCHEDULER: Any = None


def _get_night_scheduler() -> Any:
    global _NIGHT_SCHEDULER
    if _NIGHT_SCHEDULER is None:
        from lumina.nightcycle.scheduler import NightCycleScheduler

        nc_cfg: dict[str, Any] = {}
        try:
            rt = load_yaml(Path("domain-packs/system/cfg/runtime-config.yaml"))
            nc_cfg = rt.get("night_cycle", {})
        except Exception:
            pass
        _NIGHT_SCHEDULER = NightCycleScheduler(config=nc_cfg, persistence=_cfg.PERSISTENCE)
    return _NIGHT_SCHEDULER


@router.post("/api/nightcycle/trigger")
async def nightcycle_trigger(
    req: dict[str, Any] = Body(default={}),
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict[str, Any]:
    current = await get_current_user(credentials)
    user_data = require_auth(current)
    if user_data["role"] not in ("root", "domain_authority"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    scheduler = _get_night_scheduler()
    task_names = req.get("tasks")
    domain_ids = req.get("domain_ids")
    run_id = scheduler.trigger_async(
        actor_id=user_data["sub"], task_names=task_names, domain_ids=domain_ids,
    )
    return {"run_id": run_id, "status": "started"}


@router.get("/api/nightcycle/status")
async def nightcycle_status(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict[str, Any]:
    current = await get_current_user(credentials)
    user_data = require_auth(current)
    if user_data["role"] not in ("root", "domain_authority", "auditor"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    return _get_night_scheduler().get_status()


@router.get("/api/nightcycle/report/{run_id}")
async def nightcycle_report(
    run_id: str,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict[str, Any]:
    current = await get_current_user(credentials)
    user_data = require_auth(current)
    if user_data["role"] not in ("root", "domain_authority"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    report = _get_night_scheduler().get_report(run_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return report


@router.get("/api/nightcycle/proposals")
async def nightcycle_proposals(
    domain_id: str | None = None,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> list[dict[str, Any]]:
    current = await get_current_user(credentials)
    user_data = require_auth(current)
    if user_data["role"] not in ("root", "domain_authority"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    return _get_night_scheduler().get_pending_proposals(domain_id=domain_id)


@router.post("/api/nightcycle/proposals/{proposal_id}/resolve")
@requires_log_commit
async def nightcycle_resolve_proposal(
    proposal_id: str,
    req: dict[str, Any] = Body(...),
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict[str, Any]:
    current = await get_current_user(credentials)
    user_data = require_auth(current)
    if user_data["role"] not in ("root", "domain_authority"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    action = req.get("action")
    if action not in ("approved", "rejected"):
        raise HTTPException(status_code=400, detail="action must be 'approved' or 'rejected'")

    found = _get_night_scheduler().resolve_proposal(proposal_id, action)
    if not found:
        raise HTTPException(status_code=404, detail="Proposal not found")

    record = build_commitment_record(
        actor_id=user_data["sub"],
        actor_role=map_role_to_actor_role(user_data["role"]),
        commitment_type="nightcycle_proposal_resolution",
        subject_id=proposal_id,
        summary=f"Night cycle proposal {action}",
        metadata={"action": action},
    )
    _cfg.PERSISTENCE.append_log_record(
        "admin", record,
        ledger_path=_cfg.PERSISTENCE.get_system_ledger_path("admin"),
    )

    return {"proposal_id": proposal_id, "status": action}
