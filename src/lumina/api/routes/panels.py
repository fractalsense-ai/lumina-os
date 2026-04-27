"""Generic panel data endpoints — domain-agnostic panel resolver.

Every panel declared in a domain pack's ``role_layouts`` specifies a
``data_source`` (and optional ``source_path``).  This module maps
generic data-source names to resolvers that return JSON payloads.
Domain packs control *which* panels a role sees and *where* in the
profile the data lives — this module never references domain-specific
terminology.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Awaitable

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from starlette.concurrency import run_in_threadpool

from lumina.api import config as _cfg
from lumina.api.middleware import _bearer_scheme, get_current_user, require_auth
from lumina.core.pack_identity import get_model_pack_id

log = logging.getLogger("lumina-api")

router = APIRouter()

# Type alias for resolver functions
_Resolver = Callable[
    [dict[str, Any], dict[str, Any], dict[str, Any]],
    Awaitable[dict[str, Any]],
]


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def _load_profile(user_id: str, domain_key: str = "") -> dict[str, Any]:
    """Load a user profile.

    Tries the key-based persistence store first (DB backend).
    Falls back to path-based loading for backward compatibility.
    """
    if domain_key:
        profile = _cfg.PERSISTENCE.load_profile(user_id, domain_key)
        if profile is not None:
            return profile
        # Fall back to path-based loading
        from lumina.api.config import _resolve_user_profile_path
        path = str(_resolve_user_profile_path(user_id, domain_key))
    else:
        path = str(Path("data/profiles") / f"{user_id}.yaml")
    try:
        profile = _cfg.PERSISTENCE.load_subject_profile(path)
    except Exception:
        profile = {}
    return profile if isinstance(profile, dict) else {}


def _follow_path(data: dict[str, Any], dotted: str) -> Any:
    """Follow a dot-separated key path through nested dicts."""
    current: Any = data
    for part in dotted.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def _resolve_caller_layout(
    user_data: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
    """Resolve the caller's effective role layout from the domain pack.

    Returns ``(layout, sidebar_panels, domain_id)``.
    """
    from lumina.api.routes.system import _resolve_role_layout

    domain_id = _cfg.DOMAIN_REGISTRY.resolve_default_for_user(user_data)
    runtime = _cfg.DOMAIN_REGISTRY.get_runtime_context(domain_id)
    manifest = runtime.get("ui_manifest") or {}
    layout = _resolve_role_layout(manifest, user_data, {"id": domain_id})
    return layout, layout.get("sidebar_panels") or [], domain_id


def _find_panel_config(
    panels: list[dict[str, Any]], panel_id: str,
) -> dict[str, Any] | None:
    """Find a panel declaration by ID in the resolved layout."""
    for p in panels:
        if p.get("id") == panel_id:
            return p
    return None


def _resolve_da_governed(user_data: dict[str, Any]) -> set[str] | None:
    """Return the effective governed-module set for an admin.

    Returns ``None`` for non-DA roles (meaning no filtering needed).
    Unrestricted DAs (empty ``governed_modules`` *and* empty
    ``domain_roles``) are resolved to *all* modules in their default
    domain so panel resolvers return real data.
    """
    if user_data.get("role") != "admin":
        return None
    governed = set(user_data.get("governed_modules") or [])
    domain_roles = user_data.get("domain_roles") or {}
    if governed or domain_roles:
        governed |= set(domain_roles.keys())
    else:
        # Unrestricted DA — resolve all modules in their default domain
        default_domain = _cfg.DOMAIN_REGISTRY.resolve_default_for_user(user_data)
        governed.add(default_domain)
        try:
            rt = _cfg.DOMAIN_REGISTRY.get_runtime_context(default_domain)
            governed |= set(rt.get("module_map") or {})
        except Exception:
            pass
        return governed
    # Expand to include bare domain_ids for domains containing governed modules
    for d in _cfg.DOMAIN_REGISTRY.list_domains():
        did = d.get("domain_id", "")
        try:
            rt = _cfg.DOMAIN_REGISTRY.get_runtime_context(did)
            if governed & set(rt.get("module_map") or {}):
                governed.add(did)
        except Exception:
            pass
    return governed


# ─────────────────────────────────────────────────────────────
# Generic data-source resolvers
# ─────────────────────────────────────────────────────────────
# Each resolver takes (user_data, caller_profile, panel_config).

async def _resolve_self_profile(
    user_data: dict[str, Any], profile: dict[str, Any], pcfg: dict[str, Any],
) -> dict[str, Any]:
    """Caller's own profile summary."""
    prefs = profile.get("preferences") or {}
    modules = profile.get("modules") if isinstance(profile.get("modules"), dict) else {}
    module_ids = set(modules.keys())
    # Also include governed_modules from the user record
    try:
        user_rec = await run_in_threadpool(_cfg.PERSISTENCE.get_user, user_data["sub"])
        module_ids |= set((user_rec or {}).get("governed_modules") or [])
    except Exception:
        pass
    return {
        "panel": pcfg.get("id", "self_profile"),
        "user_id": user_data["sub"],
        "display_name": profile.get("display_name") or profile.get("name") or user_data["sub"],
        "role": user_data.get("role", ""),
        "preferences": dict(prefs),
        "assigned_modules": sorted(module_ids),
    }


