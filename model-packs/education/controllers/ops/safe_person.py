"""Safe Person operations — designation, handshake, and revocation.

A Safe Person is a trusted adult (teacher, school counsellor, or
nominated guardian) that a student chooses to receive Tier 3 wellness
alerts.  This is architecturally distinct from the Guardian/Parent role:

- Guardians receive academic updates and have roster-management rights.
- A Safe Person receives ONLY aggregate wellness alerts (no academic data,
  no entity maps, no journal text) — and only when the student has
  explicitly designated them AND the Safe Person has accepted a handshake
  token.

Flow:
    1. Teacher (or admin) calls ``designate_safe_person`` →
       writes ``assigned_safe_person_id`` to student profile and
       generates a one-time handshake token via invite_store pattern.

    2. Safe Person visits the acknowledgement URL with the token →
       ``safe_person_acknowledge`` validates the token and sets
       ``safe_person_handshake_accepted: true`` on the student profile.

    3. Either party (teacher or admin) can call ``revoke_safe_person``
       to clear both fields.  If revoked, no further Tier 3 alerts fire
       until a new designation + handshake cycle completes.

FERPA/COPPA note:
    The student's profile stores only the Safe Person's pseudonymous
    user_id — not their name or contact details.  Actual contact routing
    is handled by the notification layer using the stored user_id,
    keeping PII out of the profile.
"""

from __future__ import annotations

import logging
import secrets
import time
from typing import Any

log = logging.getLogger("lumina.education-ops.safe_person")

# Token TTL: 72 hours (Safe Person handshakes are not time-critical)
_SAFE_PERSON_TOKEN_TTL_SECONDS = 72 * 3600

# In-memory token store: token → {student_id, expires_at}
# Production deployments should back this with the persistence adapter.
_SAFE_PERSON_TOKENS: dict[str, dict[str, Any]] = {}


# ── Token helpers ─────────────────────────────────────────────


def _generate_handshake_token(student_id: str) -> str:
    """Generate a URL-safe handshake token for *student_id*.

    Any previous token for the same student is replaced.
    """
    _purge_expired()
    existing = [t for t, e in _SAFE_PERSON_TOKENS.items() if e["student_id"] == student_id]
    for t in existing:
        del _SAFE_PERSON_TOKENS[t]

    token = secrets.token_urlsafe(32)
    _SAFE_PERSON_TOKENS[token] = {
        "student_id": student_id,
        "expires_at": time.time() + _SAFE_PERSON_TOKEN_TTL_SECONDS,
    }
    return token


def _validate_handshake_token(token: str) -> str | None:
    """Return student_id and consume the token if valid.  None on failure."""
    _purge_expired()
    entry = _SAFE_PERSON_TOKENS.get(token)
    if entry is None:
        return None
    student_id = entry["student_id"]
    del _SAFE_PERSON_TOKENS[token]
    return student_id


def _purge_expired() -> None:
    now = time.time()
    expired = [t for t, e in _SAFE_PERSON_TOKENS.items() if now > e["expires_at"]]
    for t in expired:
        del _SAFE_PERSON_TOKENS[t]


# ── Handler: designate_safe_person ────────────────────────────


async def designate_safe_person(
    operation: str,
    params: dict[str, Any],
    user_data: dict[str, Any],
    ctx: Any,
) -> dict[str, Any]:
    """Assign a Safe Person to a student and generate a handshake token.

    Caller must be a teacher, admin, or root.  The Safe Person must be
    a valid user in the system.

    Returns the handshake token so the caller can share it with the
    Safe Person (e.g. via email notification outside the system).
    """
    from ._helpers import load_profile, log, require_user_exists, save_profile

    student_id = str(params.get("student_id", "")).strip()
    safe_person_id = str(params.get("safe_person_id", "")).strip()

    if not student_id:
        raise ctx.HTTPException(status_code=422, detail="student_id required")
    if not safe_person_id:
        raise ctx.HTTPException(status_code=422, detail="safe_person_id required")

    caller_role = user_data["role"]
    if caller_role not in ("root", "admin", "user"):
        raise ctx.HTTPException(status_code=403, detail="Insufficient permissions")
    if caller_role == "user":
        # Require teacher domain capability
        from ._helpers import require_teacher_capability
        await require_teacher_capability(user_data, ctx)

    # Validate both parties exist
    student_rec = await require_user_exists(ctx, student_id, "Student")
    student_id = student_rec["user_id"]
    sp_rec = await require_user_exists(ctx, safe_person_id, "Safe Person")
    safe_person_id = sp_rec["user_id"]

    profile = await load_profile(ctx, student_id)
    profile["assigned_safe_person_id"] = safe_person_id
    profile["safe_person_handshake_accepted"] = False
    await save_profile(ctx, student_id, profile)

    token = _generate_handshake_token(student_id)
    log.info(
        "[SAFE_PERSON] Designated safe_person=%s for student=%s by %s",
        safe_person_id, student_id, user_data.get("sub"),
    )
    return {
        "ok": True,
        "student_id": student_id,
        "safe_person_id": safe_person_id,
        "handshake_token": token,
        "message": "Safe Person designated. Share the handshake_token with them to activate.",
    }


