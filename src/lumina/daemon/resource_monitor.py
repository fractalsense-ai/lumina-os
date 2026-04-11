"""resource_monitor.py — Resource Monitor Daemon.

Background asyncio task that periodically samples system load and
opportunistically dispatches daemon maintenance tasks when the
system is idle.  If user load spikes while a task is running, the
daemon requests cooperative preemption via ``PreemptionToken``.

State machine
-------------
``STARTING`` → ``MONITORING`` → ``IDLE_DETECTED`` → ``DISPATCHING``
   ↑               ↑                                      │
   │               └──────────────────────────────────────←┘
   │
   └── ``STOPPED``

Module-level convenience functions: ``start()``, ``stop()``,
``is_running()``, ``get_status()``.
"""
from __future__ import annotations

import asyncio
import enum
import logging
import time
from typing import Any, Callable

from lumina.daemon.load_estimator import LoadEstimator, LoadSnapshot
from lumina.daemon.preemption import PreemptionToken, TaskPreempted

log = logging.getLogger("lumina-daemon")


# ── State enum ────────────────────────────────────────────────────────────────

class DaemonState(str, enum.Enum):
    STOPPED = "STOPPED"
    STARTING = "STARTING"
    MONITORING = "MONITORING"
    IDLE_DETECTED = "IDLE_DETECTED"
    DISPATCHING = "DISPATCHING"
    PREEMPTING = "PREEMPTING"


# ── Defaults ──────────────────────────────────────────────────────────────────

DEFAULT_POLL_INTERVAL: float = 15.0
DEFAULT_IDLE_THRESHOLD: float = 0.20
DEFAULT_IDLE_SUSTAIN: float = 300.0   # 5 minutes
DEFAULT_BUSY_THRESHOLD: float = 0.40
DEFAULT_GRACE_PERIOD: float = 60.0    # startup grace period


