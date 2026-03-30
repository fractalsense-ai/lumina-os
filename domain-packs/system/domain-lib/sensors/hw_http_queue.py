"""hw_http_queue.py — In-flight HTTP request counter.

Passive load probe.  Called by ``src/lumina/daemon/load_estimator.py``
(``LoadEstimator.sample()``) and ``src/lumina/lib/system_health.py``
(``SystemHealthMonitor.sample()``).

Tracks the number of HTTP requests currently being processed by the
FastAPI server.  The counter is incremented/decremented by middleware
wired in ``src/lumina/api/server.py``.

Thread-safe: uses ``threading.Lock`` so both async handlers and
``asyncio.to_thread()`` callees can safely read the value.
"""
from __future__ import annotations

import threading


_lock = threading.Lock()
_inflight: int = 0
_max_seen: int = 0


def increment() -> None:
    """Called by request middleware on request entry."""
    global _inflight, _max_seen
    with _lock:
        _inflight += 1
        if _inflight > _max_seen:
            _max_seen = _inflight


def decrement() -> None:
    """Called by request middleware on response exit."""
    global _inflight
    with _lock:
        if _inflight > 0:
            _inflight -= 1


def get_inflight_requests() -> dict[str, int] | None:
    """Return in-flight HTTP request metrics.

    Returns
    -------
    dict or None
        ``{"inflight": int, "max_seen": int}``
    """
    with _lock:
        return {"inflight": _inflight, "max_seen": _max_seen}


def reset() -> None:
    """Reset counters — primarily for testing."""
    global _inflight, _max_seen
    with _lock:
        _inflight = 0
        _max_seen = 0
