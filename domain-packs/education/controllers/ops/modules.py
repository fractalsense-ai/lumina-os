"""Module-management operations: assign_module, remove_module,
switch_active_module.
"""

from __future__ import annotations

import logging
from typing import Any

from ._helpers import (
    extract_short_name,
    list_learning_modules,
    load_profile,
    require_module_governance,
    require_user_exists,
    resolve_module_shortname,
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

    # Resolve short names (e.g. "pre-algebra" → "domain/edu/pre-algebra/v1")
    module_id = resolve_module_shortname(ctx, module_id)

    user_id = user_data["sub"]

    _profile = await load_profile(ctx, user_id)

    # Collect modules the student has state in
    _mods = _profile.get("modules")
    existing_modules = set((_mods if isinstance(_mods, dict) else {}).keys())

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

    # Include ui_overrides so the frontend can update the header/subtitle
    _ui_overrides: dict[str, Any] = {}
    try:
        _rt = ctx.domain_registry.get_runtime_context("education")
        _mod_entry = (_rt.get("module_map") or {}).get(module_id) or {}
        _ui_overrides = _mod_entry.get("ui_overrides") or {}
    except Exception:
        pass

    return {
        "operation": operation,
        "user_id": user_id,
        "module_id": module_id,
        "status": "switched",
        "message": f"Active module switched to {module_id}",
        "ui_overrides": _ui_overrides,
    }


# ── assign_modules (plural — multi-module, multi-target) ─────

async def assign_modules(
    operation: str,
    params: dict[str, Any],
    user_data: dict[str, Any],
    ctx: Any,
) -> dict[str, Any]:
    """Assign one or more learning modules to a student or classroom.

    Params
    ------
    module_ids : str
        Comma-separated module short names or full ids.
    target : str
        A student user-id/username, or the literal ``"classroom"`` to
        assign to every student on the teacher's roster.
    """
    raw_modules = str(params.get("module_ids", "")).strip()
    target = str(params.get("target", "") or params.get("user_id", "")).strip()
    if not raw_modules or not target:
        raise ctx.HTTPException(
            status_code=422,
            detail="module_ids and target required (e.g. 'pre-algebra,algebra-intro student1' or 'pre-algebra classroom')",
        )

    # RBAC: teacher with assign_modules_to_students capability
    caller_role = user_data["role"]
    if caller_role in ("root", "domain_authority"):
        if caller_role == "domain_authority":
            # DA must govern the education domain
            if not ctx.can_govern_domain(user_data, "education", registry=ctx.domain_registry):
                raise ctx.HTTPException(status_code=403, detail="Not authorised for education domain")
    elif caller_role == "user":
        await require_module_governance(user_data, ctx)
    else:
        raise ctx.HTTPException(status_code=403, detail="Insufficient permissions")

    # Resolve comma-separated module short names → full ids
    names = [n.strip() for n in raw_modules.split(",") if n.strip()]
    module_ids = [resolve_module_shortname(ctx, n) for n in names]

    # Determine target user(s)
    if target.lower() == "classroom":
        # Resolve from teacher's educator_state.assigned_students
        teacher_profile = await load_profile(ctx, user_data["sub"])
        roster = (teacher_profile.get("educator_state") or {}).get("assigned_students") or []
        if not roster:
            raise ctx.HTTPException(
                status_code=422,
                detail="No students on your roster. Use /assign to add students first.",
            )
        target_ids = list(roster)
    elif target.lower() == "self":
        target_ids = [user_data["sub"]]
    else:
        user_rec = await require_user_exists(ctx, target, label="Target user")
        target_ids = [user_rec["user_id"]]

    # Assign each module to each target
    results: list[dict[str, Any]] = []
    for tid in target_ids:
        await ctx.run_in_threadpool(
            ctx.persistence.update_user_governed_modules, tid, add=module_ids,
        )
        record = write_commitment(
            ctx,
            actor_id=user_data["sub"],
            actor_role=ctx.map_role_to_actor_role(caller_role),
            commitment_type="module_assignment",
            subject_id=tid,
            summary=f"Assigned modules {', '.join(extract_short_name(m) for m in module_ids)} to {tid}",
            metadata={"module_ids": module_ids, "assigned_by": user_data["sub"]},
            references=[tid, *module_ids],
        )
        results.append({
            "user_id": tid,
            "module_ids": module_ids,
            "record_id": record["record_id"],
        })

    return {
        "operation": operation,
        "status": "assigned",
        "count": len(results),
        "assignments": results,
    }
