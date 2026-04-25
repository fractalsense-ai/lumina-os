"""Unit tests for lumina.signals.spectral."""

from __future__ import annotations

import numpy as np

from lumina.signals import (
    DEFAULT_BAND_DEFS_DAYS,
    check_spectral_drift,
    compute_spectral_signature,
    resample_to_daily,
    update_spectral_history,
)


# ─────────────────────────────────────────────────────────────
# resample_to_daily
# ─────────────────────────────────────────────────────────────


def test_resample_empty_inputs():
    grid, n = resample_to_daily([], [])
    assert n == 0
    assert grid.size == 0


def test_resample_mismatched_lengths():
    grid, n = resample_to_daily(["2026-01-01T00:00:00Z"], [])
    assert grid.size == 0


def test_resample_single_day_window():
    ts = [f"2026-01-{d:02d}T00:00:00Z" for d in range(1, 11)]
    vals = [0.5] * 10
    grid, n = resample_to_daily(ts, vals, window_days=10)
    assert grid.size == 10
    assert n == 10
    assert all(v == 0.5 for v in grid)


def test_resample_interpolates_short_gap():
    ts = ["2026-01-01T00:00:00Z", "2026-01-04T00:00:00Z"]
    vals = [0.0, 0.6]
    grid, n = resample_to_daily(ts, vals, window_days=4)
    assert grid.size == 4
    assert n == 2
    # Linear interpolation between 0.0 (day 0) and 0.6 (day 3): 0.2, 0.4
    assert abs(grid[1] - 0.2) < 1e-6
    assert abs(grid[2] - 0.4) < 1e-6


def test_resample_rejects_oversized_gap():
    ts = ["2026-01-01T00:00:00Z", "2026-01-15T00:00:00Z"]
    vals = [0.0, 1.0]
    grid, n = resample_to_daily(ts, vals, window_days=15)
    assert grid.size == 0  # gap > MAX_INTERP_GAP_DAYS


def test_resample_handles_z_suffix():
    ts = ["2026-01-01T00:00:00Z"]
    vals = [0.5]
    grid, n = resample_to_daily(ts, vals, window_days=2)
    # window_days=2 with single observation → 1 real day, edge fill
    assert n == 1


# ─────────────────────────────────────────────────────────────
# compute_spectral_signature
# ─────────────────────────────────────────────────────────────


def test_signature_empty_for_short_series():
    assert compute_spectral_signature(np.array([])) == {}
    assert compute_spectral_signature(np.array([1.0, 2.0, 3.0])) == {}


def test_signature_constant_series_has_zero_drift():
    series = np.full(30, 0.5)
    sig = compute_spectral_signature(series)
    # mean=0.5 ≠ 0 → dc_drift=0.5; but circaseptan/ultradian should be 0
    assert sig["dc_drift"] == 0.5
    assert sig["circaseptan"] == 0.0
    assert sig["ultradian"] == 0.0
    assert "noise_floor" in sig


def test_signature_includes_default_bands():
    series = np.linspace(0, 1, 30)
    sig = compute_spectral_signature(series)
    for band in DEFAULT_BAND_DEFS_DAYS:
        assert band in sig
    assert "dc_drift" in sig
    assert "noise_floor" in sig
    assert sig["dc_direction"] in (1, -1)


def test_signature_respects_custom_band_defs():
    series = np.linspace(0, 1, 60)
    custom = {"weekly": (5.0, 9.0), "monthly": (25.0, 35.0)}
    sig = compute_spectral_signature(series, band_defs_days=custom)
    assert "weekly" in sig
    assert "monthly" in sig
    assert "circaseptan" not in sig  # default band absent under custom layout


def test_signature_dc_direction_negative_for_negative_mean():
    series = np.full(30, -0.3)
    sig = compute_spectral_signature(series)
    assert sig["dc_direction"] == -1


# ─────────────────────────────────────────────────────────────
# update_spectral_history
# ─────────────────────────────────────────────────────────────


def test_history_seeds_on_first_call():
    today = {"dc_drift": 0.5, "circaseptan": 0.1, "ultradian": 0.2,
             "noise_floor": 0.05, "dc_direction": 1}
    hist = update_spectral_history(None, today)
    assert hist["sample_count"] == 1
    assert hist["ewma"]["dc_drift"] == 0.5
    assert hist["variance"]["dc_drift"] == 0.0
    assert "last_run_utc" in hist


