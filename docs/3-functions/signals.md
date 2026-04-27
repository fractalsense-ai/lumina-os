---
version: 1.0.0
last_updated: 2026-04-25
---

# signals(3) — Domain-agnostic signal decomposition API

**Version:** 1.0.0
**Status:** Active
**Last updated:** 2026-04-25
**Module:** `src/lumina/signals/`

---

## NAME

`lumina.signals` — generalised, signal-name-agnostic primitives for
EWMA baseline tracking, envelope/shape-deviation detection, multi-band
spectral decomposition, and advisory rendering. The single source of
truth for the math behind every domain's signal monitoring.

## SYNOPSIS

```python
from lumina.signals import (
    # State containers
    SignalSample, SignalBaseline, SignalDriftSignal,

    # Acute + heartbeat layers
    update_baseline, compute_drift,
    check_envelope_deviation, check_shape_deviation,

    # Chronic spectral layer
    resample_to_daily,
    compute_spectral_signature,
    update_spectral_history,
    check_spectral_drift,

    # Advisory layer
    render_advisory_message,
    pull_active_advisory,
    upsert_spectral_advisory,

    # Defaults
    DEFAULT_BAND_DEFS_DAYS,
    DEFAULT_ADVISORY_TTL_SECONDS,
)
```

## DESCRIPTION

`lumina.signals` is the framework module that the
[signal-decomposition-framework(7)](../7-concepts/signal-decomposition-framework.md)
sits on. Every domain that monitors any scalar over time — assistant
SVA, agriculture sensors, future lab instruments — routes through this
package. Domain-specific code (e.g.
`model-packs/assistant/domain-lib/affect_monitor.py`) is now a thin
adapter that supplies a signal name and forwards to these functions.

### Data shapes

#### `SignalSample`

```python
@dataclass(frozen=True)
class SignalSample:
    name: str               # arbitrary domain-chosen identifier
    value: float            # the scalar
    timestamp_utc: str      # ISO-8601
```

#### `SignalBaseline`

Per-signal rolling state:

| Field                | Purpose |
|----------------------|---------|
| `ewma_value`         | Exponentially-weighted mean. |
| `ewma_variance`      | Exponentially-weighted variance. |
| `n_samples`          | Sample count (for warmup gating). |
| `last_value`         | Most recent raw sample. |
| `last_timestamp_utc` | Most recent sample time. |
| `spectral_history`   | Per-signal dict of band → rolling EWMA history (chronic layer). |

#### `SignalDriftSignal`

Returned by `compute_drift`: holds `z_score`, `direction`,
`run_length`, and the raw delta from baseline.

### Acute + heartbeat layers

```python
update_baseline(baseline: SignalBaseline | None,
                sample: SignalSample,
                *, alpha: float = 0.1) -> SignalBaseline
```
Folds one sample into a (possibly-`None`) baseline. Returns a new
`SignalBaseline`; the input is never mutated.

```python
compute_drift(baseline: SignalBaseline,
              sample: SignalSample) -> SignalDriftSignal
```
Computes z-score and direction of `sample` against `baseline`.

```python
check_envelope_deviation(drift: SignalDriftSignal,
                         *, threshold_z: float = 3.0) -> bool
```
True when |z| ≥ threshold (acute breach).

```python
check_shape_deviation(drift: SignalDriftSignal,
                      *, min_run_length: int = 5) -> bool
```
True when the same-direction run length is sustained beyond the
natural noise crossing rate.

### Chronic spectral layer

```python
resample_to_daily(samples: list[SignalSample]) -> list[float]
```
Bucket samples into one value per UTC day (mean of intra-day samples).

```python
compute_spectral_signature(daily_values: list[float],
                           *, bands: dict[str, list[int]] | None = None
                           ) -> dict[str, float]
```
Returns per-band magnitudes plus `dc_direction`. Bands default to
`DEFAULT_BAND_DEFS_DAYS` (`dc_drift`, `circaseptan`, `noise_floor`).

```python
update_spectral_history(history: dict, signature: dict,
                        *, alpha: float = 0.2) -> dict
```
Folds today's signature into the rolling per-band EWMA history.

```python
check_spectral_drift(history: dict, signature: dict,
                     *, threshold_z: float = 3.0) -> list[dict]
```
Returns one finding per band whose magnitude exceeds the rolling EWMA
+ threshold·σ. Each finding carries `{band, z_score, today_value,
ewma_value, direction}` — `direction` is `+1 | -1 | 0` (integer).

### Advisory layer

```python
render_advisory_message(finding: dict, signal_def: dict) -> str
```
Renders a finding into the human message. Resolution order:

1. Exact `message_overrides["<band>,<direction>"]` (direction is
   `"positive" | "negative" | "neutral"`).
2. Band-wildcard `message_overrides["<band>,*"]`.
3. Framework default neutral template, with `{label}` substituted.

```python
upsert_spectral_advisory(profile: dict, finding: dict, message: str,
                         *, ttl_seconds: int = DEFAULT_ADVISORY_TTL_SECONDS,
                         signal_def: dict | None = None) -> dict
```
Writes / replaces the advisory at
`profile.learning_state.spectral_advisories` for the same
`(signal, band)` key. Honors `signal_def["advisory_ttl_seconds"]` if
provided. Persisted records conform to
[spectral-advisory-schema-v1](../../standards/spectral-advisory-schema-v1.json).

```python
pull_active_advisory(profile: dict,
                     signal_priorities: dict[str, int] | None = None
                     ) -> dict | None
```
Returns the highest-priority unexpired advisory across all signals on
the profile. Tie-break order: signal `advisory_priority` →
`band_priority` (`dc_drift` > `circaseptan` > `ultradian` > others) →
`created_utc` (most recent wins). Used by in-session adapters (e.g.
`journal_adapters`) to surface chronic findings exactly once per
session.

### Constants

| Name | Value | Meaning |
|------|-------|---------|
| `DEFAULT_BAND_DEFS_DAYS` | `{"dc_drift": [10, 60], "circaseptan": [5, 9], "noise_floor": [1, 2]}` | Default per-band day-window bounds. |
| `DEFAULT_ADVISORY_TTL_SECONDS` | `86400` | 24-hour advisory expiry. |

## DIRECTION VOCABULARY

The framework uses two parallel direction vocabularies; one is
internal (math), one is external (advisory schema). They convert at
the daemon→advisory boundary:

| Layer            | Vocabulary                    |
|------------------|-------------------------------|
| `compute_drift` / `check_spectral_drift` finding | `+1 / -1 / 0` (int) |
| Daemon `Proposal.detail.direction`              | `+1 / -1 / 0` (int, preserved for back-compat) |
| `render_advisory_message` `message_overrides` keys | `"positive" / "negative" / "neutral" / "*"` |
| Persisted `spectral_advisories[*].direction`    | `"positive" / "negative" / "neutral"` |

## SEE ALSO

- [signal-decomposition-framework(7)](../7-concepts/signal-decomposition-framework.md)
- [affect-monitor(3)](affect-monitor.md) — the SVA adapter built on this API
- [daemon-tasks(1)](../1-commands/daemon-tasks.md) — `rhythm_fft_analysis` consumer
- [domain-physics-schema-v1](../../standards/domain-physics-schema-v1.json)
- [spectral-advisory-schema-v1](../../standards/spectral-advisory-schema-v1.json)
