"""Tests for lumina.daemon.resource_monitor."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from lumina.daemon.load_estimator import LoadSnapshot, TelemetrySummary
from lumina.daemon.preemption import TaskPreempted
from lumina.daemon.resource_monitor import (
    DaemonState,
    ResourceMonitorDaemon,
    get_status,
    init,
    is_running,
    start,
    stop,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_snapshot(load_score: float = 0.0, is_idle: bool = True) -> LoadSnapshot:
    return LoadSnapshot(
        timestamp=0.0,
        loop_latency_ms=1.0,
        inflight_requests=0,
        gpu_pct=None,
        load_score=load_score,
        is_idle=is_idle,
    )


def _make_estimator() -> MagicMock:
    estimator = MagicMock()
    estimator.get_window_summary.return_value = TelemetrySummary(
        json_summary={"load_trajectory": "stable", "samples": 1},
    )
    return estimator


# ── Lifecycle ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.anyio
async def test_start_stop_lifecycle() -> None:
    daemon = ResourceMonitorDaemon(enabled=True, poll_interval_seconds=0.1)
    assert daemon.state == DaemonState.STOPPED

    await daemon.start()
    await asyncio.sleep(0)  # yield so the loop task starts
    assert daemon.state == DaemonState.MONITORING

    await daemon.stop()
    assert daemon.state == DaemonState.STOPPED


@pytest.mark.unit
@pytest.mark.anyio
async def test_disabled_daemon_does_not_start() -> None:
    daemon = ResourceMonitorDaemon(enabled=False)
    await daemon.start()
    assert daemon.state == DaemonState.STOPPED


@pytest.mark.unit
@pytest.mark.anyio
async def test_double_start_is_safe() -> None:
    daemon = ResourceMonitorDaemon(enabled=True, poll_interval_seconds=0.1)
    await daemon.start()
    await daemon.start()  # second call is idempotent
    await asyncio.sleep(0)  # yield so the loop task starts
    assert daemon.state == DaemonState.MONITORING
    await daemon.stop()


@pytest.mark.unit
@pytest.mark.anyio
async def test_double_stop_is_safe() -> None:
    daemon = ResourceMonitorDaemon(enabled=True, poll_interval_seconds=0.1)
    await daemon.start()
    await daemon.stop()
    await daemon.stop()  # second call is idempotent
    assert daemon.state == DaemonState.STOPPED


# ── Status ────────────────────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.anyio
async def test_get_status_when_running() -> None:
    daemon = ResourceMonitorDaemon(enabled=True, poll_interval_seconds=0.1)
    await daemon.start()
    await asyncio.sleep(0)  # yield so the loop task starts
    status = daemon.get_status()
    assert status["state"] == "MONITORING"
    assert status["enabled"] is True
    await daemon.stop()


@pytest.mark.unit
def test_get_status_when_stopped() -> None:
    daemon = ResourceMonitorDaemon(enabled=True)
    status = daemon.get_status()
    assert status["state"] == "STOPPED"


# ── Grace period ──────────────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.anyio
async def test_grace_period_suppresses_dispatch() -> None:
    """During grace period, no tasks should be dispatched even if idle."""
    mock_estimator = _make_estimator()
    mock_estimator.sample = AsyncMock(return_value=_make_snapshot(load_score=0.0, is_idle=True))

    task_runner = AsyncMock(return_value={"preempted": False})

    daemon = ResourceMonitorDaemon(
        estimator=mock_estimator,
        task_runner=task_runner,
        task_priority=["test_task"],
        poll_interval_seconds=0.05,
        idle_sustain_seconds=0.0,
        grace_period_seconds=10.0,  # long grace
        enabled=True,
    )
    await daemon.start()
    await asyncio.sleep(0.2)
    await daemon.stop()

    task_runner.assert_not_called()


# ── State transitions ────────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.anyio
async def test_idle_triggers_dispatch() -> None:
    """After sustained idle, the daemon should dispatch a task."""
    mock_estimator = _make_estimator()
    mock_estimator.sample = AsyncMock(return_value=_make_snapshot(load_score=0.05, is_idle=True))

    task_runner = AsyncMock(return_value={"preempted": False})

    daemon = ResourceMonitorDaemon(
        estimator=mock_estimator,
        task_runner=task_runner,
        task_priority=["glossary_expansion"],
        poll_interval_seconds=0.05,
        idle_sustain_seconds=0.0,  # immediate dispatch
        grace_period_seconds=0.0,  # no grace
        enabled=True,
    )
    await daemon.start()
    await asyncio.sleep(0.3)
    await daemon.stop()

    assert task_runner.call_count >= 1
    args = task_runner.call_args[0]
    assert args[0] == "glossary_expansion"


# ── Preemption ────────────────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.anyio
async def test_preemption_on_load_spike() -> None:
    """When load spikes mid-task, the token should request yield."""
    call_count = 0
    yielded = False

    async def slow_task(task_name, token):
        nonlocal yielded
        # Simulate a long-running task that checks for preemption
        for _ in range(50):
            try:
                await token.checkpoint()
            except TaskPreempted:
                yielded = True
                return {"preempted": True}
            await asyncio.sleep(0.01)
        return {"preempted": False}

    # Start idle, then spike after a few polls
    snapshots = iter([
        _make_snapshot(0.05, True),   # idle
        _make_snapshot(0.05, True),   # still idle → dispatch
        _make_snapshot(0.8, False),   # spike → preempt
        _make_snapshot(0.8, False),
        _make_snapshot(0.05, True),
    ])

    mock_estimator = _make_estimator()
    mock_estimator.sample = AsyncMock(side_effect=lambda: next(snapshots, _make_snapshot(0.05, True)))

    daemon = ResourceMonitorDaemon(
        estimator=mock_estimator,
        task_runner=slow_task,
        task_priority=["test_task"],
        poll_interval_seconds=0.05,
        idle_sustain_seconds=0.0,
        busy_threshold=0.4,
        grace_period_seconds=0.0,
        enabled=True,
    )
    await daemon.start()
    await asyncio.sleep(0.5)
    await daemon.stop()

    assert yielded is True


# ── Module-level functions ────────────────────────────────────────────────────


@pytest.mark.unit
def test_module_get_status_without_init() -> None:
    """get_status() should be safe before init()."""
    # Reset any previously set daemon
    import lumina.daemon.resource_monitor as mod
    prev = mod._daemon
    mod._daemon = None
    try:
        status = get_status()
        assert status["state"] == "STOPPED"
        assert status["enabled"] is False
    finally:
        mod._daemon = prev


@pytest.mark.unit
def test_is_running_without_init() -> None:
    import lumina.daemon.resource_monitor as mod
    prev = mod._daemon
    mod._daemon = None
    try:
        assert is_running() is False
    finally:
        mod._daemon = prev
