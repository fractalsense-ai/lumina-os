"""rhythm_fft.py — Spectral chronic-drift helpers (Phase G).

Pure-NumPy spectral analysis of an actor's SVA history. Designed to be
called from a daemon task (``rhythm_fft_analysis`` in ``tasks.py``) when
the system is idle — NOT on a fixed cron.

Conceptual layering above Phase A-F:

- Phase A-E (envelope):  amplitude, this turn — z-score of |x - μ| / σ.
- Phase F   (rhythm):    shape, last ~10 turns — sustained run-length
                         vs. actor's natural crossing rate.
- Phase G   (spectral):  chronic, last 30 days — frequency-domain
                         signature vs. the actor's own historical shape.

Why FFT, not just longer EWMA?
EWMA forgets old samples by design, so a slow slide into depression looks
"normal at every step" — every day's residual is small relative to a mean
that has already crawled with it. The DC bin of the FFT over a 30-day
window does not forget; it integrates the drift.

Public API:
    resample_to_daily(timestamps_iso, values, window_days=30)
        -> tuple[np.ndarray, int]
    compute_spectral_signature(daily_series) -> dict[str, float]
    update_spectral_history(prev_history, today, alpha=0.1) -> dict
    check_spectral_drift(history, today, k_spectral=2.5, min_samples=5,
                         harmful_dc_direction=-1) -> list[dict]

Storage contract (lives on AffectBaseline.spectral_history):
    {
        "ewma":   {"dc_drift": 0.0, "circaseptan": 0.0, ...},
        "variance": {"dc_drift": 0.0, ...},
        "sample_count": int,
        "last_run_utc": str,
        "last_signature": {...},  # most recent today_signature for debug
    }
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import numpy as np

# ── Constants ─────────────────────────────────────────────────

# Period (in days) bin definitions. Edges are half-open [low, high).
# Using period rather than frequency keeps the semantic obvious — these
# numbers map directly to "weekly cycle", "multi-day swing", etc.
BAND_DEFS_DAYS: dict[str, tuple[float, float]] = {
    "circaseptan": (5.0, 9.0),   # weekly rhythms (e.g. Sunday-night dread)
    "ultradian":   (2.0, 4.0),   # multi-day mood swings
    # noise_floor = sum of remaining bins (period < 2 days, excluding DC)
}

# Maximum allowed gap (in days) between consecutive observations before we
# refuse to interpolate. A gap larger than this likely means the actor
# stopped journaling for a while; we shouldn't fabricate a smooth signal
# across that void.
MAX_INTERP_GAP_DAYS: int = 7

# Default smoothing for the spectral-history EWMA. Lower than per-turn
# smoothing because each FFT run already represents 30 days of data —
# we don't want one outlier window to swamp the historical signature.
DEFAULT_SPECTRAL_ALPHA: float = 0.1


# ── Resampling ────────────────────────────────────────────────


def _parse_iso(ts: str) -> datetime:
    """Parse an ISO-8601 UTC timestamp; tolerate trailing 'Z'."""
    s = ts.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s).astimezone(timezone.utc)


def resample_to_daily(
    timestamps_iso: list[str],
    values: list[float],
    window_days: int = 30,
) -> tuple[np.ndarray, int]:
    """Resample irregular (timestamp, value) pairs onto a fixed daily grid.

    Strategy:
    - Group observations by UTC calendar day; take the mean of each day.
    - The output grid spans the most recent ``window_days`` ending on the
      most recent observation's day (inclusive).
    - Missing days inside the window are linearly interpolated from the
      surrounding day means.
    - If any interpolation gap exceeds ``MAX_INTERP_GAP_DAYS`` consecutive
      missing days, we refuse and return ``(np.array([]), 0)``. The caller
      should treat that as "not enough recent data — skip this actor".

    Returns
    -------
    (daily_series, n_real_samples) : tuple
        daily_series is a length-``window_days`` ndarray when valid,
        empty when the window cannot be filled. n_real_samples is the
        count of days that had at least one real observation (so the
        caller can decide to skip if the window is mostly synthetic).
    """
    if not timestamps_iso or not values or len(timestamps_iso) != len(values):
        return np.array([]), 0
    if window_days < 2:
        return np.array([]), 0

    # Group by calendar day → mean per day
    by_day: dict[int, list[float]] = {}
    for ts, v in zip(timestamps_iso, values):
        try:
            dt = _parse_iso(ts)
        except (ValueError, TypeError):
            continue
        day_ord = dt.toordinal()
        by_day.setdefault(day_ord, []).append(float(v))

    if not by_day:
        return np.array([]), 0

    day_means = {d: sum(vs) / len(vs) for d, vs in by_day.items()}
    last_day = max(day_means)
    first_day = last_day - window_days + 1

    # Build the dense series, interpolating gaps
    grid = np.full(window_days, np.nan, dtype=float)
    n_real = 0
    for d, mean in day_means.items():
        if first_day <= d <= last_day:
            grid[d - first_day] = mean
            n_real += 1

    if n_real == 0:
        return np.array([]), 0

    # Detect oversized interpolation gaps before filling
    nan_mask = np.isnan(grid)
    if nan_mask.any():
        # Walk runs of NaNs; reject if any run length > MAX_INTERP_GAP_DAYS
        run = 0
        for is_nan in nan_mask:
            if is_nan:
                run += 1
                if run > MAX_INTERP_GAP_DAYS:
                    return np.array([]), 0
            else:
                run = 0
        # Linear interpolation over remaining short gaps. np.interp needs
        # the indices of known points and known values.
        known_idx = np.flatnonzero(~nan_mask)
        known_val = grid[known_idx]
        all_idx = np.arange(window_days)
        # Edge NaNs get clamped to the nearest known value via np.interp
        grid = np.interp(all_idx, known_idx, known_val)

    return grid, n_real


# ── Spectral signature ────────────────────────────────────────


def compute_spectral_signature(daily_series: np.ndarray) -> dict[str, float]:
    """Compute a per-band spectral fingerprint of a daily series.

    Pipeline:
    1. Detrend by subtracting the series mean. This means the "DC drift"
       we report is the residual offset of the *windowed* mean from the
       long-term mean — i.e. how much the actor's recent mood has drifted
       relative to themselves. (We track the sign separately so callers
       can tell an upward drift from a downward one.)
    2. Hann window to reduce spectral leakage.
    3. Real FFT → magnitude spectrum.
    4. Aggregate into named period bands.

    Returns ``{}`` for series shorter than 4 samples (FFT needs minimal
    length and no useful bands fit).
    """
    if daily_series is None or len(daily_series) < 4:
        return {}

    n = len(daily_series)
    series_mean = float(np.mean(daily_series))
    detrended = daily_series - series_mean

    # Hann window — keeps the math interpretable without leakage artifacts.
    # We DO compute DC after detrending+windowing because the windowed mean
    # is what FFT bin 0 actually measures.
    window = np.hanning(n)
    windowed = detrended * window

    spectrum = np.abs(np.fft.rfft(windowed))
    freqs_per_day = np.fft.rfftfreq(n, d=1.0)  # cycles per day

    # Bin 0 is the DC component AFTER windowing. We report the mean shift
    # itself (with sign) so the daemon can decide which direction is harmful.
    dc_magnitude = float(spectrum[0])
    dc_direction = 1 if series_mean >= 0 else -1
    # The signed mean shift carries more semantic weight than the DC bin
    # magnitude alone, since after detrending the bin is dominated by the
    # window's DC leakage. We track both.
    dc_drift = abs(series_mean)

    # Period (days) for each non-DC bin; freq=0 → infinity, skip bin 0
    with np.errstate(divide="ignore"):
        periods = np.where(freqs_per_day > 0, 1.0 / np.maximum(freqs_per_day, 1e-12), np.inf)

    bands: dict[str, float] = {}
    used_mask = np.zeros(len(spectrum), dtype=bool)
    used_mask[0] = True  # DC bin is reported separately

    for name, (low, high) in BAND_DEFS_DAYS.items():
        sel = (periods >= low) & (periods < high)
        bands[name] = float(np.sum(spectrum[sel]))
        used_mask |= sel

    # Everything left over (period < smallest band low, > 0) is noise floor
    noise_mask = (~used_mask) & (freqs_per_day > 0)
    bands["noise_floor"] = float(np.sum(spectrum[noise_mask]))

    return {
        "dc_drift": round(dc_drift, 6),
        "dc_direction": dc_direction,
        "dc_bin_magnitude": round(dc_magnitude, 6),
        **{k: round(v, 6) for k, v in bands.items()},
    }


# ── Spectral-history EWMA ─────────────────────────────────────

# Keys we EWMA-track. dc_direction is categorical (+1/-1) so we don't
# average it; we just keep the most recent value.
_TRACKED_BANDS: tuple[str, ...] = ("dc_drift", "circaseptan", "ultradian", "noise_floor")


def update_spectral_history(
    prev_history: dict[str, Any] | None,
    today: dict[str, float],
    alpha: float = DEFAULT_SPECTRAL_ALPHA,
    now_utc: str | None = None,
) -> dict[str, Any]:
    """Fold today's spectral signature into the running EWMA history.

    EWMA mean and variance per band, identical pattern to Phase C envelope:
        μ_new  = α·x  + (1-α)·μ_old
        σ²_new = α·(x - μ_old)² + (1-α)·σ²_old

    First call (``prev_history`` empty/None) seeds the EWMA at today's value
    with variance 0.0 — the next call is the first one that can yield a
    meaningful z-score. Caller's ``min_samples`` gate enforces maturity.
    """
    if not today:
        # Defensive: empty signature (series too short) — preserve prior
        return dict(prev_history or {})

    prev = prev_history or {}
    prev_ewma = dict(prev.get("ewma", {}))
    prev_var = dict(prev.get("variance", {}))
    prev_count = int(prev.get("sample_count", 0))

    if prev_count == 0:
        new_ewma = {band: float(today.get(band, 0.0)) for band in _TRACKED_BANDS}
        new_var = {band: 0.0 for band in _TRACKED_BANDS}
    else:
        new_ewma = {}
        new_var = {}
        for band in _TRACKED_BANDS:
            x = float(today.get(band, 0.0))
            mu_old = float(prev_ewma.get(band, x))
            var_old = float(prev_var.get(band, 0.0))
            residual = x - mu_old
            new_ewma[band] = round(alpha * x + (1.0 - alpha) * mu_old, 6)
            new_var[band] = round(
                alpha * residual * residual + (1.0 - alpha) * var_old, 6,
            )

    return {
        "ewma": new_ewma,
        "variance": new_var,
        "sample_count": prev_count + 1,
        "last_run_utc": now_utc or datetime.now(timezone.utc).isoformat(),
        "last_signature": dict(today),
    }


# ── Drift detection ───────────────────────────────────────────


def check_spectral_drift(
    history: dict[str, Any] | None,
    today: dict[str, float],
    k_spectral: float = 2.5,
    min_samples: int = 5,
    min_variance_floor: float = 1e-6,
    harmful_dc_direction: int = -1,
) -> list[dict[str, Any]]:
    """Return a list of bands whose today-value deviates from the actor's
    historical EWMA spectral signature by more than ``k_spectral`` σ.

    For ``dc_drift`` specifically we additionally require the *direction*
    of today's mean shift to match ``harmful_dc_direction`` — symmetric
    flagging would false-fire on recovery (e.g. a kid coming back up out
    of a slump would otherwise look like an emergency).

    Returns
    -------
    list of dicts: each ``{band, z_score, today_value, ewma_value,
        direction, reason}``. Empty list when nothing tripped, when
        history is immature, or when today is empty.

    Reason codes:
        - "history_immature"      — sample_count < min_samples (no findings)
        - "drift_detected"        — band exceeded k_spectral σ
        - "drift_within_envelope" — included in returned-empty case implicitly
        - "direction_benign"      — DC drift exceeded but direction is recovery
    """
    if not today or not history:
        return []

    sample_count = int(history.get("sample_count", 0))
    if sample_count < min_samples:
        return []

    ewma = history.get("ewma") or {}
    variance = history.get("variance") or {}

    findings: list[dict[str, Any]] = []
    for band in _TRACKED_BANDS:
        x = float(today.get(band, 0.0))
        mu = float(ewma.get(band, 0.0))
        var = max(float(variance.get(band, 0.0)), min_variance_floor)
        sigma = var ** 0.5
        z = (x - mu) / sigma
        if abs(z) <= k_spectral:
            continue

        direction = 1 if x >= mu else -1
        if band == "dc_drift":
            today_dc_direction = int(today.get("dc_direction", 0))
            if today_dc_direction != harmful_dc_direction:
                # Drift is real but it's a recovery — don't alarm.
                continue
            direction = today_dc_direction

        findings.append({
            "band": band,
            "z_score": round(z, 4),
            "today_value": round(x, 6),
            "ewma_value": round(mu, 6),
            "direction": direction,
            "reason": "drift_detected",
        })

    return findings
