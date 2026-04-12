"""RBAC operations: update_user_role, deactivate_user, assign_domain_role, revoke_domain_role."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from lumina.api.admin_context import AdminOperationContext
from lumina.auth.auth import VALID_ROLES
from lumina.core.domain_registry import DomainNotFoundError


async def execute(
    operation: str,
    params: dict[str, Any],
    user_data: dict[str, Any],
    ctx: AdminOperationContext,
    *,
    parsed: dict[str, Any] | None = None,
    **kw: Any,
) -> dict[str, Any] | None:
    parsed = parsed or {}
    target = parsed.get("target", "")

    if operation == "update_user_role":
        if user_data["role"] != "root":
            raise ctx.HTTPException(status_code=403, detail="Only root can update user roles")
        target_user_id = str(params.get("user_id", target))
        new_role = str(params.get("new_role", ""))
        if not target_user_id or new_role not in VALID_ROLES:
            raise ctx.HTTPException(status_code=422, detail="user_id and valid new_role required")
        governed_modules_raw = params.get("governed_modules")
        governed_modules = list(governed_modules_raw) if governed_modules_raw else None
        await ctx.run_in_threadpool(
            ctx.persistence.update_user_role, target_user_id, new_role, governed_modules,
        )
        result: dict[str, Any] = {"operation": operation, "user_id": target_user_id, "new_role": new_role}
        if governed_modules is not None:
            result["governed_modules"] = governed_modules
        return result

    if operation == "deactivate_user":
        if user_data["role"] != "root":
            raise ctx.HTTPException(status_code=403, detail="Only root can deactivate users")
        target_user_id = str(params.get("user_id", target))
        if not target_user_id:
            raise ctx.HTTPException(status_code=422, detail="user_id required")
        if target_user_id == user_data["sub"]:
            raise ctx.HTTPException(status_code=400, detail="Cannot deactivate yourself")
        await ctx.run_in_threadpool(ctx.persistence.deactivate_user, target_user_id)
        return {"operation": operation, "user_id": target_user_id}

    if operation == "assign_domain_role":
        if user_data["role"] not in ("root", "domain_authority"):
            raise ctx.HTTPException(status_code=403, detail="Insufficient permissions")
        target_user_id = str(params.get("user_id", target))
        module_id = str(params.get("module_id", ""))
        domain_role = str(params.get("domain_role", ""))
        if not target_user_id or not module_id or not domain_role:
            raise ctx.HTTPException(status_code=422, detail="user_id, module_id, and domain_role required")
        if user_data["role"] == "domain_authority" and not ctx.can_govern_domain(user_data, module_id, registry=ctx.domain_registry):
            raise ctx.HTTPException(status_code=403, detail="Not authorized for this domain")
        # Validate role_id against the module's actual domain_roles block
        try:
            _mod_domain = ctx.domain_registry.resolve_domain_id(module_id)
            _mod_runtime = ctx.domain_registry.get_runtime_context(_mod_domain)
            _module_map = _mod_runtime.get("module_map") or {}
            if module_id in _module_map:
                _dp_path = Path(ctx.domain_registry._repo_root) / _module_map[module_id]["domain_physics_path"]
            else:
                _dp_path = Path(ctx.domain_registry._repo_root) / _mod_runtime["domain_physics_path"]
            _dp_data = json.loads(_dp_path.read_text(encoding="utf-8"))
            _valid_roles = [
                r.get("role_id") for r in (_dp_data.get("domain_roles", {}).get("roles") or [])
                if isinstance(r, dict) and r.get("role_id")
            ]
            if _valid_roles and domain_role not in _valid_roles:
                raise ctx.HTTPException(
                    status_code=422,
                    detail=f"Unknown domain role {domain_role!r} for module {module_id!r}. "
                    f"Valid roles: {_valid_roles}. Use list_domain_rbac_roles to discover.",
                )
        except (DomainNotFoundError, FileNotFoundError, KeyError):
            pass  # Module not in registry or no physics file — allow assignment
        target_user = await ctx.run_in_threadpool(ctx.persistence.get_user, target_user_id)
        if target_user is None:
            raise ctx.HTTPException(status_code=404, detail="User not found")
        await ctx.run_in_threadpool(
            ctx.persistence.update_user_domain_roles, target_user_id, {module_id: domain_role}
        )
        record = ctx.build_domain_role_assignment(
            actor_id=user_data["sub"],
            actor_role=ctx.map_role_to_actor_role(user_data["role"]),
            target_user_id=target_user_id,
            module_id=module_id,
            domain_role=domain_role,
        )
        ctx.persistence.append_log_record(
            "admin", record,
            ledger_path=ctx.persistence.get_domain_ledger_path(module_id),
        )
        return {
            "operation": operation,
            "user_id": target_user_id,
            "module_id": module_id,
            "domain_role": domain_role,
            "record_id": record["record_id"],
        }

    if operation == "revoke_domain_role":
        if user_data["role"] not in ("root", "domain_authority"):
            raise ctx.HTTPException(status_code=403, detail="Insufficient permissions")
        target_user_id = str(params.get("user_id", target))
        module_id = str(params.get("module_id", ""))
        if not target_user_id or not module_id:
            raise ctx.HTTPException(status_code=422, detail="user_id and module_id required")
        if user_data["role"] == "domain_authority" and not ctx.can_govern_domain(user_data, module_id, registry=ctx.domain_registry):
            raise ctx.HTTPException(status_code=403, detail="Not authorized for this domain")
        target_user = await ctx.run_in_threadpool(ctx.persistence.get_user, target_user_id)
        if target_user is None:
            raise ctx.HTTPException(status_code=404, detail="User not found")
        prev_role = (target_user.get("domain_roles") or {}).get(module_id, "")
        # Revoke by removing the key (set empty string signals removal; persistence merges)
        await ctx.run_in_threadpool(
            ctx.persistence.update_user_domain_roles, target_user_id, {module_id: ""}
        )
        record = ctx.build_domain_role_revocation(
            actor_id=user_data["sub"],
            actor_role=ctx.map_role_to_actor_role(user_data["role"]),
            target_user_id=target_user_id,
            module_id=module_id,
            prev_role=prev_role or "unknown",
        )
        ctx.persistence.append_log_record(
            "admin", record,
            ledger_path=ctx.persistence.get_domain_ledger_path(module_id),
        )
        return {
            "operation": operation,
            "user_id": target_user_id,
            "module_id": module_id,
            "prev_role": prev_role,
            "record_id": record["record_id"],
        }

    return None
