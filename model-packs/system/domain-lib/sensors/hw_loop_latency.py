"""hw_loop_latency.py — Asyncio event-loop latency probe.

Passive load probe.  Called by ``src/lumina/daemon/load_estimator.py``
(``LoadEstimator.sample()``) and ``src/lumina/lib/system_health.py``
(``SystemHealthMonitor.sample()``).

Measures event-loop responsiveness by scheduling a zero-delay callback
and timing how long the loop actually takes to execute it.  High latency
indicates the loop is saturated by other coroutines or blocking calls.

Platform notes
--------------
- Requires a running asyncio event loop (call the ``async`` variant).
- ``load_ratio`` = ``latency_ms / expected_ms``.
  * 1.0  → loop is unloaded
  * >5.0 → loop is heavily saturated
"""
from __future__ import annotations

import asyncio
import time


async def measure_loop_latency_async(expected_ms: float = 1.0) -> dict[str, float] | None:
    """Measure current asyncio event-loop latency.

    Schedules a zero-delay callback and measures actual vs *expected_ms*.

    Parameters
    ----------
    expected_ms:
        Baseline callback delay in an unloaded loop (default ``1.0``).

    Returns
    -------
    dict or None
        ``{"latency_ms": float, "expected_ms": float, "load_ratio": float}``
        or ``None`` when the probe cannot run.
    """
    loop = asyncio.get_running_loop()
    future: asyncio.Future[float] = loop.create_future()
    scheduled = time.perf_counter()

    def _cb() -> None:
        if not future.done():
            future.set_result(time.perf_counter())

    loop.call_soon(_cb)
    actual = await future
    latency_ms = (actual - scheduled) * 1000.0
    load_ratio = latency_ms / expected_ms if expected_ms > 0 else 1.0

    return {
        "latency_ms": latency_ms,
        "expected_ms": expected_ms,
        "load_ratio": load_ratio,
    }


def measure_loop_latency() -> dict[str, float] | None:
    """Synchronous stub — returns ``None`` outside a running event loop.

    Use :func:`measure_loop_latency_async` from within async code.
    """
    # TODO: bridge to async variant via running loop detection.
    return None
