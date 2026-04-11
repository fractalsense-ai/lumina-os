"""preemption.py — Cooperative yielding protocol.

Provides ``PreemptionToken`` (passed to tasks at dispatch time) and
``TaskPreempted`` (raised at checkpoints when the daemon requests yield).

Design
------
Tasks call ``await token.checkpoint()`` (async) or
``token.checkpoint_sync()`` (thread) at natural break points — e.g.
between processing each domain in a daemon batch task.  If the daemon
has called ``token.request_yield()`` because user load spiked, the
next checkpoint raises ``TaskPreempted`` and the task unwinds cleanly.

Tasks that never call checkpoints simply run to completion; preemption
is opt-in and backward-compatible.
"""
from __future__ import annotations

import asyncio
import threading


class TaskPreempted(Exception):
    """Raised when a task should yield due to resource pressure."""


class PreemptionToken:
    """Cooperative yielding token shared between daemon and task.

    The daemon calls :meth:`request_yield` when load exceeds the busy
    threshold.  The running task calls :meth:`checkpoint` (async) or
    :meth:`checkpoint_sync` (thread) periodically; if a yield has been
    requested the checkpoint raises :class:`TaskPreempted`.
    """

    def __init__(self) -> None:
        self._yield_requested = False
        self._lock = threading.Lock()

    # ── Daemon side ───────────────────────────────────────────

    def request_yield(self) -> None:
        """Signal the running task to yield at its next checkpoint."""
        with self._lock:
            self._yield_requested = True

    def reset(self) -> None:
        """Clear the yield flag (e.g. when resuming a paused task)."""
        with self._lock:
            self._yield_requested = False

    @property
    def is_yield_requested(self) -> bool:
        with self._lock:
            return self._yield_requested

    # ── Task side ─────────────────────────────────────────────

    async def checkpoint(self) -> None:
        """Async checkpoint — call between units of work.

        Raises :class:`TaskPreempted` if a yield has been requested,
        otherwise cooperatively yields to the event loop via
        ``await asyncio.sleep(0)``.
        """
        with self._lock:
            if self._yield_requested:
                raise TaskPreempted("Preemption requested by resource monitor daemon")
        await asyncio.sleep(0)

    def checkpoint_sync(self) -> None:
        """Synchronous checkpoint for tasks running in threads.

        Raises :class:`TaskPreempted` if a yield has been requested.
        """
        with self._lock:
            if self._yield_requested:
                raise TaskPreempted("Preemption requested by resource monitor daemon")