# ── Handler: safe_person_acknowledge ─────────────────────────


async def safe_person_acknowledge(
    operation: str,
    params: dict[str, Any],
    user_data: dict[str, Any],
    ctx: Any,
) -> dict[str, Any]:
    """Accept the Safe Person handshake using a one-time token.

    The Safe Person calls this endpoint (authenticated as themselves)
    after receiving their invitation token.  On success, sets
    ``safe_person_handshake_accepted: true`` on the student profile.
    """
    from ._helpers import load_profile, log, save_profile

    token = str(params.get("token", "")).strip()
    if not token:
        raise ctx.HTTPException(status_code=422, detail="token required")

    student_id = _validate_handshake_token(token)
    if student_id is None:
        raise ctx.HTTPException(
            status_code=400,
            detail="Invalid or expired handshake token",
        )

    profile = await load_profile(ctx, student_id)
    assigned = profile.get("assigned_safe_person_id")
    caller_id = user_data.get("sub")

    # Validate the caller is actually the designated Safe Person
    if assigned and caller_id and assigned != caller_id:
        log.warning(
            "[SAFE_PERSON] Token valid but caller %s != assigned %s",
            caller_id, assigned,
        )
        raise ctx.HTTPException(
            status_code=403,
            detail="This token is not for your account",
        )

    profile["safe_person_handshake_accepted"] = True
    await save_profile(ctx, student_id, profile)

    log.info(
        "[SAFE_PERSON] Handshake accepted by %s for student=%s",
        caller_id, student_id,
    )
    return {
        "ok": True,
        "student_id": student_id,
        "message": "Handshake accepted. You will be notified if a wellness alert is triggered.",
    }


# ── Handler: revoke_safe_person ───────────────────────────────


async def revoke_safe_person(
    operation: str,
    params: dict[str, Any],
    user_data: dict[str, Any],
    ctx: Any,
) -> dict[str, Any]:
    """Remove the Safe Person designation from a student's profile.

    After revocation, no Tier 3 alerts will fire until a new designation
    + handshake cycle is completed.
    """
    from ._helpers import load_profile, log, save_profile

    student_id = str(params.get("student_id", "")).strip()
    if not student_id:
        raise ctx.HTTPException(status_code=422, detail="student_id required")

    caller_role = user_data["role"]
    if caller_role not in ("root", "admin", "user"):
        raise ctx.HTTPException(status_code=403, detail="Insufficient permissions")
    if caller_role == "user":
        from ._helpers import require_teacher_capability
        await require_teacher_capability(user_data, ctx)

    from ._helpers import require_user_exists
    student_rec = await require_user_exists(ctx, student_id, "Student")
    student_id = student_rec["user_id"]

    profile = await load_profile(ctx, student_id)
    previous = profile.get("assigned_safe_person_id")
    profile["assigned_safe_person_id"] = None
    profile["safe_person_handshake_accepted"] = False
    await save_profile(ctx, student_id, profile)

    # Purge any pending handshake tokens for this student
    stale = [t for t, e in _SAFE_PERSON_TOKENS.items() if e["student_id"] == student_id]
    for t in stale:
        del _SAFE_PERSON_TOKENS[t]

    log.info(
        "[SAFE_PERSON] Revoked safe_person=%s for student=%s by %s",
        previous, student_id, user_data.get("sub"),
    )
    return {
        "ok": True,
        "student_id": student_id,
        "message": "Safe Person designation removed.",
    }