async def _resolve_self_modules(
    user_data: dict[str, Any], profile: dict[str, Any], pcfg: dict[str, Any],
) -> dict[str, Any]:
    """Caller's module list with state summaries.

    Merges modules from two sources so newly-assigned modules appear
    even before the student has interacted with them:

    1. ``profile["modules"]`` — modules with session state (turn history).
    2. ``user_rec["governed_modules"]`` — modules assigned via /assign.
    """
    modules = profile.get("modules") if isinstance(profile.get("modules"), dict) else {}

    # Also include governed_modules from the user record
    user_id = user_data["sub"]
    try:
        user_rec = await run_in_threadpool(_cfg.PERSISTENCE.get_user, user_id)
        governed = set((user_rec or {}).get("governed_modules") or [])
    except Exception:
        governed = set()

    summaries = []
    seen: set[str] = set()
    for mk, mv in modules.items():
        entry: dict[str, Any] = {"module_id": mk}
        if isinstance(mv, dict):
            entry["turn_count"] = int(mv.get("turn_count", 0))
            if "mastery" in mv:
                entry["mastery_level"] = mv["mastery"] if isinstance(mv["mastery"], (int, float, str)) else "present"
        summaries.append(entry)
        seen.add(mk)

    # Append governed modules not yet in profile (no session state yet)
    for gm in sorted(governed - seen):
        summaries.append({"module_id": gm, "turn_count": 0})

    return {
        "panel": pcfg.get("id", "self_modules"),
        "user_id": user_data["sub"],
        "modules": summaries,
    }


async def _resolve_self_preferences(
    user_data: dict[str, Any], profile: dict[str, Any], pcfg: dict[str, Any],
) -> dict[str, Any]:
    """Caller's preferences object."""
    prefs = profile.get("preferences") or {}
    return {
        "panel": pcfg.get("id", "self_preferences"),
        "user_id": user_data["sub"],
        "preferences": dict(prefs),
    }


async def _resolve_managed_users(
    user_data: dict[str, Any], profile: dict[str, Any], pcfg: dict[str, Any],
) -> dict[str, Any]:
    """Users managed by the caller — reads user IDs from ``source_path``."""
    source_path = pcfg.get("source_path", "")
    user_ids = _follow_path(profile, source_path) if source_path else []
    if not isinstance(user_ids, list):
        user_ids = []
    users = []
    for uid in user_ids:
        u = await run_in_threadpool(_cfg.PERSISTENCE.get_user, str(uid))
        users.append({
            "user_id": str(uid),
            "display_name": (u or {}).get("display_name", str(uid)),
        })
    return {
        "panel": pcfg.get("id", "managed_users"),
        "user_id": user_data["sub"],
        "count": len(users),
        "users": users,
    }


