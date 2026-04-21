"""Pre-turn gate checks: freeze, consent.

These run before any domain logic.  If a gate triggers, the turn is
rejected with a short response before the pipeline does any real work.

See also:
    docs/7-concepts/zero-trust-architecture.md
"""

from __future__ import annotations

import logging
import re
from typing import Any

log = logging.getLogger("lumina-api")


# ---------------------------------------------------------------------------
# User-level freeze gate
# ---------------------------------------------------------------------------

def check_user_freeze(
    session_id: str,
    input_text: str,
    user: dict[str, Any] | None,
    domain_id: str | None,
    session: dict[str, Any],
    session_containers: dict,
) -> dict[str, Any] | None:
    """Block all sessions for a frozen user.

    A user-level freeze prevents the actor from starting a new conversation
    to bypass a session freeze.  Returns an early response dict when the
    user is frozen (and did not provide a valid unlock PIN), or *None* to
    let the pipeline continue.
    """
    _user_id = (user or {}).get("sub", "")
    if not _user_id:
        return None

    from lumina.core.session_unlock import is_user_frozen

    if not is_user_frozen(_user_id):
        return None

    # Still allow PIN entry to unfreeze
    _pin = input_text.strip()
    if re.fullmatch(r"\d{6}", _pin):
        from lumina.core.session_unlock import (
            _FROZEN_USERS,
            unfreeze_user,
            validate_unlock_pin,
        )

        _frozen_entry = _FROZEN_USERS.get(_user_id)
        _frozen_sid = _frozen_entry.get("session_id", "") if _frozen_entry else ""
        if _frozen_sid and validate_unlock_pin(_frozen_sid, _pin):
            unfreeze_user(_user_id)
            _orig = session_containers.get(_frozen_sid)
            if _orig is not None:
                _orig.frozen = False
            log.info(
                "[%s] User %s unlocked via PIN (cross-session)",
                session_id,
                _user_id,
            )
            return None  # unlocked — continue

    return {
        "response": (
            "Your account is temporarily locked pending teacher review. "
            "Please enter your unlock PIN."
        ),
        "action": "user_frozen",
        "prompt_type": "user_frozen",
        "escalated": True,
        "tool_results": {},
        "domain_id": domain_id or session.get("domain_id", ""),
    }


# ---------------------------------------------------------------------------
# Session-level freeze gate
# ---------------------------------------------------------------------------

def check_session_freeze(
    session_id: str,
    input_text: str,
    user: dict[str, Any] | None,
    domain_id: str | None,
    session: dict[str, Any],
    session_containers: dict,
) -> dict[str, Any] | None:
    """Block input on a frozen session until a valid unlock PIN is entered.

    Returns an early response dict when the session is frozen, or *None*
    to let the pipeline continue.
    """
    container = session_containers.get(session_id)
    if container is None or not container.frozen:
        return None

    from lumina.core.session_unlock import validate_unlock_pin

    _pin = input_text.strip()
    if re.fullmatch(r"\d{6}", _pin) and validate_unlock_pin(session_id, _pin):
        container.frozen = False
        # Also lift user-level freeze
        _user_id = (user or {}).get("sub", "")
        if _user_id:
            from lumina.core.session_unlock import unfreeze_user

            unfreeze_user(_user_id)
        log.info("[%s] Session unlocked via PIN in chat turn", session_id)
        return {
            "response": "Session unlocked. You may continue.",
            "action": "session_unlocked",
            "prompt_type": "session_unlocked",
            "escalated": False,
            "tool_results": {},
            "domain_id": domain_id or session.get("domain_id", ""),
        }

    return {
        "response": "This session is temporarily locked pending teacher review.",
        "action": "session_frozen",
        "prompt_type": "session_frozen",
        "escalated": True,
        "tool_results": {},
        "domain_id": domain_id or session.get("domain_id", ""),
    }


# ---------------------------------------------------------------------------
# Magic-circle consent gate
# ---------------------------------------------------------------------------

_GOVERNANCE_ROLES = frozenset(
    {"root", "admin", "super_admin", "operator", "half_operator"}
)


def check_consent_gate(
    session_id: str,
    user: dict[str, Any] | None,
    domain_id: str | None,
    session: dict[str, Any],
    runtime: dict[str, Any],
    session_containers: dict,
    persistence: Any,
) -> dict[str, Any] | None:
    """Enforce magic-circle consent when the domain requires it.

    Only the ``"user"`` role needs consent; governance roles and
    unauthenticated sessions bypass entirely.  Returns an early response
    dict when consent is required but not yet granted, or *None*.
    """
    _user_role = (user or {}).get("role", "")
    if user is None or _user_role in _GOVERNANCE_ROLES:
        return None

    pre_turn_checks = runtime.get("pre_turn_checks") or []
    consent_check = next(
        (
            c
            for c in pre_turn_checks
            if c.get("id") == "consent_boundary" and c.get("enabled")
        ),
        None,
    )
    if consent_check is None:
        return None

    container = session_containers.get(session_id)
    if container is None or container.consent_accepted:
        return None

    # Check persisted consent before blocking — the user may have
    # accepted consent before this session was created.
    try:
        _user_id = (user or {}).get("sub", "")
        if _user_id:
            _consent_rec = persistence.get_user_consent(_user_id)
            if _consent_rec and _consent_rec.get("accepted"):
                container.consent_accepted = True
                container.consent_timestamp = _consent_rec.get("timestamp")
                return None
    except Exception:
        pass

    return {
        "response": (
            "Please accept the magic-circle consent agreement "
            "before continuing."
        ),
        "action": "consent_required",
        "prompt_type": "consent_required",
        "escalated": False,
        "tool_results": None,
        "domain_id": domain_id or session.get("domain_id", ""),
    }
