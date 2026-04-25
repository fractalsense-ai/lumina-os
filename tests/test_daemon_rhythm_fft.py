"""Tests for the rhythm_fft_analysis daemon task (Phase G).

These tests establish a daemon-task test pattern (none existed) and
validate the integrated pipeline:

- A mock persistence backend exposing list_users / list_profiles /
  load_profile / save_profile / query_log_records.
- Synthetic 60 days of TraceEvents for one actor with a slow downward
  valence drift embedded in the most recent ~14 days.
- After the task runs we assert at least one Proposal of type
  ``chronic_spectral_drift`` for the dc_drift band, direction = -1.
- Spectral history is persisted back to the actor profile.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from lumina.daemon.tasks import get_task


# ── Mock persistence ─────────────────────────────────────────


class _MockPersistence:
    """Minimal in-memory persistence stub matching the task's contract."""

    def __init__(self, profiles: dict[str, dict], records: list[dict]):
        self._profiles = profiles  # {user_id: {domain_key: profile_dict}}
        self._records = records

    def list_users(self) -> list[dict[str, Any]]:
        return [{"user_id": uid} for uid in self._profiles]

    def list_profiles(self, user_id: str) -> list[str]:
        return list(self._profiles.get(user_id, {}).keys())

    def load_profile(self, user_id: str, domain_key: str):
        return self._profiles.get(user_id, {}).get(domain_key)

    def save_profile(self, user_id: str, domain_key: str, data: dict[str, Any]) -> None:
        self._profiles.setdefault(user_id, {})[domain_key] = data

    def query_log_records(
        self,
        record_type: str | None = None,
        domain_id: str | None = None,
        limit: int = 100,
        **_kw: Any,
    ) -> list[dict[str, Any]]:
        out = self._records
        if record_type:
            out = [r for r in out if r.get("record_type") == record_type]
        return out[:limit]


# ── Helpers ──────────────────────────────────────────────────


def _make_trace(actor_id: str, ts: datetime, valence: float) -> dict[str, Any]:
    return {
        "record_type": "TraceEvent",
        "actor_id": actor_id,
        "timestamp_utc": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "event_type": "turn_processed",
        "metadata": {
            "sva_direct": {"salience": 0.5, "valence": valence, "arousal": 0.5},
        },
    }


def _make_baseline_history(stable_dc: float = 0.02, runs: int = 8) -> dict:
    """Pre-seed the actor's spectral_history with a stable, mature signature."""
    from lumina.signals import update_spectral_history
    hist: dict = {}
    # Tiny natural jitter so variance > 0 → finite z-scores
    for i in range(runs):
        sig = {
            "dc_drift": stable_dc + (0.002 if i % 2 else -0.002),
            "circaseptan": 0.4,
            "ultradian": 0.15,
            "noise_floor": 0.2,
            "dc_direction": 1,
        }
        hist = update_spectral_history(hist, sig)
    return hist


# ── Tests ────────────────────────────────────────────────────


class TestRhythmFFTDaemonTask:

    def test_task_is_registered(self):
        assert get_task("rhythm_fft_analysis") is not None

    def test_no_profiles_returns_clean_skip(self):
        task = get_task("rhythm_fft_analysis")
        persistence = _MockPersistence({}, [])
        result = task("education", {}, persistence=persistence)
        assert result.success
        assert result.proposals == []
        assert result.metadata.get("no_profiles") is True

    def test_chronic_downward_drift_emits_proposal(self):
        task = get_task("rhythm_fft_analysis")

        # One actor in the education domain with a mature spectral history
        actor = "student_alpha"
        domain_key = "education"
        profile = {
            "subject_id": actor,
            "learning_state": {
                "signal_baselines": {
                    "spectral_history": {
                        "valence": _make_baseline_history(stable_dc=0.02),
                    },
                },
            },
        }
        profiles = {actor: {domain_key: profile}}

        # Build 60 days of trace events. First 46 days = mild positive
        # baseline; last 14 days = steady downward slide so the WINDOW
        # (last 30 days) has a large negative mean.
        now = datetime(2026, 4, 30, 12, 0, 0, tzinfo=timezone.utc)
        records: list[dict] = []
        for d in range(60):
            ts = now - timedelta(days=59 - d)
            if d < 46:
                v = 0.05 + 0.02 * math.sin(2 * math.pi * d / 7.0)
            else:
                # Slide from 0 down to -0.6 over the last 14 days
                v = -0.6 * (d - 45) / 14.0
            # 3 turns per day for realism
            for hour_offset in (0, 4, 8):
                records.append(_make_trace(actor, ts + timedelta(hours=hour_offset), v))

        persistence = _MockPersistence(profiles, records)

        physics = {
            "spectral_drift_thresholds": {
                "window_days": 30,
                "k_spectral": 2.0,
                "min_samples_for_drift": 5,
                "alpha": 0.1,
                "axes": ["valence"],
            },
        }

        result = task("education", physics, persistence=persistence)

        assert result.success, f"task failed: {result.error}"
        assert result.metadata["profiles_analyzed"] == 1
        assert result.metadata["signals_run"] == ["valence"]

        # At least one chronic_spectral_drift proposal for dc_drift / negative
        chronic = [
            p for p in result.proposals
            if p.proposal_type == "chronic_spectral_drift"
        ]
        assert chronic, "expected a chronic_spectral_drift proposal"
        dc_props = [p for p in chronic if p.detail.get("band") == "dc_drift"]
        assert dc_props, "expected a dc_drift proposal in the chronic findings"
        assert dc_props[0].detail["direction"] == -1
        assert dc_props[0].detail["signal"] == "valence"
        assert dc_props[0].detail["user_id"] == actor

    def test_history_is_persisted_back_to_profile(self):
        task = get_task("rhythm_fft_analysis")
        actor = "student_beta"
        domain_key = "education"
        profile = {
            "subject_id": actor,
            "learning_state": {"signal_baselines": {}},
        }
        profiles = {actor: {domain_key: profile}}

        # Generate 30 days of clean weekly oscillation
        now = datetime(2026, 4, 30, 12, 0, 0, tzinfo=timezone.utc)
        records: list[dict] = []
        for d in range(30):
            ts = now - timedelta(days=29 - d)
            v = 0.3 * math.sin(2 * math.pi * d / 7.0)
            records.append(_make_trace(actor, ts, v))

        persistence = _MockPersistence(profiles, records)
        result = task("education", {}, persistence=persistence)

        assert result.success
        # Inspect the saved profile for spectral_history under valence axis
        saved = persistence.load_profile(actor, domain_key)
        sh = saved["learning_state"]["signal_baselines"]["spectral_history"]
        assert "valence" in sh
        assert sh["valence"]["sample_count"] >= 1
        assert "circaseptan" in sh["valence"]["ewma"]


