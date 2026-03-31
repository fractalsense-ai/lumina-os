"""Invite-token store for the pending-user onboarding flow.

When an admin invites a new user via ``POST /api/auth/invite``, a one-time
setup token is generated here.  The invited user visits the setup URL, submits
the token alongside their chosen password, and the account is activated.

Primary storage is an in-memory cache for fast lookups.  A persistence adapter
(set via ``register_persistence``) is used as a durable fallback so that tokens
survive server restarts.  Expired entries are lazily purged on each call.
Default TTL is 24 hours; configurable via ``LUMINA_INVITE_TOKEN_TTL_SECONDS``.
"""

from __future__ import annotations

import os
import secrets
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from lumina.persistence.adapter import PersistenceAdapter

_INVITE_TOKEN_TTL_SECONDS: int = int(os.environ.get("LUMINA_INVITE_TOKEN_TTL_SECONDS", "86400"))

# token → {user_id, username, expires_at}
_INVITE_TOKENS: dict[str, dict[str, Any]] = {}

# Optional persistence adapter for durable fallback (set by the server on startup).
_persistence: "PersistenceAdapter | None" = None


def register_persistence(adapter: "PersistenceAdapter") -> None:
    """Register a persistence adapter so tokens survive server restarts."""
    global _persistence  # noqa: PLW0603
    _persistence = adapter


def _purge_expired() -> None:
    """Remove entries whose TTL has elapsed."""
    now = time.time()
    expired = [tok for tok, entry in _INVITE_TOKENS.items() if now > entry["expires_at"]]
    for tok in expired:
        del _INVITE_TOKENS[tok]


def generate_invite_token(user_id: str, username: str) -> str:
    """Generate a URL-safe 32-byte token for *user_id*, store it, and return it.

    Any previously stored invite token for the same *user_id* is replaced.
    """
    _purge_expired()
    # Replace any existing token for this user so there is never more than one
    existing = [tok for tok, entry in _INVITE_TOKENS.items() if entry["user_id"] == user_id]
    for tok in existing:
        del _INVITE_TOKENS[tok]

    token = secrets.token_urlsafe(32)
    _INVITE_TOKENS[token] = {
        "user_id": user_id,
        "username": username,
        "expires_at": time.time() + _INVITE_TOKEN_TTL_SECONDS,
    }
    return token


def validate_invite_token(token: str) -> str | None:
    """Return the *user_id* and remove the token if valid and unexpired.

    Checks the in-memory cache first, then falls back to the persistence adapter
    (if registered) so that tokens survive server restarts.
    Returns ``None`` for an unknown, expired, or already-consumed token.
    """
    _purge_expired()
    entry = _INVITE_TOKENS.get(token)
    if entry is not None:
        user_id = entry["user_id"]
        del _INVITE_TOKENS[token]
        if _persistence is not None:
            _persistence.clear_user_invite_token(user_id)
        return user_id

    # Cache miss — check durable persistence (handles post-restart lookups).
    if _persistence is not None:
        record = _persistence.get_user_by_invite_token(token)
        if record is not None:
            user_id = record["user_id"]
            _persistence.clear_user_invite_token(user_id)
            return user_id

    return None


def has_pending_invite(user_id: str) -> bool:
    """Return True if a valid, unexpired invite token exists for *user_id*."""
    _purge_expired()
    return any(entry["user_id"] == user_id for entry in _INVITE_TOKENS.values())
