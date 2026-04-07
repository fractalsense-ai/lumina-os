"""Session unlock via one-time PIN.

A teacher resolves an escalation event and optionally requests a 6-digit PIN
(``generate_pin=True`` on the resolve request).  The PIN is delivered to the
responsible adult out-of-band and then entered by the child into the chat
input.  Entering the correct, unexpired PIN lifts the session freeze.

Storage is intentionally in-memory (same pattern as ``_STAGED_COMMANDS``):
  - No sensitive data persists beyond the process lifetime.
  - Expired entries are lazily purged on each generate/validate call.
  - Default TTL is 15 minutes; configurable via ``LUMINA_UNLOCK_PIN_TTL_SECONDS``.
"""

from __future__ import annotations

import os
import secrets
import time
from typing import Any

_UNLOCK_PIN_TTL_SECONDS: int = int(os.environ.get("LUMINA_UNLOCK_PIN_TTL_SECONDS", "900"))

# session_id → {pin, escalation_id, expires_at}
_UNLOCK_PINS: dict[str, dict[str, Any]] = {}


def _purge_expired() -> None:
    """Remove entries whose TTL has elapsed."""
    now = time.time()
    expired = [sid for sid, entry in _UNLOCK_PINS.items() if now > entry["expires_at"]]
    for sid in expired:
        del _UNLOCK_PINS[sid]


def generate_unlock_pin(session_id: str, escalation_id: str) -> str:
    """Generate a 6-digit PIN for *session_id*, store it, and return the PIN string.

    Any previously stored PIN for the same session is overwritten.
    """
    _purge_expired()
    pin = f"{secrets.randbelow(1_000_000):06d}"
    _UNLOCK_PINS[session_id] = {
        "pin": pin,
        "escalation_id": escalation_id,
        "expires_at": time.time() + _UNLOCK_PIN_TTL_SECONDS,
    }
    return pin


def validate_unlock_pin(session_id: str, submitted_pin: str) -> bool:
    """Return True and remove the PIN entry if *submitted_pin* matches and hasn't expired.

    Returns False for wrong PIN, unknown session, or expired PIN.
    Expired entries are removed on both paths.
    """
    _purge_expired()
    entry = _UNLOCK_PINS.get(session_id)
    if entry is None:
        return False
    if entry["pin"] == submitted_pin:
        del _UNLOCK_PINS[session_id]
        return True
    return False


def has_pending_pin(session_id: str) -> bool:
    """Return True if a valid, unexpired PIN exists for *session_id*."""
    _purge_expired()
    return session_id in _UNLOCK_PINS


# ── User-level freeze ────────────────────────────────────────
# A session-level freeze only blocks a single session_id — creating a new
# conversation bypasses it.  The user-level freeze blocks ALL sessions for
# that user until an unlock PIN is successfully entered.
_USER_FREEZE_TTL_SECONDS: int = int(os.environ.get("LUMINA_USER_FREEZE_TTL_SECONDS", "3600"))

# user_id → {frozen_at, expires_at, escalation_id, session_id}
_FROZEN_USERS: dict[str, dict[str, Any]] = {}


def _purge_expired_user_freezes() -> None:
    """Remove user-freeze entries whose TTL has elapsed."""
    now = time.time()
    expired = [uid for uid, entry in _FROZEN_USERS.items() if now > entry["expires_at"]]
    for uid in expired:
        del _FROZEN_USERS[uid]


def freeze_user(user_id: str, escalation_id: str = "", session_id: str = "") -> None:
    """Freeze *user_id* across all sessions until a PIN unlock or TTL expiry."""
    _purge_expired_user_freezes()
    _FROZEN_USERS[user_id] = {
        "frozen_at": time.time(),
        "expires_at": time.time() + _USER_FREEZE_TTL_SECONDS,
        "escalation_id": escalation_id,
        "session_id": session_id,
    }


def is_user_frozen(user_id: str) -> bool:
    """Return True if *user_id* is currently frozen."""
    _purge_expired_user_freezes()
    return user_id in _FROZEN_USERS


def unfreeze_user(user_id: str) -> None:
    """Remove the user-level freeze for *user_id*."""
    _FROZEN_USERS.pop(user_id, None)
