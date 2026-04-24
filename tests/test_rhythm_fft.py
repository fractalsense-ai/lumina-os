"""Tests for lumina.daemon.rhythm_fft (Phase G).

Pure-numpy spectral helpers that detect chronic drift across an actor's
SVA history. These tests cover:

- Resampling irregular timestamps onto a daily grid (incl. gap rejection).
- Spectral signature shapes for known synthetic inputs.
- EWMA spectral-history round-trip (mean + variance).
- Drift detection thresholds and direction-asymmetry on dc_drift.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from lumina.daemon import rhythm_fft as rf


# ── Helpers ───────────────────────────────────────────────────


def _iso(base: datetime, day_offset: float) -> str:
    """Build a UTC ISO string `day_offset` days after `base`."""
    return (base + timedelta(days=day_offset)).strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture
def base_dt() -> datetime:
    return datetime(2026, 3, 1, tzinfo=timezone.utc)


# ── resample_to_daily ─────────────────────────────────────────


class TestResample:

    def test_uniform_daily_input_passes_through(self, base_dt: datetime):
        ts = [_iso(base_dt, d) for d in range(30)]
        vals = list(np.linspace(0.0, 0.5, 30))
        series, n = rf.resample_to_daily(ts, vals, window_days=30)
        assert len(series) == 30
        assert n == 30
        # Each daily mean equals the single observation
        assert np.allclose(series, vals)

    def test_multiple_observations_per_day_are_averaged(self, base_dt: datetime):
        ts = [
            _iso(base_dt, 0), _iso(base_dt, 0.25), _iso(base_dt, 0.75),
            *[_iso(base_dt, d) for d in range(1, 30)],
        ]
        vals = [0.0, 0.6, 0.9, *[0.0] * 29]
        series, n = rf.resample_to_daily(ts, vals, window_days=30)
        # First day mean = (0 + 0.6 + 0.9) / 3 = 0.5
        assert series[0] == pytest.approx(0.5, abs=1e-6)
        assert n == 30

    def test_short_gap_is_interpolated(self, base_dt: datetime):
        # Drop days 5 and 6 (a 2-day gap, well under the 7-day cap)
        present = [d for d in range(30) if d not in (5, 6)]
        ts = [_iso(base_dt, d) for d in present]
        vals = [float(d) / 30.0 for d in present]
        series, n = rf.resample_to_daily(ts, vals, window_days=30)
        assert len(series) == 30
        # Interpolated values lie between the surrounding day values
        assert series[5] == pytest.approx((series[4] + series[7]) * 0.5 - (series[7] - series[4]) / 6, abs=0.05)
        assert n == 28

    def test_oversized_gap_returns_empty(self, base_dt: datetime):
        # Drop days 5..14 (10-day gap, exceeds MAX_INTERP_GAP_DAYS=7)
        present = [d for d in range(30) if not (5 <= d <= 14)]
        ts = [_iso(base_dt, d) for d in present]
        vals = [0.1 * d for d in present]
        series, n = rf.resample_to_daily(ts, vals, window_days=30)
        assert len(series) == 0
        assert n == 0

    def test_empty_input_returns_empty(self):
        series, n = rf.resample_to_daily([], [], window_days=30)
        assert len(series) == 0
        assert n == 0

    def test_mismatched_lengths_returns_empty(self, base_dt: datetime):
        ts = [_iso(base_dt, 0), _iso(base_dt, 1)]
        series, n = rf.resample_to_daily(ts, [0.1], window_days=30)
        assert len(series) == 0


# ── compute_spectral_signature ────────────────────────────────


class TestSpectralSignature:

    def test_seven_day_sine_dominates_circaseptan_band(self):
        days = np.arange(30)
        series = 0.4 * np.sin(2 * np.pi * days / 7.0)
        sig = rf.compute_spectral_signature(series)
        assert sig["circaseptan"] > sig["ultradian"]
        assert sig["circaseptan"] > sig["noise_floor"]

    def test_three_day_sine_dominates_ultradian_band(self):
        days = np.arange(30)
        series = 0.4 * np.sin(2 * np.pi * days / 3.0)
        sig = rf.compute_spectral_signature(series)
        assert sig["ultradian"] > sig["circaseptan"]

    def test_negative_constant_offset_reports_negative_dc_direction(self):
        series = np.full(30, -0.4)
        sig = rf.compute_spectral_signature(series)
        assert sig["dc_drift"] == pytest.approx(0.4, abs=1e-6)
        assert sig["dc_direction"] == -1

    def test_positive_constant_offset_reports_positive_dc_direction(self):
        series = np.full(30, 0.3)
        sig = rf.compute_spectral_signature(series)
        assert sig["dc_drift"] == pytest.approx(0.3, abs=1e-6)
        assert sig["dc_direction"] == 1

    def test_too_short_series_returns_empty(self):
        assert rf.compute_spectral_signature(np.array([0.1, 0.2])) == {}
        assert rf.compute_spectral_signature(np.array([])) == {}


# ── update_spectral_history ──────────────────────────────────


class TestSpectralHistory:

    def test_first_call_seeds_with_zero_variance(self):
        today = {"dc_drift": 0.1, "circaseptan": 0.5, "ultradian": 0.2, "noise_floor": 0.3}
        hist = rf.update_spectral_history({}, today)
        assert hist["sample_count"] == 1
        assert hist["ewma"]["circaseptan"] == pytest.approx(0.5, abs=1e-6)
        assert all(v == 0.0 for v in hist["variance"].values())

    def test_repeated_identical_inputs_keep_ewma_stable(self):
        today = {"dc_drift": 0.1, "circaseptan": 0.5, "ultradian": 0.2, "noise_floor": 0.3}
        hist: dict = {}
        for _ in range(10):
            hist = rf.update_spectral_history(hist, today)
        assert hist["sample_count"] == 10
        assert hist["ewma"]["circaseptan"] == pytest.approx(0.5, abs=1e-4)
        # Variance never inflates when inputs don't change
        assert hist["variance"]["circaseptan"] == pytest.approx(0.0, abs=1e-6)

    def test_round_trip_via_dict_preserves_structure(self):
        today = {"dc_drift": 0.1, "circaseptan": 0.5, "ultradian": 0.2, "noise_floor": 0.3}
        hist = rf.update_spectral_history({}, today, now_utc="2026-04-01T00:00:00+00:00")
        # Simulate save/load cycle through a dict copy
        round_tripped = dict(hist)
        assert round_tripped["last_run_utc"] == "2026-04-01T00:00:00+00:00"
        assert round_tripped["last_signature"] == today

    def test_empty_today_preserves_history(self):
        prior = rf.update_spectral_history({}, {"dc_drift": 0.1, "circaseptan": 0.5,
                                                  "ultradian": 0.0, "noise_floor": 0.0})
        out = rf.update_spectral_history(prior, {})
        assert out == prior


# ── check_spectral_drift ─────────────────────────────────────


def _build_mature_history(stable_sig: dict, runs: int = 6) -> dict:
    """Build a spectral history with `runs` repeats of `stable_sig`."""
    hist: dict = {}
    for _ in range(runs):
        hist = rf.update_spectral_history(hist, stable_sig)
    return hist


class TestDriftDetection:

    def test_immature_history_returns_no_findings(self):
        today = {"dc_drift": 0.5, "circaseptan": 0.0, "ultradian": 0.0,
                 "noise_floor": 0.0, "dc_direction": -1}
        hist = rf.update_spectral_history({}, today)  # only 1 sample
        findings = rf.check_spectral_drift(hist, today, min_samples=5)
        assert findings == []

    def test_stable_history_with_matching_today_yields_no_findings(self):
        sig = {"dc_drift": 0.05, "circaseptan": 0.4, "ultradian": 0.1,
               "noise_floor": 0.1, "dc_direction": 1}
        hist = _build_mature_history(sig)
        findings = rf.check_spectral_drift(hist, sig, k_spectral=2.5)
        assert findings == []

    def test_dc_drift_in_harmful_direction_triggers(self):
        # Build a history where dc_drift is small and positive
        baseline = {"dc_drift": 0.02, "circaseptan": 0.3, "ultradian": 0.1,
                    "noise_floor": 0.1, "dc_direction": 1}
        # Inject some natural variance so sigma > 0
        hist: dict = {}
        for v in (0.02, 0.03, 0.025, 0.018, 0.022, 0.024, 0.021):
            sample = dict(baseline, dc_drift=v)
            hist = rf.update_spectral_history(hist, sample)
        # Today: large negative dc shift
        today = dict(baseline, dc_drift=0.45, dc_direction=-1)
        findings = rf.check_spectral_drift(hist, today, k_spectral=2.0,
                                            harmful_dc_direction=-1)
        bands = {f["band"] for f in findings}
        assert "dc_drift" in bands
        dc_finding = next(f for f in findings if f["band"] == "dc_drift")
        assert dc_finding["direction"] == -1

    def test_dc_drift_in_recovery_direction_does_not_trigger(self):
        # Same setup, but today's dc_drift is large in the BENIGN direction
        baseline = {"dc_drift": 0.02, "circaseptan": 0.3, "ultradian": 0.1,
                    "noise_floor": 0.1, "dc_direction": -1}
        hist: dict = {}
        for v in (0.02, 0.03, 0.025, 0.018, 0.022, 0.024, 0.021):
            hist = rf.update_spectral_history(hist, dict(baseline, dc_drift=v))
        today = dict(baseline, dc_drift=0.45, dc_direction=1)  # recovery
        findings = rf.check_spectral_drift(hist, today, k_spectral=2.0,
                                            harmful_dc_direction=-1)
        # dc_drift should NOT be in findings even though z is huge
        assert all(f["band"] != "dc_drift" for f in findings)

    def test_empty_inputs_return_empty(self):
        assert rf.check_spectral_drift({}, {"dc_drift": 0.1}) == []
        assert rf.check_spectral_drift({"sample_count": 10}, {}) == []