def test_history_ewma_recurrence_on_second_call():
    today1 = {"dc_drift": 0.5, "circaseptan": 0.0, "ultradian": 0.0,
              "noise_floor": 0.0}
    hist1 = update_spectral_history(None, today1)
    today2 = {"dc_drift": 1.5, "circaseptan": 0.0, "ultradian": 0.0,
              "noise_floor": 0.0}
    hist2 = update_spectral_history(hist1, today2, alpha=0.1)
    # μ_new = 0.1 * 1.5 + 0.9 * 0.5 = 0.6
    assert abs(hist2["ewma"]["dc_drift"] - 0.6) < 1e-6
    assert hist2["sample_count"] == 2


def test_history_empty_today_preserves_prior():
    prior = {"ewma": {"dc_drift": 0.5}, "variance": {}, "sample_count": 3}
    out = update_spectral_history(prior, {})
    assert out == prior


def test_history_uses_custom_band_layout():
    custom = {"weekly": (5.0, 9.0)}
    today = {"dc_drift": 0.5, "weekly": 0.2, "noise_floor": 0.05}
    hist = update_spectral_history(None, today, band_defs_days=custom)
    assert "weekly" in hist["ewma"]
    assert "circaseptan" not in hist["ewma"]


# ─────────────────────────────────────────────────────────────
# check_spectral_drift
# ─────────────────────────────────────────────────────────────


def test_drift_returns_empty_when_history_immature():
    history = {
        "ewma": {"dc_drift": 0.5},
        "variance": {"dc_drift": 0.04},
        "sample_count": 3,
    }
    today = {"dc_drift": 5.0, "dc_direction": -1}
    findings = check_spectral_drift(history, today, min_samples=5)
    assert findings == []


def test_drift_returns_empty_for_no_today():
    history = {"ewma": {}, "variance": {}, "sample_count": 10}
    assert check_spectral_drift(history, {}) == []
    assert check_spectral_drift(history, None) == []


def test_drift_detects_z_score_excursion_on_circaseptan():
    history = {
        "ewma": {"dc_drift": 0.0, "circaseptan": 0.1,
                 "ultradian": 0.0, "noise_floor": 0.0},
        "variance": {"dc_drift": 0.0, "circaseptan": 0.001,
                     "ultradian": 0.0, "noise_floor": 0.0},
        "sample_count": 10,
    }
    # circaseptan jumps to 1.0 with σ ≈ 0.0316 → z ≈ 28
    today = {"dc_drift": 0.0, "circaseptan": 1.0,
             "ultradian": 0.0, "noise_floor": 0.0, "dc_direction": 0}
    findings = check_spectral_drift(history, today, k_spectral=2.5)
    bands = {f["band"] for f in findings}
    assert "circaseptan" in bands


def test_drift_filters_dc_direction_recovery():
    """If dc_drift exceeds k_spectral but direction is +1 (recovery) and
    harmful_dc_direction is -1, the dc_drift band must NOT be flagged."""
    history = {
        "ewma": {"dc_drift": 0.0, "circaseptan": 0.0,
                 "ultradian": 0.0, "noise_floor": 0.0},
        "variance": {"dc_drift": 0.001, "circaseptan": 0.0,
                     "ultradian": 0.0, "noise_floor": 0.0},
        "sample_count": 10,
    }
    today_recovery = {"dc_drift": 1.0, "circaseptan": 0.0,
                      "ultradian": 0.0, "noise_floor": 0.0,
                      "dc_direction": 1}
    findings = check_spectral_drift(history, today_recovery,
                                    harmful_dc_direction=-1, k_spectral=2.5)
    assert all(f["band"] != "dc_drift" for f in findings)


def test_drift_flags_dc_drift_when_direction_matches_harmful():
    history = {
        "ewma": {"dc_drift": 0.0, "circaseptan": 0.0,
                 "ultradian": 0.0, "noise_floor": 0.0},
        "variance": {"dc_drift": 0.001, "circaseptan": 0.0,
                     "ultradian": 0.0, "noise_floor": 0.0},
        "sample_count": 10,
    }
    today = {"dc_drift": 1.0, "circaseptan": 0.0,
             "ultradian": 0.0, "noise_floor": 0.0,
             "dc_direction": -1}
    findings = check_spectral_drift(history, today,
                                    harmful_dc_direction=-1, k_spectral=2.5)
    bands = {f["band"] for f in findings}
    assert "dc_drift" in bands
