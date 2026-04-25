"""Unit tests for lumina.signals.advisories."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from lumina.signals import pull_active_advisory
from lumina.signals.advisories import upsert_spectral_advisory


# ─────────────────────────────────────────────────────────────
# upsert_spectral_advisory
# ─────────────────────────────────────────────────────────────


def test_upsert_into_empty_list_inserts_entry():
    out = upsert_spectral_advisory(
        None,
        signal="valence",
        band="dc_drift",
        finding={"direction": "negative", "z_score": 3.2},
        message="Test message",
    )
    assert len(out) == 1
    entry = out[0]
    assert entry["signal"] == "valence"
    assert entry["band"] == "dc_drift"
    assert entry["direction"] == "negative"
    assert entry["z_score"] == 3.2
    assert entry["message"] == "Test message"
    assert "advisory_id" in entry
    assert "created_utc" in entry
    assert "expires_utc" in entry


def test_upsert_replaces_same_signal_band():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    advisories = [{
        "advisory_id": "old",
        "signal": "valence",
        "band": "dc_drift",
        "direction": "negative",
        "z_score": 2.5,
        "message": "old",
        "created_utc": now.isoformat(),
        "expires_utc": (now + timedelta(seconds=3600)).isoformat(),
    }]
    out = upsert_spectral_advisory(
        advisories,
        signal="valence", band="dc_drift",
        finding={"direction": "negative", "z_score": 4.0},
        message="new message",
        now_utc=now,
    )
    assert len(out) == 1
    assert out[0]["message"] == "new message"
    assert out[0]["advisory_id"] != "old"


def test_upsert_keeps_other_signal_band():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    other = {
        "advisory_id": "keep",
        "signal": "arousal",
        "band": "ultradian",
        "direction": "positive",
        "z_score": 2.6,
        "message": "keep me",
        "created_utc": now.isoformat(),
        "expires_utc": (now + timedelta(seconds=3600)).isoformat(),
    }
    out = upsert_spectral_advisory(
        [other],
        signal="valence", band="dc_drift",
        finding={"direction": "negative", "z_score": 3.0},
        message="new",
        now_utc=now,
    )
    assert len(out) == 2
    assert any(a["advisory_id"] == "keep" for a in out)


def test_upsert_prunes_expired_entries():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    expired = {
        "signal": "arousal", "band": "ultradian",
        "direction": "positive", "z_score": 2.6, "message": "old",
        "created_utc": (now - timedelta(days=2)).isoformat(),
        "expires_utc": (now - timedelta(seconds=10)).isoformat(),
    }
    out = upsert_spectral_advisory(
        [expired],
        signal="valence", band="dc_drift",
        finding={"direction": "negative", "z_score": 3.0},
        message="new",
        now_utc=now,
    )
    assert len(out) == 1
    assert out[0]["signal"] == "valence"


def test_upsert_does_not_mutate_input():
    advisories: list[dict] = []
    _ = upsert_spectral_advisory(
        advisories,
        signal="x", band="dc_drift",
        finding={"direction": "negative"},
        message="m",
    )
    assert advisories == []


def test_upsert_custom_ttl_seconds():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    out = upsert_spectral_advisory(
        None,
        signal="motor_vibration", band="dc_drift",
        finding={"direction": "positive", "z_score": 3.5},
        message="m",
        now_utc=now, ttl_seconds=600,
    )
    expires = datetime.fromisoformat(out[0]["expires_utc"])
    assert (expires - now).total_seconds() == 600


# ─────────────────────────────────────────────────────────────
# pull_active_advisory
# ─────────────────────────────────────────────────────────────


def _make(now: datetime, *, signal: str, band: str, expires_in: int = 3600,
          created_offset: int = 0) -> dict:
    return {
        "advisory_id": f"{signal}-{band}",
        "signal": signal, "band": band,
        "direction": "negative", "z_score": 3.0, "message": "m",
        "created_utc": (now - timedelta(seconds=created_offset)).isoformat(),
        "expires_utc": (now + timedelta(seconds=expires_in)).isoformat(),
    }


def test_pull_active_returns_none_when_no_advisories():
    best, surviving = pull_active_advisory(None)
    assert best is None
    assert surviving == []


def test_pull_active_filters_expired():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    expired = _make(now, signal="x", band="dc_drift", expires_in=-100)
    fresh = _make(now, signal="y", band="dc_drift")
    best, surviving = pull_active_advisory([expired, fresh], now_utc=now)
    assert best is not None
    assert best["signal"] == "y"
    assert len(surviving) == 1


def test_pull_active_priority_ordering_by_signal():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    sal = _make(now, signal="salience", band="dc_drift")
    val = _make(now, signal="valence", band="dc_drift")
    best, _ = pull_active_advisory(
        [sal, val],
        signal_priority=("valence", "arousal", "salience"),
        band_priority=("dc_drift", "circaseptan", "ultradian"),
        now_utc=now,
    )
    assert best["signal"] == "valence"


def test_pull_active_priority_ordering_by_band_when_signal_ties():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    a = _make(now, signal="valence", band="ultradian")
    b = _make(now, signal="valence", band="dc_drift")
    best, _ = pull_active_advisory(
        [a, b],
        signal_priority=("valence",),
        band_priority=("dc_drift", "circaseptan", "ultradian"),
        now_utc=now,
    )
    assert best["band"] == "dc_drift"


def test_pull_active_unknown_signal_ranks_last():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    known = _make(now, signal="valence", band="dc_drift")
    unknown = _make(now, signal="weird", band="dc_drift")
    best, _ = pull_active_advisory(
        [unknown, known],
        signal_priority=("valence",),
        band_priority=("dc_drift",),
        now_utc=now,
    )
    assert best["signal"] == "valence"


def test_pull_active_no_priorities_falls_back_to_most_recent():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    older = _make(now, signal="a", band="x", created_offset=300)
    newer = _make(now, signal="b", band="y", created_offset=10)
    best, _ = pull_active_advisory([older, newer], now_utc=now)
    assert best["signal"] == "b"