class ResourceMonitorDaemon:
    """Load-aware daemon that dispatches maintenance tasks opportunistically.

    Parameters
    ----------
    estimator:
        ``LoadEstimator`` instance for taking load snapshots.
    task_runner:
        Async callable ``(task_name, token) -> dict`` that executes one
        daemon task with preemption support.  Typically
        ``task_adapter.run_task_preemptible``.
    task_priority:
        Ordered list of task names to dispatch when idle.
    poll_interval_seconds:
        Seconds between load samples.
    idle_threshold:
        Load score below which the system is considered idle.
    idle_sustain_seconds:
        How long idle must persist before dispatching.
    busy_threshold:
        Load score above which a running task is preempted.
    grace_period_seconds:
        Seconds after startup during which no tasks are dispatched.
    enabled:
        Master on/off toggle.
    """

    def __init__(
        self,
        estimator: LoadEstimator | None = None,
        task_runner: Callable[..., Any] | None = None,
        task_priority: list[str] | None = None,
        poll_interval_seconds: float = DEFAULT_POLL_INTERVAL,
        idle_threshold: float = DEFAULT_IDLE_THRESHOLD,
        idle_sustain_seconds: float = DEFAULT_IDLE_SUSTAIN,
        busy_threshold: float = DEFAULT_BUSY_THRESHOLD,
        grace_period_seconds: float = DEFAULT_GRACE_PERIOD,
        enabled: bool = True,
    ) -> None:
        self._estimator = estimator or LoadEstimator()
        self._task_runner = task_runner
        self._task_priority = list(task_priority or [])
        self._poll_interval = poll_interval_seconds
        self._idle_threshold = idle_threshold
        self._idle_sustain = idle_sustain_seconds
        self._busy_threshold = busy_threshold
        self._grace_period = grace_period_seconds
        self._enabled = enabled

        # Runtime state
        self._state = DaemonState.STOPPED
        self._task: asyncio.Task[None] | None = None
        self._dispatch_task: asyncio.Task[None] | None = None
        self._last_snapshot: LoadSnapshot | None = None
        self._idle_since: float | None = None
        self._current_token: PreemptionToken | None = None
        self._current_task_name: str | None = None
        self._started_at: float = 0.0

        # Round-robin index into _task_priority
        self._task_index: int = 0

    # ── Lifecycle ─────────────────────────────────────────────

    async def start(self) -> None:
        """Start the daemon background task."""
        if self._task is not None:
            return
        if not self._enabled:
            log.info("Resource Monitor Daemon disabled by config")
            return
        self._state = DaemonState.STARTING
        self._started_at = time.monotonic()
        self._task = asyncio.create_task(self._monitor_loop(), name="resource-monitor-daemon")
        log.info("Resource Monitor Daemon started (poll=%.0fs, grace=%.0fs)",
                 self._poll_interval, self._grace_period)

    async def stop(self) -> None:
        """Stop the daemon background task."""
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
        # Cancel any in-flight dispatched task
        if self._dispatch_task is not None:
            self._dispatch_task.cancel()
            try:
                await self._dispatch_task
            except asyncio.CancelledError:
                pass
            self._dispatch_task = None
        self._state = DaemonState.STOPPED
        log.info("Resource Monitor Daemon stopped")

    @property
    def state(self) -> DaemonState:
        return self._state

    def get_status(self) -> dict[str, Any]:
        """Return daemon status for ``/api/health``."""
        snap = self._last_snapshot
        telem = self._estimator.get_window_summary()
        return {
            "state": self._state.value,
            "enabled": self._enabled,
            "load_score": snap.load_score if snap else None,
            "is_idle": snap.is_idle if snap else None,
            "current_task": self._current_task_name,
            "idle_since": self._idle_since,
            "poll_interval_seconds": self._poll_interval,
            "telemetry_window": telem.json_summary,
        }

    # ── Main loop ─────────────────────────────────────────────

    async def _monitor_loop(self) -> None:
        """Core polling loop — runs as an asyncio background task."""
        self._state = DaemonState.MONITORING
        try:
            while True:
                await asyncio.sleep(self._poll_interval)
                try:
                    await self._poll_once()
                except Exception:
                    log.exception("Daemon poll error")
        except asyncio.CancelledError:
            return

    async def _poll_once(self) -> None:
        """Single poll iteration."""
        snap = await self._estimator.sample()
        self._last_snapshot = snap

        # ── Check blackbox triggers against telemetry state ───
        try:
            from lumina.session.blackbox_triggers import trigger_registry
            telem = self._estimator.get_window_summary()
            event = dict(telem.json_summary)
            event["load_score"] = snap.load_score
            event["is_idle"] = snap.is_idle
            fired = trigger_registry.check(event)
            if fired:
                from lumina.session.blackbox import capture_blackbox, write_blackbox
                from lumina.api.session import _session_containers

                for sid, container in list(_session_containers.items()):
                    try:
                        rb_snap = container.ring_buffer.snapshot() if hasattr(container, "ring_buffer") else []
                        bb = capture_blackbox(
                            session_id=sid,
                            domain_id=container.active_domain_id,
                            trigger_type=",".join(fired),
                            trigger_source="daemon_telemetry",
                            ring_buffer_snapshot=rb_snap,
                            telemetry_summary=telem.json_summary,
                            session_state={"domain_id": container.active_domain_id},
                        )
                        write_blackbox(bb)
                    except Exception:
                        log.warning("Blackbox capture failed for session %s", sid, exc_info=True)
        except Exception:
            pass  # Trigger check is best-effort

        # Grace period — don't dispatch during startup
        if (time.monotonic() - self._started_at) < self._grace_period:
            return

        # If a task is currently running, check for preemption
        if self._state == DaemonState.DISPATCHING and self._current_token:
            if snap.load_score >= self._busy_threshold:
                log.warning(
                    "Load spike (%.2f >= %.2f), preempting task %s",
                    snap.load_score, self._busy_threshold, self._current_task_name,
                )
                self._state = DaemonState.PREEMPTING
                self._current_token.request_yield()
            return

        # If preempting, just wait for the task to finish
        if self._state == DaemonState.PREEMPTING:
            return

        # Track idle duration
        if snap.is_idle:
            if self._idle_since is None:
                self._idle_since = time.monotonic()
            idle_duration = time.monotonic() - self._idle_since

            if idle_duration >= self._idle_sustain:
                self._state = DaemonState.IDLE_DETECTED
                await self._dispatch_next_task()
        else:
            self._idle_since = None
            if self._state not in (DaemonState.DISPATCHING, DaemonState.PREEMPTING):
                self._state = DaemonState.MONITORING

    async def _dispatch_next_task(self) -> None:
        """Pick the next task from the priority list and dispatch it concurrently."""
        if not self._task_priority or self._task_runner is None:
            self._state = DaemonState.MONITORING
            return

        task_name = self._task_priority[self._task_index % len(self._task_priority)]
        self._task_index = (self._task_index + 1) % len(self._task_priority)

        token = PreemptionToken()
        self._current_token = token
        self._current_task_name = task_name
        self._state = DaemonState.DISPATCHING

        log.info("Idle threshold sustained, dispatching task: %s", task_name)
        self._dispatch_task = asyncio.create_task(
            self._run_dispatched(task_name, token),
            name=f"daemon-dispatch-{task_name}",
        )

    async def _run_dispatched(self, task_name: str, token: PreemptionToken) -> None:
        """Run a dispatched task and clean up state on completion."""
        try:
            result = await self._task_runner(task_name, token)
            if isinstance(result, dict) and result.get("preempted"):
                log.info("Task %s yielded (preempted)", task_name)
            else:
                log.info("Task %s completed", task_name)
        except TaskPreempted:
            log.info("Task %s yielded via TaskPreempted", task_name)
        except Exception:
            log.exception("Task %s failed", task_name)
        finally:
            self._current_token = None
            self._current_task_name = None
            self._dispatch_task = None
            self._idle_since = None  # Reset idle timer after task
            self._state = DaemonState.MONITORING


