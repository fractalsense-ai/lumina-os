"""
slm_ppa_worker.py — Async SLM PPA Enrichment Worker

Runs as an asyncio task ("same bus, different lane") alongside FastAPI.
Processes enrichment requests for local-only domains via an asyncio.Queue,
keeping SLM I/O-bound HTTP calls off the main request path.

Lifecycle:
    - ``start()`` is called from the FastAPI startup event.
    - ``stop()`` is called from the FastAPI shutdown event (or atexit).
    - ``enqueue()`` submits an enrichment request and returns a Future
      that the caller can ``await`` to get the result.

Architecture:
    The worker pulls ``EnrichmentRequest`` items from an asyncio.Queue,
    calls the SLM for physics context interpretation and/or command
    parsing, and resolves the attached Future with the result.  Because
    the SLM calls are I/O-bound (HTTP via httpx), asyncio handles the
    waiting without blocking the event loop.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

log = logging.getLogger("lumina.slm-ppa-worker")


# ── Request / Response Types ─────────────────────────────────


class EnrichmentKind(str, Enum):
    """The type of SLM enrichment to perform."""

    PHYSICS_CONTEXT = "physics_context"
    COMMAND_PARSE = "command_parse"


@dataclass
class EnrichmentRequest:
    """A unit of work for the SLM PPA worker."""

    kind: EnrichmentKind
    payload: dict[str, Any]
    future: asyncio.Future = field(default_factory=lambda: asyncio.get_event_loop().create_future())


# ── Worker State ─────────────────────────────────────────────

_queue: asyncio.Queue[EnrichmentRequest | None] = asyncio.Queue()
_worker_task: asyncio.Task | None = None
_running: bool = False


# ── Public API ───────────────────────────────────────────────


async def enqueue(kind: EnrichmentKind, payload: dict[str, Any]) -> Any:
    """Submit an enrichment request and wait for the result.

    Returns the enrichment result directly.  Raises on worker failure.
    """
    loop = asyncio.get_running_loop()
    req = EnrichmentRequest(kind=kind, payload=payload, future=loop.create_future())
    await _queue.put(req)
    return await req.future


async def start() -> None:
    """Start the background SLM PPA worker task."""
    global _worker_task, _running

    if _running:
        log.warning("SLM PPA worker already running — skipping duplicate start")
        return

    _running = True
    _worker_task = asyncio.create_task(_worker_loop(), name="slm-ppa-worker")
    log.info("SLM PPA worker started")


async def stop() -> None:
    """Gracefully stop the worker by sending a sentinel and awaiting drain."""
    global _worker_task, _running

    if not _running:
        return

    _running = False
    # Sentinel: None signals the worker to exit.
    await _queue.put(None)

    if _worker_task is not None:
        try:
            await asyncio.wait_for(_worker_task, timeout=10.0)
        except asyncio.TimeoutError:
            log.warning("SLM PPA worker did not stop within 10 s — cancelling")
            _worker_task.cancel()
        _worker_task = None

    log.info("SLM PPA worker stopped")


def is_running() -> bool:
    """Return True if the worker task is active."""
    return _running and _worker_task is not None and not _worker_task.done()


# ── Internal Worker Loop ─────────────────────────────────────


async def _worker_loop() -> None:
    """Process enrichment requests until a None sentinel is received."""
    log.info("SLM PPA worker loop entering")

    while _running:
        try:
            req = await _queue.get()
        except asyncio.CancelledError:
            break

        if req is None:
            # Sentinel — shut down gracefully.
            break

        try:
            result = await _dispatch(req)
            if not req.future.done():
                req.future.set_result(result)
        except Exception as exc:
            log.warning("SLM PPA enrichment failed (%s): %s", req.kind.value, exc)
            if not req.future.done():
                req.future.set_exception(exc)
        finally:
            _queue.task_done()

    log.info("SLM PPA worker loop exiting")


async def _dispatch(req: EnrichmentRequest) -> Any:
    """Route an enrichment request to the appropriate SLM function.

    SLM calls are synchronous (httpx.post) so we use ``asyncio.to_thread``
    to keep them off the event loop.  This is the one place where we bridge
    sync → async, and it's intentional: httpx's sync client is what the SLM
    layer already uses, and wrapping it here avoids rewriting the entire
    SLM transport layer.
    """
    if req.kind is EnrichmentKind.PHYSICS_CONTEXT:
        return await _enrich_physics(req.payload)
    if req.kind is EnrichmentKind.COMMAND_PARSE:
        return await _enrich_command(req.payload)

    raise ValueError(f"Unknown enrichment kind: {req.kind}")


async def _enrich_physics(payload: dict[str, Any]) -> dict[str, Any]:
    """Run SLM physics context interpretation off the event loop."""
    from lumina.core.slm import slm_interpret_physics_context

    return await asyncio.to_thread(
        slm_interpret_physics_context,
        incoming_signals=payload["incoming_signals"],
        domain_physics=payload["domain_physics"],
        glossary=payload.get("glossary"),
    )


async def _enrich_command(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Run SLM admin command parsing off the event loop."""
    from lumina.core.slm import slm_parse_admin_command

    return await asyncio.to_thread(
        slm_parse_admin_command,
        natural_language=payload["natural_language"],
        available_operations=payload.get("available_operations"),
    )
