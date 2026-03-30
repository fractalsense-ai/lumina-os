"""hw_disk.py — Disk usage passive probe.

Passive hardware probe.  Called by src/lumina/lib/system_health.py
(SystemHealthMonitor.sample()); NOT called directly by the core
orchestrator or by policy-driven standing orders.

Returns raw disk metrics for the filesystem root.  Implementation
requires either psutil (preferred) or shutil.disk_usage (stdlib fallback).

Platform notes
--------------
- Default path is "/" (POSIX).  On Windows pass "C:\\\\" explicitly or
  enumerate drives via psutil.disk_partitions().
- psutil provides per-partition breakdowns; shutil.disk_usage covers
  one mount point but has no external dependency.
"""
from __future__ import annotations


def get_disk_usage(path: str = "/") -> dict[str, float] | None:
    """Return disk usage metrics for *path*.

    Parameters
    ----------
    path:
        Filesystem path to check (default ``"/"``).

    Returns
    -------
    dict or None
        ``{"total_gb": float, "used_gb": float, "free_gb": float,
        "pct_used": float}`` or ``None`` when the probe cannot run.
    """
    # TODO: implement with psutil (preferred) or shutil.disk_usage fallback.
    #
    # Example — psutil:
    #   import psutil
    #   usage = psutil.disk_usage(path)
    #   return {
    #       "total_gb": usage.total / 1e9,
    #       "used_gb":  usage.used  / 1e9,
    #       "free_gb":  usage.free  / 1e9,
    #       "pct_used": usage.percent,
    #   }
    #
    # Example — stdlib fallback:
    #   import shutil
    #   total, used, free = shutil.disk_usage(path)
    #   pct_used = (used / total * 100) if total else 0.0
    #   return {
    #       "total_gb": total / 1e9,
    #       "used_gb":  used  / 1e9,
    #       "free_gb":  free  / 1e9,
    #       "pct_used": pct_used,
    #   }
    return None  # stub — platform implementation pending
