"""Affect monitor for the assistant domain — SVA with EWMA per module.

This module is the **assistant pack's domain monitor** for one specific
actor (the assistant user). It owns its own actor shape
(``AffectBaseline`` carries SVA mean + variance + rhythm + per-module
signatures + spectral history) and its own persistence key
(``entity_state.affect_baseline`` and ``learning_state.affect_baseline``).

The scalar math primitives — EWMA + variance recurrence, heartbeat-shape
crossing-rate / run-length tracking, z-score envelope checks — live in
``lumina.signals`` and are reused here. This file's responsibility is the
assistant-domain *interpretation*: turning structured turn evidence into
an SVA reading, folding it into the per-actor baseline, and surfacing
per-module deviation. Other domains (education, agriculture, system) own
their own actor shapes and monitors and call into ``lumina.signals``
directly with whatever signals are meaningful for them.

Maintains a compressed representation of actor engagement/affect across
sessions without storing conversational history.  The affect baseline
floats with the actor over time via exponential weighted moving average,
and per-module signatures capture how the actor's affect deviates in
each module context.

Drift velocity (the rate of change of the EWMA) is the primary signal:
a fast-dropping valence or salience indicates something is wrong even
without access to conversation content.

Architecture parallels:
    education domain → zpd_monitor_v0_2.py + education_profile_serializer.py
    assistant domain → this file (unified — simpler domain, fewer state vars)
    framework        → src/lumina/signals/ (instrument, domain-agnostic)

Evidence contract (from turn interpreter / tool adapters):
    - task_status: "completed" | "abandoned" | "open" | "deferred" | "n/a"
    - satisfaction_signal: "positive" | "neutral" | "negative" | "unknown"
    - tool_call_requested: bool
    - response_latency_sec: float
    - off_task_ratio: float (0..1)
    - intent_type: str
    - intent_switches_in_window: int (computed by domain_step)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from lumina.signals.baseline import (
    _initial_run as _framework_initial_run,
    _update_rhythm as _framework_update_rhythm,
    _z as _framework_z,
)


# ─────────────────────────────────────────────────────────────
# Data Structures
# ─────────────────────────────────────────────────────────────


@dataclass
class AffectState:
    """SVA triad: Salience, Valence, Arousal — assistant domain interpretation.

    - Salience: engagement/focus (0..1). Low = disengaged, drifting.
    - Valence: satisfaction tone (-1..1). Negative = frustrated/unhappy.
    - Arousal: activation level (0..1). High = frantic/rapid; low = flat/bored.
    """

    salience: float = 0.5
    valence: float = 0.0
    arousal: float = 0.5

    def __post_init__(self) -> None:
        self.salience = _clamp(self.salience, 0.0, 1.0)
        self.valence = _clamp(self.valence, -1.0, 1.0)
        self.arousal = _clamp(self.arousal, 0.0, 1.0)

    def to_dict(self) -> dict[str, float]:
        return {
            "salience": round(self.salience, 6),
            "valence": round(self.valence, 6),
            "arousal": round(self.arousal, 6),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AffectState":
        return cls(
            salience=float(data.get("salience", 0.5)),
            valence=float(data.get("valence", 0.0)),
            arousal=float(data.get("arousal", 0.5)),
        )


@dataclass
class DriftSignal:
    """Result of drift velocity analysis for a single turn."""

    velocity_salience: float = 0.0  # Rate of change (negative = dropping)
    velocity_valence: float = 0.0
    velocity_arousal: float = 0.0
    is_fast_drift: bool = False  # True if any axis exceeds threshold
    drift_axis: str | None = None  # Which axis triggered ("salience", "valence", "arousal")
    drift_magnitude: float = 0.0  # Absolute magnitude of worst drift

    def to_dict(self) -> dict[str, Any]:
        return {
            "velocity_salience": round(self.velocity_salience, 6),
            "velocity_valence": round(self.velocity_valence, 6),
            "velocity_arousal": round(self.velocity_arousal, 6),
            "is_fast_drift": self.is_fast_drift,
            "drift_axis": self.drift_axis,
            "drift_magnitude": round(self.drift_magnitude, 6),
        }


@dataclass
class AffectBaseline:
    """Domain-wide EWMA baseline for an actor, with per-module signatures."""

    salience: float = 0.5
    valence: float = 0.0
    arousal: float = 0.5
    sample_count: int = 0
    per_module: dict[str, dict[str, Any]] = field(default_factory=dict)

    # Velocity tracking: previous EWMA values for rate-of-change computation
    prev_salience: float = 0.5
    prev_valence: float = 0.0
    prev_arousal: float = 0.5

    # Envelope tracking: EWMA variance per axis. Captures the actor's normal
    # oscillation amplitude so escalations fire on z-score deviation rather
    # than universal absolute thresholds. Seeded at 0.04 (std≈0.2).
    salience_variance: float = 0.04
    valence_variance: float = 0.04
    arousal_variance: float = 0.04

    # Rhythm/shape tracking (Phase F — heartbeat analogy):
    #   crossing_rate = EWMA of "did residual flip sign this turn?" (0..1).
    #     Captures the actor's natural oscillation frequency. A naturally-flat
    #     actor has low crossing_rate; a volatile actor has high crossing_rate.
    #   run_length = signed count of consecutive same-direction residuals.
    #     Positive = sustained drift up, negative = sustained drift down, 0 = no
    #     prior direction. Detects STEMI-like sustained shifts that stay inside
    #     the amplitude envelope but break the actor's normal rhythm.
    salience_crossing_rate: float = 0.5
    valence_crossing_rate: float = 0.5
    arousal_crossing_rate: float = 0.5
    salience_run_length: int = 0
    valence_run_length: int = 0
    arousal_run_length: int = 0

    # Spectral chronic-drift fingerprint (Phase G). Owned exclusively by the
    # `rhythm_fft_analysis` daemon task — per-turn updates do NOT touch it.
    # Shape (when populated):
    #   {"ewma": {band: float, ...},
    #    "variance": {band: float, ...},
    #    "sample_count": int,
    #    "last_run_utc": iso str,
    #    "last_signature": {band: float, ...}}
    # Stored verbatim — keeping the whole structure opaque to the per-turn
    # path means the daemon can evolve the band layout without touching
    # journal_adapters.
    spectral_history: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "salience": round(self.salience, 6),
            "valence": round(self.valence, 6),
            "arousal": round(self.arousal, 6),
            "sample_count": self.sample_count,
            "per_module": dict(self.per_module),
            "prev_salience": round(self.prev_salience, 6),
            "prev_valence": round(self.prev_valence, 6),
            "prev_arousal": round(self.prev_arousal, 6),
            "salience_variance": round(self.salience_variance, 6),
            "valence_variance": round(self.valence_variance, 6),
            "arousal_variance": round(self.arousal_variance, 6),
            "salience_crossing_rate": round(self.salience_crossing_rate, 6),
            "valence_crossing_rate": round(self.valence_crossing_rate, 6),
            "arousal_crossing_rate": round(self.arousal_crossing_rate, 6),
            "salience_run_length": int(self.salience_run_length),
            "valence_run_length": int(self.valence_run_length),
            "arousal_run_length": int(self.arousal_run_length),
            "spectral_history": dict(self.spectral_history),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AffectBaseline":
        return cls(
            salience=float(data.get("salience", 0.5)),
            valence=float(data.get("valence", 0.0)),
            arousal=float(data.get("arousal", 0.5)),
            sample_count=int(data.get("sample_count", 0)),
            per_module=dict(data.get("per_module") or {}),
            prev_salience=float(data.get("prev_salience", 0.5)),
            prev_valence=float(data.get("prev_valence", 0.0)),
            prev_arousal=float(data.get("prev_arousal", 0.5)),
            salience_variance=float(data.get("salience_variance", 0.04)),
            valence_variance=float(data.get("valence_variance", 0.04)),
            arousal_variance=float(data.get("arousal_variance", 0.04)),
            salience_crossing_rate=float(data.get("salience_crossing_rate", 0.5)),
            valence_crossing_rate=float(data.get("valence_crossing_rate", 0.5)),
            arousal_crossing_rate=float(data.get("arousal_crossing_rate", 0.5)),
            salience_run_length=int(data.get("salience_run_length", 0)),
            valence_run_length=int(data.get("valence_run_length", 0)),
            arousal_run_length=int(data.get("arousal_run_length", 0)),
            spectral_history=dict(data.get("spectral_history") or {}),
        )


# ─────────────────────────────────────────────────────────────
# Parameters
# ─────────────────────────────────────────────────────────────

DEFAULT_PARAMS: dict[str, Any] = {
    # EWMA smoothing factor — lower = slower baseline adaptation
    "ewma_alpha": 0.1,
    # Drift velocity thresholds (per-turn delta on the EWMA)
    "fast_drift_threshold": 0.05,
    # Intent-switching signals confusion/searching
    "intent_switch_salience_penalty": 0.08,
    "intent_switch_arousal_boost": 0.05,
    # Latency thresholds (seconds)
    "latency_low": 2.0,   # Very fast → high arousal
    "latency_high": 30.0,  # Very slow → low arousal, low salience
    # Minimum samples before drift detection activates
    "min_samples_for_drift": 5,
}


# ─────────────────────────────────────────────────────────────
# Helper
# ─────────────────────────────────────────────────────────────

def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


# ─────────────────────────────────────────────────────────────
# Affect Estimator
# ─────────────────────────────────────────────────────────────

def update_affect(
    prev: AffectState,
    evidence: dict[str, Any],
    params: dict[str, Any] | None = None,
) -> AffectState:
    """Compute new SVA reading from structured evidence.

    All inputs are structured signals — no raw text is ever read.
    Returns a new AffectState (immutable pattern).
    """
    p = params or DEFAULT_PARAMS

    task_status = str(evidence.get("task_status", "n/a"))
    satisfaction = str(evidence.get("satisfaction_signal", "unknown"))
    tool_requested = bool(evidence.get("tool_call_requested", False))
    latency = float(evidence.get("response_latency_sec", 5.0) or 5.0)
    off_task = float(evidence.get("off_task_ratio", 0.0) or 0.0)
    intent_switches = int(evidence.get("intent_switches_in_window", 0) or 0)

    latency_low = float(p.get("latency_low", 2.0))
    latency_high = float(p.get("latency_high", 30.0))
    switch_s_penalty = float(p.get("intent_switch_salience_penalty", 0.08))
    switch_a_boost = float(p.get("intent_switch_arousal_boost", 0.05))

    # ── Salience (engagement) ────────────────────────────────
    d_salience = 0.0
    if task_status == "completed":
        d_salience += 0.06  # Completed a task → engaged
    elif task_status == "abandoned":
        d_salience -= 0.10  # Gave up → disengaged
    if off_task > 0.5:
        d_salience -= 0.08
    if latency > latency_high:
        d_salience -= 0.05  # Slow response → possibly disengaged
    if satisfaction == "positive":
        d_salience += 0.04
    elif satisfaction == "negative":
        d_salience -= 0.06
    # Rapid intent-switching = searching/confused → salience drop
    if intent_switches >= 3:
        d_salience -= switch_s_penalty

    # ── Valence (satisfaction tone) ──────────────────────────
    d_valence = 0.0
    if task_status == "completed":
        d_valence += 0.10
    elif task_status == "abandoned":
        d_valence -= 0.12
    if satisfaction == "positive":
        d_valence += 0.08
    elif satisfaction == "negative":
        d_valence -= 0.10
    elif satisfaction == "neutral":
        d_valence += 0.01  # Slight positive bias for neutral
    # Tool failure implicit in abandoned after tool request
    if task_status == "abandoned" and tool_requested:
        d_valence -= 0.05  # Tool didn't help → extra frustration

    # ── Arousal (activation level) ───────────────────────────
    d_arousal = 0.0
    if latency < latency_low:
        d_arousal += 0.06  # Rapid-fire interaction
    elif latency > latency_high:
        d_arousal -= 0.08  # Flat/bored/gone
    if intent_switches >= 3:
        d_arousal += switch_a_boost  # Frantic switching
    if task_status == "abandoned":
        d_arousal += 0.04  # Frustration bump

    return AffectState(
        salience=_clamp(prev.salience + d_salience, 0.0, 1.0),
        valence=_clamp(prev.valence + d_valence, -1.0, 1.0),
        arousal=_clamp(prev.arousal + d_arousal, 0.0, 1.0),
    )


# ─────────────────────────────────────────────────────────────
# EWMA Baseline Update
# ─────────────────────────────────────────────────────────────

def update_baseline(
    baseline: AffectBaseline,
    current_affect: AffectState,
    module_id: str | None = None,
    params: dict[str, Any] | None = None,
) -> AffectBaseline:
    """Update the actor's floating EWMA baseline with a new affect reading.

    Tracks per-module signatures with delta_from_baseline, and stores
    the previous EWMA values for velocity computation.

    This is the persistent state update — called once per turn, result
    is written back to the actor profile.
    """
    p = params or DEFAULT_PARAMS
    alpha = float(p.get("ewma_alpha", 0.1))
    noise_floor = float(p.get("rhythm_noise_floor", 0.05))

    # EWMA variance: residual is observed - prev_mean. Smooth squared residual.
    res_s = current_affect.salience - baseline.salience
    res_v = current_affect.valence - baseline.valence
    res_a = current_affect.arousal - baseline.arousal
    new_var_s = round(alpha * (res_s ** 2) + (1 - alpha) * baseline.salience_variance, 6)
    new_var_v = round(alpha * (res_v ** 2) + (1 - alpha) * baseline.valence_variance, 6)
    new_var_a = round(alpha * (res_a ** 2) + (1 - alpha) * baseline.arousal_variance, 6)

    # Rhythm/shape: update crossing rate + run length per axis (heartbeat shape)
    new_run_s, new_cross_s = _update_rhythm(
        res_s, baseline.salience_run_length, baseline.salience_crossing_rate, alpha, noise_floor)
    new_run_v, new_cross_v = _update_rhythm(
        res_v, baseline.valence_run_length, baseline.valence_crossing_rate, alpha, noise_floor)
    new_run_a, new_cross_a = _update_rhythm(
        res_a, baseline.arousal_run_length, baseline.arousal_crossing_rate, alpha, noise_floor)

    # Store previous values for velocity tracking
    new_baseline = AffectBaseline(
        prev_salience=baseline.salience,
        prev_valence=baseline.valence,
        prev_arousal=baseline.arousal,
        sample_count=baseline.sample_count + 1,
        per_module=dict(baseline.per_module),
        # EWMA update
        salience=round(alpha * current_affect.salience + (1 - alpha) * baseline.salience, 6),
        valence=round(alpha * current_affect.valence + (1 - alpha) * baseline.valence, 6),
        arousal=round(alpha * current_affect.arousal + (1 - alpha) * baseline.arousal, 6),
        salience_variance=new_var_s,
        valence_variance=new_var_v,
        arousal_variance=new_var_a,
        salience_crossing_rate=round(new_cross_s, 6),
        valence_crossing_rate=round(new_cross_v, 6),
        arousal_crossing_rate=round(new_cross_a, 6),
        salience_run_length=new_run_s,
        valence_run_length=new_run_v,
        arousal_run_length=new_run_a,
    )

    # Per-module affect signature with delta_from_baseline
    if module_id:
        new_baseline.per_module[module_id] = {
            "salience": current_affect.salience,
            "valence": current_affect.valence,
            "arousal": current_affect.arousal,
            "delta_from_baseline": {
                "salience": round(current_affect.salience - new_baseline.salience, 6),
                "valence": round(current_affect.valence - new_baseline.valence, 6),
                "arousal": round(current_affect.arousal - new_baseline.arousal, 6),
            },
            "sample_count": (
                baseline.per_module.get(module_id, {}).get("sample_count", 0) + 1
            ),
        }

    return new_baseline


# ─────────────────────────────────────────────────────────────
# Drift Velocity Detection
# ─────────────────────────────────────────────────────────────

def compute_drift(
    baseline: AffectBaseline,
    params: dict[str, Any] | None = None,
) -> DriftSignal:
    """Compute drift velocity from the EWMA rate of change.

    Velocity = current_ewma - previous_ewma (per turn).
    Fast drift occurs when any axis exceeds the threshold.
    This is the key signal that something is happening with
    the actor WITHOUT needing conversational history.
    """
    p = params or DEFAULT_PARAMS
    threshold = float(p.get("fast_drift_threshold", 0.05))
    min_samples = int(p.get("min_samples_for_drift", 5))

    # Not enough data yet — no drift signal
    if baseline.sample_count < min_samples:
        return DriftSignal()

    vel_s = baseline.salience - baseline.prev_salience
    vel_v = baseline.valence - baseline.prev_valence
    vel_a = baseline.arousal - baseline.prev_arousal

    # Find the worst drifting axis (largest absolute velocity)
    axes = [
        ("salience", abs(vel_s)),
        ("valence", abs(vel_v)),
        ("arousal", abs(vel_a)),
    ]
    worst_axis, worst_mag = max(axes, key=lambda x: x[1])

    is_fast = worst_mag >= threshold

    return DriftSignal(
        velocity_salience=round(vel_s, 6),
        velocity_valence=round(vel_v, 6),
        velocity_arousal=round(vel_a, 6),
        is_fast_drift=is_fast,
        drift_axis=worst_axis if is_fast else None,
        drift_magnitude=round(worst_mag, 6),
    )


# ─────────────────────────────────────────────────────────────
# Module-level Drift Analysis
# ─────────────────────────────────────────────────────────────

def module_deviation(
    baseline: AffectBaseline,
    module_id: str,
) -> dict[str, float] | None:
    """Get the delta_from_baseline for a specific module.

    Returns None if no data for that module. Otherwise returns:
    {"salience": Δ, "valence": Δ, "arousal": Δ}

    Positive delta = actor does better in this module than baseline.
    Negative delta = actor does worse in this module.
    """
    mod_data = baseline.per_module.get(module_id)
    if not mod_data:
        return None
    return mod_data.get("delta_from_baseline")


# ─────────────────────────────────────────────────────────────
# Relational Baseline Update
# ─────────────────────────────────────────────────────────────

def update_relational_baseline(
    relational_baseline: dict[str, Any],
    entity_hash: str,
    valence_delta: float,
    arousal_delta: float,
    salience_delta: float,
    params: dict[str, Any] | None = None,
    global_baseline: "AffectBaseline | None" = None,
) -> dict[str, Any]:
    """Update the per-entity EWMA baseline for a named entity reference.

    The entity is identified only by its privacy-preserving hash
    (e.g. ``"Entity_A4F9"``).  Entity names are never passed here.

    New entities are seeded at the actor's current global baseline values
    rather than zero — seeding at zero would cause a spurious intervention
    trigger on first mention and would not reflect that this entity is new
    but the actor's overall baseline is known.

    Args:
        relational_baseline: Current ``learning_state.relational_baseline``
                             dict from the actor profile.  Mutated in-place
                             and returned for convenience.
        entity_hash:         Privacy-preserving entity identifier.
        valence_delta:       Per-entity valence signal for this turn.
        arousal_delta:       Per-entity arousal signal for this turn.
        salience_delta:      Per-entity salience signal for this turn.
        params:              Optional param overrides (e.g. ``ewma_alpha``).
        global_baseline:     Actor's current global AffectBaseline, used to
                             seed new entities.  Falls back to neutral if None.

    Returns:
        The updated ``relational_baseline`` dict.
    """
    p = params or DEFAULT_PARAMS
    alpha = float(p.get("ewma_alpha", 0.1))
    # Initial variance seed (std≈0.2). Wide enough that early observations don't
    # produce huge z-scores during warm-up; narrows down as samples accumulate.
    seed_var = float(p.get("ewma_initial_variance", 0.04))
    noise_floor = float(p.get("rhythm_noise_floor", 0.05))

    # Determine seed values for first encounter
    if global_baseline is not None:
        seed_s = global_baseline.salience
        seed_v = global_baseline.valence
        seed_a = global_baseline.arousal
    else:
        seed_s, seed_v, seed_a = 0.5, 0.0, 0.5

    entry = relational_baseline.get(entity_hash)
    if entry is None:
        # First mention — seed at global baseline, then apply this turn's delta
        entry = {
            "salience": round(_clamp(seed_s + salience_delta * alpha, 0.0, 1.0), 6),
            "valence": round(_clamp(seed_v + valence_delta * alpha, -1.0, 1.0), 6),
            "arousal": round(_clamp(seed_a + arousal_delta * alpha, 0.0, 1.0), 6),
            "salience_variance": round(seed_var, 6),
            "valence_variance": round(seed_var, 6),
            "arousal_variance": round(seed_var, 6),
            "salience_crossing_rate": 0.5,
            "valence_crossing_rate": 0.5,
            "arousal_crossing_rate": 0.5,
            "salience_run_length": _initial_run(salience_delta, noise_floor),
            "valence_run_length": _initial_run(valence_delta, noise_floor),
            "arousal_run_length": _initial_run(arousal_delta, noise_floor),
            "sample_count": 1,
        }
    else:
        prev_s = float(entry.get("salience", seed_s))
        prev_v = float(entry.get("valence", seed_v))
        prev_a = float(entry.get("arousal", seed_a))
        prev_var_s = float(entry.get("salience_variance", seed_var))
        prev_var_v = float(entry.get("valence_variance", seed_var))
        prev_var_a = float(entry.get("arousal_variance", seed_var))
        prev_run_s = int(entry.get("salience_run_length", 0))
        prev_run_v = int(entry.get("valence_run_length", 0))
        prev_run_a = int(entry.get("arousal_run_length", 0))
        prev_cross_s = float(entry.get("salience_crossing_rate", 0.5))
        prev_cross_v = float(entry.get("valence_crossing_rate", 0.5))
        prev_cross_a = float(entry.get("arousal_crossing_rate", 0.5))
        n = int(entry.get("sample_count", 1)) + 1
        # Residuals (this turn's delta IS the residual since the "observation" being
        # smoothed is prev + delta, and (prev + delta) - prev = delta).
        new_var_s = alpha * (salience_delta ** 2) + (1 - alpha) * prev_var_s
        new_var_v = alpha * (valence_delta ** 2) + (1 - alpha) * prev_var_v
        new_var_a = alpha * (arousal_delta ** 2) + (1 - alpha) * prev_var_a
        new_run_s, new_cross_s = _update_rhythm(salience_delta, prev_run_s, prev_cross_s, alpha, noise_floor)
        new_run_v, new_cross_v = _update_rhythm(valence_delta, prev_run_v, prev_cross_v, alpha, noise_floor)
        new_run_a, new_cross_a = _update_rhythm(arousal_delta, prev_run_a, prev_cross_a, alpha, noise_floor)
        entry = {
            "salience": round(_clamp(alpha * (prev_s + salience_delta) + (1 - alpha) * prev_s, 0.0, 1.0), 6),
            "valence": round(_clamp(alpha * (prev_v + valence_delta) + (1 - alpha) * prev_v, -1.0, 1.0), 6),
            "arousal": round(_clamp(alpha * (prev_a + arousal_delta) + (1 - alpha) * prev_a, 0.0, 1.0), 6),
            "salience_variance": round(new_var_s, 6),
            "valence_variance": round(new_var_v, 6),
            "arousal_variance": round(new_var_a, 6),
            "salience_crossing_rate": round(new_cross_s, 6),
            "valence_crossing_rate": round(new_cross_v, 6),
            "arousal_crossing_rate": round(new_cross_a, 6),
            "salience_run_length": new_run_s,
            "valence_run_length": new_run_v,
            "arousal_run_length": new_run_a,
            "sample_count": n,
        }

    relational_baseline[entity_hash] = entry
    return relational_baseline


# ─────────────────────────────────────────────────────────────
# Rhythm / shape helpers (Phase F — heartbeat-shape detection)
# ─────────────────────────────────────────────────────────────


def _initial_run(residual: float, noise_floor: float) -> int:
    """Sign-of-first-observation seed for run_length tracking.

    Thin delegator to ``lumina.signals.baseline._initial_run`` — kept as a
    local name for backward compatibility with existing call sites.
    """
    return _framework_initial_run(residual, noise_floor)


def _update_rhythm(
    residual: float,
    prev_run: int,
    prev_crossing_rate: float,
    alpha: float,
    noise_floor: float,
) -> tuple[int, float]:
    """Update (run_length, crossing_rate) for one axis given this turn's residual.

    Thin delegator to ``lumina.signals.baseline._update_rhythm``. The
    framework owns the math; the assistant pack uses it per-axis.
    """
    return _framework_update_rhythm(
        residual, prev_run, prev_crossing_rate, alpha, noise_floor
    )


def check_shape_deviation(
    crossing_rate: float,
    run_length: int,
    sample_count: int,
    k_shape: float = 2.0,
    min_samples: int = 10,
    min_crossing_rate: float = 0.05,
) -> dict[str, Any]:
    """Detect sustained-direction drift inside the actor's amplitude envelope.

    The "heartbeat-shape" check: even when each individual reading sits inside
    the per-axis z-score envelope, an unusually long run of same-direction
    residuals means the actor's natural rhythm is broken. The expected mean
    run length for a Bernoulli flip process with crossing rate p is 1/p
    (geometric distribution), so we trigger when ``|run_length| > k_shape / p``.

    Args:
        crossing_rate:    EWMA of "did residual flip sign?" — actor's natural
                          oscillation frequency. 0 = never flips; 1 = flips
                          every turn.
        run_length:       Signed current run count.
        sample_count:     Total observations on this baseline.
        k_shape:          Run-length tolerance multiplier. 2.0 = trigger at
                          twice the expected mean run length for this actor.
        min_samples:      Maturity gate; below this, return immature.
        min_crossing_rate: Floor on crossing_rate when computing expected run
                          length, to avoid divide-by-zero / runaway thresholds
                          on actors that have only ever drifted one way.

    Returns:
        ``{triggered, run_length, expected_max_run, direction, reason, mature}``
    """
    if int(sample_count) < int(min_samples):
        return {
            "triggered": False, "run_length": int(run_length),
            "expected_max_run": 0.0, "direction": None,
            "reason": "rhythm_immature", "mature": False,
        }
    cr = max(float(crossing_rate), float(min_crossing_rate))
    expected_mean_run = 1.0 / cr
    threshold = expected_mean_run * float(k_shape)
    triggered = abs(int(run_length)) > threshold
    direction = None
    if triggered:
        direction = "positive" if run_length > 0 else "negative"
    return {
        "triggered": triggered,
        "run_length": int(run_length),
        "expected_max_run": round(threshold, 4),
        "direction": direction,
        "reason": "rhythm_broken" if triggered else "rhythm_normal",
        "mature": True,
    }


# ─────────────────────────────────────────────────────────────
# Envelope (z-score) deviation checks
# ─────────────────────────────────────────────────────────────


def _z(observed: float, mean: float, variance: float, var_floor: float) -> float:
    """Return |z| score. Thin delegator to ``lumina.signals.baseline._z``."""
    return _framework_z(observed, mean, variance, var_floor)


def check_relational_deviation(
    entry: dict[str, Any] | None,
    valence: float,
    arousal: float,
    salience: float,
    k_sigma: float,
    min_samples: int = 5,
    min_variance_floor: float = 0.001,
) -> dict[str, Any]:
    """Z-score envelope check for an entity's per-axis affect.

    Compares this turn's observed values against the entity's learned mean and
    EWMA variance. Returns whether any axis is outside the actor's normal
    oscillation envelope and which axis tripped first.

    Returns:
        {
            "triggered": bool,
            "axis": "valence" | "arousal" | "salience" | None,
            "z_score": float,        # worst (largest) z across axes
            "reason": str,           # short tag for logging
            "mature": bool,          # False if baseline still warming up
        }
    """
    if entry is None or int(entry.get("sample_count", 0)) < int(min_samples):
        return {"triggered": False, "axis": None, "z_score": 0.0,
                "reason": "baseline_immature", "mature": False}

    z_v = _z(valence, float(entry.get("valence", 0.0)),
             float(entry.get("valence_variance", min_variance_floor)), min_variance_floor)
    z_a = _z(arousal, float(entry.get("arousal", 0.5)),
             float(entry.get("arousal_variance", min_variance_floor)), min_variance_floor)
    z_s = _z(salience, float(entry.get("salience", 0.5)),
             float(entry.get("salience_variance", min_variance_floor)), min_variance_floor)

    worst_axis, worst_z = max(
        (("valence", z_v), ("arousal", z_a), ("salience", z_s)),
        key=lambda kv: kv[1],
    )
    triggered = worst_z > float(k_sigma)
    return {
        "triggered": triggered,
        "axis": worst_axis if triggered else None,
        "z_score": round(worst_z, 4),
        "reason": "envelope_exceeded" if triggered else "within_envelope",
        "mature": True,
    }


def check_global_deviation(
    baseline: "AffectBaseline | None",
    valence: float,
    arousal: float,
    salience: float,
    k_sigma: float,
    min_samples: int = 5,
    min_variance_floor: float = 0.001,
) -> dict[str, Any]:
    """Z-score envelope check against the actor's global SVA baseline.

    Mirrors ``check_relational_deviation`` but reads variance fields from
    AffectBaseline (which stores them as attributes).
    """
    if baseline is None or baseline.sample_count < int(min_samples):
        return {"triggered": False, "axis": None, "z_score": 0.0,
                "reason": "baseline_immature", "mature": False}

    var_v = getattr(baseline, "valence_variance", min_variance_floor)
    var_a = getattr(baseline, "arousal_variance", min_variance_floor)
    var_s = getattr(baseline, "salience_variance", min_variance_floor)

    z_v = _z(valence, baseline.valence, var_v, min_variance_floor)
    z_a = _z(arousal, baseline.arousal, var_a, min_variance_floor)
    z_s = _z(salience, baseline.salience, var_s, min_variance_floor)

    worst_axis, worst_z = max(
        (("valence", z_v), ("arousal", z_a), ("salience", z_s)),
        key=lambda kv: kv[1],
    )
    triggered = worst_z > float(k_sigma)
    return {
        "triggered": triggered,
        "axis": worst_axis if triggered else None,
        "z_score": round(worst_z, 4),
        "reason": "envelope_exceeded" if triggered else "within_envelope",
        "mature": True,
    }

