---
version: 1.2.0
last_updated: 2026-03-31
---

# Concept — Resource Monitor Daemon

**Version:** 1.2.0  
**Status:** Active  
**Last updated:** 2026-03-31  

---

## NAME

resource-monitor-daemon — load-based opportunistic task scheduling for Lumina

## SYNOPSIS

The **Resource Monitor Daemon** is a background asyncio task that periodically
samples system load and dispatches batch maintenance tasks when the host
is idle.  If user activity spikes while a task is running, the daemon requests
cooperative preemption, pausing background work so latency-sensitive requests
are not degraded.

The daemon is the primary dispatch mechanism for batch processing tasks.
Manual triggers via the `trigger_daemon_task` admin command are also supported.

---

## DESCRIPTION

### A. Design Principle

Traditional batch systems run on a wall-clock schedule (e.g. daily at 02:00).
This works poorly when the system is heavily used at night or sits idle during
the day.  The Resource Monitor Daemon inverts the trigger model: instead of
asking “is it 2 AM?”, it asks “is the system idle right now?”

> **Analogy:** a workbench janitor who tidies up whenever the workshop is empty
> but immediately backs off when someone walks in.

The daemon runs on the **same asyncio event loop** as the FastAPI server, using a
single `asyncio.Task`.  No threads, no subprocesses, no separate scheduler.
Cooperative yielding keeps overhead near zero during normal operation.

### B. Load Estimation

The `LoadEstimator` samples three probes and blends them into a single
0.0 – 1.0 `load_score`:

| Probe | Module | Measures | Normalisation Ceiling |
|-------|--------|----------|-----------------------|
| Event-loop latency | `hw_loop_latency` | Delay between `call_soon` and actual callback execution | 50 ms |
| HTTP queue depth | `hw_http_queue` | Thread-safe counter of in-flight HTTP requests | 20 concurrent |
| GPU VRAM usage | `hw_gpu` | VRAM utilisation percentage (stub — pluggable) | 100 % |

Each probe returns a `dict | None`.  When a probe returns `None` (unavailable
or errored), its configured weight is **redistributed** proportionally among
the remaining probes so that the total weight stays at 1.0.

Default weights (configurable in `cfg/system-runtime-config.yaml`):

```yaml
probe_weights:
  loop_latency: 0.5
  http_queue: 0.3
  gpu: 0.2
```

The load score drives two thresholds:

| Threshold | Default | Meaning |
|-----------|---------|---------|
| `idle_threshold` | 0.20 | Load below this for `idle_sustain_seconds` triggers dispatch |
| `busy_threshold` | 0.40 | Load above this during a dispatch requests preemption |

### C. State Machine

```
STOPPED ──→ STARTING ──→ MONITORING ──→ IDLE_DETECTED ──→ DISPATCHING
                              ↑                                 │
                              └──────────── (task done) ────────┘
```

| State | Description |
|-------|-------------|
| `STOPPED` | Daemon not running |
| `STARTING` | `start()` called, poll loop task created but not yet yielded |
| `MONITORING` | Polling load at `poll_interval_seconds` |
| `IDLE_DETECTED` | Load below `idle_threshold` but sustain window not yet met |
| `DISPATCHING` | A maintenance task is running concurrently |
| `PREEMPTING` | Load spiked — `PreemptionToken.request_yield()` called, awaiting task exit |

### D. Preemption Protocol

Tasks run via `TaskAdapter.run_task_preemptible()`.  The adapter inserts
`token.checkpoint_sync()` calls between domain iterations.  When the daemon
detects a load spike, it calls `token.request_yield()`.  The next checkpoint
raises `TaskPreempted`, unwinding the task cleanly.

The preemption model is **cooperative** — the daemon cannot forcibly kill a
running task.  Tasks that honour checkpoints exit within one domain iteration.

### E. Grace Period

For 60 seconds after startup (configurable via `grace_period_seconds`) the
daemon suppresses all dispatch.  This prevents thrashing during server boot
when event-loop latency is transiently high.

### F. Task Priority

The daemon walks a priority-ordered task list.  Each poll, it selects the
**next** task in round-robin order from `task_priority`:

```yaml
task_priority:
  - knowledge_graph_rebuild
  - glossary_expansion
  - glossary_pruning
  - rebuild_domain_vectors
  - telemetry_summary_refresh
  - rejection_corpus_alignment
  - pacing_heuristic_recompute
  - slm_hint_generation
  - context_crawler
```

Only tasks registered in the daemon's task registry are eligible.  Unknown
tasks are skipped with a warning.

---

## CONFIGURATION

All daemon settings live in `cfg/system-runtime-config.yaml` under the
`daemon:` key.  Set `enabled: false` to disable the daemon entirely (the poll
loop is never created).

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `enabled` | bool | `true` | Master switch |
| `poll_interval_seconds` | float | 15 | Seconds between load samples |
| `idle_threshold` | float | 0.20 | Load score below which system is idle |
| `idle_sustain_seconds` | float | 300 | Seconds of sustained idle before dispatch |
| `busy_threshold` | float | 0.40 | Load score above which a running task is preempted |
| `grace_period_seconds` | float | 60 | Startup grace period (no dispatch) |
| `probe_weights` | map | see above | Per-probe weight for load scoring |
| `task_priority` | list | see above | Ordered task names for dispatch |

---

## API ENDPOINTS

| Method | Path | RBAC | Description |
|--------|------|------|-------------|
| `GET` | `/api/health` | — | Includes `daemon` object with current state |
| `GET` | `/api/health/load` | root, auditor | Full daemon status + last `LoadSnapshot` |

---

## INTEGRATION POINTS

- **Server lifecycle** — `server.py` calls `daemon.init()` at startup and
  `daemon.stop()` at shutdown.
- **Middleware** — `_InFlightCounterMiddleware` increments/decrements the
  `hw_http_queue` probe around every HTTP request.
- **Batch task dispatch** — The daemon dispatches maintenance tasks directly
  via `TaskAdapter.run_task_preemptible()`, walking the `task_priority` list
  in round-robin order each time the system becomes idle.
- **System health** — `SystemHealthMonitor.sample()` exposes all three daemon
  probes (loop latency, HTTP queue, GPU) in the health state.

---

## SOURCE FILES

- `src/lumina/daemon/__init__.py` — Package init
- `src/lumina/daemon/load_estimator.py` — `LoadEstimator` + `LoadSnapshot`
- `src/lumina/daemon/preemption.py` — `PreemptionToken` + `TaskPreempted`
- `src/lumina/daemon/resource_monitor.py` — `ResourceMonitorDaemon` state machine
- `src/lumina/daemon/task_adapter.py` — `run_task_preemptible()` + `run_cross_domain_task_preemptible()` bridges
- `src/lumina/systools/hw_loop_latency.py` — Event-loop latency probe
- `src/lumina/systools/hw_http_queue.py` — In-flight HTTP counter
- `src/lumina/systools/hw_gpu.py` — GPU VRAM probe (stub)
- `cfg/system-runtime-config.yaml` — Daemon configuration

---

## SEE ALSO

- [`edge-vectorization(7)`](edge-vectorization.md) — per-domain vector stores and daemon-driven rebuild triggers
- [`group-libraries-and-tools(7)`](group-libraries-and-tools.md) — Group Library dependency-aware rebuilds via `rebuild_group_library_dependents()`
- [`execution-route-compilation(7)`](execution-route-compilation.md) — ahead-of-time route compilation (may be re-triggered after physics changes)
- [`daemon-batch-processing(8)`](../8-admin/daemon-batch-processing.md) — batch processing subsystem that the daemon dispatches into
