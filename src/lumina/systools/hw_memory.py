"""hw_memory.py — System memory passive probe.

Passive hardware probe.  Called by src/lumina/lib/system_health.py
(SystemHealthMonitor.sample()); NOT called by the core orchestrator.

Preferred implementation uses ``psutil.virtual_memory()`` for a full
breakdown (total / used / free / available / cached).  Returns ``None``
gracefully when psutil is not installed so callers can degrade cleanly.

Note: "free" (pages completely unused) differs from "available" (free +
reclaimable cache).  SystemHealthMonitor evaluates thresholds against
``pct_used`` which psutil derives from ``available``, not raw ``free``.
"""
from __future__ import annotations


def get_memory_usage() -> dict[str, float] | None:
    """Return system virtual memory metrics.

    Returns
    -------
    dict or None
        ``{"total_mb": float, "used_mb": float, "free_mb": float,
        "available_mb": float, "pct_used": float}`` or ``None`` when
        the probe cannot run.
    """
    # TODO: implement using psutil.virtual_memory().
    #
    # Example — psutil:
    #   import psutil
    #   vm = psutil.virtual_memory()
    #   return {
    #       "total_mb":     vm.total     / 1e6,
    #       "used_mb":      vm.used      / 1e6,
    #       "free_mb":      vm.free      / 1e6,
    #       "available_mb": vm.available / 1e6,
    #       "pct_used":     vm.percent,
    #   }
    return None  # stub — platform implementation pending
