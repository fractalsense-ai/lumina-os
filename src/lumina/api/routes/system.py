"""System endpoints: health, domains, domain-info, tool invocation, System Log validation."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from starlette.concurrency import run_in_threadpool

from lumina.api import config as _cfg
from lumina.api.middleware import _bearer_scheme, get_current_user, require_role
from lumina.api.models import SystemLogValidateResponse, ToolRequestWithDomain, ToolResponse
from lumina.api.runtime_helpers import invoke_runtime_tool
from lumina.core.domain_registry import DomainNotFoundError
from lumina.core.permissions import Operation, check_permission

log = logging.getLogger("lumina-api")

router = APIRouter()


@router.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "provider": _cfg.LLM_PROVIDER}


@router.get("/api/domains")
async def list_domains() -> list[dict[str, Any]]:
    return _cfg.DOMAIN_REGISTRY.list_domains()


@router.get("/api/domain-info")
async def domain_info(domain_id: str | None = None) -> dict[str, Any]:
    try:
        resolved = _cfg.DOMAIN_REGISTRY.resolve_domain_id(domain_id)
    except DomainNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    runtime = _cfg.DOMAIN_REGISTRY.get_runtime_context(resolved)
    domain_physics_path = runtime["domain_physics_path"]
    domain = _cfg.PERSISTENCE.load_domain_physics(str(domain_physics_path))
    manifest = runtime.get("ui_manifest") or {}
    return {
        "domain_id": domain.get("id", "unknown"),
        "domain_version": domain.get("version", "unknown"),
        "ui_manifest": manifest,
    }


@router.post("/api/tool/{tool_id}", response_model=ToolResponse)
async def run_tool(
    tool_id: str,
    req: ToolRequestWithDomain,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> ToolResponse:
    try:
        resolved = _cfg.DOMAIN_REGISTRY.resolve_domain_id(req.domain_id)
    except DomainNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    runtime = _cfg.DOMAIN_REGISTRY.get_runtime_context(resolved)

    user = await get_current_user(credentials)
    if user is not None:
        domain_physics_path = runtime["domain_physics_path"]
        domain = await run_in_threadpool(_cfg.PERSISTENCE.load_domain_physics, str(domain_physics_path))
        module_perms = domain.get("permissions")
        if module_perms and not check_permission(
            user_id=user["sub"],
            user_role=user["role"],
            module_permissions=module_perms,
            operation=Operation.EXECUTE,
        ):
            raise HTTPException(status_code=403, detail="Module access denied")
    try:
        result = await run_in_threadpool(invoke_runtime_tool, tool_id, req.payload, runtime)
    except Exception as exc:
        log.exception("Tool invocation failed for %s", tool_id)
        raise HTTPException(status_code=400, detail=str(exc))
    return ToolResponse(tool_id=tool_id, result=result)


@router.get("/api/system-log/validate", response_model=SystemLogValidateResponse)
async def validate_system_log(
    session_id: str | None = None,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> SystemLogValidateResponse:
    user = await get_current_user(credentials)
    if user is not None:
        require_role(user, "root", "domain_authority", "qa", "auditor")
    try:
        result = await run_in_threadpool(_cfg.PERSISTENCE.validate_log_chain, session_id)
    except Exception as exc:
        log.exception("System Log validation failed")
        raise HTTPException(status_code=500, detail=str(exc))
    return SystemLogValidateResponse(result=result)
