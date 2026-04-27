"""lumina.signals.baseline — EWMA baseline + envelope + heartbeat-shape math.

Generalises the per-axis math previously hardcoded in
``model-packs/assistant/domain-lib/affect_monitor.py`` to operate on
any named scalar signal. Bands of bounds (range clamps) are driven by
the caller via ``clamp`` arguments — the framework is range-agnostic.

Every public function is pure: no I/O, no profile mutation, no globals.
The daemon and the assistant adapter both wrap these to update the
persisted ``learning_state.signal_baselines`` dict.
"""

from __future__ import annotations

import math
from typing import Any

from .state import (
    DEFAULT_CROSSING_RATE_SEED,
    DEFAULT_VARIANCE_SEED,
    SignalBaseline,
    SignalDriftSignal,
    SignalSample,
)

# ─────────────────────────────────────────────────────────────
# Defaults — tuned to match the SVA constants the assistant pack
# has been running with, so adapter migration is behaviour-neutral.
# ─────────────────────────────────────────────────────────────

DEFAULT_EWMA_ALPHA: float = 0.1
DEFAULT_FAST_DRIFT_THRESHOLD: float = 0.05
DEFAULT_MIN_SAMPLES_FOR_DRIFT: int = 5
DEFAULT_NOISE_FLOOR: float = 0.05
DEFAULT_K_SIGMA: float = 2.0
DEFAULT_K_SHAPE: float = 2.0
DEFAULT_MIN_SAMPLES_ENVELOPE: int = 5
DEFAULT_MIN_SAMPLES_SHAPE: int = 10
DEFAULT_VARIANCE_FLOOR: float = 0.001


def _clamp(value: float, lo: float | None, hi: float | None) -> float:
    if lo is not None and value < lo:
        return lo
    if hi is not None and value > hi:
        return hi
    return value


# ─────────────────────────────────────────────────────────────
# Rhythm helpers (unchanged math, generic name)
# ─────────────────────────────────────────────────────────────


def _initial_run(residual: float, noise_floor: float) -> int:
    if abs(residual) < noise_floor:
        return 0
    return 1 if residual > 0 else -1


def _update_rhythm(
    residual: float,
    prev_run: int,
    prev_crossing_rate: float,
    alpha: float,
    noise_floor: float,
) -> tuple[int, float]:
    """Update (run_length, crossing_rate) given this turn's residual.

    Mirrors the affect_monitor logic exactly.
    """
    if abs(residual) < noise_floor:
        return prev_run, prev_crossing_rate
    cur_sign = 1 if residual > 0 else -1
    if prev_run == 0:
        return cur_sign, prev_crossing_rate
    prev_sign = 1 if prev_run > 0 else -1
    if cur_sign == prev_sign:
        new_cross = (1 - alpha) * prev_crossing_rate
        return prev_run + cur_sign, new_cross
    new_cross = alpha * 1.0 + (1 - alpha) * prev_crossing_rate
    return cur_sign, new_cross


# ─────────────────────────────────────────────────────────────
# Baseline update
# ─────────────────────────────────────────────────────────────


def update_baseline(
    baseline: SignalBaseline,
    sample: SignalSample,
    *,
    range_lo: float | None = None,
    range_hi: float | None = None,
    alpha: float = DEFAULT_EWMA_ALPHA,
    noise_floor: float = DEFAULT_NOISE_FLOOR,
    variance_seed: float = DEFAULT_VARIANCE_SEED,
) -> SignalBaseline:
    """Fold a single ``SignalSample`` into the EWMA baseline.

    First observation seeds the per-signal entry at the observed value
    with ``variance_seed`` variance, run-length seeded by sign of the
    observation residual against zero, and crossing rate at the default
    seed. Subsequent observations follow the standard EWMA + variance
    + heartbeat-shape recurrence.

    Returns a NEW SignalBaseline; never mutates the input. Other
    signals carry over unchanged (shallow copy of their per-signal dict).
    """
    new_per: dict[str, dict[str, Any]] = {}
    for name, entry in baseline.per_signal.items():
        if name != sample.name:
            new_per[name] = dict(entry)

    prev = baseline.per_signal.get(sample.name)
    observed = _clamp(float(sample.value), range_lo, range_hi)

    if prev is None:
        new_per[sample.name] = {
            "ewma": observed,
            "variance": float(variance_seed),
            "prev_ewma": observed,
            "crossing_rate": float(DEFAULT_CROSSING_RATE_SEED),
            "run_length": _initial_run(observed, noise_floor),
            "sample_count": 1,
            "spectral_history": {},
        }
        return SignalBaseline(per_signal=new_per)

    prev_ewma = float(prev.get("ewma", observed))
    prev_var = float(prev.get("variance", variance_seed))
    prev_run = int(prev.get("run_length", 0))
    prev_cross = float(prev.get("crossing_rate", DEFAULT_CROSSING_RATE_SEED))
    prev_count = int(prev.get("sample_count", 0))

    residual = observed - prev_ewma
    new_ewma = alpha * observed + (1 - alpha) * prev_ewma
    new_var = alpha * (residual ** 2) + (1 - alpha) * prev_var
    new_run, new_cross = _update_rhythm(residual, prev_run, prev_cross, alpha, noise_floor)

    new_per[sample.name] = {
        "ewma": round(new_ewma, 6),
        "variance": round(new_var, 6),
        "prev_ewma": round(prev_ewma, 6),
        "crossing_rate": round(new_cross, 6),
        "run_length": int(new_run),
        "sample_count": prev_count + 1,
        "spectral_history": dict(prev.get("spectral_history") or {}),
    }
    return SignalBaseline(per_signal=new_per)


