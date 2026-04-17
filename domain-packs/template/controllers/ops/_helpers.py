"""Shared guard and helper functions for template domain ops.

These are *private* to the template domain pack — not intended for
cross-domain reuse.  Every handler module in ``ops/`` imports from here
instead of re-implementing the same boilerplate.

HOW TO USE:
  1. Copy the patterns below into your domain's _helpers.py.
  2. Adjust role names, capability names, and profile paths.
  3. Import from your ops handler modules:
       from ._helpers import require_user_exists, load_profile, save_profile

COMMON PATTERNS:
  - require_user_exists():  Look up a user by ID or username, raise 404 if not found.
  - require_capability():   Guard an operation behind a domain-role capability.
  - load_profile() / save_profile():  Read/write entity profiles via ctx.persistence.
  - write_commitment():     Append an auditable commitment record to the domain log.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("lumina.template-ops")


# ── User existence check ─────────────────────────────────────────────

async def require_user_exists(
    ctx: Any,
    user_id: str,
    label: str = "User",
) -> dict[str, Any]:
    """Return the user record, or raise 404.

    Accepts either a user ID (UUID) or a username.  Tries ID lookup first,
    then falls back to username lookup.

    TODO: Adjust the label for your domain (e.g. "Operator", "Patient").
    """
    user = await ctx.run_in_threadpool(ctx.persistence.get_user, user_id)
    if user is None:
        user = await ctx.run_in_threadpool(
            ctx.persistence.get_user_by_username, user_id,
        )
    if user is None:
        raise ctx.HTTPException(
            status_code=404, detail=f"{label} not found: {user_id}",
        )
    if "user_id" not in user:
        user["user_id"] = user.get("sub", user_id)
    return user


# ── Capability guard ─────────────────────────────────────────────────

async def require_capability(
    user_data: dict[str, Any],
    ctx: Any,
    capability: str,
    required_role: str | None = None,
) -> None:
    """Raise 403 unless *user_data* holds *capability* on at least one module.

    If *required_role* is set, only that domain role is checked.

    TODO: Adjust role names and capabilities for your domain.
    """
    for _mid, _rid in (user_data.get("domain_roles") or {}).items():
        if required_role and _rid != required_role:
            continue
        if ctx.has_domain_capability(user_data, _mid, capability):
            return
    raise ctx.HTTPException(
        status_code=403,
        detail=f"Requires {capability} capability",
    )


# ── Profile I/O ──────────────────────────────────────────────────────

async def load_profile(
    ctx: Any,
    user_id: str,
    domain: str = "template",
) -> dict[str, Any]:
    """Load a user's subject profile, returning {} on any failure.

    TODO: Replace default domain= with your pack_id.
    """
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
    domain: str = "template",
) -> None:
    """Persist a user's subject profile.

    TODO: Replace default domain= with your pack_id.
    """
    path = str(ctx.resolve_user_profile_path(user_id, domain))
    await ctx.run_in_threadpool(
        ctx.persistence.save_subject_profile, path, profile,
    )


# ── Commitment record helper ─────────────────────────────────────────

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
    """Build a commitment record, append to the domain log, and return it.

    Commitment records provide an auditable trail of administrative
    actions (assignments, removals, role changes, etc.).

    TODO: Use this in your ops handlers for any state-changing operation.
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
