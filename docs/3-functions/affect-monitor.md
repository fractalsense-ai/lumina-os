---
version: 1.0.0
last_updated: 2026-07-17
---

# affect-monitor(3) — Public function-level API

**Version:** 1.0.0
**Status:** Active
**Last updated:** 2026-07-17
**Module:** `domain-packs/assistant/domain-lib/affect_monitor.py`

---

## NAME

`affect_monitor` — domain-lib component that maintains a compressed
representation of an actor's affect (Salience, Valence, Arousal) over
time, with envelope-aware variance, rhythm-shape tracking, and a
chronic spectral fingerprint.

## SYNOPSIS

```python
from affect_monitor import (
    AffectState, AffectBaseline, DriftSignal,
    update_affect, update_baseline, compute_drift,
    update_relational_baseline,
    check_shape_deviation, check_relational_deviation, check_global_deviation,
)
```

## DESCRIPTION

The affect-monitor implements the **acute envelope** and **heartbeat
shape** layers of the affect monitoring pipeline (see
[affect-monitoring-pipeline(7)](../7-concepts/affect-monitoring-pipeline.md)).
The **chronic spectral** layer is owned by the
`rhythm_fft_analysis` daemon task (see [daemon-tasks(1)](../1-commands/daemon-tasks.md))
and writes back into the `spectral_history` field of `AffectBaseline`
plus `learning_state.spectral_advisories` on the actor profile.

### Data shapes

#### `AffectState`

The SVA triad for a single turn.

| Field      | Range  | Meaning |
|------------|--------|---------|
| `salience` | 0..1   | Engagement / focus (low = drifting). |
| `valence`  | -1..1  | Satisfaction tone (negative = frustrated). |
| `arousal`  | 0..1   | Activation level (high = frantic, low = flat). |

#### `AffectBaseline`

Domain-wide rolling state for an actor.  Three concentric layers:

**Layer 1 — central tendency (Phase A–E, acute envelope).**

`salience`, `valence`, `arousal` — EWMA estimates.
`prev_*` — previous-turn EWMA values, used by `compute_drift`.
`salience_variance`, `valence_variance`, `arousal_variance` — EWMA
variance per axis; seeded at `0.04` (≈ std 0.2). Provides the
*envelope* against which deviations are scored.
`per_module` — per-module signature dict for relational baselines.

**Layer 2 — rhythm shape (Phase F, heartbeat).**

`*_crossing_rate` — EWMA of "did residual flip sign this turn?".
Captures the actor's natural oscillation frequency.
`*_run_length` — signed count of consecutive same-direction residuals.
Detects sustained shifts that stay inside the amplitude envelope but
break the actor's normal rhythm.

**Layer 3 — chronic spectral (Phase G, daemon-owned).**

`spectral_history` — opaque blob owned exclusively by
`rhythm_fft_analysis`.  Per-turn paths must not mutate it.  Shape:

```python
{
  "ewma":      {band: float, ...},
  "variance":  {band: float, ...},
  "sample_count":   int,
  "last_run_utc":   "ISO-8601",
  "last_signature": {band: float, ...},
}
```

#### `DriftSignal`

One-turn output of `compute_drift`.

| Field              | Meaning |
|--------------------|---------|
| `velocity_*`       | Rate of change on each axis (negative = dropping). |
| `is_fast_drift`    | True when any axis exceeds `fast_drift_threshold`. |
| `drift_axis`       | Name of the worst-offender axis. |
| `drift_magnitude`  | Absolute value of the worst velocity. |

### Public API by phase

#### Phase A–E — acute envelope

`update_affect(prior: AffectState, evidence: dict, params: dict) -> AffectState`
- Applies one turn of evidence to the per-turn affect estimate. Pure function; returns a new `AffectState`.

`update_baseline(baseline: AffectBaseline, observed: AffectState, module: str | None, params: dict) -> AffectBaseline`
- EWMA-folds the observed turn into the rolling baseline and updates per-axis variance. Updates `prev_*` for next-turn drift computation.

`compute_drift(baseline: AffectBaseline, params: dict) -> DriftSignal`
- Computes per-axis velocity and flags fast drift.

`update_relational_baseline(baseline: AffectBaseline, observed: AffectState, module: str, params: dict) -> AffectBaseline`
- Folds the observed turn into the per-module relational signature inside `baseline.per_module[module]`.

#### Phase F — heartbeat shape

`check_shape_deviation(baseline: AffectBaseline, observed: AffectState, params: dict) -> dict`
- Runs the rhythm-shape check (crossing-rate + run-length deviation) and returns a structured advisory dict (or empty dict if no deviation).

`check_relational_deviation(baseline: AffectBaseline, observed: AffectState, module: str, params: dict) -> dict`
- Z-score deviation of the observed turn against the per-module signature.

`check_global_deviation(baseline: AffectBaseline, observed: AffectState, params: dict) -> dict`
- Z-score deviation against the domain-wide baseline.

#### Phase G / G.5 — chronic spectral & advisory surface

The chronic layer is **not** invoked from the per-turn path.  See:

- [daemon-tasks(1) → `rhythm_fft_analysis`](../1-commands/daemon-tasks.md) — the daemon task that writes `spectral_history` and upserts advisories.
- `_upsert_spectral_advisory(advisories, *, axis, band, finding, now_utc=None, ttl_seconds=86400)` (in `src/lumina/daemon/tasks.py`) — writes the advisory record and returns the new pruned list.  Default TTL is 24 hours; same-`(axis, band)` writes replace prior records.

The journal adapter consumes those advisories via:

- `journal_session_start(state, profile_data=None, persistence=None, user_id=None, session_id=None) -> (state, decision)` — returns the highest-priority active advisory for surfacing in the opening turn.
- `journal_domain_step(...)` — sticky piggyback delivery on the first ordinary turn that has not yet surfaced an advisory in this session.

Priority order (used by both surfacing entry points):

1. Axis: `valence` > `arousal` > `salience`.
2. Band: `dc_drift` > `circaseptan` > `ultradian`.

### Configuration keys (`DEFAULT_PARAMS`)

| Key                                | Default | Purpose |
|------------------------------------|---------|---------|
| `ewma_alpha`                       | 0.1     | EWMA smoothing factor for the baseline. |
| `fast_drift_threshold`             | 0.05    | Per-turn velocity beyond which `is_fast_drift` fires. |
| `intent_switch_salience_penalty`   | 0.08    | Salience drop applied when an intent switch is detected. |
| `intent_switch_arousal_boost`      | 0.05    | Arousal boost on intent switch. |
| `latency_low`                      | 2.0     | Sub-threshold latency (seconds) → high arousal. |
| `latency_high`                     | 30.0    | Above this latency → low arousal & salience. |
| `min_samples_for_drift`            | 5       | Minimum samples before drift detection activates. |

## SEE ALSO

- [affect-monitoring-pipeline(7)](../7-concepts/affect-monitoring-pipeline.md) — three-layer architecture concept doc.
- [daemon-tasks(1)](../1-commands/daemon-tasks.md) — `rhythm_fft_analysis` and other registered daemon tasks.
- [baseline-before-escalation(7)](../7-concepts/baseline-before-escalation.md) — companion gate that suppresses delta-driven escalation while baselines are still priming.
- [domain-state-lib(3)](./domain-state-lib.md) — the broader contract that domain-lib components conform to.