# ─────────────────────────────────────────────────────────────
# Drift velocity
# ─────────────────────────────────────────────────────────────


def compute_drift(
    baseline: SignalBaseline,
    signal_name: str,
    *,
    fast_drift_threshold: float = DEFAULT_FAST_DRIFT_THRESHOLD,
    min_samples: int = DEFAULT_MIN_SAMPLES_FOR_DRIFT,
) -> SignalDriftSignal:
    """Per-signal drift velocity: ``ewma - prev_ewma``.

    Returns a zeroed ``SignalDriftSignal`` when the baseline is not
    yet mature or when the signal has never been observed.
    """
    entry = baseline.per_signal.get(signal_name)
    if entry is None:
        return SignalDriftSignal(name=signal_name)
    if int(entry.get("sample_count", 0)) < int(min_samples):
        return SignalDriftSignal(name=signal_name)
    velocity = float(entry.get("ewma", 0.0)) - float(entry.get("prev_ewma", 0.0))
    magnitude = abs(velocity)
    return SignalDriftSignal(
        name=signal_name,
        velocity=round(velocity, 6),
        magnitude=round(magnitude, 6),
        is_fast_drift=magnitude >= float(fast_drift_threshold),
    )


# ─────────────────────────────────────────────────────────────
# Envelope (z-score) check
# ─────────────────────────────────────────────────────────────


def _z(observed: float, mean: float, variance: float, var_floor: float) -> float:
    var = max(float(variance), float(var_floor))
    return abs(observed - mean) / math.sqrt(var)


def check_envelope_deviation(
    entry: dict[str, Any] | None,
    observed: float,
    *,
    k_sigma: float = DEFAULT_K_SIGMA,
    min_samples: int = DEFAULT_MIN_SAMPLES_ENVELOPE,
    variance_floor: float = DEFAULT_VARIANCE_FLOOR,
) -> dict[str, Any]:
    """Acute z-score envelope check for a single signal entry.

    Returns ``{triggered, z_score, reason, mature}``. Compatible with
    the historical ``check_global_deviation`` / ``check_relational_deviation``
    return shape minus the ``axis`` field — callers know which signal
    they passed in.
    """
    if entry is None or int(entry.get("sample_count", 0)) < int(min_samples):
        return {"triggered": False, "z_score": 0.0,
                "reason": "baseline_immature", "mature": False}
    z = _z(observed, float(entry.get("ewma", 0.0)),
           float(entry.get("variance", variance_floor)), variance_floor)
    triggered = z > float(k_sigma)
    return {
        "triggered": triggered,
        "z_score": round(z, 4),
        "reason": "envelope_exceeded" if triggered else "within_envelope",
        "mature": True,
    }


# ─────────────────────────────────────────────────────────────
# Heartbeat-shape check
# ─────────────────────────────────────────────────────────────


def check_shape_deviation(
    entry: dict[str, Any] | None,
    *,
    k_shape: float = DEFAULT_K_SHAPE,
    min_samples: int = DEFAULT_MIN_SAMPLES_SHAPE,
    min_crossing_rate: float = 0.05,
) -> dict[str, Any]:
    """Sustained-direction (heartbeat-shape) deviation check.

    Reads ``crossing_rate``, ``run_length``, ``sample_count`` from a
    per-signal baseline entry; returns the same dict shape the
    assistant pack already publishes so the journal_adapters consumer
    stays compatible.
    """
    if entry is None or int(entry.get("sample_count", 0)) < int(min_samples):
        return {
            "triggered": False, "run_length": int((entry or {}).get("run_length", 0)),
            "expected_max_run": 0.0, "direction": None,
            "reason": "rhythm_immature", "mature": False,
        }
    cr = max(float(entry.get("crossing_rate", DEFAULT_CROSSING_RATE_SEED)),
             float(min_crossing_rate))
    run_length = int(entry.get("run_length", 0))
    expected_mean_run = 1.0 / cr
    threshold = expected_mean_run * float(k_shape)
    triggered = abs(run_length) > threshold
    return {
        "triggered": triggered,
        "run_length": run_length,
        "expected_max_run": round(threshold, 4),
        "direction": ("positive" if run_length > 0 else "negative") if triggered else None,
        "reason": "rhythm_broken" if triggered else "rhythm_normal",
        "mature": True,
    }
