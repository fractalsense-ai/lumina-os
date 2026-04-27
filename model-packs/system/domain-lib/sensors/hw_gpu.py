"""hw_gpu.py — GPU VRAM utilisation probe.

Passive hardware probe.  Called by ``src/lumina/daemon/load_estimator.py``
(``LoadEstimator.sample()``) and ``src/lumina/lib/system_health.py``
(``SystemHealthMonitor.sample()``).

Returns GPU memory and load metrics.  Implementation requires
``pynvml`` (NVIDIA) or equivalent vendor library.

Platform notes
--------------
- Returns ``None`` when no supported GPU is detected.
- For multi-GPU hosts, reports the *first* device (device index 0).
- Weight in the load estimator auto-redistributes when this probe
  returns ``None``, so stub behaviour is fully safe.
"""
from __future__ import annotations


def get_gpu_usage() -> dict[str, float] | None:
    """Return GPU utilisation metrics.

    Returns
    -------
    dict or None
        ``{"vram_used_mb": float, "vram_total_mb": float,
        "vram_pct_used": float, "gpu_load_pct": float}``
        or ``None`` when the probe cannot run.
    """
    # TODO: implement with pynvml (preferred).
    #
    # Example — pynvml:
    #   import pynvml
    #   pynvml.nvmlInit()
    #   handle = pynvml.nvmlDeviceGetHandleByIndex(0)
    #   mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
    #   util = pynvml.nvmlDeviceGetUtilizationRates(handle)
    #   return {
    #       "vram_used_mb": mem.used / 1e6,
    #       "vram_total_mb": mem.total / 1e6,
    #       "vram_pct_used": (mem.used / mem.total * 100) if mem.total else 0.0,
    #       "gpu_load_pct": util.gpu,
    #   }
    return None