async def _resolve_managed_user_progress(
    user_data: dict[str, Any], profile: dict[str, Any], pcfg: dict[str, Any],
) -> dict[str, Any]:
    """Module progress for users managed by the caller."""
    source_path = pcfg.get("source_path", "")
    user_ids = _follow_path(profile, source_path) if source_path else []
    if not isinstance(user_ids, list):
        user_ids = []
    progress = []
    for uid in user_ids:
        uid_str = str(uid)
        uprof = await run_in_threadpool(_load_profile, uid_str, pcfg.get("_domain_id", ""))
        modules = uprof.get("modules") if isinstance(uprof.get("modules"), dict) else {}
        progress.append({
            "user_id": uid_str,
            "display_name": uprof.get("display_name") or uprof.get("name") or uid_str,
            "modules": [
                {"module_id": mk, "turn_count": int((mv if isinstance(mv, dict) else {}).get("turn_count", 0))}
                for mk, mv in modules.items()
            ],
        })
    return {
        "panel": pcfg.get("id", "managed_user_progress"),
        "user_id": user_data["sub"],
        "users": progress,
    }


async def _resolve_governed_modules(
    user_data: dict[str, Any], profile: dict[str, Any], pcfg: dict[str, Any],
) -> dict[str, Any]:
    """Modules the caller governs (from domain roles)."""
    governed = list((user_data.get("domain_roles") or {}).keys())
    return {
        "panel": pcfg.get("id", "governed_modules"),
        "governed_modules": governed,
    }


async def _resolve_domain_overview(
    user_data: dict[str, Any], profile: dict[str, Any], pcfg: dict[str, Any],
) -> dict[str, Any]:
    """Domain inventory — shape varies by role.

    System-track (root / super_admin): domain-centric with domain_count.
    Domain-track (admin): module-centric with module_count,
    active student and staff counts.
    """
    if user_data.get("role") not in ("root", "admin", "super_admin"):
        raise HTTPException(status_code=403, detail="Insufficient system role")

    governed = _resolve_da_governed(user_data)

    # ── DA gets a module-centric overview ──────────────────────
    if governed is not None:
        all_domains = _cfg.DOMAIN_REGISTRY.list_domains()
        modules: list[dict[str, Any]] = []
        for d in all_domains:
            did = d.get("domain_id", "")
            try:
                rt = _cfg.DOMAIN_REGISTRY.get_runtime_context(did)
                for mk in (rt.get("module_map") or {}):
                    if mk in governed:
                        modules.append({"module_id": mk, "domain_id": did})
            except Exception:
                pass
        # Count active students / staff from persistence
        all_users = await run_in_threadpool(_cfg.PERSISTENCE.list_users)
        active_students = 0
        active_staff = 0
        for u in (all_users or []):
            d_roles = u.get("domain_roles") or {}
            for mid, rid in d_roles.items():
                if mid not in governed:
                    continue
                if rid == "student":
                    active_students += 1
                elif rid in ("teacher", "teaching_assistant", "domain_authority"):
                    active_staff += 1
                break  # count each user once
        # Also count system-role admins whose governed scope overlaps
        for u in (all_users or []):
            if u.get("role") != "admin":
                continue
            if u.get("domain_roles"):
                continue  # already counted above if applicable
            u_gov = set(u.get("governed_modules") or [])
            if not u_gov or (u_gov & governed):
                active_staff += 1
        return {
            "panel": pcfg.get("id", "domain_overview"),
            "module_count": len(modules),
            "modules": modules,
            "active_students": active_students,
            "active_staff": active_staff,
        }

    # ── System-track: domain-centric overview ──────────────────
    all_domains = _cfg.DOMAIN_REGISTRY.list_domains()
    return {
        "panel": pcfg.get("id", "domain_overview"),
        "domain_count": len(all_domains),
        "domains": [{"domain_id": d.get("domain_id", ""), "label": d.get("label", "")} for d in all_domains],
    }


async def _resolve_user_directory(
    user_data: dict[str, Any], profile: dict[str, Any], pcfg: dict[str, Any],
) -> dict[str, Any]:
    """User directory — requires elevated system role."""
    if user_data.get("role") not in ("root", "admin", "super_admin"):
        raise HTTPException(status_code=403, detail="Insufficient system role")
    users = await run_in_threadpool(_cfg.PERSISTENCE.list_users)
    return {
        "panel": pcfg.get("id", "user_directory"),
        "users": [
            {"display_name": u.get("display_name") or u.get("username") or u.get("user_id", "")}
            for u in (users or [])
        ],
    }


