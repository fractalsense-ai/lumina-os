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

def _load_profile(user_id: str) -> dict[str, Any]:
    """Load a user profile by flat path."""
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
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Resolve the caller's effective role layout from the domain pack."""
    from lumina.api.routes.system import _resolve_role_layout

    domain_id = _cfg.DOMAIN_REGISTRY.resolve_default_for_user(user_data)
    runtime = _cfg.DOMAIN_REGISTRY.get_runtime_context(domain_id)
    manifest = runtime.get("ui_manifest") or {}
    layout = _resolve_role_layout(manifest, user_data, {"id": domain_id})
    return layout, layout.get("sidebar_panels") or []


def _find_panel_config(
    panels: list[dict[str, Any]], panel_id: str,
) -> dict[str, Any] | None:
    """Find a panel declaration by ID in the resolved layout."""
    for p in panels:
        if p.get("id") == panel_id:
            return p
    return None


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
    return {
        "panel": pcfg.get("id", "self_profile"),
        "user_id": user_data["sub"],
        "display_name": profile.get("display_name") or profile.get("name") or user_data["sub"],
        "role": user_data.get("role", ""),
        "preferences": dict(prefs),
        "assigned_modules": list(modules.keys()),
    }


async def _resolve_self_modules(
    user_data: dict[str, Any], profile: dict[str, Any], pcfg: dict[str, Any],
) -> dict[str, Any]:
    """Caller's module list with state summaries."""
    modules = profile.get("modules") if isinstance(profile.get("modules"), dict) else {}
    summaries = []
    for mk, mv in modules.items():
        entry: dict[str, Any] = {"module_id": mk}
        if isinstance(mv, dict):
            entry["turn_count"] = int(mv.get("turn_count", 0))
            if "mastery" in mv:
                entry["mastery_level"] = mv["mastery"] if isinstance(mv["mastery"], (int, float, str)) else "present"
        summaries.append(entry)
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
        uprof = await run_in_threadpool(_load_profile, uid_str)
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
    """Domain inventory — requires elevated system role."""
    if user_data.get("role") not in ("root", "domain_authority", "it_support"):
        raise HTTPException(status_code=403, detail="Insufficient system role")
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
    if user_data.get("role") not in ("root", "domain_authority", "it_support"):
        raise HTTPException(status_code=403, detail="Insufficient system role")
    users = await run_in_threadpool(_cfg.PERSISTENCE.list_users)
    return {
        "panel": pcfg.get("id", "user_directory"),
        "users": [
            {"user_id": u.get("user_id", ""), "display_name": u.get("display_name", u.get("user_id", ""))}
            for u in (users or [])
        ],
    }


async def _resolve_module_directory(
    user_data: dict[str, Any], profile: dict[str, Any], pcfg: dict[str, Any],
) -> dict[str, Any]:
    """Module inventory — requires elevated system role."""
    if user_data.get("role") not in ("root", "domain_authority", "it_support"):
        raise HTTPException(status_code=403, detail="Insufficient system role")
    all_domains = _cfg.DOMAIN_REGISTRY.list_domains()
    modules = []
    for d in all_domains:
        did = d.get("domain_id", "")
        try:
            rt = _cfg.DOMAIN_REGISTRY.get_runtime_context(did)
            for mk in (rt.get("module_map") or {}):
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


async def _resolve_staff_directory(
    user_data: dict[str, Any], profile: dict[str, Any], pcfg: dict[str, Any],
) -> dict[str, Any]:
    """Teachers + TAs visible to the domain authority."""
    if user_data.get("role") not in ("root", "domain_authority", "it_support"):
        raise HTTPException(status_code=403, detail="Insufficient system role")
    all_users = await run_in_threadpool(_cfg.PERSISTENCE.list_users)
    staff: list[dict[str, Any]] = []
    for u in all_users:
        uid = u.get("sub") or u.get("user_id", "")
        d_roles = u.get("domain_roles") or {}
        for _mid, _rid in d_roles.items():
            if _rid in ("teacher", "teaching_assistant"):
                staff.append({
                    "user_id": uid,
                    "display_name": u.get("display_name", uid),
                    "domain_role": _rid,
                    "module_id": _mid,
                })
                break  # one entry per user
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
    _layout, panels = _resolve_caller_layout(user_data)
    pcfg = _find_panel_config(panels, panel_id)
    if pcfg is None:
        raise HTTPException(status_code=404, detail=f"Panel not available: {panel_id}")

    data_source = pcfg.get("data_source", panel_id)
    resolver = _DATA_RESOLVERS.get(data_source)
    if resolver is None:
        raise HTTPException(status_code=404, detail=f"Unknown data source: {data_source}")

    profile = await run_in_threadpool(_load_profile, user_data["sub"])
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

    _layout, panels = _resolve_caller_layout(user_data)
    pcfg = _find_panel_config(panels, panel_id)
    if pcfg is None:
        raise HTTPException(status_code=404, detail=f"Panel not available: {panel_id}")

    data_source = pcfg.get("data_source", panel_id)
    if data_source != "self_preferences":
        raise HTTPException(status_code=405, detail="PATCH not supported for this panel")

    updates = body.get("updates") or body
    if not isinstance(updates, dict) or not updates:
        raise HTTPException(status_code=422, detail="Request body must contain preference updates")

    profile_path = str(Path("data/profiles") / f"{caller_id}.yaml")
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