# ── Module-level singleton ────────────────────────────────────────────────────

_daemon: ResourceMonitorDaemon | None = None


def init(
    estimator: LoadEstimator | None = None,
    task_runner: Callable[..., Any] | None = None,
    config: dict[str, Any] | None = None,
) -> ResourceMonitorDaemon:
    """Create or reconfigure the module-level daemon singleton."""
    global _daemon
    cfg = config or {}
    if estimator is None:
        estimator = LoadEstimator(
            window_depth=cfg.get("telemetry_window_depth", 20),
        )
    _daemon = ResourceMonitorDaemon(
        estimator=estimator,
        task_runner=task_runner,
        task_priority=cfg.get("task_priority", []),
        poll_interval_seconds=cfg.get("poll_interval_seconds", DEFAULT_POLL_INTERVAL),
        idle_threshold=cfg.get("idle_threshold", DEFAULT_IDLE_THRESHOLD),
        idle_sustain_seconds=cfg.get("idle_sustain_seconds", DEFAULT_IDLE_SUSTAIN),
        busy_threshold=cfg.get("busy_threshold", DEFAULT_BUSY_THRESHOLD),
        grace_period_seconds=cfg.get("grace_period_seconds", DEFAULT_GRACE_PERIOD),
        enabled=cfg.get("enabled", True),
    )
    return _daemon


async def start() -> None:
    """Start the module-level daemon."""
    if _daemon is not None:
        await _daemon.start()


async def stop() -> None:
    """Stop the module-level daemon."""
    if _daemon is not None:
        await _daemon.stop()


def is_running() -> bool:
    """Return ``True`` if the daemon is actively monitoring."""
    return _daemon is not None and _daemon.state != DaemonState.STOPPED


def get_status() -> dict[str, Any]:
    """Return daemon status dict (safe to call even when not initialised)."""
    if _daemon is None:
        return {"state": DaemonState.STOPPED.value, "enabled": False}
    return _daemon.get_status()