async def _resolve_module_directory(
    user_data: dict[str, Any], profile: dict[str, Any], pcfg: dict[str, Any],
) -> dict[str, Any]:
    """Module inventory — requires elevated system role."""
    if user_data.get("role") not in ("root", "admin", "super_admin"):
        raise HTTPException(status_code=403, detail="Insufficient system role")
    governed = _resolve_da_governed(user_data)
    all_domains = _cfg.DOMAIN_REGISTRY.list_domains()
    modules = []
    for d in all_domains:
        did = d.get("domain_id", "")
        try:
            rt = _cfg.DOMAIN_REGISTRY.get_runtime_context(did)
            for mk in (rt.get("module_map") or {}):
                if governed is not None and mk not in governed:
                    continue
                modules.append({"domain_id": did, "module_id": mk})
        except Exception:
            pass
    return {
        "panel": pcfg.get("id", "module_directory"),
        "modules": modules,
    }


async def _resolve_notification_settings(
    user_data: dict[str, Any], profile: dict[str, Any], pcfg: dict[str, Any],
) -> dict[str, Any]:
    """Caller's notification preferences from ``source_path``."""
    source_path = pcfg.get("source_path", "notification_preferences")
    prefs = _follow_path(profile, source_path) or {}
    if not isinstance(prefs, dict):
        prefs = {}
    return {
        "panel": pcfg.get("id", "notification_settings"),
        "user_id": user_data["sub"],
        "preferences": prefs,
    }


async def _resolve_empty_queue(
    user_data: dict[str, Any], profile: dict[str, Any], pcfg: dict[str, Any],
) -> dict[str, Any]:
    """Placeholder: empty request queue."""
    return {
        "panel": pcfg.get("id", "empty_queue"),
        "items": [],
    }


async def _resolve_escalation_queue(
    user_data: dict[str, Any], profile: dict[str, Any], pcfg: dict[str, Any],
) -> dict[str, Any]:
    """Escalation queue — pending escalations scoped by caller's domain role.

    Education-domain escalations route to teachers (via
    ``receive_escalations`` in domain-physics), not to system-level roles.
    This resolver delegates to the domain's own API route at
    ``/api/escalations`` when available, but provides a direct persistence
    fallback filtered by the caller's domain-role scope.
    """
    domain_id = _cfg.DOMAIN_REGISTRY.resolve_default_for_user(user_data)

    # Determine which modules the caller can receive escalations for.
    # Domain-role holders (teacher, admin) see escalations for
    # their assigned modules; system admins see everything.
    domain_roles_map = user_data.get("domain_roles") or {}
    governed = _resolve_da_governed(user_data)
    system_admin = user_data.get("role") in ("root", "super_admin", "operator", "half_operator")

    if not system_admin and not governed and not domain_roles_map:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    records = await run_in_threadpool(
        _cfg.PERSISTENCE.query_escalations,
        status="pending",
        domain_id=domain_id if not system_admin else None,
        limit=100,
        offset=0,
    )

    # Scope by governed modules (DA) or assigned domain roles (teacher)
    if governed is not None:
        records = [r for r in records if get_model_pack_id(r) in governed]
    elif not system_admin:
        records = [r for r in records if get_model_pack_id(r) in domain_roles_map]

    return {
        "panel": pcfg.get("id", "escalation_queue"),
        "escalations": records,
        "count": len(records),
    }


async def _resolve_staff_directory(
    user_data: dict[str, Any], profile: dict[str, Any], pcfg: dict[str, Any],
) -> dict[str, Any]:
    """Staff visible to the domain authority — teachers, TAs, and DAs."""
    if user_data.get("role") not in ("root", "admin", "super_admin"):
        raise HTTPException(status_code=403, detail="Insufficient system role")
    governed = _resolve_da_governed(user_data)
    all_users = await run_in_threadpool(_cfg.PERSISTENCE.list_users)
    staff: list[dict[str, Any]] = []
    _seen_ids: set[str] = set()
    for u in (all_users or []):
        uid = u.get("user_id", "")
        d_roles = u.get("domain_roles") or {}
        for _mid, _rid in d_roles.items():
            if _rid in ("teacher", "teaching_assistant", "domain_authority"):
                if governed is not None and _mid not in governed:
                    continue
                staff.append({
                    "display_name": u.get("display_name") or u.get("username") or uid,
                    "domain_role": _rid,
                    "module_id": _mid,
                })
                _seen_ids.add(uid)
                break  # one entry per user
    # Include system-role DAs who lack domain_roles entries
    for u in (all_users or []):
        uid = u.get("user_id", "")
        if uid in _seen_ids:
            continue
        if u.get("role") != "admin":
            continue
        u_gov = set(u.get("governed_modules") or [])
        if governed is not None and u_gov and not (u_gov & governed):
            continue  # scoped to a different domain
        staff.append({
            "display_name": u.get("display_name") or u.get("username") or uid,
            "domain_role": "admin",
            "module_id": "",
        })
    return {
        "panel": pcfg.get("id", "staff_directory"),
        "staff": staff,
    }


