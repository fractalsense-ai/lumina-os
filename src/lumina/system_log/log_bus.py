"""
log_bus.py — Central Async Event Bus

Provides a single async queue that every Lumina subsystem can emit
:class:`~lumina.system_log.event_payload.LogEvent` instances into.
Subscribers register via :func:`subscribe` and receive events that match
their optional *level_filter* / *category_filter* predicates.

Lifecycle is tied to the FastAPI startup/shutdown hooks:

    @app.on_event("startup")
    async def _start():
        await log_bus.start()

    @app.on_event("shutdown")
    async def _stop():
        await log_bus.stop()

Sync-safe ``emit()`` is provided for callers that are not in an async
context (e.g. the synchronous PPA orchestrator).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Awaitable, Sequence

from lumina.system_log.event_payload import LogEvent, LogLevel
from lumina.system_log.telemetry_mask import apply_masking

log = logging.getLogger("lumina.log-bus")

# Type alias for subscriber callbacks.  Subscribers may be sync or async.
Subscriber = Callable[[LogEvent], Any]
AsyncSubscriber = Callable[[LogEvent], Awaitable[Any]]


# ── Subscription record ──────────────────────────────────────

class _Subscription:
    __slots__ = ("callback", "is_async", "level_filter", "category_filter")

    def __init__(
        self,
        callback: Subscriber | AsyncSubscriber,
        *,
        is_async: bool = False,
        level_filter: set[LogLevel] | None = None,
        category_filter: set[str] | None = None,
    ) -> None:
        self.callback = callback
        self.is_async = is_async
        self.level_filter = level_filter
        self.category_filter = category_filter

    def matches(self, event: LogEvent) -> bool:
        if self.level_filter and event.level not in self.level_filter:
            return False
        if self.category_filter and event.category not in self.category_filter:
            return False
        return True


# ── Module state ─────────────────────────────────────────────

_queue: asyncio.Queue[LogEvent | None] = asyncio.Queue()
_subscriptions: list[_Subscription] = []
_task: asyncio.Task[None] | None = None
_running: bool = False


# ── Public API ───────────────────────────────────────────────


def subscribe(
    callback: Subscriber | AsyncSubscriber,
    *,
    is_async: bool = False,
    level_filter: Sequence[LogLevel | str] | None = None,
    category_filter: Sequence[str] | None = None,
) -> None:
    """Register a subscriber.

    Args:
        callback:        Invoked for every matching event.
        is_async:        Set ``True`` if *callback* is a coroutine function.
        level_filter:    If provided, only events whose level is in this set
                         are delivered.
        category_filter: If provided, only events whose category is in this
                         set are delivered.
    """
    lf: set[LogLevel] | None = None
    if level_filter is not None:
        lf = {LogLevel(l) if isinstance(l, str) else l for l in level_filter}
    cf: set[str] | None = None
    if category_filter is not None:
        cf = set(category_filter)
    _subscriptions.append(
        _Subscription(callback, is_async=is_async, level_filter=lf, category_filter=cf)
    )


def emit(event: LogEvent) -> None:
    """Queue an event for dispatch (sync-safe).

    When called from a running event loop, this schedules the put via
    ``call_soon_threadsafe``.  When no loop is running it falls back to
    a direct synchronous put (unit-test convenience).

    Telemetry masking is applied before the event reaches the queue,
    controlled by ``LUMINA_TELEMETRY_MASKING_ENABLED``.
    """
    if not _running:
        return
    event = apply_masking(event)
    try:
        loop = asyncio.get_running_loop()
        loop.call_soon_threadsafe(_queue.put_nowait, event)
    except RuntimeError:
        # No running loop — best-effort put_nowait.
        try:
            _queue.put_nowait(event)
        except Exception:
            pass


async def emit_async(event: LogEvent) -> None:
    """Queue an event for dispatch (async).

    Telemetry masking is applied before the event reaches the queue.
    """
    if not _running:
        return
    event = apply_masking(event)
    await _queue.put(event)


async def start() -> None:
    """Start the dispatch loop as a background asyncio task."""
    global _task, _running

    if _running:
        log.warning("Log bus already running — skipping duplicate start")
        return

    _running = True
    _task = asyncio.create_task(_dispatch_loop(), name="log-bus-dispatch")
    log.info("Log bus started")


async def stop() -> None:
    """Gracefully drain queued events and stop the dispatch loop."""
    global _task, _running

    if not _running:
        return

    _running = False
    # Sentinel — tells the dispatch loop to exit.
    await _queue.put(None)

    if _task is not None:
        try:
            await asyncio.wait_for(_task, timeout=10.0)
        except asyncio.TimeoutError:
            log.warning("Log bus did not stop within 10 s — cancelling")
            _task.cancel()
        _task = None

    log.info("Log bus stopped")


def is_running() -> bool:
    """Return ``True`` when the dispatch loop is active."""
    return _running and _task is not None and not _task.done()


def clear_subscriptions() -> None:
    """Remove all subscribers (useful in tests)."""
    _subscriptions.clear()


# ── Internal dispatch loop ───────────────────────────────────


async def _dispatch_loop() -> None:
    """Pull events from the queue and fan out to matching subscribers."""
    log.info("Log bus dispatch loop entering")

    while True:
        try:
            event = await _queue.get()
        except asyncio.CancelledError:
            break

        if event is None:
            # Sentinel — drain remaining items then exit.
            break

        for sub in _subscriptions:
            if not sub.matches(event):
                continue
            try:
                if sub.is_async:
                    await sub.callback(event)  # type: ignore[misc]
                else:
                    sub.callback(event)
            except Exception:
                log.exception(
                    "Subscriber %s failed for event %s/%s",
                    sub.callback,
                    event.level.value,
                    event.category,
                )

        _queue.task_done()

    log.info("Log bus dispatch loop exiting")
