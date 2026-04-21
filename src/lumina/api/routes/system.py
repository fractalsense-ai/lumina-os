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


# ── Role-layout resolution ──────────────────────────────────

def _resolve_role_layout(
    manifest: dict[str, Any],
    user: dict[str, Any] | None,
    domain: dict[str, Any],
) -> dict[str, Any]:
    """Flatten the ``role_layouts`` inheritance chain for the current user.

    Returns a dict with ``sidebar_panels`` (list) and ``capabilities`` (list)
    that the frontend uses to render the correct UI.  Unauthenticated
    requests receive the most restrictive layout (student / empty).
    """
    from lumina.api.config import _SYSTEM_ROLE_TO_DOMAIN_ROLE

    role_layouts: dict[str, Any] = manifest.get("role_layouts") or {}
    if not role_layouts:
        return {"sidebar_panels": [], "capabilities": [], "effective_role": None}

    # Determine the user's effective domain role
    effective_role: str | None = None
    if user is not None:
        system_role = user.get("role", "user")
        # Try explicit domain_roles from JWT first
        domain_roles_map = user.get("domain_roles") or {}
        domain_id_prefix = domain.get("id", "")
        for key, val in domain_roles_map.items():
            if domain_id_prefix and domain_id_prefix in key:
                effective_role = val
                break
            # Bare domain ID match (e.g. "education")
            parts = domain_id_prefix.split("/")
            if len(parts) >= 2 and key == parts[1]:
                effective_role = val
                break
        # Fallback: map system role to domain role via domain pack config,
        # then fall back to _SYSTEM_ROLE_TO_DOMAIN_ROLE mapping.
        if not effective_role:
            pack_mapping = manifest.get("system_role_to_domain_role") or {}
            effective_role = pack_mapping.get(system_role) or _SYSTEM_ROLE_TO_DOMAIN_ROLE.get(system_role)

    # No match → empty layout (no panels, no capabilities)
    if effective_role is None or effective_role not in role_layouts:
        return {"sidebar_panels": [], "capabilities": [], "effective_role": effective_role}

    # Flatten the inherits chain (guard against cycles)
    panels: list[dict[str, Any]] = []
    capabilities: list[str] = []
    seen_ids: set[str] = set()
    visited: set[str] = set()
    current: str | None = effective_role

    while current and current not in visited:
        visited.add(current)
        layout = role_layouts.get(current)
        if layout is None:
            break
        # Prepend inherited panels (parent panels come first)
        for panel in reversed(layout.get("sidebar_panels") or []):
            pid = panel.get("id", "")
            if pid not in seen_ids:
                panels.insert(0, panel)
                seen_ids.add(pid)
        for cap in layout.get("capabilities") or []:
            if cap not in capabilities:
                capabilities.append(cap)
        current = layout.get("inherits")

    return {
        "sidebar_panels": panels,
        "capabilities": capabilities,
        "effective_role": effective_role,
    }


@router.get("/api/health")
async def health() -> dict[str, Any]:
    from lumina.daemon.resource_monitor import get_status as _daemon_status
    return {"status": "ok", "provider": _cfg.LLM_PROVIDER, "daemon": _daemon_status()}


