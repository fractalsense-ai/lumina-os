"""Domain-owned session-unlock REST handler for the education domain pack.

Mounted dynamically at startup via ``api_routes`` in runtime-config.yaml.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("lumina-api.education")


async def unlock_session(
    *,
    user_data: dict[str, Any],
    session_containers: dict[str, Any],
    path_params: dict[str, Any],
    body: dict[str, Any] | None,
    **_kw: Any,
) -> dict[str, Any]:
    """Allow a student to unlock a frozen session by submitting the OTP PIN."""
    from lumina.core.session_unlock import validate_unlock_pin

    session_id = path_params.get("session_id", "")
    pin = (body or {}).get("pin", "")

    if not validate_unlock_pin(session_id, pin):
        return {"__status": 403, "detail": "Invalid or expired unlock PIN"}

    container = session_containers.get(session_id)
    if container is not None:
        container.frozen = False
        log.info("[%s] Session unfrozen via PIN unlock", session_id)

    return {"session_id": session_id, "unlocked": True}