# ── Phase G.5 — chronic spectral advisory persistence ─────────


def _drift_profile(actor: str) -> dict:
    """Helper: build the same drift-prone profile used by the chronic test."""
    return {
        "subject_id": actor,
        "learning_state": {
            "signal_baselines": {
                "spectral_history": {
                    "valence": _make_baseline_history(stable_dc=0.02),
                },
            },
        },
    }


def _drift_records(actor: str) -> list[dict]:
    """Helper: 60d of trace events with a 14-day downward valence slide."""
    now = datetime(2026, 4, 30, 12, 0, 0, tzinfo=timezone.utc)
    out: list[dict] = []
    for d in range(60):
        ts = now - timedelta(days=59 - d)
        if d < 46:
            v = 0.05 + 0.02 * math.sin(2 * math.pi * d / 7.0)
        else:
            v = -0.6 * (d - 45) / 14.0
        for hour_offset in (0, 4, 8):
            out.append(_make_trace(actor, ts + timedelta(hours=hour_offset), v))
    return out


_PHYSICS_DRIFT = {
    "spectral_drift_thresholds": {
        "window_days": 30,
        "k_spectral": 2.0,
        "min_samples_for_drift": 5,
        "alpha": 0.1,
        "axes": ["valence"],
    },
}


class TestSpectralAdvisoryPersistence:
    """Phase G.5: chronic_spectral_drift Proposals must also write a
    user-facing advisory entry into ``profile.learning_state.spectral_advisories``
    so the journal session-start / piggyback path can surface it."""

    def test_proposal_writes_spectral_advisory(self):
        task = get_task("rhythm_fft_analysis")
        actor = "student_g51"
        profiles = {actor: {"education": _drift_profile(actor)}}
        persistence = _MockPersistence(profiles, _drift_records(actor))

        result = task("education", _PHYSICS_DRIFT, persistence=persistence)
        assert result.success
        chronic = [p for p in result.proposals if p.proposal_type == "chronic_spectral_drift"]
        assert chronic

        saved = persistence.load_profile(actor, "education")
        advisories = saved["learning_state"].get("spectral_advisories")
        assert isinstance(advisories, list) and advisories, (
            "expected at least one advisory written alongside the Proposal"
        )
        adv = advisories[0]
        for key in ("advisory_id", "signal", "band", "direction",
                    "message", "created_utc", "expires_utc"):
            assert key in adv, f"advisory missing key {key!r}: {adv}"
        assert adv["signal"] == "valence"
        assert adv["band"] == "dc_drift"
        assert isinstance(adv["message"], str) and adv["message"]

    def test_advisory_ttl_is_24_hours(self):
        task = get_task("rhythm_fft_analysis")
        actor = "student_g51_ttl"
        profiles = {actor: {"education": _drift_profile(actor)}}
        persistence = _MockPersistence(profiles, _drift_records(actor))

        task("education", _PHYSICS_DRIFT, persistence=persistence)
        adv = persistence.load_profile(actor, "education")[
            "learning_state"]["spectral_advisories"][0]

        created = datetime.fromisoformat(adv["created_utc"])
        expires = datetime.fromisoformat(adv["expires_utc"])
        ttl = expires - created
        # Expect exactly 24h window with a small (sub-second) tolerance.
        assert abs(ttl.total_seconds() - 24 * 3600) < 5

    def test_repeat_drift_replaces_same_band_advisory(self):
        """A second daemon pass for the same (signal, band) must replace
        rather than accumulate advisories."""
        task = get_task("rhythm_fft_analysis")
        actor = "student_g51_replace"
        profiles = {actor: {"education": _drift_profile(actor)}}
        persistence = _MockPersistence(profiles, _drift_records(actor))

        task("education", _PHYSICS_DRIFT, persistence=persistence)
        first = persistence.load_profile(actor, "education")[
            "learning_state"]["spectral_advisories"]
        assert len(first) >= 1
        first_id = first[0]["advisory_id"]

        # Run again — same drift fixtures, same (axis, band) finding.
        task("education", _PHYSICS_DRIFT, persistence=persistence)
        second = persistence.load_profile(actor, "education")[
            "learning_state"]["spectral_advisories"]

        same_band = [
            a for a in second
            if a["signal"] == "valence" and a["band"] == "dc_drift"
        ]
        assert len(same_band) == 1, (
            f"expected exactly one (valence,dc_drift) advisory after replay; "
            f"got {len(same_band)}: {same_band}"
        )
        # Replacement => new advisory_id.
        assert same_band[0]["advisory_id"] != first_id