@router.get("/api/health/load")
async def health_load(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict[str, Any]:
    """Return current load snapshot.  Requires root or auditor role."""
    user = await get_current_user(credentials)
    if user is not None:
        require_role(user, "root", "auditor")
    from lumina.daemon.resource_monitor import get_status as _daemon_status
    return _daemon_status()


@router.get("/api/domains")
async def list_domains() -> list[dict[str, Any]]:
    return _cfg.DOMAIN_REGISTRY.list_domains()


@router.get("/api/domain-info")
async def domain_info(
    domain_id: str | None = None,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict[str, Any]:
    user = await get_current_user(credentials)
    try:
        if domain_id is not None:
            resolved = _cfg.DOMAIN_REGISTRY.resolve_domain_id(domain_id)
        elif user is not None:
            resolved = _cfg.DOMAIN_REGISTRY.resolve_default_for_user(user)
        else:
            resolved = _cfg.DOMAIN_REGISTRY.resolve_domain_id(None)
    except DomainNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    runtime = _cfg.DOMAIN_REGISTRY.get_runtime_context(resolved)
    domain_physics_path = runtime["domain_physics_path"]

    # ── Role-based module routing ──
    _role_mod: str | None = None
    if user is not None:
        from lumina.api.config import _SYSTEM_ROLE_TO_DOMAIN_ROLE, _resolve_user_profile_path
        _user_dr = user.get("domain_roles") or {}
        _eff_role = _user_dr.get(resolved)
        if not _eff_role:
            # Fallback: scan for module-ID keys belonging to this domain
            _mm = runtime.get("module_map") or {}
            for _mk in _mm:
                if _mk in _user_dr:
                    _eff_role = _user_dr[_mk]
                    break
        if not _eff_role:
            _pack_role_map = (runtime.get("ui_manifest") or {}).get("system_role_to_domain_role") or {}
            _eff_role = _pack_role_map.get(user.get("role", "")) or _SYSTEM_ROLE_TO_DOMAIN_ROLE.get(user.get("role", ""))
        _r2m = runtime.get("role_to_default_module") or {}
        _mm = runtime.get("module_map") or {}
        _role_mod = _r2m.get(_eff_role or "")
        if _role_mod and _role_mod in _mm:
            domain_physics_path = _mm[_role_mod]["domain_physics_path"]

        # ── Profile-aware module override ──
        # If the user already has a profile with a domain_id pointing to a
        # specific module, honour that instead of the generic role default.
        try:
            _profile_path = _resolve_user_profile_path(str(user["sub"]), resolved)
            if _profile_path.exists():
                _prof = _cfg.PERSISTENCE.load_subject_profile(str(_profile_path))
                _prof_domain_id = _prof.get("domain_id") or _prof.get("subject_domain_id")
                if _prof_domain_id and _prof_domain_id in _mm:
                    _role_mod = _prof_domain_id
                    domain_physics_path = _mm[_prof_domain_id]["domain_physics_path"]
        except Exception:
            pass  # graceful fallback — role-based routing still applies

    domain = _cfg.PERSISTENCE.load_domain_physics(str(domain_physics_path))
    manifest = dict(runtime.get("ui_manifest") or {})

    # ── Apply per-module UI overrides (e.g. subtitle per role) ──
    _mm = runtime.get("module_map") or {}
    if _role_mod and _role_mod in _mm:
        _ui_ov = _mm[_role_mod].get("ui_overrides")
        if isinstance(_ui_ov, dict):
            manifest = {**manifest, **_ui_ov}

    # ── Resolve role-based layout for the authenticated user ──
    role_layout = _resolve_role_layout(manifest, user, domain)

    resp: dict[str, Any] = {
        "domain_id": domain.get("id", "unknown"),
        "domain_key": resolved,
        "domain_version": domain.get("version", "unknown"),
        "ui_manifest": manifest,
        "role_layout": role_layout,
    }

    # ── Expose domain-pack UI plugin metadata (plugin_bundle, slash_commands, dashboard_tabs) ──
    ui_plugin = runtime.get("ui_plugin")
    if isinstance(ui_plugin, dict):
        resp["ui_plugin"] = ui_plugin

    return resp


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
        if module_perms:
            user_domain_roles = user.get("domain_roles") or {}
            mod_id = runtime.get("module_id", resolved)
            user_dr = user_domain_roles.get(mod_id) or user_domain_roles.get(resolved)
            if not check_permission(
                user_id=user["sub"],
                user_role=user["role"],
                module_permissions=module_perms,
                operation=Operation.EXECUTE,
                domain_role=user_dr,
                domain_roles_config=domain.get("domain_roles"),
                groups_config=domain.get("groups"),
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
        require_role(user, "root", "admin", "super_admin", "operator", "half_operator")
    try:
        result = await run_in_threadpool(_cfg.PERSISTENCE.validate_log_chain, session_id)
    except Exception as exc:
        log.exception("System Log validation failed")
        raise HTTPException(status_code=500, detail=str(exc))
    return SystemLogValidateResponse(result=result)