# ─────────────────────────────────────────────────────────────
# Resolver registry — maps data_source names to functions
# ─────────────────────────────────────────────────────────────

_DATA_RESOLVERS: dict[str, _Resolver] = {
    "self_profile": _resolve_self_profile,
    "self_modules": _resolve_self_modules,
    "self_preferences": _resolve_self_preferences,
    "managed_users": _resolve_managed_users,
    "managed_user_progress": _resolve_managed_user_progress,
    "governed_modules": _resolve_governed_modules,
    "domain_overview": _resolve_domain_overview,
    "user_directory": _resolve_user_directory,
    "module_directory": _resolve_module_directory,
    "notification_settings": _resolve_notification_settings,
    "empty_queue": _resolve_empty_queue,
    "escalation_queue": _resolve_escalation_queue,
    "staff_directory": _resolve_staff_directory,
}


# ─────────────────────────────────────────────────────────────
# Generic panel endpoints
# ─────────────────────────────────────────────────────────────

@router.get("/api/panels/{panel_id}")
async def get_panel_data(
    panel_id: str,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict[str, Any]:
    """Resolve panel data from a domain-pack role-layout declaration."""
    current = await get_current_user(credentials)
    user_data = require_auth(current)

    # Verify panel is in the caller's resolved layout
    _layout, panels, domain_id = _resolve_caller_layout(user_data)
    pcfg = _find_panel_config(panels, panel_id)
    if pcfg is None:
        raise HTTPException(status_code=404, detail=f"Panel not available: {panel_id}")

    data_source = pcfg.get("data_source", panel_id)
    resolver = _DATA_RESOLVERS.get(data_source)
    if resolver is None:
        raise HTTPException(status_code=404, detail=f"Unknown data source: {data_source}")

    profile = await run_in_threadpool(_load_profile, user_data["sub"], domain_id)
    # Inject domain_id so resolvers that load sub-profiles can use it.
    pcfg = {**pcfg, "_domain_id": domain_id}
    return await resolver(user_data, profile, pcfg)


@router.patch("/api/panels/{panel_id}")
async def update_panel_data(
    panel_id: str,
    body: dict[str, Any],
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict[str, Any]:
    """Update panel data — currently supports ``self_preferences`` only."""
    current = await get_current_user(credentials)
    user_data = require_auth(current)
    caller_id = user_data["sub"]

    _layout, panels, domain_id = _resolve_caller_layout(user_data)
    pcfg = _find_panel_config(panels, panel_id)
    if pcfg is None:
        raise HTTPException(status_code=404, detail=f"Panel not available: {panel_id}")

    data_source = pcfg.get("data_source", panel_id)
    if data_source != "self_preferences":
        raise HTTPException(status_code=405, detail="PATCH not supported for this panel")

    updates = body.get("updates") or body
    if not isinstance(updates, dict) or not updates:
        raise HTTPException(status_code=422, detail="Request body must contain preference updates")

    from lumina.api.config import _resolve_user_profile_path
    profile_path = str(_resolve_user_profile_path(caller_id, domain_id)) if domain_id else str(Path("data/profiles") / f"{caller_id}.yaml")
    try:
        profile = await run_in_threadpool(_cfg.PERSISTENCE.load_subject_profile, profile_path)
    except Exception:
        profile = {}
    if not isinstance(profile, dict):
        profile = {}

    prefs = profile.setdefault("preferences", {})
    for k, v in updates.items():
        prefs[k] = v

    await run_in_threadpool(_cfg.PERSISTENCE.save_subject_profile, profile_path, profile)

    return {
        "panel": panel_id,
        "status": "updated",
        "updated_fields": list(updates.keys()),
    }
