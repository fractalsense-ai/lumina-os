"""SSE event stream: ``GET /api/events/stream``.

Pushes real-time log-bus events to connected dashboard / chat clients via
Server-Sent Events.  Each client subscribes with level and category
filters; the stream is RBAC-scoped so users only receive events for
domains they govern.

Auth uses a short-lived SSE token obtained from ``GET /api/events/token``
(because ``EventSource`` cannot set Authorization headers).

Heartbeat: an empty SSE comment line (``:heartbeat``) every 30 s keeps
the TCP connection alive through proxies.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import secrets
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials

from lumina.api.middleware import _bearer_scheme, get_current_user, require_auth
from lumina.system_log import log_bus
from lumina.system_log.event_payload import LogEvent, LogLevel

log = logging.getLogger("lumina-api")

router = APIRouter()

# ── SSE scoped tokens ────────────────────────────────────────

_SSE_TOKEN_TTL: int = 300          # 5 minutes
_sse_tokens: dict[str, dict[str, Any]] = {}  # token_hash → {user, expires_at}


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _purge_expired_tokens() -> None:
    now = time.time()
    expired = [h for h, v in _sse_tokens.items() if v["expires_at"] < now]
    for h in expired:
        del _sse_tokens[h]


@router.get("/api/events/token")
async def get_sse_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict[str, Any]:
    """Issue a short-lived token for SSE connections."""
    current = await get_current_user(credentials)
    user_data = require_auth(current)

    # Governance roles always allowed; domain-role holders (e.g. teachers)
    # are allowed so they can receive real-time escalation events.
    _governance_roles = {"root", "domain_authority", "auditor", "it_support", "qa"}
    if user_data.get("role") not in _governance_roles:
        if not (user_data.get("domain_roles") or {}):
            raise HTTPException(status_code=403, detail="Insufficient permissions")

    _purge_expired_tokens()

    raw_token = secrets.token_urlsafe(32)
    token_hash = _hash_token(raw_token)
    _sse_tokens[token_hash] = {
        "user": user_data,
        "expires_at": time.time() + _SSE_TOKEN_TTL,
    }

    return {"token": raw_token, "expires_in": _SSE_TOKEN_TTL}


def _validate_sse_token(raw_token: str) -> dict[str, Any]:
    """Validate and consume an SSE token, returning the user payload."""
    _purge_expired_tokens()
    token_hash = _hash_token(raw_token)
    entry = _sse_tokens.pop(token_hash, None)
    if entry is None:
        raise HTTPException(status_code=401, detail="Invalid or expired SSE token")
    if entry["expires_at"] < time.time():
        raise HTTPException(status_code=401, detail="SSE token expired")
    return entry["user"]


# ── SSE Event Types ──────────────────────────────────────────

# Map log-bus (level, category) combinations to SSE event types.
_CATEGORY_EVENT_MAP: dict[str, str] = {
    "escalation": "escalation",
    "hash_chain": "audit",
    "daemon": "daemon_state",
    "daemon": "daemon_state",
    "preemption": "daemon_state",
    "session_lifecycle": "session",
    "hitl_command": "command_staged",
}

_LEVEL_EVENT_MAP: dict[LogLevel, str] = {
    LogLevel.WARNING: "warning",
    LogLevel.ERROR: "alert",
    LogLevel.CRITICAL: "alert",
}


def _classify_sse_event(event: LogEvent) -> str:
    """Determine the SSE event type string for a log event."""
    # Category takes precedence over level.
    if event.category in _CATEGORY_EVENT_MAP:
        return _CATEGORY_EVENT_MAP[event.category]
    return _LEVEL_EVENT_MAP.get(event.level, "log")


# ── RBAC filter ──────────────────────────────────────────────

def _event_visible_to_user(event: LogEvent, user: dict[str, Any]) -> bool:
    """Return True if *user* is permitted to see *event*."""
    role = user.get("role", "")
    if role == "root":
        return True

    # domain_authority only sees events for governed domains.
    governed = set(user.get("governed_modules") or [])
    if role == "domain_authority":
        event_domain = event.data.get("domain_id", "")
        if event_domain and event_domain not in governed:
            record = event.record or {}
            rec_domain = record.get("domain_pack_id", "")
            if rec_domain and rec_domain not in governed:
                return False
        return True

    # Auditors and IT support see warnings/errors/critical only.
    if role in ("auditor", "it_support", "qa"):
        return event.level in (
            LogLevel.WARNING,
            LogLevel.ERROR,
            LogLevel.CRITICAL,
        )

    # Domain-role holders (e.g. teachers) see only escalation events
    # for modules they hold a role in.
    domain_roles = user.get("domain_roles") or {}
    if domain_roles and event.category == "escalation":
        event_domain = event.data.get("domain_id", "")
        return event_domain in domain_roles

    return False


# ── SSE stream ───────────────────────────────────────────────

_SSE_HEARTBEAT_INTERVAL: float = 30.0

# Levels that the SSE stream subscribes to (excludes DEBUG).
_SSE_LEVELS: set[LogLevel] = {
    LogLevel.INFO,
    LogLevel.WARNING,
    LogLevel.ERROR,
    LogLevel.CRITICAL,
    LogLevel.AUDIT,
}


def _format_sse(event_type: str, data: str) -> str:
    """Format a single SSE frame."""
    return f"event: {event_type}\ndata: {data}\n\n"


@router.get("/api/events/stream")
async def event_stream(
    request: Request,
    token: str = Query(..., description="SSE auth token from /api/events/token"),
) -> StreamingResponse:
    """Server-Sent Event stream of real-time log-bus events."""
    user_data = _validate_sse_token(token)

    queue: asyncio.Queue[LogEvent | None] = asyncio.Queue(maxsize=256)

    async def _on_event(event: LogEvent) -> None:
        """Subscriber callback — enqueue events for the SSE generator."""
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            pass  # Drop oldest; client is falling behind.

    log_bus.subscribe(
        _on_event,
        is_async=True,
        level_filter=list(_SSE_LEVELS),
    )

    async def _generate():  # type: ignore[override]
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(
                        queue.get(), timeout=_SSE_HEARTBEAT_INTERVAL,
                    )
                except asyncio.TimeoutError:
                    # Heartbeat keeps connection alive.
                    yield ": heartbeat\n\n"
                    continue

                if event is None:
                    break

                if not _event_visible_to_user(event, user_data):
                    continue

                sse_type = _classify_sse_event(event)
                payload = event.to_dict()
                yield _format_sse(sse_type, json.dumps(payload, default=str))
        except asyncio.CancelledError:
            pass

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
