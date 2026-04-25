"""Unit tests for lumina.signals.baseline."""

from __future__ import annotations

from lumina.signals import (
    SignalBaseline,
    SignalSample,
    check_envelope_deviation,
    check_shape_deviation,
    compute_drift,
    update_baseline,
)


# ─────────────────────────────────────────────────────────────
# update_baseline
# ─────────────────────────────────────────────────────────────


def test_update_baseline_seeds_first_observation_at_value():
    base = SignalBaseline()
    new = update_baseline(base, SignalSample("soil_pH", 6.5, "2026-01-01T00:00:00Z"))
    entry = new.per_signal["soil_pH"]
    assert entry["ewma"] == 6.5
    assert entry["sample_count"] == 1
    assert entry["prev_ewma"] == 6.5
    assert entry["run_length"] != 0  # seeded from sign of first residual


def test_update_baseline_clamps_to_range():
    base = SignalBaseline()
    new = update_baseline(
        base,
        SignalSample("salience", 1.7, "2026-01-01T00:00:00Z"),
        range_lo=0.0,
        range_hi=1.0,
    )
    assert new.per_signal["salience"]["ewma"] == 1.0


def test_update_baseline_carries_unrelated_signals_unchanged():
    base = update_baseline(SignalBaseline(),
                           SignalSample("soil_pH", 6.5, "t1"))
    base = update_baseline(base, SignalSample("moisture", 0.3, "t2"))
    new = update_baseline(base, SignalSample("soil_pH", 6.7, "t3"))
    # moisture entry must survive intact
    assert new.per_signal["moisture"]["ewma"] == 0.3
    assert new.per_signal["moisture"]["sample_count"] == 1


def test_update_baseline_ewma_recurrence_matches_alpha_0_1():
    """After several updates, EWMA should match the canonical recurrence."""
    alpha = 0.1
    samples = [0.5, 0.6, 0.7, 0.8, 0.9]
    base = SignalBaseline()
    expected = samples[0]
    base = update_baseline(base, SignalSample("x", samples[0], "t0"), alpha=alpha)
    for i, v in enumerate(samples[1:], start=1):
        base = update_baseline(base, SignalSample("x", v, f"t{i}"), alpha=alpha)
        expected = round(alpha * v + (1 - alpha) * expected, 6)
    assert base.per_signal["x"]["ewma"] == expected
    assert base.per_signal["x"]["sample_count"] == len(samples)


def test_update_baseline_does_not_mutate_input():
    base = update_baseline(SignalBaseline(), SignalSample("x", 0.1, "t0"))
    snapshot = dict(base.per_signal["x"])
    _ = update_baseline(base, SignalSample("x", 0.9, "t1"))
    assert base.per_signal["x"] == snapshot


# ─────────────────────────────────────────────────────────────
# compute_drift
# ─────────────────────────────────────────────────────────────


def test_compute_drift_immature_baseline_returns_zero():
    base = update_baseline(SignalBaseline(), SignalSample("x", 0.5, "t0"))
    drift = compute_drift(base, "x", min_samples=5)
    assert drift.is_fast_drift is False
    assert drift.velocity == 0.0


def test_compute_drift_detects_fast_drift():
    base = SignalBaseline()
    # Long warmup at 0.5
    for i in range(10):
        base = update_baseline(base, SignalSample("x", 0.5, f"t{i}"))
    # Sudden jump
    base = update_baseline(base, SignalSample("x", 1.0, "t10"))
    drift = compute_drift(base, "x", fast_drift_threshold=0.04)
    assert drift.is_fast_drift is True
    assert drift.velocity > 0


def test_compute_drift_unknown_signal_returns_zero():
    drift = compute_drift(SignalBaseline(), "nope")
    assert drift.is_fast_drift is False
    assert drift.name == "nope"


# ─────────────────────────────────────────────────────────────
# check_envelope_deviation
# ─────────────────────────────────────────────────────────────


def test_envelope_immature_below_min_samples():
    entry = {"ewma": 0.5, "variance": 0.04, "sample_count": 2}
    out = check_envelope_deviation(entry, 0.9, min_samples=5)
    assert out["triggered"] is False
    assert out["mature"] is False


def test_envelope_triggers_outside_k_sigma():
    entry = {"ewma": 0.5, "variance": 0.01, "sample_count": 10}
    # std = 0.1; observed at 1.0 → z = 5.0
    out = check_envelope_deviation(entry, 1.0, k_sigma=2.0)
    assert out["triggered"] is True
    assert out["z_score"] >= 4.9


def test_envelope_within_envelope():
    entry = {"ewma": 0.5, "variance": 0.04, "sample_count": 10}
    out = check_envelope_deviation(entry, 0.55, k_sigma=2.0)
    assert out["triggered"] is False
    assert out["reason"] == "within_envelope"


def test_envelope_none_entry_immature():
    out = check_envelope_deviation(None, 0.5)
    assert out["triggered"] is False
    assert out["mature"] is False


# ─────────────────────────────────────────────────────────────
# check_shape_deviation
# ─────────────────────────────────────────────────────────────


def test_shape_immature_below_min_samples():
    entry = {"crossing_rate": 0.5, "run_length": 6, "sample_count": 3}
    out = check_shape_deviation(entry, min_samples=10)
    assert out["mature"] is False
    assert out["triggered"] is False


def test_shape_triggers_long_run():
    # crossing_rate=0.5 → expected_mean_run=2; k_shape=2 → threshold=4
    entry = {"crossing_rate": 0.5, "run_length": 6, "sample_count": 20}
    out = check_shape_deviation(entry, k_shape=2.0)
    assert out["triggered"] is True
    assert out["direction"] == "positive"


def test_shape_triggers_negative_direction():
    entry = {"crossing_rate": 0.5, "run_length": -8, "sample_count": 20}
    out = check_shape_deviation(entry, k_shape=2.0)
    assert out["triggered"] is True
    assert out["direction"] == "negative"


def test_shape_normal_run_within_threshold():
    entry = {"crossing_rate": 0.5, "run_length": 2, "sample_count": 20}
    out = check_shape_deviation(entry, k_shape=2.0)
    assert out["triggered"] is False
    assert out["reason"] == "rhythm_normal"


# ─────────────────────────────────────────────────────────────
# SignalBaseline serialisation
# ─────────────────────────────────────────────────────────────


def test_baseline_to_dict_and_from_dict_roundtrip():
    base = SignalBaseline()
    for i, v in enumerate([0.5, 0.6, 0.55, 0.7, 0.65]):
        base = update_baseline(base, SignalSample("x", v, f"t{i}"))
    serialised = base.to_dict()
    revived = SignalBaseline.from_dict(serialised)
    assert revived.per_signal["x"]["sample_count"] == 5
    assert revived.per_signal["x"]["ewma"] == base.per_signal["x"]["ewma"]


def test_baseline_from_dict_handles_empty_input():
    assert SignalBaseline.from_dict(None).per_signal == {}
    assert SignalBaseline.from_dict({}).per_signal == {}
