"""Invite operation: invite_user."""

from __future__ import annotations

import os
import time
import uuid as _uuid_mod
from typing import Any

from lumina.api.admin_context import AdminOperationContext
from lumina.auth.auth import VALID_ROLES
from lumina.core.email_sender import send_invite_email
from lumina.core.invite_store import (
    generate_invite_token,
    _INVITE_TOKEN_TTL_SECONDS as _INVITE_TOKEN_TTL,
)


async def execute(
    operation: str,
    params: dict[str, Any],
    user_data: dict[str, Any],
    ctx: AdminOperationContext,
    *,
    parsed: dict[str, Any] | None = None,
    **kw: Any,
) -> dict[str, Any] | None:
    if operation != "invite_user":
        return None

    parsed = parsed or {}
    target = parsed.get("target", "")

    # See: docs/7-concepts/domain-role-hierarchy.md
    # See: docs/7-concepts/domain-adapter-pattern.md
    if user_data["role"] not in ("root", "it_support", "domain_authority"):
        raise ctx.HTTPException(status_code=403, detail="Only root, it_support, or domain_authority can invite users")
    username = str(params.get("username", target))
    role = str(params.get("role", "user"))
    governed_modules_raw = params.get("governed_modules")
    # None / absent means "all modules" for DA; [] means explicitly empty; present list → validate
    if governed_modules_raw is None:
        governed_modules = None  # explicit null or absent = all modules for DA
    else:
        governed_modules: list[str] = list(governed_modules_raw) if governed_modules_raw else []
    email = str(params.get("email", "")) or None

    # Validate governed_modules against real module IDs (only when
    # the registry is populated — skip in minimal/test environments).
    if governed_modules and ctx.domain_registry is not None:
        _known_modules: set[str] = set()
        for _dom in (ctx.domain_registry.list_domains() or []):
            for _m in (ctx.domain_registry.list_modules_for_domain(_dom.get("domain_id", "")) or []):
                _known_modules.add(_m["module_id"])
        if _known_modules:  # only enforce when registry is populated
            _invalid = [m for m in governed_modules if m not in _known_modules]
            if _invalid:
                raise ctx.HTTPException(
                    status_code=422,
                    detail=f"Unknown governed_modules: {_invalid}. Use list_modules to see valid IDs.",
                )

    if not username:
        raise ctx.HTTPException(status_code=422, detail="username required")
    if role not in VALID_ROLES:
        raise ctx.HTTPException(status_code=400, detail=f"Invalid role: {role}")
    # domain_authority with governed_modules=None means access to ALL
    # modules in their domain. This is intentional — DAs are the
    # subject-matter experts / domain administrators.
    # An explicit empty list [] is rejected — use None for "all".
    if role == "domain_authority" and governed_modules is not None and len(governed_modules) == 0:
        raise ctx.HTTPException(
            status_code=400,
            detail="governed_modules is required when role is domain_authority (use null for all modules)",
        )

    # DA-scoped invite: domain_authority can only invite "user" role within their governed modules
    if user_data["role"] == "domain_authority":
        if role not in ("user", "guest"):
            raise ctx.HTTPException(
                status_code=403,
                detail="Domain authority can only invite users with 'user' or 'guest' role",
            )
        da_governed = set(user_data.get("governed_modules") or [])
        if governed_modules and not set(governed_modules).issubset(da_governed):
            raise ctx.HTTPException(
                status_code=403,
                detail="Cannot invite user to modules outside your governed scope",
            )

    existing = await ctx.run_in_threadpool(ctx.persistence.get_user_by_username, username)
    if existing is not None:
        raise ctx.HTTPException(status_code=409, detail="Username already taken")

    # ── Auto-assign default module for non-DA users without modules ──
    if role != "domain_authority" and not governed_modules and ctx.domain_registry is not None:
        _idr = params.get("intended_domain_role", "")
        _domain_hint = params.get("domain_id", "")
        if not _domain_hint and _idr:
            pass
        if _domain_hint:
            try:
                _resolved_dom = ctx.domain_registry.resolve_domain_id(_domain_hint)
                _default_mod = ctx.domain_registry.get_default_module_id(
                    _resolved_dom, domain_role=_idr,
                )
                if _default_mod:
                    governed_modules = [_default_mod]
            except Exception:
                pass

    new_user_id = str(_uuid_mod.uuid4())
    await ctx.run_in_threadpool(
        ctx.persistence.create_user,
        new_user_id, username, "", role, governed_modules or None, False,
    )

    # ── Pre-assign domain role so it's ready when the user activates ──
    _intended_dr = params.get("intended_domain_role", "")
    if _intended_dr and governed_modules:
        _dr_map = {mod: _intended_dr for mod in governed_modules}
        _dh = params.get("domain_id", "")
        if _dh and ctx.domain_registry is not None:
            try:
                _dr_map[ctx.domain_registry.resolve_domain_id(_dh)] = _intended_dr
            except Exception:
                pass
        try:
            await ctx.run_in_threadpool(
                ctx.persistence.update_user_domain_roles, new_user_id, _dr_map,
            )
        except Exception:
            ctx.log.debug("Could not pre-assign domain role for %s", new_user_id)

    invite_token = generate_invite_token(new_user_id, username)
    ctx.persistence.set_user_invite_token(new_user_id, invite_token, time.time() + _INVITE_TOKEN_TTL)
    base_url = os.environ.get("LUMINA_BASE_URL", "").rstrip("/")
    setup_url = f"{base_url}/?token={invite_token}"

    email_sent = False
    if email:
        sent, _err = await ctx.run_in_threadpool(send_invite_email, email, username, setup_url)
        email_sent = sent

    invite_event = ctx.build_trace_event(
        session_id="admin",
        actor_id=user_data["sub"],
        event_type="other",
        decision="user_invited",
        evidence_summary={
            "invited_user_id": new_user_id,
            "invited_username": username,
            "invited_role": role,
            "governed_modules": governed_modules,
            "email_sent": email_sent,
            "via": "hitl_command",
        },
    )
    try:
        ctx.persistence.append_log_record(
            "admin", invite_event,
            ledger_path=ctx.persistence.get_log_ledger_path("admin", domain_id="_admin"),
        )
    except Exception:
        ctx.log.debug("Could not write user_invited trace event")

    return {
        "operation": operation,
        "user_id": new_user_id,
        "username": username,
        "role": role,
        "governed_modules": governed_modules,
        "setup_url": setup_url,
        "email_sent": email_sent,
    }
