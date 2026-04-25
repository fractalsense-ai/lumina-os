"""lumina.signals — Domain-agnostic signal decomposition framework.

A "signal" is any named scalar stream observed over time. The framework
treats human affect axes (salience/valence/arousal), environmental sensors
(soil pH, soil moisture, motor vibration), and any other declared scalar
the same way: it tracks an EWMA baseline + variance per signal, detects
acute envelope breaches (z-score), heartbeat-shape breaches (sustained
run length vs. natural crossing rate), and chronic spectral drift
(per-band FFT signature over a configurable window).

Domains declare their signals in ``domain-physics.json`` under a top-level
``signals`` block; the framework consumes the declarations, the daemon
runs the math, and consumers (`journal_adapters`, future tooling) read
back ``learning_state.signal_baselines`` + ``learning_state.spectral_advisories``.

The historical SVA implementation in
``domain-packs/assistant/domain-lib/affect_monitor.py`` is now a thin
adapter over this package.

Public API:

    SignalSample, SignalBaseline, SignalDriftSignal,
    update_baseline, compute_drift,
    check_envelope_deviation, check_shape_deviation,
    resample_to_daily, compute_spectral_signature,
    update_spectral_history, check_spectral_drift,
    render_advisory_message, pull_active_advisory,

    DEFAULT_BAND_DEFS_DAYS,
    DEFAULT_ADVISORY_TTL_SECONDS,
"""

from __future__ import annotations

from .advisories import (
    DEFAULT_ADVISORY_TTL_SECONDS,
    pull_active_advisory,
    upsert_spectral_advisory,
)
from .baseline import (
    check_envelope_deviation,
    check_shape_deviation,
    compute_drift,
    update_baseline,
)
from .spectral import (
    DEFAULT_BAND_DEFS_DAYS,
    check_spectral_drift,
    compute_spectral_signature,
    resample_to_daily,
    update_spectral_history,
)
from .state import SignalBaseline, SignalDriftSignal, SignalSample
from .templates import render_advisory_message

__all__ = [
    "SignalSample",
    "SignalBaseline",
    "SignalDriftSignal",
    "update_baseline",
    "compute_drift",
    "check_envelope_deviation",
    "check_shape_deviation",
    "resample_to_daily",
    "compute_spectral_signature",
    "update_spectral_history",
    "check_spectral_drift",
    "render_advisory_message",
    "pull_active_advisory",
    "upsert_spectral_advisory",
    "DEFAULT_BAND_DEFS_DAYS",
    "DEFAULT_ADVISORY_TTL_SECONDS",
]
