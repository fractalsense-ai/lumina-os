"""Phase H.7 — Generic daemon-task integration test.

Validates that ``rhythm_fft_analysis`` is fully signal-name-agnostic:
the test synthesizes an ad-hoc "lab" domain (not assistant, not
education, not agriculture) with arbitrary signal names, custom
``record_path`` extractors, custom band sets, per-signal
``message_overrides``, and per-signal ``advisory_priority`` /
``advisory_ttl_seconds``. The daemon must run end-to-end against this
synthetic domain with no special-casing.

This test exists to prevent regression to the SVA-specific assumptions
the daemon used to carry. It complements
``test_signals_agriculture_poc.py`` (which exercises a real domain
pack) by running the same wiring against a physics block constructed
inline, with no agriculture-pack files involved.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any

from lumina.daemon.tasks import get_task
from lumina.signals import update_spectral_history


# ── Mock persistence ─────────────────────────────────────────


class _MockPersistence:
    def __init__(self, profiles: dict[str, dict], records: list[dict]):
        self._profiles = profiles
        self._records = records

    def list_users(self):
        return [{"user_id": uid} for uid in self._profiles]

    def list_profiles(self, user_id):
        return list(self._profiles.get(user_id, {}).keys())

    def load_profile(self, user_id, domain_key):
        return self._profiles.get(user_id, {}).get(domain_key)

    def save_profile(self, user_id, domain_key, data):
        self._profiles.setdefault(user_id, {})[domain_key] = data

    def query_log_records(self, record_type=None, domain_id=None,
                          limit=100, **_kw):
        out = self._records
        if record_type:
            out = [r for r in out if r.get("record_type") == record_type]
        return out[:limit]


# ── Helpers ──────────────────────────────────────────────────


def _seed_history(stable_dc: float, runs: int = 8) -> dict[str, Any]:
    hist: dict[str, Any] = {}
    for i in range(runs):
        sig = {
            "dc_drift": stable_dc + (0.01 if i % 2 else -0.01),
            "circaseptan": 0.05,
            "noise_floor": 0.04,
            "dc_direction": 1 if stable_dc >= 0 else -1,
        }
        hist = update_spectral_history(hist, sig)
    return hist


def _trace(actor_id: str, ts: datetime, *, lab_signal: float) -> dict[str, Any]:
    """Generic lab record with a deeply nested record_path target."""
    return {
        "record_type": "TraceEvent",
        "actor_id": actor_id,
        "timestamp_utc": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "event_type": "lab_measurement",
        "metadata": {
            "lab": {
                "instruments": {
                    "spectrometer_alpha": {"reading": lab_signal},
                },
            },
        },
    }


def _build_drift_records(
    actor_id: str, *, baseline: float, drift_to: float,
) -> list[dict[str, Any]]:
    """60 days of records: 46 stable around `baseline`, then 14 days
    sliding linearly toward `drift_to`. 3 readings per day."""
    now = datetime(2026, 4, 30, 12, 0, 0, tzinfo=timezone.utc)
    out: list[dict[str, Any]] = []
    for d in range(60):
        ts = now - timedelta(days=59 - d)
        if d < 46:
            v = baseline + 0.05 * math.sin(2 * math.pi * d / 7.0)
        else:
            v = baseline + (drift_to - baseline) * (d - 45) / 14.0
        for hour in (0, 6, 12):
            out.append(_trace(actor_id, ts + timedelta(hours=hour),
                              lab_signal=v))
    return out


def _make_lab_physics(
    *, message_overrides: dict[str, str] | None = None,
    advisory_priority: int = 0,
    advisory_ttl_seconds: int | None = None,
) -> dict[str, Any]:
    sig_def: dict[str, Any] = {
        "label": "alpha-particle flux",
        "units": "counts/s",
        "range": [0.0, 1000.0],
        "record_path": "metadata.lab.instruments.spectrometer_alpha.reading",
        "advisory_priority": advisory_priority,
        "bands": {
            "dc_drift":    {"window_days": [10, 60]},
            "circaseptan": {"window_days": [5, 9]},
        },
    }
    if message_overrides is not None:
        sig_def["message_overrides"] = message_overrides
    if advisory_ttl_seconds is not None:
        sig_def["advisory_ttl_seconds"] = advisory_ttl_seconds
    return {
        "signals": {
            "alpha_flux": sig_def,
        },
    }


# ─────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────


class TestDaemonRhythmFFTGeneric:

    def test_arbitrary_signal_name_routes_through_daemon(self):
        """The daemon must accept a signal whose name is not in the
        legacy SVA axis set and whose record_path is deeply nested."""
        task = get_task("rhythm_fft_analysis")
        actor = "lab_subject_01"
        domain_key = "lab_research"
        profile = {
            "subject_id": actor,
            "learning_state": {
                "signal_baselines": {
                    "spectral_history": {
                        "alpha_flux": _seed_history(stable_dc=120.0),
                    },
                },
            },
        }
        persistence = _MockPersistence(
            {actor: {domain_key: profile}},
            _build_drift_records(actor, baseline=120.0, drift_to=60.0),
        )

        result = task(domain_key, _make_lab_physics(),
                      persistence=persistence)

        assert result.success, f"task failed: {result.error}"
        # The daemon iterated exactly the signal we declared
        assert result.metadata["signals_run"] == ["alpha_flux"]
        assert result.metadata["profiles_analyzed"] == 1

        # At least one chronic_spectral_drift proposal landed under our
        # arbitrary signal name (not "valence", not "soil_pH").
        chronic = [
            p for p in result.proposals
            if p.proposal_type == "chronic_spectral_drift"
            and p.detail.get("signal") == "alpha_flux"
        ]
        assert chronic, (
            "expected at least one chronic_spectral_drift proposal "
            "for the arbitrary signal name 'alpha_flux'")

    def test_persisted_advisory_uses_generic_default_template(self):
        """Without message_overrides, the framework's neutral default
        template must render — and substitute the signal label."""
        task = get_task("rhythm_fft_analysis")
        actor = "lab_subject_02"
        domain_key = "lab_research"
        profile = {
            "subject_id": actor,
            "learning_state": {
                "signal_baselines": {
                    "spectral_history": {
                        "alpha_flux": _seed_history(stable_dc=120.0),
                    },
                },
            },
        }
        persistence = _MockPersistence(
            {actor: {domain_key: profile}},
            _build_drift_records(actor, baseline=120.0, drift_to=60.0),
        )

        result = task(domain_key, _make_lab_physics(message_overrides=None),
                      persistence=persistence)
        assert result.success

        saved = persistence.load_profile(actor, domain_key)
        advisories = saved["learning_state"].get("spectral_advisories", [])
        assert advisories
        for adv in advisories:
            # No override → label must appear in framework default text
            assert "alpha-particle flux" in adv["message"], (
                f"label substitution missing in default template: "
                f"{adv['message']!r}")
            # Direction normalized to schema vocabulary
            assert adv["direction"] in ("positive", "negative", "neutral")

    def test_per_signal_message_override_is_honored(self):
        """An exact (band, direction) override must win over both
        framework defaults and band-wildcard overrides."""
        task = get_task("rhythm_fft_analysis")
        actor = "lab_subject_03"
        domain_key = "lab_research"
        profile = {
            "subject_id": actor,
            "learning_state": {
                "signal_baselines": {
                    "spectral_history": {
                        "alpha_flux": _seed_history(stable_dc=120.0),
                    },
                },
            },
        }
        persistence = _MockPersistence(
            {actor: {domain_key: profile}},
            _build_drift_records(actor, baseline=120.0, drift_to=60.0),
        )

        physics = _make_lab_physics(message_overrides={
            "circaseptan,*": "WILDCARD-MARKER on {label}",
            "dc_drift,negative": "EXACT-NEG-MARKER on {label}",
            "dc_drift,positive": "EXACT-POS-MARKER on {label}",
        })

        result = task(domain_key, physics, persistence=persistence)
        assert result.success

        saved = persistence.load_profile(actor, domain_key)
        advisories = saved["learning_state"].get("spectral_advisories", [])
        assert advisories

        # Every advisory carries the override marker for its band, and
        # the {label} placeholder is substituted.
        for adv in advisories:
            band = adv["band"]
            direction = adv["direction"]
            msg = adv["message"]
            assert "alpha-particle flux" in msg
            if band == "dc_drift" and direction == "negative":
                assert msg == "EXACT-NEG-MARKER on alpha-particle flux"
            elif band == "dc_drift" and direction == "positive":
                assert msg == "EXACT-POS-MARKER on alpha-particle flux"
            elif band == "circaseptan":
                assert "WILDCARD-MARKER" in msg, (
                    f"circaseptan wildcard override missed: {msg!r}")

    def test_per_signal_ttl_override_shortens_expiry(self):
        """``advisory_ttl_seconds`` on the signal definition must be
        honored at upsert time (not the framework default)."""
        task = get_task("rhythm_fft_analysis")
        actor = "lab_subject_04"
        domain_key = "lab_research"
        profile = {
            "subject_id": actor,
            "learning_state": {
                "signal_baselines": {
                    "spectral_history": {
                        "alpha_flux": _seed_history(stable_dc=120.0),
                    },
                },
            },
        }
        persistence = _MockPersistence(
            {actor: {domain_key: profile}},
            _build_drift_records(actor, baseline=120.0, drift_to=60.0),
        )

        # 1-hour TTL on this signal (default is 24h). Verify the
        # persisted advisory expires inside a 2-hour window.
        physics = _make_lab_physics(advisory_ttl_seconds=3600)

        result = task(domain_key, physics, persistence=persistence)
        assert result.success

        saved = persistence.load_profile(actor, domain_key)
        advisories = saved["learning_state"].get("spectral_advisories", [])
        assert advisories
        for adv in advisories:
            created = datetime.fromisoformat(adv["created_utc"])
            expires = datetime.fromisoformat(adv["expires_utc"])
            window = (expires - created).total_seconds()
            # Allow 1s of slack for serialization rounding
            assert 3500 <= window <= 3700, (
                f"expected ~1h TTL, got {window}s on {adv}")
