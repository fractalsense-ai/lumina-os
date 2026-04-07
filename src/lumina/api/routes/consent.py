"""POST /api/consent/accept — magic-circle consent recording."""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from lumina.api.middleware import _bearer_scheme, get_current_user
from lumina.api.session import _session_containers

log = logging.getLogger("lumina-api")

router = APIRouter()


@router.post("/api/consent/accept")
async def accept_consent(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict[str, Any]:
    """Record magic-circle consent for the authenticated user's session."""
    user = await get_current_user(credentials)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")

    user_id = user.get("sub", "")
    now = time.time()

    # Find all session containers belonging to this user and mark consent
    marked = 0
    for sid, container in _session_containers.items():
        if container.user and container.user.get("sub") == user_id:
            container.consent_accepted = True
            container.consent_timestamp = now
            marked += 1

    # Persist consent at the user level so new sessions also see it
    persisted = False
    try:
        from lumina.api.routes.admin import _cfg
        if _cfg.PERSISTENCE and user_id:
            persisted = _cfg.PERSISTENCE.set_user_consent(user_id, True, now)
    except Exception:
        log.debug("Could not persist consent for user %s", user_id)

    return {
        "status": "accepted",
        "user_id": user_id,
        "timestamp": now,
        "sessions_updated": marked,
        "persisted": persisted,
    }
