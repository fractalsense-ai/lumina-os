"""Shared guard, profile, and commitment helpers for education ops.

These are *private* to the education domain-pack — not intended for
cross-domain reuse.  Every handler module in ``ops/`` imports from here
instead of re-implementing the same boilerplate.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("lumina.education-ops")


# ── Role / capability guards ─────────────────────────────────

async def require_teacher_capability(
    user_data: dict[str, Any],
    ctx: Any,
    capability: str = "receive_escalations",
) -> None:
    """Raise 403 unless *user_data* has a teacher domain-role with *capability*.

    Used by assign_student / remove_student where system-level "user"
    callers must prove they hold the right domain capability.
    """
    for _mid, _rid in (user_data.get("domain_roles") or {}).items():
        if _rid in ("teacher",) and ctx.has_domain_capability(user_data, _mid, capability):
            return
    raise ctx.HTTPException(
        status_code=403,
        detail=f"Requires teacher domain role with {capability} capability",
    )


async def require_module_governance(
    user_data: dict[str, Any],
    ctx: Any,
    capability: str = "assign_modules_to_students",
) -> None:
    """Raise 403 unless *user_data* holds *capability* on any module."""
    for _mid, _rid in (user_data.get("domain_roles") or {}).items():
        if ctx.has_domain_capability(user_data, _mid, capability):
            return
    raise ctx.HTTPException(
        status_code=403,
        detail=f"Requires {capability} capability",
    )


# ── Profile I/O ──────────────────────────────────────────────

async def load_profile(
    ctx: Any,
    user_id: str,
    domain: str = "education",
) -> dict[str, Any]:
    """Load a user's subject-profile, returning ``{}`` on any failure."""
    path = str(ctx.resolve_user_profile_path(user_id, domain))
    try:
        return await ctx.run_in_threadpool(
            ctx.persistence.load_subject_profile, path,
        )
    except Exception:
        return {}


async def save_profile(
    ctx: Any,
    user_id: str,
    profile: dict[str, Any],
    domain: str = "education",
) -> None:
    """Persist a user's subject-profile."""
    path = str(ctx.resolve_user_profile_path(user_id, domain))
    await ctx.run_in_threadpool(
        ctx.persistence.save_subject_profile, path, profile,
    )


# ── User existence check ─────────────────────────────────────

async def require_user_exists(
    ctx: Any,
    user_id: str,
    label: str = "User",
) -> dict[str, Any]:
    """Return the user record, or raise 404."""
    user = await ctx.run_in_threadpool(ctx.persistence.get_user, user_id)
    if user is None:
        raise ctx.HTTPException(
            status_code=404, detail=f"{label} not found: {user_id}",
        )
    return user


# ── Commitment record helper ─────────────────────────────────

def write_commitment(
    ctx: Any,
    *,
    actor_id: str,
    actor_role: str,
    commitment_type: str,
    subject_id: str,
    summary: str,
    metadata: dict[str, Any],
    references: list[str],
) -> dict[str, Any]:
    """Build a commitment record, append it to the domain log, and return it.

    When ``ctx.persistence`` is a ``ScopedPersistenceAdapter`` the record
    is automatically routed to the correct domain-tier ledger.
    """
    record = ctx.build_commitment_record(
        actor_id=actor_id,
        actor_role=actor_role,
        commitment_type=commitment_type,
        subject_id=subject_id,
        summary=summary,
        metadata=metadata,
        references=references,
    )
    ctx.persistence.append_log_record("admin", record)
    return record
