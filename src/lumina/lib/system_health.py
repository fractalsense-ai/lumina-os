"""system_health.py — System health state estimator for Project Lumina.

Passive state estimator analogous to domain-lib components in named
domain packs (e.g., ZPD monitor, fluency tracker).  Called by the
system runtime adapter each cycle; never called directly by the core
orchestrator.

``SystemHealthMonitor.sample()`` invokes the three passive hardware
probes in ``lumina.systools`` and aggregates their raw values into a
single ``SystemHealthState`` that can be injected as evidence for
system-layer orchestration turns.

Platform implementation of the hw_* probes is pending — see:
  src/lumina/systools/hw_disk.py
  src/lumina/systools/hw_temp.py
  src/lumina/systools/hw_memory.py
"""
from __future__ import annotations

from dataclasses import dataclass, field

# ── Default alert thresholds (configurable at init) ──────────────────────────

DISK_WARN_PCT: float = 80.0      # % used before disk_ok becomes False
MEMORY_WARN_PCT: float = 85.0    # % used before memory_ok becomes False
TEMP_WARN_C: float = 75.0        # °C before temp_ok becomes False


# ── State type ────────────────────────────────────────────────────────────────

@dataclass
class SystemHealthState:
    """Aggregate health snapshot produced by ``SystemHealthMonitor.sample()``."""

    disk_ok: bool = True
    disk_pct_used: float = 0.0
    disk_free_gb: float = 0.0

    memory_ok: bool = True
    memory_pct_used: float = 0.0
    memory_free_mb: float = 0.0

    temp_ok: bool = True
    temp_c: float | None = None   # None when platform probe unavailable

    errors: list[str] = field(default_factory=list)  # non-fatal probe errors


# ── Monitor ───────────────────────────────────────────────────────────────────

class SystemHealthMonitor:
    """Sample hardware probes and produce a ``SystemHealthState``.

    Analogous to a ZPD monitor or fluency tracker in a named domain-lib.
    Called by the system runtime adapter; never by the core orchestrator.

    Parameters
    ----------
    disk_warn_pct:
        Disk-used percentage above which ``disk_ok`` is set to ``False``.
    memory_warn_pct:
        Memory-used percentage above which ``memory_ok`` is set to ``False``.
    temp_warn_c:
        CPU temperature (°C) above which ``temp_ok`` is set to ``False``.
    """

    def __init__(
        self,
        disk_warn_pct: float = DISK_WARN_PCT,
        memory_warn_pct: float = MEMORY_WARN_PCT,
        temp_warn_c: float = TEMP_WARN_C,
    ) -> None:
        self._disk_warn = disk_warn_pct
        self._memory_warn = memory_warn_pct
        self._temp_warn = temp_warn_c

    def sample(self) -> SystemHealthState:
        """Collect one health snapshot by invoking passive hardware probes.

        Returns a ``SystemHealthState`` with best-effort values.  Individual
        probe failures are captured in ``SystemHealthState.errors`` and do
        not raise; callers receive a partial result rather than an exception.
        """
        state = SystemHealthState()

        # ── Disk ─────────────────────────────────────────────────────────────
        try:
            from lumina.systools.hw_disk import get_disk_usage
            disk = get_disk_usage()
            if disk is not None:
                state.disk_pct_used = disk.get("pct_used", 0.0)
                state.disk_free_gb = disk.get("free_gb", 0.0)
                state.disk_ok = state.disk_pct_used < self._disk_warn
        except Exception as exc:  # noqa: BLE001
            state.errors.append(f"disk probe: {exc}")

        # ── Memory ───────────────────────────────────────────────────────────
        try:
            from lumina.systools.hw_memory import get_memory_usage
            mem = get_memory_usage()
            if mem is not None:
                state.memory_pct_used = mem.get("pct_used", 0.0)
                state.memory_free_mb = mem.get("free_mb", 0.0)
                state.memory_ok = state.memory_pct_used < self._memory_warn
        except Exception as exc:  # noqa: BLE001
            state.errors.append(f"memory probe: {exc}")

        # ── Temperature ──────────────────────────────────────────────────────
        try:
            from lumina.systools.hw_temp import get_cpu_temp
            temp = get_cpu_temp()
            if temp is not None:
                state.temp_c = temp.get("cpu_temp_c")
                if state.temp_c is not None:
                    state.temp_ok = state.temp_c < self._temp_warn
        except Exception as exc:  # noqa: BLE001
            state.errors.append(f"temp probe: {exc}")

        return state
