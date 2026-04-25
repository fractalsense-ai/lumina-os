"""Phase G.5 — chronic spectral advisory surface.

Validates ``journal_session_start`` (explicit session-init adapter) and
the first-turn piggyback path inside ``journal_domain_step``.  Both
project a stored ``profile.learning_state.spectral_advisories`` entry
into ``decision["advisory"]`` so the web banner can render it.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

# ── sys.path setup (domain-packs is hyphenated → not a Python package) ──
_REPO_ROOT = Path(__file__).resolve().parent.parent
_CTRL_DIR = _REPO_ROOT / "domain-packs" / "education" / "controllers"
if str(_CTRL_DIR) not in sys.path:
    sys.path.insert(0, str(_CTRL_DIR))

from journal_adapters import (  # noqa: E402
    journal_domain_step,
    journal_session_start,
)


# ── Helpers ─────────────────────────────────────────────────────────────


def _adv(
    *,
    signal: str = "valence",
    band: str = "dc_drift",
    direction: str = "negative",
    advisory_id: str = "adv-1",
    expires_in_seconds: float = 3600.0,
    message: str = "Heads-up message",
) -> dict:
    now = datetime.now(timezone.utc)
    return {
        "advisory_id": advisory_id,
        "signal": signal,
        "band": band,
        "direction": direction,
        "z_score": -3.0,
        "message": message,
        "created_utc": now.isoformat(),
        "expires_utc": (now + timedelta(seconds=expires_in_seconds)).isoformat(),
    }


def _profile(advisories: list[dict] | None) -> dict:
    return {
        "subject_id": "u1",
        "learning_state": {
            "spectral_advisories": list(advisories) if advisories is not None else [],
        },
    }


# ── journal_session_start ──────────────────────────────────────────────


class TestJournalSessionStart:
    def test_returns_active_advisory(self):
        prof = _profile([_adv(message="Things have felt heavier lately.")])
        state, decision = journal_session_start({}, profile_data=prof)
        assert decision["tier"] == "ok"
        assert decision["action"] is None
        assert decision["advisory"] is not None
        assert decision["advisory"]["signal"] == "valence"
        assert decision["advisory"]["band"] == "dc_drift"
        assert decision["advisory"]["message"] == "Things have felt heavier lately."
        assert state.get("session_advisory_surfaced") is True

    def test_no_advisory_returns_none(self):
        state, decision = journal_session_start({}, profile_data=_profile([]))
        assert decision["tier"] == "ok"
        assert decision["advisory"] is None
        assert "session_advisory_surfaced" not in state

    def test_expired_advisory_pruned(self):
        prof = _profile([_adv(expires_in_seconds=-60, advisory_id="old")])
        state, decision = journal_session_start({}, profile_data=prof)
        assert decision["advisory"] is None
        # Pruned out of the in-memory profile (best-effort even without persistence).
        # (Mutation only flushed via save_profile; here we check no surfacing.)
        assert "session_advisory_surfaced" not in state

    def test_priority_valence_outranks_arousal(self):
        prof = _profile([
            _adv(signal="arousal", band="dc_drift", advisory_id="ar"),
            _adv(signal="valence", band="ultradian", advisory_id="va"),
        ])
        _, decision = journal_session_start({}, profile_data=prof)
        # valence (signal priority 0) outranks arousal (priority 1) regardless
        # of band ordering.
        assert decision["advisory"]["signal"] == "valence"
        assert decision["advisory"]["advisory_id"] == "va"


# ── piggyback inside journal_domain_step ──────────────────────────────


class TestJournalDomainStepPiggyback:
    def test_first_turn_includes_advisory(self):
        prof = _profile([_adv(message="Notice slow downward shift.")])
        state = {"baseline_sessions_remaining": 0, "turn_count": 0}
        _, decision = journal_domain_step(
            state, {}, {}, {}, profile_data=prof,
        )
        assert decision.get("advisory") is not None
        assert decision["advisory"]["message"] == "Notice slow downward shift."
        assert state.get("session_advisory_surfaced") is True

    def test_subsequent_turn_does_not_re_surface(self):
        prof = _profile([_adv()])
        state = {
            "baseline_sessions_remaining": 0,
            "turn_count": 1,
            "session_advisory_surfaced": True,
        }
        _, decision = journal_domain_step(
            state, {}, {}, {}, profile_data=prof,
        )
        # Decision must not carry an advisory once the session has surfaced one.
        assert decision.get("advisory") is None
