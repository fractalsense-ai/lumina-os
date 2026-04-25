---
version: 1.0.0
last_updated: 2026-07-17
---

# daemon-tasks(1)

**Version:** 1.0.0
**Status:** Active
**Last updated:** 2026-07-17

---

## NAME

`lumina-daemon-tasks` — registered idle-dispatch tasks that run when the
resource monitor reports spare capacity.

## SYNOPSIS

```python
from lumina.daemon.tasks import list_tasks, list_cross_domain_tasks, get_task

# Enumerate registered tasks
list_tasks()                 # → list[str]
list_cross_domain_tasks()    # → list[str]

# Look up a task by name
get_task("rhythm_fft_analysis")
```

## DESCRIPTION

Daemon tasks are lightweight, opportunistically scheduled functions that
run inside the `ResourceMonitorDaemon` when load is low.  Each task is
declared with the `@register_task(name)` decorator (or
`@register_cross_domain_task(name)` for tasks that need the full
opt-in domain set rather than a single domain).

Tasks are **proposal-emitting**: they observe state and write `Proposal`
records for downstream Domain Authority review rather than mutating
state directly.  This preserves the framework's two-key-write
invariant — only an authority confirmation can promote a proposal into
a state change.

### Lifecycle

1. The resource monitor samples CPU / memory pressure on a fixed cadence.
2. When pressure is below the configured threshold, the next task in the rotation is dispatched.
3. The task receives the actor profile (and, for cross-domain tasks, the union of opt-in domains), runs to completion, and emits zero or more `Proposal` records (and, for `rhythm_fft_analysis`, advisory records — see below).
4. Cooperative preemption: tasks check the cancellation flag and return early when load rises.

### Registered tasks

| Name                              | Scope        | Purpose |
|-----------------------------------|--------------|---------|
| `glossary_expansion`              | per-domain   | Suggest new vocabulary entries from recent traffic. |
| `glossary_pruning`                | per-domain   | Mark stale glossary entries as candidates for removal. |
| `rejection_corpus_alignment`      | per-domain   | Re-cluster rejected utterances against current taxonomy. |
| `cross_module_consistency`        | per-domain   | Detect contradictions between sibling modules. |
| `knowledge_graph_rebuild`         | per-domain   | Recompute derived edges in the domain knowledge graph. |
| `pacing_heuristic_recompute`      | per-domain   | Refresh per-actor pacing constants. |
| `domain_physics_constraint_refresh` | per-domain | Re-validate physics constraints against current evidence. |
| `slm_hint_generation`             | per-domain   | Pre-generate SLM hint cache entries for hot prompts. |
| `telemetry_summary_refresh`       | per-domain   | Roll up telemetry counters into summary snapshots. |
| `logic_scrape_review`             | per-domain   | Review staged logic-scrape candidates. |
| `context_crawler`                 | per-domain   | Walk linked context to surface stale references. |
| `gated_staging`                   | per-domain   | Promote eligible staged files past their quarantine gate. |
| `rebuild_domain_vectors`          | cross-domain | Rebuild per-domain vector stores after edge-vectorization changes. |
| `rhythm_fft_analysis`             | per-domain   | Phase G chronic spectral layer — see below. |

### `rhythm_fft_analysis` (Phase G / G.5)

This task scans the actor's historical affect samples per axis
(valence, arousal, salience), runs a lightweight FFT over each axis,
and looks for sustained drift across three temporal bands:

| Band           | Window                      |
|----------------|-----------------------------|
| `dc_drift`     | mean shift over weeks       |
| `circaseptan`  | ~7-day periodicity          |
| `ultradian`    | sub-daily (multi-hour)      |

For each (axis, band) finding, it:

1. Writes a `Proposal` record (downstream review hook).
2. **Phase G.5**: upserts an advisory record into
   `profile["learning_state"]["spectral_advisories"]` via
   `_upsert_spectral_advisory`.  Advisories carry a 24-hour TTL and are
   deduped by `(axis, band)` so the most recent finding always wins.

These advisories are the bridge between the chronic layer and the
in-session adapter; see [affect-monitoring-pipeline(7)](../7-concepts/affect-monitoring-pipeline.md) for the full architecture.

## EXIT STATUS

Daemon tasks return a `TaskResult` dataclass; they do not propagate exit
codes to the OS.  Failures are logged and the rotation advances.

## SEE ALSO

- [resource-monitor-daemon(7)](../7-concepts/resource-monitor-daemon.md) — scheduler that dispatches these tasks.
- [affect-monitoring-pipeline(7)](../7-concepts/affect-monitoring-pipeline.md) — three-layer model that `rhythm_fft_analysis` belongs to.
- [affect-monitor(3)](../3-functions/affect-monitor.md) — function-level API for the affect-monitor module.
