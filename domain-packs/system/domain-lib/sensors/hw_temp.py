"""hw_temp.py — CPU temperature passive probe.

Passive hardware probe.  Called by src/lumina/lib/system_health.py
(SystemHealthMonitor.sample()); NOT called by the core orchestrator.

Platform divergence
-------------------
Temperature sensing is highly platform-specific:

- **Linux**: typically available via ``psutil.sensors_temperatures()``
  (requires ``lm-sensors``; may be unavailable in containers).
- **Windows**: ``psutil`` does not expose temperature; requires WMI or
  a third-party sensor library such as OpenHardwareMonitor.
- **macOS**: ``psutil.sensors_temperatures()`` available on Intel Macs;
  unsupported on Apple Silicon.

Callers MUST treat a ``None`` response as "temperature data unavailable",
not as an error.  Log a warning only, never raise.
"""
from __future__ import annotations


def get_cpu_temp() -> dict[str, float] | None:
    """Return primary CPU temperature.

    Returns
    -------
    dict or None
        ``{"cpu_temp_c": float}`` where ``cpu_temp_c`` is the primary
        CPU core temperature in degrees Celsius, or ``None`` when the
        probe cannot run on this platform.
    """
    # TODO: implement with psutil.sensors_temperatures() on Linux/macOS.
    # Fall back to None on Windows and platforms without sensor support.
    #
    # Example — psutil (Linux / Intel macOS):
    #   import psutil
    #   temps = psutil.sensors_temperatures()
    #   if not temps:
    #       return None
    #   # prefer "coretemp" (Intel) or "k10temp" (AMD)
    #   for key in ("coretemp", "k10temp"):
    #       if key in temps and temps[key]:
    #           return {"cpu_temp_c": temps[key][0].current}
    #   first_key = next(iter(temps))
    #   if temps[first_key]:
    #       return {"cpu_temp_c": temps[first_key][0].current}
    #   return None
    return None  # stub — platform implementation pending
