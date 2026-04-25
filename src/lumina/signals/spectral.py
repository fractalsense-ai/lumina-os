"""lumina.signals.spectral — Spectral chronic-drift helpers.

Pure-NumPy spectral analysis for a single signal's history. The previous
``src/lumina/daemon/rhythm_fft.py`` module is replaced by this one — the
math is identical but the band layout is now per-signal, supplied by the
caller (typically read from the domain physics signal definition).

Public API:
    resample_to_daily(timestamps_iso, values, window_days=30)
        -> tuple[np.ndarray, int]
    compute_spectral_signature(daily_series, *, band_defs_days=None)
        -> dict[str, float]
    update_spectral_history(prev_history, today, *, band_defs_days=None,
                            alpha=0.1, now_utc=None) -> dict
    check_spectral_drift(history, today, *, band_defs_days=None,
                         k_spectral=2.5, min_samples=5,
                         harmful_dc_direction=-1) -> list[dict]

Storage contract for a per-signal ``spectral_history`` dict:
    {
        "ewma":   {"dc_drift": ..., "<band>": ..., "noise_floor": ...},
        "variance": {... same keys ...},
        "sample_count": int,
        "last_run_utc": str,
        "last_signature": dict,
    }
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import numpy as np


# ─────────────────────────────────────────────────────────────
# Defaults — historical SVA layout. Domains override per signal.
# ─────────────────────────────────────────────────────────────

DEFAULT_BAND_DEFS_DAYS: dict[str, tuple[float, float]] = {
    "circaseptan": (5.0, 9.0),
    "ultradian":   (2.0, 4.0),
}

MAX_INTERP_GAP_DAYS: int = 7
DEFAULT_SPECTRAL_ALPHA: float = 0.1


def _tracked_bands(band_defs_days: dict[str, tuple[float, float]] | None) -> tuple[str, ...]:
    """Compute the EWMA-tracked key set for a given band layout."""
    bands = band_defs_days or DEFAULT_BAND_DEFS_DAYS
    return ("dc_drift", *bands.keys(), "noise_floor")


# ─────────────────────────────────────────────────────────────
# Resampling
# ─────────────────────────────────────────────────────────────


def _parse_iso(ts: str) -> datetime:
    s = ts.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s).astimezone(timezone.utc)


def resample_to_daily(
    timestamps_iso: list[str],
    values: list[float],
    window_days: int = 30,
) -> tuple[np.ndarray, int]:
    """Group irregular observations onto a daily grid; interpolate small gaps.

    Identical semantics to the historical ``rhythm_fft.resample_to_daily`` —
    sub-day rates collapse to per-day means, missing days inside the
    window are linearly interpolated, and any gap longer than
    ``MAX_INTERP_GAP_DAYS`` aborts (returns empty array).
    """
    if not timestamps_iso or not values or len(timestamps_iso) != len(values):
        return np.array([]), 0
    if window_days < 2:
        return np.array([]), 0

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

    grid = np.full(window_days, np.nan, dtype=float)
    n_real = 0
    for d, mean in day_means.items():
        if first_day <= d <= last_day:
            grid[d - first_day] = mean
            n_real += 1

    if n_real == 0:
        return np.array([]), 0

    nan_mask = np.isnan(grid)
    if nan_mask.any():
        run = 0
        for is_nan in nan_mask:
            if is_nan:
                run += 1
                if run > MAX_INTERP_GAP_DAYS:
                    return np.array([]), 0
            else:
                run = 0
        known_idx = np.flatnonzero(~nan_mask)
        known_val = grid[known_idx]
        all_idx = np.arange(window_days)
        grid = np.interp(all_idx, known_idx, known_val)

    return grid, n_real


# ─────────────────────────────────────────────────────────────
# Spectral signature
# ─────────────────────────────────────────────────────────────


def compute_spectral_signature(
    daily_series: np.ndarray,
    *,
    band_defs_days: dict[str, tuple[float, float]] | None = None,
) -> dict[str, float]:
    """Per-band spectral fingerprint of a daily series.

    Detrend → Hann window → rFFT → aggregate magnitudes into named
    period bands. Returns ``{}`` when the series is shorter than 4
    samples. Reported bands include the supplied ``band_defs_days``
    plus the synthetic ``dc_drift`` (signed mean shift, |·|),
    ``dc_direction`` (+1 / -1), ``dc_bin_magnitude`` (rFFT bin 0
    after windowing), and ``noise_floor`` (sum of remaining bins).
    """
    if daily_series is None or len(daily_series) < 4:
        return {}

    bands_def = band_defs_days or DEFAULT_BAND_DEFS_DAYS

    n = len(daily_series)
    series_mean = float(np.mean(daily_series))
    detrended = daily_series - series_mean

    window = np.hanning(n)
    windowed = detrended * window

    spectrum = np.abs(np.fft.rfft(windowed))
    freqs_per_day = np.fft.rfftfreq(n, d=1.0)

    dc_magnitude = float(spectrum[0])
    dc_direction = 1 if series_mean >= 0 else -1
    dc_drift = abs(series_mean)

    with np.errstate(divide="ignore"):
        periods = np.where(freqs_per_day > 0,
                           1.0 / np.maximum(freqs_per_day, 1e-12), np.inf)

    bands: dict[str, float] = {}
    used_mask = np.zeros(len(spectrum), dtype=bool)
    used_mask[0] = True

    for name, (low, high) in bands_def.items():
        sel = (periods >= low) & (periods < high)
        bands[name] = float(np.sum(spectrum[sel]))
        used_mask |= sel

    noise_mask = (~used_mask) & (freqs_per_day > 0)
    bands["noise_floor"] = float(np.sum(spectrum[noise_mask]))

    return {
        "dc_drift": round(dc_drift, 6),
        "dc_direction": dc_direction,
        "dc_bin_magnitude": round(dc_magnitude, 6),
        **{k: round(v, 6) for k, v in bands.items()},
    }


# ─────────────────────────────────────────────────────────────
# History EWMA
# ─────────────────────────────────────────────────────────────


def update_spectral_history(
    prev_history: dict[str, Any] | None,
    today: dict[str, float],
    *,
    band_defs_days: dict[str, tuple[float, float]] | None = None,
    alpha: float = DEFAULT_SPECTRAL_ALPHA,
    now_utc: str | None = None,
) -> dict[str, Any]:
    """Fold today's spectral signature into the running EWMA history.

    Identical EWMA recurrence to the previous ``rhythm_fft`` impl, with
    the tracked-band set derived from ``band_defs_days`` so per-signal
    layouts (e.g. agriculture) stay consistent across runs.
    """
    if not today:
        return dict(prev_history or {})

    tracked = _tracked_bands(band_defs_days)

    prev = prev_history or {}
    prev_ewma = dict(prev.get("ewma", {}))
    prev_var = dict(prev.get("variance", {}))
    prev_count = int(prev.get("sample_count", 0))

    if prev_count == 0:
        new_ewma = {band: float(today.get(band, 0.0)) for band in tracked}
        new_var = {band: 0.0 for band in tracked}
    else:
        new_ewma = {}
        new_var = {}
        for band in tracked:
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


# ─────────────────────────────────────────────────────────────
# Drift detection
# ─────────────────────────────────────────────────────────────


def check_spectral_drift(
    history: dict[str, Any] | None,
    today: dict[str, float],
    *,
    band_defs_days: dict[str, tuple[float, float]] | None = None,
    k_spectral: float = 2.5,
    min_samples: int = 5,
    min_variance_floor: float = 1e-6,
    harmful_dc_direction: int = -1,
) -> list[dict[str, Any]]:
    """Return a list of bands whose today-value exceeds ``k_spectral`` σ.

    Direction filtering for ``dc_drift`` is preserved from the original
    impl: only flag when today's signed mean shift matches
    ``harmful_dc_direction`` (otherwise it's a recovery).
    """
    if not today or not history:
        return []

    sample_count = int(history.get("sample_count", 0))
    if sample_count < min_samples:
        return []

    ewma = history.get("ewma") or {}
    variance = history.get("variance") or {}
    tracked = _tracked_bands(band_defs_days)

    findings: list[dict[str, Any]] = []
    for band in tracked:
        x = float(today.get(band, 0.0))
        mu = float(ewma.get(band, 0.0))
        var = max(float(variance.get(band, 0.0)), min_variance_floor)
        sigma = var ** 0.5
        if sigma == 0:
            continue
        z = (x - mu) / sigma
        if abs(z) <= k_spectral:
            continue

        direction = 1 if x >= mu else -1
        if band == "dc_drift":
            today_dc_direction = int(today.get("dc_direction", 0))
            if today_dc_direction != harmful_dc_direction:
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
