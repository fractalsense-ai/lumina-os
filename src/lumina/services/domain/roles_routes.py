"""Domain Roles endpoints.

Provides:
  GET  /api/domain-roles/defaults          — list built-in tier definitions
  GET  /api/domain-roles/{module_id}       — active roles for a specific module
  POST /api/domain-roles/{module_id}/assign — assign a domain role to a user
  DELETE /api/domain-roles/{module_id}/{user_id} — revoke domain role from user
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from lumina.api import config as _cfg
from lumina.api.middleware import _bearer_scheme, get_current_user, require_auth
from lumina.system_log.admin_operations import (
    build_domain_role_assignment,
    build_domain_role_revocation,
    can_govern_domain,
    map_role_to_actor_role,
)
from lumina.system_log.commit_guard import requires_log_commit
from lumina.core.domain_roles import get_active_role_defs, get_default_role_defs, get_domain_role_def
from lumina.core.domain_registry import DomainNotFoundError

log = logging.getLogger("lumina-api")

router = APIRouter()


class DomainRoleAssignRequest(BaseModel):
    user_id: str
    domain_role: str


# ─────────────────────────────────────────────────────────────
# Default tier definitions
# ─────────────────────────────────────────────────────────────


@router.get("/api/domain-roles/defaults")
async def list_default_roles(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> list[dict[str, Any]]:
    """Return the built-in domain role tier definitions."""
    current = await get_current_user(credentials)
    user_data = require_auth(current)

    if user_data["role"] not in ("root", "domain_authority", "it_support", "qa", "auditor"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    return get_default_role_defs()


# ─────────────────────────────────────────────────────────────
# Module-specific active roles
# ─────────────────────────────────────────────────────────────


@router.get("/api/domain-roles/{module_id}")
async def get_module_roles(
    module_id: str,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict[str, Any]:
    """Return roles active for a specific module (defaults + domain overrides)."""
    current = await get_current_user(credentials)
    user_data = require_auth(current)

    if user_data["role"] not in ("root", "domain_authority", "it_support", "qa", "auditor"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    if user_data["role"] == "domain_authority" and not can_govern_domain(user_data, module_id):
        raise HTTPException(status_code=403, detail="Not authorized for this domain")

    try:
        resolved = _cfg.DOMAIN_REGISTRY.resolve_domain_id(module_id)
    except DomainNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    runtime = _cfg.DOMAIN_REGISTRY.get_runtime_context(resolved)
    domain_physics = await run_in_threadpool(
        _cfg.PERSISTENCE.load_domain_physics, runtime["domain_physics_path"]
    )
    active_roles = get_active_role_defs(domain_physics)

    return {"module_id": resolved, "roles": active_roles}


# ─────────────────────────────────────────────────────────────
# Assign a domain role to a user
# ─────────────────────────────────────────────────────────────


@router.post("/api/domain-roles/{module_id}/assign")
@requires_log_commit
async def assign_domain_role(
    module_id: str,
    req: DomainRoleAssignRequest,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict[str, Any]:
    """Assign a domain-scoped role to a user for the given module."""
    current = await get_current_user(credentials)
    user_data = require_auth(current)

    if user_data["role"] not in ("root", "domain_authority"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    if user_data["role"] == "domain_authority" and not can_govern_domain(user_data, module_id):
        raise HTTPException(status_code=403, detail="Not authorized for this domain")

    # Validate that the requested role_id is known for this module
    try:
        mod_resolved = _cfg.DOMAIN_REGISTRY.resolve_domain_id(module_id)
        mod_runtime = _cfg.DOMAIN_REGISTRY.get_runtime_context(mod_resolved)
        mod_physics = await run_in_threadpool(
            _cfg.PERSISTENCE.load_domain_physics, mod_runtime["domain_physics_path"]
        )
        active_roles = get_active_role_defs(mod_physics)
        valid_ids = [r["role_id"] for r in active_roles if "role_id" in r]
        if valid_ids and req.domain_role not in valid_ids:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown domain role: {req.domain_role!r}. "
                f"Valid roles for {module_id}: {valid_ids}. "
                "Use GET /api/domain-roles/{module_id} to list.",
            )
    except DomainNotFoundError:
        # Module not in domain registry — fall back to generic defaults
        if get_domain_role_def(req.domain_role) is None:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown domain role: {req.domain_role!r}. "
                "Use GET /api/domain-roles/defaults to list valid role IDs.",
            )

    target = await run_in_threadpool(_cfg.PERSISTENCE.get_user, req.user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")

    updated = await run_in_threadpool(
        _cfg.PERSISTENCE.update_user_domain_roles, req.user_id, {module_id: req.domain_role}
    )

    record = build_domain_role_assignment(
        actor_id=user_data["sub"],
        actor_role=map_role_to_actor_role(user_data["role"]),
        target_user_id=req.user_id,
        module_id=module_id,
        domain_role=req.domain_role,
    )
    try:
        _cfg.PERSISTENCE.append_log_record(
            "admin", record,
            ledger_path=_cfg.PERSISTENCE.get_domain_ledger_path(module_id),
        )
    except Exception:
        log.debug("Could not write domain_role_assignment System Log record")

    return {
        "user_id": req.user_id,
        "module_id": module_id,
        "domain_role": req.domain_role,
        "record_id": record["record_id"],
        "domain_roles": (updated or {}).get("domain_roles", {}),
    }


# ─────────────────────────────────────────────────────────────
# Revoke a domain role from a user
# ─────────────────────────────────────────────────────────────


@router.delete("/api/domain-roles/{module_id}/{user_id}", status_code=200)
@requires_log_commit
async def revoke_domain_role(
    module_id: str,
    user_id: str,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict[str, Any]:
    """Revoke a user's domain-scoped role for the given module."""
    current = await get_current_user(credentials)
    user_data = require_auth(current)

    if user_data["role"] not in ("root", "domain_authority"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    if user_data["role"] == "domain_authority" and not can_govern_domain(user_data, module_id):
        raise HTTPException(status_code=403, detail="Not authorized for this domain")

    target = await run_in_threadpool(_cfg.PERSISTENCE.get_user, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")

    prev_role = (target.get("domain_roles") or {}).get(module_id, "")
    if not prev_role:
        raise HTTPException(
            status_code=404, detail=f"User has no domain role in module {module_id!r}"
        )

    # Empty string signals removal in the persistence merge
    await run_in_threadpool(
        _cfg.PERSISTENCE.update_user_domain_roles, user_id, {module_id: ""}
    )

    record = build_domain_role_revocation(
        actor_id=user_data["sub"],
        actor_role=map_role_to_actor_role(user_data["role"]),
        target_user_id=user_id,
        module_id=module_id,
        prev_role=prev_role,
    )
    try:
        _cfg.PERSISTENCE.append_log_record(
            "admin", record,
            ledger_path=_cfg.PERSISTENCE.get_domain_ledger_path(module_id),
        )
    except Exception:
        log.debug("Could not write domain_role_revocation System Log record")

    return {
        "user_id": user_id,
        "module_id": module_id,
        "revoked_role": prev_role,
        "record_id": record["record_id"],
    }
