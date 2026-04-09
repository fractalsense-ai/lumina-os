"""Module-management operations: assign_module, remove_module,
switch_active_module.
"""

from __future__ import annotations

import logging
from typing import Any

from ._helpers import (
    load_profile,
    require_module_governance,
    require_user_exists,
    save_profile,
    write_commitment,
)

log = logging.getLogger("lumina.education-ops")


# ── assign_module ─────────────────────────────────────────────

async def assign_module(
    operation: str,
    params: dict[str, Any],
    user_data: dict[str, Any],
    ctx: Any,
) -> dict[str, Any]:
    target_user_id = str(params.get("user_id", "") or params.get("_target", "")).strip()
    module_id = str(params.get("module_id", "")).strip()
    if not target_user_id or not module_id:
        raise ctx.HTTPException(status_code=422, detail="user_id and module_id required")

    caller_role = user_data["role"]
    if caller_role in ("root", "domain_authority"):
        if caller_role == "domain_authority" and not ctx.can_govern_domain(user_data, module_id, registry=ctx.domain_registry):
            raise ctx.HTTPException(status_code=403, detail="Not authorised for this domain/module")
    elif caller_role == "user":
        await require_module_governance(user_data, ctx)
    else:
        raise ctx.HTTPException(status_code=403, detail="Insufficient permissions")

    await require_user_exists(ctx, target_user_id)

    await ctx.run_in_threadpool(
        ctx.persistence.update_user_governed_modules, target_user_id, add=[module_id],
    )
    record = write_commitment(
        ctx,
        actor_id=user_data["sub"],
        actor_role=ctx.map_role_to_actor_role(caller_role),
        commitment_type="module_assignment",
        subject_id=target_user_id,
        summary=f"Assigned module {module_id} to user {target_user_id}",
        metadata={"module_id": module_id, "assigned_by": user_data["sub"]},
        references=[target_user_id, module_id],
    )
    return {
        "operation": operation,
        "user_id": target_user_id,
        "module_id": module_id,
        "status": "assigned",
        "record_id": record["record_id"],
    }


# ── remove_module ─────────────────────────────────────────────

async def remove_module(
    operation: str,
    params: dict[str, Any],
    user_data: dict[str, Any],
    ctx: Any,
) -> dict[str, Any]:
    target_user_id = str(params.get("user_id", "") or params.get("_target", "")).strip()
    module_id = str(params.get("module_id", "")).strip()
    if not target_user_id or not module_id:
        raise ctx.HTTPException(status_code=422, detail="user_id and module_id required")

    caller_role = user_data["role"]
    if caller_role in ("root", "domain_authority"):
        if caller_role == "domain_authority" and not ctx.can_govern_domain(user_data, module_id, registry=ctx.domain_registry):
            raise ctx.HTTPException(status_code=403, detail="Not authorised for this domain/module")
    elif caller_role == "user":
        await require_module_governance(user_data, ctx)
    else:
        raise ctx.HTTPException(status_code=403, detail="Insufficient permissions")

    await require_user_exists(ctx, target_user_id)

    await ctx.run_in_threadpool(
        ctx.persistence.update_user_governed_modules, target_user_id, remove=[module_id],
    )
    record = write_commitment(
        ctx,
        actor_id=user_data["sub"],
        actor_role=ctx.map_role_to_actor_role(caller_role),
        commitment_type="module_removal",
        subject_id=target_user_id,
        summary=f"Removed module {module_id} from user {target_user_id}",
        metadata={"module_id": module_id, "removed_by": user_data["sub"]},
        references=[target_user_id, module_id],
    )
    return {
        "operation": operation,
        "user_id": target_user_id,
        "module_id": module_id,
        "status": "removed",
        "record_id": record["record_id"],
    }


# ── switch_active_module ──────────────────────────────────────

async def switch_active_module(
    operation: str,
    params: dict[str, Any],
    user_data: dict[str, Any],
    ctx: Any,
) -> dict[str, Any]:
    """Self-service module switch for students.

    Only switches between modules the student already has state in
    (profile["modules"] keys) or is listed in governed_modules.
    Does NOT create new enrolments.
    """
    module_id = str(params.get("module_id", "")).strip()
    if not module_id:
        raise ctx.HTTPException(status_code=422, detail="module_id is required")

    user_id = user_data["sub"]

    _profile = await load_profile(ctx, user_id)

    # Collect modules the student has state in
    existing_modules = set((_profile.get("modules") or {}).keys())

    # Also check governed_modules from user record
    user_rec = await ctx.run_in_threadpool(ctx.persistence.get_user, user_id)
    if user_rec:
        governed = set(user_rec.get("governed_modules") or [])
        existing_modules |= governed

    if module_id not in existing_modules:
        raise ctx.HTTPException(
            status_code=403,
            detail=f"Not enrolled in module '{module_id}'. Available modules: {sorted(existing_modules)}",
        )

    # Validate that the module actually exists in the domain registry
    try:
        _mods = ctx.domain_registry.list_modules_for_domain("education")
        _valid_ids = {m["module_id"] for m in _mods}
        if module_id not in _valid_ids:
            raise ctx.HTTPException(
                status_code=422,
                detail=f"Unknown module_id: {module_id}",
            )
    except ctx.HTTPException:
        raise
    except Exception:
        pass  # registry unavailable — trust the profile

    # Update active module
    _profile["domain_id"] = module_id
    await save_profile(ctx, user_id, _profile)

    log.info("User %s switched active module to %s", user_id, module_id)

    return {
        "operation": operation,
        "user_id": user_id,
        "module_id": module_id,
        "status": "switched",
        "message": f"Active module switched to {module_id}",
    }
