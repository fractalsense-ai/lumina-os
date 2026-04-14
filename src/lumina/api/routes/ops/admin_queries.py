"""Query operations: list_domains, list_commands, list_modules, list_domain_rbac_roles,
get_domain_module_manifest, list_users, list_daemon_tasks."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from lumina.api.admin_context import AdminOperationContext
from lumina.core.domain_registry import DomainNotFoundError
from lumina.core.yaml_loader import load_yaml


async def execute(
    operation: str,
    params: dict[str, Any],
    user_data: dict[str, Any],
    ctx: AdminOperationContext,
    *,
    parsed: dict[str, Any] | None = None,
    get_known_operations: Callable[[], set[str]] | None = None,
    get_domain_scoped_operations: Callable[[str | None], frozenset[str]] | None = None,
    get_hitl_exempt_ops: Callable[[], set[str]] | None = None,
    get_min_role_policy: Callable[[], dict[str, str]] | None = None,
    get_role_hierarchy: Callable[[], dict[str, int]] | None = None,
    get_cmd_schema: Callable[[str], dict[str, Any] | None] | None = None,
    get_domain_role_level: Callable[[str, str], int | None] | None = None,
    **kw: Any,
) -> dict[str, Any] | None:
    parsed = parsed or {}
    target = parsed.get("target", "")

    if operation == "list_domains":
        domains = ctx.domain_registry.list_domains()
        return {"operation": operation, "domains": domains, "count": len(domains)}

    if operation == "list_commands":
        assert get_known_operations and get_hitl_exempt_ops and get_min_role_policy and get_role_hierarchy
        include_details = bool(params.get("include_details", True))
        domain_id = str(params.get("domain_id", "")) or ctx.domain_id
        _min_role = get_min_role_policy()
        _role_rank = get_role_hierarchy()
        _hitl_exempt = get_hitl_exempt_ops()
        actor_rank = _role_rank.get(user_data["role"], 0)
        # Use domain-scoped operations when available; fall back to global set
        if get_domain_scoped_operations is not None:
            ops_set = get_domain_scoped_operations(domain_id)
        else:
            ops_set = get_known_operations()
        commands: list[dict[str, Any]] = []
        for op_name in sorted(ops_set):
            min_role = _min_role.get(op_name, "user")
            if actor_rank < _role_rank.get(min_role, 0):
                continue
            entry: dict[str, Any] = {"name": op_name}
            if include_details:
                schema = get_cmd_schema(op_name) if get_cmd_schema else None
                entry["description"] = (schema or {}).get("description", "")
                entry["hitl_exempt"] = op_name in _hitl_exempt
                entry["min_role"] = min_role
            commands.append(entry)
        return {"operation": operation, "commands": commands, "count": len(commands)}

    if operation == "list_modules":
        domain_id = str(params.get("domain_id", target))
        if not domain_id:
            raise ctx.HTTPException(status_code=422, detail="domain_id required")
        try:
            resolved = ctx.domain_registry.resolve_domain_id(domain_id)
        except DomainNotFoundError as exc:
            raise ctx.HTTPException(status_code=400, detail=str(exc))
        # DA scoping: domain_authority sees only governed domain modules
        if user_data["role"] == "domain_authority" and not ctx.can_govern_domain(user_data, resolved, registry=ctx.domain_registry):
            raise ctx.HTTPException(status_code=403, detail="Not authorized for this domain")
        modules = ctx.domain_registry.list_modules_for_domain(resolved)
        # Add short_name to each module for user-friendly display
        for m in modules:
            parts = m["module_id"].split("/")
            m["short_name"] = parts[-2] if len(parts) >= 3 else m["module_id"]
        # Non-elevated users see only learning modules (exclude local_only role modules)
        if user_data["role"] not in ("root", "domain_authority"):
            modules = [m for m in modules if not m.get("local_only")]
        return {"operation": operation, "domain_id": resolved, "modules": modules, "count": len(modules)}

    if operation == "list_domain_rbac_roles":
        domain_id = str(params.get("domain_id", target))
        if not domain_id:
            raise ctx.HTTPException(status_code=422, detail="domain_id required")
        try:
            resolved = ctx.domain_registry.resolve_domain_id(domain_id)
        except DomainNotFoundError as exc:
            raise ctx.HTTPException(status_code=400, detail=str(exc))

        # Helper to extract domain_roles from a physics JSON file
        def _extract_roles(dp_full: Path) -> list[dict[str, Any]]:
            dp_data = json.loads(dp_full.read_text(encoding="utf-8"))
            dr_block = dp_data.get("domain_roles", {})
            return [
                {
                    "role_id": r.get("role_id"),
                    "role_name": r.get("role_name"),
                    "hierarchy_level": r.get("hierarchy_level"),
                    "maps_to_system_role": r.get("maps_to_system_role"),
                    "default_access": r.get("default_access"),
                    "scoped_capabilities": r.get("scoped_capabilities", {}),
                }
                for r in dr_block.get("roles", [])
                if isinstance(r, dict)
            ]

        domain_roles: dict[str, Any] = {}

        # First: check the domain-level domain-physics.json
        try:
            entry = ctx.domain_registry._domains.get(resolved, {})
            cfg_path = Path(ctx.domain_registry._repo_root) / entry.get("runtime_config_path", "")
            raw = load_yaml(str(cfg_path))
            runtime_block = raw.get("runtime") or raw
            domain_dp_path = runtime_block.get("domain_physics_path", "")
            if domain_dp_path:
                dp_full = Path(ctx.domain_registry._repo_root) / domain_dp_path
                domain_pack_physics = dp_full.parent.parent.parent / "domain-physics.json"
                if domain_pack_physics.exists():
                    roles = _extract_roles(domain_pack_physics)
                    if roles:
                        domain_roles["_domain"] = {"roles": roles}
        except Exception:
            ctx.log.debug("Could not read domain-level physics for %s", resolved)

        # Then: collect from per-module physics files
        modules = ctx.domain_registry.list_modules_for_domain(resolved)
        for mod in modules:
            dp_path = mod.get("domain_physics_path", "")
            if not dp_path:
                continue
            try:
                dp_full = Path(ctx.domain_registry._repo_root) / dp_path
                roles = _extract_roles(dp_full)
                if roles:
                    domain_roles[mod["module_id"]] = {"roles": roles}
            except Exception:
                ctx.log.debug("Could not read domain physics for %s", mod.get("module_id"))
        return {"operation": operation, "domain_id": resolved, "domain_roles": domain_roles}

    if operation == "get_domain_module_manifest":
        domain_id = str(params.get("domain_id", target))
        if not domain_id:
            raise ctx.HTTPException(status_code=422, detail="domain_id required")
        try:
            resolved = ctx.domain_registry.resolve_domain_id(domain_id)
        except DomainNotFoundError as exc:
            raise ctx.HTTPException(status_code=400, detail=str(exc))
        modules = ctx.domain_registry.list_modules_for_domain(resolved)
        manifest_entries: list[dict[str, Any]] = []
        for mod in modules:
            dp_path = mod.get("domain_physics_path", "")
            entry: dict[str, Any] = {"module_id": mod["module_id"]}
            if dp_path:
                try:
                    dp_full = Path(ctx.domain_registry._repo_root) / dp_path
                    dp_data = json.loads(dp_full.read_text(encoding="utf-8"))
                    entry["label"] = dp_data.get("label", "")
                    entry["version"] = dp_data.get("version", "")
                    entry["description"] = dp_data.get("description", "")
                    entry["domain"] = dp_data.get("domain", resolved)
                except Exception:
                    pass
            manifest_entries.append(entry)
        return {"operation": operation, "domain_id": resolved, "modules": manifest_entries, "count": len(manifest_entries)}

    if operation == "list_users":
        assert get_domain_role_level is not None
        role_filter = params.get("role")
        domain_id_filter = params.get("domain_id", "")
        module_id_filter = params.get("module_id", "")
        domain_role_filter = params.get("domain_role", "")

        # Resolve domain_id to canonical name and get its module IDs
        domain_module_ids: set[str] | None = None
        if domain_id_filter:
            try:
                resolved_domain = ctx.domain_registry.resolve_domain_id(domain_id_filter)
            except DomainNotFoundError as exc:
                raise ctx.HTTPException(status_code=400, detail=str(exc))
            # DA boundary check: must govern the requested domain
            if user_data["role"] == "domain_authority" and not ctx.can_govern_domain(
                user_data, resolved_domain, registry=ctx.domain_registry
            ):
                raise ctx.HTTPException(status_code=403, detail="Not authorized for this domain")
            domain_modules = ctx.domain_registry.list_modules_for_domain(resolved_domain)
            domain_module_ids = {m["module_id"] for m in domain_modules}
        elif user_data["role"] == "domain_authority":
            # No domain_id given — scope to DA's own governed modules
            pass  # handled below in DA scoping block

        # Specific module filter — also enforce DA boundary
        if module_id_filter and user_data["role"] == "domain_authority":
            if not ctx.can_govern_domain(user_data, module_id_filter, registry=ctx.domain_registry):
                raise ctx.HTTPException(status_code=403, detail="Not authorized for this module")

        users = ctx.persistence.list_users()
        if role_filter:
            users = [u for u in users if u.get("role") == role_filter]

        # Domain-scoped filtering: DAs only see users in their governed modules.
        if user_data["role"] == "domain_authority":
            da_modules = set(user_data.get("governed_modules") or [])
            da_domain_roles = set((user_data.get("domain_roles") or {}).keys())
            da_scope = da_modules | da_domain_roles
            if da_scope:
                scoped: list[dict[str, Any]] = []
                for u in users:
                    u_modules = set(u.get("governed_modules") or [])
                    u_domain_roles = u.get("domain_roles") or {}
                    if u_modules & da_scope or set(u_domain_roles) & da_scope:
                        scoped.append(u)
                users = scoped

        # Apply domain_id filter (narrow to users in domain's modules)
        if domain_module_ids is not None:
            filtered: list[dict[str, Any]] = []
            for u in users:
                u_modules = set(u.get("governed_modules") or [])
                u_domain_roles = u.get("domain_roles") or {}
                if u_modules & domain_module_ids or set(u_domain_roles) & domain_module_ids:
                    filtered.append(u)
            users = filtered

        # Apply module_id filter (narrow to users in a specific module)
        if module_id_filter:
            users = [
                u for u in users
                if module_id_filter in (u.get("governed_modules") or [])
                or module_id_filter in (u.get("domain_roles") or {})
            ]

        # Apply domain_role filter (narrow to users with a specific domain role)
        if domain_role_filter:
            users = [
                u for u in users
                if domain_role_filter in (u.get("domain_roles") or {}).values()
            ]

        # ── Hierarchy-based visibility filter ─────────────────────
        _caller_role = user_data.get("role", "")
        _FULL_VISIBILITY_ROLES = frozenset({"root", "it_support", "domain_authority"})
        _strip_user_id = False
        if _caller_role not in _FULL_VISIBILITY_ROLES and domain_id_filter:
            caller_domain_roles = user_data.get("domain_roles") or {}
            caller_level: int | None = None
            for _mod_id, _dr in caller_domain_roles.items():
                _lvl = get_domain_role_level(domain_id_filter, _dr)
                if _lvl is not None:
                    caller_level = _lvl if caller_level is None else min(caller_level, _lvl)
            if caller_level is not None:
                if caller_level >= 3:
                    _visible_levels = {1, 2}
                    _strip_user_id = True
                elif caller_level == 2:
                    _visible_levels = {1, 3}
                elif caller_level == 1:
                    _visible_levels = {0, 1, 2, 3}
                else:
                    _visible_levels = None  # level 0 = DA, full view

                if _visible_levels is not None:
                    hierarchy_filtered: list[dict[str, Any]] = []
                    for u in users:
                        if u.get("user_id") == user_data.get("sub"):
                            continue
                        u_domain_roles = u.get("domain_roles") or {}
                        u_level: int | None = None
                        for _um, _ur in u_domain_roles.items():
                            _ul = get_domain_role_level(domain_id_filter, _ur)
                            if _ul is not None:
                                u_level = _ul if u_level is None else min(u_level, _ul)
                        if u_level is None:
                            u_sys_role = u.get("role", "")
                            if u_sys_role == "domain_authority":
                                u_level = 0
                        if u_level is not None and u_level in _visible_levels:
                            hierarchy_filtered.append(u)
                    users = hierarchy_filtered

        # Strip sensitive fields
        _strip_keys = {"password_hash", "invite_token", "invite_expires_at", "invite_token_expires_at"}
        if _strip_user_id:
            _strip_keys.add("user_id")
        safe_users = []
        for u in users:
            safe_users.append({
                k: v for k, v in u.items()
                if k not in _strip_keys
            })
        return {"operation": operation, "users": safe_users, "count": len(safe_users)}

    if operation == "list_daemon_tasks":
        from lumina.daemon import resource_monitor as _daemon_mod
        status = _daemon_mod.get_status()
        task_list: list[str] = []
        if _daemon_mod._daemon is not None and _daemon_mod._daemon._task_priority:
            task_list = list(_daemon_mod._daemon._task_priority)
        else:
            try:
                rt = load_yaml(Path("domain-packs/system/cfg/runtime-config.yaml"))
                task_list = rt.get("daemon", {}).get("task_priority", [])
            except Exception:
                pass
        return {
            "operation": operation,
            "tasks": task_list,
            "count": len(task_list),
            "daemon_state": status.get("state", "UNKNOWN"),
            "daemon_enabled": status.get("enabled", False),
        }

    return None
