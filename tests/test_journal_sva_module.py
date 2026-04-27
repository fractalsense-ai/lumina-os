"""Tests for SVA-gated journaling — entity hashing, relational baseline EWMA,
wellness tier thresholds, and escalation routing.

Privacy guarantee under test:
    Entity names must NEVER appear in any output from extract_journal_evidence().
    Only opaque hashes (Entity_XXXX) are permitted.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

# ── sys.path setup ────────────────────────────────────────────────────────
# model-packs uses a hyphenated directory name, so it is NOT a Python
# package root.  We add each relevant directory to sys.path directly.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_CTRL_DIR   = _REPO_ROOT / "model-packs" / "education" / "controllers"
_ASST_LIB   = _REPO_ROOT / "model-packs" / "assistant" / "domain-lib"

for _p in (_CTRL_DIR, _ASST_LIB):
    _sp = str(_p)
    if _sp not in sys.path:
        sys.path.insert(0, _sp)


# ── Helpers ───────────────────────────────────────────────────────────────

def _hash_entity(raw_name: str, salt: str) -> str:
    """Mirror the hash function in journal_nlp_pre_interpreter."""
    digest = hashlib.sha256((salt + raw_name.lower()).encode()).hexdigest()[:4].upper()
    return f"Entity_{digest}"


# ── journal_nlp_pre_interpreter ───────────────────────────────────────────


class TestEntityHashing:
    def test_deterministic_same_salt(self):
        from journal_nlp_pre_interpreter import (
            _hash_entity,
        )
        salt = "abc123"
        assert _hash_entity("Alice", salt) == _hash_entity("Alice", salt)

    def test_case_insensitive(self):
        from journal_nlp_pre_interpreter import (
            _hash_entity,
        )
        salt = "abc123"
        assert _hash_entity("alice", salt) == _hash_entity("ALICE", salt)

    def test_different_salts_different_hashes(self):
        from journal_nlp_pre_interpreter import (
            _hash_entity,
        )
        h1 = _hash_entity("Alice", "salt_a")
        h2 = _hash_entity("Alice", "salt_b")
        assert h1 != h2

    def test_different_entities_different_hashes(self):
        from journal_nlp_pre_interpreter import (
            _hash_entity,
        )
        salt = "fixed_salt"
        assert _hash_entity("Alice", salt) != _hash_entity("Bob", salt)

    def test_hash_format(self):
        from journal_nlp_pre_interpreter import (
            _hash_entity,
        )
        h = _hash_entity("Charlie", "mysalt")
        assert h.startswith("Entity_")
        suffix = h[len("Entity_"):]
        assert len(suffix) == 4
        assert suffix.isupper()

    def test_entity_name_absent_from_output(self):
        from journal_nlp_pre_interpreter import (
            extract_journal_evidence,
        )
        result = extract_journal_evidence(
            "Alice told me she was really upset today.", "mysalt", {}
        )
        result_str = str(result)
        assert "Alice" not in result_str
        assert "alice" not in result_str

    def test_entity_name_absent_multiple_entities(self):
        from journal_nlp_pre_interpreter import (
            extract_journal_evidence,
        )
        text = "Bob and Carol had a big argument. Dave tried to help."
        result = extract_journal_evidence(text, "s33d", {})
        result_str = str(result).lower()
        for name in ["bob", "carol", "dave"]:
            assert name not in result_str


class TestExtractJournalEvidence:
    def test_returns_required_keys(self):
        from journal_nlp_pre_interpreter import (
            extract_journal_evidence,
        )
        result = extract_journal_evidence("Hello world.", "salt", {})
        assert "entity_mentions" in result
        assert "sva_direct" in result
        assert "entity_count" in result

    def test_sva_direct_keys(self):
        from journal_nlp_pre_interpreter import (
            extract_journal_evidence,
        )
        sva = extract_journal_evidence("test", "s", {})["sva_direct"]
        assert "salience" in sva
        assert "valence" in sva
        assert "arousal" in sva

    def test_salience_capped_at_one(self):
        from journal_nlp_pre_interpreter import (
            extract_journal_evidence,
        )
        very_long = " ".join(["word"] * 200)
        result = extract_journal_evidence(very_long, "x", {})
        assert result["sva_direct"]["salience"] <= 1.0

    def test_arousal_elevated_with_caps_and_punct(self):
        from journal_nlp_pre_interpreter import (
            extract_journal_evidence,
        )
        calm = extract_journal_evidence("today was nice", "x", {})
        excited = extract_journal_evidence("I HATE THIS!!! IT IS SO UNFAIR!!!", "x", {})
        assert excited["sva_direct"]["arousal"] > calm["sva_direct"]["arousal"]

    def test_valence_negative_for_distress_words(self):
        from journal_nlp_pre_interpreter import (
            extract_journal_evidence,
        )
        result = extract_journal_evidence("I am sad and angry and hate everything", "x", {})
        assert result["sva_direct"]["valence"] < 0

    def test_valence_positive_for_happy_words(self):
        from journal_nlp_pre_interpreter import (
            extract_journal_evidence,
        )
        result = extract_journal_evidence("I am happy and grateful and love my friends", "x", {})
        assert result["sva_direct"]["valence"] > 0

    def test_empty_entity_mentions_when_no_entities(self):
        from journal_nlp_pre_interpreter import (
            extract_journal_evidence,
        )
        result = extract_journal_evidence("the cat sat on the mat", "x", {})
        # No capitalised proper nouns → likely no entities
        assert isinstance(result["entity_mentions"], dict)

    def test_entity_mention_structure(self):
        from journal_nlp_pre_interpreter import (
            extract_journal_evidence,
        )
        result = extract_journal_evidence("Jordan was really mean today", "x", {})
        for key, val in result["entity_mentions"].items():
            assert key.startswith("Entity_")
            assert "valence_delta" in val
            assert "arousal_delta" in val


# ── affect_monitor.update_relational_baseline ────────────────────────────


class TestRelationalBaseline:
    def _global_baseline(self, valence=0.0, arousal=0.3):
        from affect_monitor import AffectBaseline

        return AffectBaseline(valence=valence, arousal=arousal, salience=0.5)

    def test_new_entity_seeded_from_global(self):
        from affect_monitor import (
            update_relational_baseline,
        )

        global_bl = self._global_baseline(valence=0.1, arousal=0.4)
        result = update_relational_baseline(
            relational_baseline={},
            entity_hash="Entity_AB12",
            valence_delta=0.0,
            arousal_delta=0.0,
            salience_delta=0.1,
            params={},
            global_baseline=global_bl,
        )
        entry = result["Entity_AB12"]
        assert abs(entry["valence"] - 0.1) < 0.01
        assert abs(entry["arousal"] - 0.4) < 0.01

    def test_new_entity_not_seeded_at_zero(self):
        from affect_monitor import (
            update_relational_baseline,
        )

        global_bl = self._global_baseline(valence=0.5, arousal=0.6)
        result = update_relational_baseline(
            relational_baseline={},
            entity_hash="Entity_CD34",
            valence_delta=0.0,
            arousal_delta=0.0,
            salience_delta=0.1,
            params={},
            global_baseline=global_bl,
        )
        entry = result["Entity_CD34"]
        # Should be seeded from global, not zero
        assert entry["valence"] != 0.0 or global_bl.valence == 0.0

    def test_ewma_convergence(self):
        from affect_monitor import (
            update_relational_baseline,
        )

        global_bl = self._global_baseline(valence=0.0, arousal=0.3)
        rb: dict[str, Any] = {}
        target_valence = -0.8
        for _ in range(100):
            rb = update_relational_baseline(
                relational_baseline=rb,
                entity_hash="Entity_EE00",
                valence_delta=target_valence,
                arousal_delta=0.5,
                salience_delta=0.1,
                params={},
                global_baseline=global_bl,
            )
        # After many updates, should approach target
        assert rb["Entity_EE00"]["valence"] < -0.5

    def test_per_entity_independent_tracking(self):
        from affect_monitor import (
            update_relational_baseline,
        )

        global_bl = self._global_baseline()
        rb: dict[str, Any] = {}
        rb = update_relational_baseline(rb, "Entity_AA00", 0.8, 0.2, 0.1, {}, global_bl)
        rb = update_relational_baseline(rb, "Entity_BB00", -0.8, 0.9, 0.1, {}, global_bl)
        assert rb["Entity_AA00"]["valence"] != rb["Entity_BB00"]["valence"]

    def test_sample_count_increments(self):
        from affect_monitor import (
            update_relational_baseline,
        )

        global_bl = self._global_baseline()
        rb: dict[str, Any] = {}
        for _ in range(5):
            rb = update_relational_baseline(rb, "Entity_CC00", 0.1, 0.1, 0.1, {}, global_bl)
        assert rb["Entity_CC00"]["sample_count"] == 5

    def test_existing_baseline_updated_by_ewma(self):
        from affect_monitor import (
            update_relational_baseline,
        )

        global_bl = self._global_baseline(valence=0.0, arousal=0.3)
        rb = {"Entity_DD00": {"valence": 0.0, "arousal": 0.3, "salience": 0.5, "sample_count": 10, "last_updated_utc": None}}
        rb = update_relational_baseline(rb, "Entity_DD00", 1.0, 1.0, 1.0, {}, global_bl)
        # EWMA alpha=0.1 → valence = 0.1 * 1.0 + 0.9 * 0.0 = 0.1
        assert abs(rb["Entity_DD00"]["valence"] - 0.1) < 0.02


# ── journal_adapters — tier thresholds ───────────────────────────────────


def _make_state(
    sustained=0, cross_session=0, tier1_count=0, t2_pending=False, sp_alerted=False
):
    return {
        "sustained_elevation_count": sustained,
        "cross_session_elevation_count": cross_session,
        "tier1_triggered_count": tier1_count,
        "tier2_opt_in_pending": t2_pending,
        "safe_person_alerted": sp_alerted,
        "entity_mentions": {},
        "vocabulary_tracking": {"baseline_sessions_remaining": 0},
    }


def _make_evidence(valence=0.0, arousal=0.0, entity_count=0, entity_mentions=None):
    return {
        "sva_direct": {"salience": 0.5, "valence": valence, "arousal": arousal},
        "entity_mentions": entity_mentions or {},
        "entity_count": entity_count,
    }


class TestJournalAdaptersTier1:
    def test_tier1_fires_on_arousal_spike(self):
        from journal_adapters import journal_domain_step

        state = _make_state()
        evidence = _make_evidence(arousal=0.4, valence=0.0)
        _, decision = journal_domain_step(state, {}, evidence, {})
        assert decision["tier"] == "tier1"
        assert decision["action"] == "journal_tier1_breathing"

    def test_tier1_fires_on_valence_drop(self):
        from journal_adapters import journal_domain_step

        state = _make_state()
        evidence = _make_evidence(valence=-0.35, arousal=0.0)
        _, decision = journal_domain_step(state, {}, evidence, {})
        assert decision["tier"] == "tier1"

    def test_tier1_does_not_fire_below_threshold(self):
        from journal_adapters import journal_domain_step

        state = _make_state()
        evidence = _make_evidence(arousal=0.30, valence=-0.25)
        _, decision = journal_domain_step(state, {}, evidence, {})
        assert decision["tier"] in ("ok", "warmup")

    def test_tier1_increments_sustained_elevation_count(self):
        from journal_adapters import journal_domain_step

        state = _make_state(sustained=1)
        evidence = _make_evidence(arousal=0.5, valence=0.0)
        new_state, _ = journal_domain_step(state, {}, evidence, {})
        assert new_state["sustained_elevation_count"] == 2


class TestJournalAdaptersTier2:
    def test_tier2_fires_after_sustained_turns(self):
        from journal_adapters import journal_domain_step

        # sustained_elevation_count already at 3 with another arousal spike
        state = _make_state(sustained=3)
        evidence = _make_evidence(arousal=0.4)
        _, decision = journal_domain_step(state, {}, evidence, {})
        assert decision["tier"] == "tier2"
        assert decision["action"] == "journal_tier2_opt_in_ask"

    def test_tier2_not_repeated_when_already_pending(self):
        from journal_adapters import journal_domain_step

        state = _make_state(sustained=3, t2_pending=True)
        evidence = _make_evidence(arousal=0.4)
        _, decision = journal_domain_step(state, {}, evidence, {})
        # Should fire tier1 at most, not another tier2
        assert decision["tier"] != "tier2"

    def test_tier2_sets_opt_in_pending_flag(self):
        from journal_adapters import journal_domain_step

        state = _make_state(sustained=3)
        evidence = _make_evidence(arousal=0.4)
        new_state, _ = journal_domain_step(state, {}, evidence, {})
        assert new_state["tier2_opt_in_pending"] is True


class TestJournalAdaptersTier3:
    def _make_t3_state(self):
        s = _make_state(sustained=3, cross_session=2, t2_pending=True)
        s["safe_person_alerted"] = False
        return s

    def test_tier3_fires_with_all_conditions_met(self):
        from journal_adapters import journal_domain_step

        state = self._make_t3_state()
        evidence = _make_evidence(valence=-0.65, arousal=0.5)
        profile = {
            "assigned_safe_person_id": "sp_user_01",
            "safe_person_handshake_accepted": True,
        }
        _, decision = journal_domain_step(
            state, {}, evidence, {}, profile_data=profile, persistence=MagicMock()
        )
        assert decision["tier"] == "tier3"
        assert decision["action"] == "journal_tier3_safe_person_alert"

    def test_tier3_does_not_fire_without_safe_person(self):
        from journal_adapters import journal_domain_step

        state = self._make_t3_state()
        evidence = _make_evidence(valence=-0.65, arousal=0.5)
        _, decision = journal_domain_step(
            state, {}, evidence, {}, profile_data={}, persistence=MagicMock()
        )
        assert decision["tier"] != "tier3"

    def test_tier3_does_not_fire_without_handshake(self):
        from journal_adapters import journal_domain_step

        state = self._make_t3_state()
        evidence = _make_evidence(valence=-0.65, arousal=0.5)
        profile = {"assigned_safe_person_id": "sp_user_01", "safe_person_handshake_accepted": False}
        _, decision = journal_domain_step(
            state, {}, evidence, {}, profile_data=profile, persistence=MagicMock()
        )
        assert decision["tier"] != "tier3"

    def test_tier3_not_repeated_when_already_alerted(self):
        from journal_adapters import journal_domain_step

        state = self._make_t3_state()
        state["safe_person_alerted"] = True
        evidence = _make_evidence(valence=-0.65, arousal=0.5)
        profile = {"assigned_safe_person_id": "sp_user_01", "safe_person_handshake_accepted": True}
        _, decision = journal_domain_step(
            state, {}, evidence, {}, profile_data=profile, persistence=MagicMock()
        )
        assert decision["tier"] != "tier3"

    def test_tier3_sets_safe_person_alerted_flag(self):
        from journal_adapters import journal_domain_step

        state = self._make_t3_state()
        evidence = _make_evidence(valence=-0.65, arousal=0.5)
        profile = {"assigned_safe_person_id": "sp_01", "safe_person_handshake_accepted": True}
        new_state, _ = journal_domain_step(
            state, {}, evidence, {}, profile_data=profile, persistence=MagicMock()
        )
        assert new_state["safe_person_alerted"] is True

    def test_tier3_escalation_uses_wellness_critical_trigger(self):
        from journal_adapters import journal_domain_step

        state = self._make_t3_state()
        evidence = _make_evidence(valence=-0.65, arousal=0.5)
        profile = {"assigned_safe_person_id": "sp_01", "safe_person_handshake_accepted": True}
        mock_persistence = MagicMock()
        journal_domain_step(
            state, {}, evidence, {},
            profile_data=profile,
            persistence=mock_persistence,
            user_id="student_xyz",
            session_id="ses_001",
        )
        calls = mock_persistence.append_log_record.call_args_list
        assert len(calls) >= 1
        _, kwargs = calls[0]
        written_record = calls[0][0][1] if calls[0][0] else calls[0][1].get("record", {})
        # Flatten all call args to check trigger
        all_args_str = str(mock_persistence.append_log_record.call_args_list)
        assert "wellness_critical" in all_args_str

    def test_tier3_escalation_excludes_entity_map(self):
        """CRITICAL: No entity map, hashes, or text in escalation evidence."""
        from journal_adapters import journal_domain_step

        state = self._make_t3_state()
        state["entity_mentions"] = {"Entity_AB12": {"valence_delta": -0.5, "arousal_delta": 0.6}}
        evidence = _make_evidence(
            valence=-0.65, arousal=0.5,
            entity_mentions={"Entity_AB12": {"valence_delta": -0.5, "arousal_delta": 0.6}},
        )
        profile = {"assigned_safe_person_id": "sp_01", "safe_person_handshake_accepted": True}
        mock_persistence = MagicMock()
        journal_domain_step(
            state, {}, evidence, {},
            profile_data=profile,
            persistence=mock_persistence,
            user_id="student_xyz",
            session_id="ses_001",
        )
        all_args_str = str(mock_persistence.append_log_record.call_args_list)
        assert "entity_mentions" not in all_args_str
        assert "Entity_" not in all_args_str


class TestBaselineWarmupGate:
    def test_warmup_suppresses_tier1(self):
        from journal_adapters import journal_domain_step

        state = _make_state()
        state["vocabulary_tracking"] = {"baseline_sessions_remaining": 2}
        evidence = _make_evidence(arousal=0.9, valence=-0.9)
        _, decision = journal_domain_step(state, {}, evidence, {})
        assert decision.get("action") is None or decision["tier"] in ("ok", "warmup")

    def test_warmup_zero_allows_tier1(self):
        from journal_adapters import journal_domain_step

        state = _make_state()
        state["vocabulary_tracking"] = {"baseline_sessions_remaining": 0}
        evidence = _make_evidence(arousal=0.9)
        _, decision = journal_domain_step(state, {}, evidence, {})
        assert decision["tier"] == "tier1"


class TestBreathingRegulationTool:
    def test_returns_box_breathing_structure(self):
        from journal_adapters import (
            breathing_regulation_tool,
        )

        result = breathing_regulation_tool({})
        assert result.get("ok") is True
        assert "steps" in result
        assert len(result["steps"]) > 0

    def test_has_four_phases(self):
        from journal_adapters import (
            breathing_regulation_tool,
        )

        result = breathing_regulation_tool({})
        phase_types = {s.get("phase") for s in result["steps"]}
        # Should have inhale, hold, exhale at minimum
        assert phase_types >= {"inhale", "hold", "exhale"}

    def test_duration_field_present(self):
        from journal_adapters import (
            breathing_regulation_tool,
        )

        result = breathing_regulation_tool({})
        assert "duration_seconds" in result
        assert result["duration_seconds"] > 0


class TestFreeformAdapterDelegation:
    """Integration: freeform_domain_step should delegate to journal_adapters."""

    def test_delegates_when_entity_mentions_present(self):
        from freeform_adapters import (
            freeform_domain_step,
        )

        state = _make_state()
        evidence = _make_evidence(
            arousal=0.5,
            entity_mentions={"Entity_AB12": {"valence_delta": -0.4, "arousal_delta": 0.5}},
        )
        _, decision = freeform_domain_step(state, {}, evidence, {})
        # Journal delegation should have fired
        assert decision.get("tier") in ("tier1", "tier2", "tier3", "ok", "warmup")

    def test_delegates_when_sva_direct_present(self):
        from freeform_adapters import (
            freeform_domain_step,
        )

        state = _make_state()
        evidence = {
            "sva_direct": {"salience": 0.5, "valence": -0.4, "arousal": 0.45},
            "entity_mentions": {},
            "entity_count": 0,
        }
        _, decision = freeform_domain_step(state, {}, evidence, {})
        assert "tier" in decision

    def test_no_delegation_without_journal_evidence(self):
        from freeform_adapters import (
            freeform_domain_step,
        )

        state = {"vocabulary_tracking": {"baseline_sessions_remaining": 0}}
        evidence = {"intent_type": "conversational", "vocabulary_complexity_score": None}
        _, decision = freeform_domain_step(state, {}, evidence, {})
        assert decision["tier"] == "ok"
        assert "tier1" not in str(decision)


# ── Envelope (z-score) tracking tests ───────────────────────────────────


class TestEnvelopeTracking:
    """EWMA variance fields appear and grow with per-turn deltas."""

    def test_variance_fields_seeded_on_first_encounter(self):
        from affect_monitor import AffectBaseline, update_relational_baseline

        gb = AffectBaseline(valence=0.0, arousal=0.3, salience=0.5)
        rb = update_relational_baseline({}, "Entity_X", 0.1, 0.0, 0.1, {}, gb)
        entry = rb["Entity_X"]
        assert "valence_variance" in entry
        assert "arousal_variance" in entry
        assert "salience_variance" in entry
        # Seed default = 0.04
        assert abs(entry["valence_variance"] - 0.04) < 1e-6

    def test_variance_responds_to_volatile_residuals(self):
        from affect_monitor import AffectBaseline, update_relational_baseline

        gb = AffectBaseline(valence=0.0, arousal=0.3, salience=0.5)
        rb: dict[str, Any] = {}
        # Alternate large positive/negative valence deltas to inflate variance
        for delta in [0.6, -0.6, 0.6, -0.6, 0.6, -0.6]:
            rb = update_relational_baseline(rb, "Entity_V", delta, 0.0, 0.0, {}, gb)
        # Should grow well above seed
        assert rb["Entity_V"]["valence_variance"] > 0.10

    def test_variance_stable_for_quiet_actor(self):
        from affect_monitor import AffectBaseline, update_relational_baseline

        gb = AffectBaseline(valence=0.0, arousal=0.3, salience=0.5)
        rb: dict[str, Any] = {}
        # Tiny consistent deltas → variance should decay below seed
        for _ in range(20):
            rb = update_relational_baseline(rb, "Entity_Q", 0.01, 0.01, 0.01, {}, gb)
        assert rb["Entity_Q"]["valence_variance"] < 0.04

    def test_global_baseline_round_trips_variance(self):
        from affect_monitor import AffectBaseline

        bl = AffectBaseline(valence=0.1, valence_variance=0.07, arousal_variance=0.05)
        d = bl.to_dict()
        assert d["valence_variance"] == 0.07
        assert d["arousal_variance"] == 0.05
        roundtrip = AffectBaseline.from_dict(d)
        assert roundtrip.valence_variance == 0.07
        assert roundtrip.arousal_variance == 0.05


class TestZScoreGate:
    """check_relational_deviation triggers on z-score, not absolute thresholds."""

    def _mature_entry(self, valence=0.0, valence_var=0.04, sample_count=10):
        return {
            "valence": valence,
            "arousal": 0.5,
            "salience": 0.5,
            "valence_variance": valence_var,
            "arousal_variance": 0.04,
            "salience_variance": 0.04,
            "sample_count": sample_count,
        }

    def test_within_envelope_does_not_trigger(self):
        from affect_monitor import check_relational_deviation

        # Actor's valence baseline = -0.4, std = 0.2 (var = 0.04). Reading -0.45
        # is z=0.25 — well inside the 2σ envelope.
        entry = self._mature_entry(valence=-0.4, valence_var=0.04)
        result = check_relational_deviation(entry, valence=-0.45, arousal=0.5,
                                            salience=0.5, k_sigma=2.0)
        assert result["triggered"] is False
        assert result["mature"] is True
        assert result["reason"] == "within_envelope"

    def test_outside_envelope_triggers(self):
        from affect_monitor import check_relational_deviation

        # Same baseline, but valence drops to -0.85 → z=2.25 > 2.0
        entry = self._mature_entry(valence=-0.4, valence_var=0.04)
        result = check_relational_deviation(entry, valence=-0.85, arousal=0.5,
                                            salience=0.5, k_sigma=2.0)
        assert result["triggered"] is True
        assert result["axis"] == "valence"
        assert result["z_score"] > 2.0

    def test_picks_worst_axis(self):
        from affect_monitor import check_relational_deviation

        entry = self._mature_entry(valence=0.0, valence_var=0.04)
        entry["arousal"] = 0.3
        entry["arousal_variance"] = 0.01  # std=0.1
        # arousal jumps to 0.7 → z = 4.0; valence to -0.5 → z = 2.5
        result = check_relational_deviation(entry, valence=-0.5, arousal=0.7,
                                            salience=0.5, k_sigma=2.0)
        assert result["triggered"] is True
        assert result["axis"] == "arousal"

    def test_variance_floor_prevents_divide_by_zero(self):
        from affect_monitor import check_relational_deviation

        entry = self._mature_entry(valence=0.0, valence_var=0.0)
        # With min_variance_floor=0.001, sqrt=0.0316; tiny deltas still get
        # finite z-scores rather than infinity.
        result = check_relational_deviation(entry, valence=0.05, arousal=0.5,
                                            salience=0.5, k_sigma=2.0,
                                            min_variance_floor=0.001)
        assert result["mature"] is True
        # Should be finite
        assert result["z_score"] < 1e6


class TestWarmupFallback:
    """Below min_samples_for_zscore the absolute fallback governs Tier 1."""

    def test_immature_baseline_returns_immature(self):
        from affect_monitor import check_relational_deviation

        entry = {
            "valence": 0.0, "arousal": 0.5, "salience": 0.5,
            "valence_variance": 0.04, "arousal_variance": 0.04,
            "salience_variance": 0.04,
            "sample_count": 2,  # below default min_samples=5
        }
        result = check_relational_deviation(entry, valence=-0.9, arousal=0.9,
                                            salience=0.9, k_sigma=2.0,
                                            min_samples=5)
        assert result["triggered"] is False
        assert result["mature"] is False
        assert result["reason"] == "baseline_immature"

    def test_fallback_thresholds_drive_cold_start_tier1(self):
        from journal_adapters import journal_domain_step

        # No profile_data → no mature baseline anywhere → fallback path active.
        state = _make_state()
        evidence = _make_evidence(arousal=0.5, valence=0.0)
        _, decision = journal_domain_step(state, {}, evidence, {})
        assert decision["tier"] == "tier1"
        assert decision["message"] == "fallback_absolute_threshold"


class TestTier3EnvelopeFloor:
    """Tier 3 fires on z-score≥k_sigma_tier3 even when raw valence > legacy floor."""

    def test_envelope_tier3_fires_within_legacy_floor(self):
        from journal_adapters import journal_domain_step

        # Mature entity baseline: valence mean=-0.1, very tight variance.
        # Observed valence delta of -0.3 → obs ≈ -0.4, residual=-0.3, std=0.1
        # → z=3.0 → exceeds k_sigma_tier3=3.0 (use slightly worse delta to be safe).
        entity_hash = "Entity_TT00"
        relational_baseline = {
            entity_hash: {
                "valence": -0.1, "arousal": 0.4, "salience": 0.5,
                "valence_variance": 0.01, "arousal_variance": 0.04,
                "salience_variance": 0.04,
                "sample_count": 20,
            }
        }
        profile_data = {
            "learning_state": {"relational_baseline": relational_baseline},
            "assigned_safe_person_id": "sp_42",
            "safe_person_handshake_accepted": True,
        }
        # Cross-session count primed; SVA direct still > legacy -0.60 floor.
        state = _make_state(cross_session=2)
        evidence = _make_evidence(
            valence=-0.40, arousal=0.0,
            entity_mentions={entity_hash: {"valence_delta": -0.35, "arousal_delta": 0.0, "salience_delta": 0.0}},
        )
        _, decision = journal_domain_step(state, {}, evidence, {}, profile_data=profile_data)
        # Despite raw valence -0.40 being above the legacy -0.60 floor, the
        # envelope deviation should have escalated to Tier 3.
        assert decision["tier"] == "tier3", f"got {decision}"

# ── Phase F: Rhythm tracking & shape detection ──────────────────────────


class TestRhythmTracking:
    """crossing_rate and run_length update correctly under EWMA semantics."""

    def test_run_length_grows_on_sustained_drift(self):
        from affect_monitor import AffectBaseline, update_relational_baseline

        gb = AffectBaseline(valence=0.0, arousal=0.3, salience=0.5)
        rb: dict[str, Any] = {}
        # Five same-direction (positive) valence deltas above noise floor
        for _ in range(5):
            rb = update_relational_baseline(rb, "Entity_R", 0.2, 0.0, 0.0, {}, gb)
        entry = rb["Entity_R"]
        # First call seeds (run=+1), then 4 same-sign continuations → +5
        assert entry["valence_run_length"] == 5
        # crossing_rate decays toward 0 because no flips
        assert entry["valence_crossing_rate"] < 0.5

    def test_run_length_resets_on_flip(self):
        from affect_monitor import AffectBaseline, update_relational_baseline

        gb = AffectBaseline(valence=0.0, arousal=0.3, salience=0.5)
        rb: dict[str, Any] = {}
        for _ in range(3):
            rb = update_relational_baseline(rb, "Entity_F", 0.2, 0.0, 0.0, {}, gb)
        # Now flip sign
        rb = update_relational_baseline(rb, "Entity_F", -0.2, 0.0, 0.0, {}, gb)
        entry = rb["Entity_F"]
        assert entry["valence_run_length"] == -1

    def test_noise_floor_ignores_tiny_residuals(self):
        from affect_monitor import _update_rhythm

        # Tiny residual (below default 0.05 noise floor) → unchanged
        new_run, new_cr = _update_rhythm(
            residual=0.01, prev_run=4, prev_crossing_rate=0.2,
            alpha=0.1, noise_floor=0.05,
        )
        assert new_run == 4
        assert new_cr == 0.2

    def test_rhythm_round_trips_via_to_dict(self):
        from affect_monitor import AffectBaseline

        bl = AffectBaseline(
            valence=0.1,
            valence_crossing_rate=0.23,
            valence_run_length=7,
            arousal_crossing_rate=0.41,
            arousal_run_length=-3,
        )
        d = bl.to_dict()
        assert d["valence_crossing_rate"] == 0.23
        assert d["valence_run_length"] == 7
        assert d["arousal_run_length"] == -3
        rt = AffectBaseline.from_dict(d)
        assert rt.valence_crossing_rate == 0.23
        assert rt.valence_run_length == 7
        assert rt.arousal_run_length == -3


class TestShapeDeviation:
    """check_shape_deviation triggers on broken rhythm, not amplitude."""

    def test_alternating_actor_does_not_trigger(self):
        from affect_monitor import check_shape_deviation

        # Volatile actor: crossing_rate 0.5, currently mid-run length 2.
        # Threshold = 2.0 * 1/0.5 = 4.0 → run of 2 is normal.
        result = check_shape_deviation(
            crossing_rate=0.5, run_length=2, sample_count=20,
            k_shape=2.0,
        )
        assert result["triggered"] is False
        assert result["reason"] == "rhythm_normal"
        assert result["mature"] is True

    def test_sustained_drift_triggers(self):
        from affect_monitor import check_shape_deviation

        # Volatile actor (crossing_rate=0.5) with long run of 8
        # Threshold = 4.0 → run of 8 breaks rhythm
        result = check_shape_deviation(
            crossing_rate=0.5, run_length=8, sample_count=20,
            k_shape=2.0,
        )
        assert result["triggered"] is True
        assert result["direction"] == "positive"
        assert result["reason"] == "rhythm_broken"

    def test_negative_run_direction(self):
        from affect_monitor import check_shape_deviation

        result = check_shape_deviation(
            crossing_rate=0.5, run_length=-9, sample_count=20,
            k_shape=2.0,
        )
        assert result["triggered"] is True
        assert result["direction"] == "negative"

    def test_immature_baseline(self):
        from affect_monitor import check_shape_deviation

        result = check_shape_deviation(
            crossing_rate=0.3, run_length=20, sample_count=5,
            k_shape=2.0, min_samples=10,
        )
        assert result["triggered"] is False
        assert result["mature"] is False
        assert result["reason"] == "rhythm_immature"

    def test_min_crossing_rate_caps_threshold(self):
        from affect_monitor import check_shape_deviation

        # Actor has only ever drifted one way: crossing_rate=0.0
        # Without floor, threshold would be infinite. With min=0.05,
        # threshold = 2.0 * 1/0.05 = 40. Run of 50 still triggers.
        result = check_shape_deviation(
            crossing_rate=0.0, run_length=50, sample_count=60,
            k_shape=2.0, min_crossing_rate=0.05,
        )
        assert result["triggered"] is True
        # And run of 30 does not trigger (below 40)
        result2 = check_shape_deviation(
            crossing_rate=0.0, run_length=30, sample_count=60,
            k_shape=2.0, min_crossing_rate=0.05,
        )
        assert result2["triggered"] is False


class TestJournalAdaptersShape:
    """Shape check escalates Tier 1 when amplitude stays inside the envelope."""

    def test_sustained_drift_inside_envelope_fires_shape_tier1(self):
        from journal_adapters import journal_domain_step

        # Mature entity with flat crossing_rate (low) and long positive valence
        # run. Amplitude (valence_delta) is small → envelope check would NOT
        # fire. Shape check should catch it.
        entity_hash = "Entity_SHP1"
        relational_baseline = {
            entity_hash: {
                "valence": 0.0, "arousal": 0.4, "salience": 0.5,
                "valence_variance": 0.04, "arousal_variance": 0.04,
                "salience_variance": 0.04,
                "valence_crossing_rate": 0.1,
                "valence_run_length": 25,  # 25 > 2*1/0.1=20 → triggers
                "arousal_crossing_rate": 0.5,
                "salience_crossing_rate": 0.5,
                "arousal_run_length": 0,
                "salience_run_length": 0,
                "sample_count": 30,
            }
        }
        profile_data = {"learning_state": {"relational_baseline": relational_baseline}}
        state = _make_state()
        # Small valence delta → inside the envelope
        evidence = _make_evidence(
            valence=0.05, arousal=0.0,
            entity_mentions={entity_hash: {"valence_delta": 0.05, "arousal_delta": 0.0, "salience_delta": 0.0}},
        )
        _, decision = journal_domain_step(state, {}, evidence, {}, profile_data=profile_data)
        assert decision["tier"] == "tier1"
        assert decision["message"].startswith("entity_shape_valence_run")

    def test_normal_rhythm_no_tier1(self):
        from journal_adapters import journal_domain_step

        entity_hash = "Entity_SHP2"
        relational_baseline = {
            entity_hash: {
                "valence": 0.0, "arousal": 0.4, "salience": 0.5,
                "valence_variance": 0.04, "arousal_variance": 0.04,
                "salience_variance": 0.04,
                "valence_crossing_rate": 0.5,
                "valence_run_length": 2,
                "arousal_crossing_rate": 0.5,
                "salience_crossing_rate": 0.5,
                "arousal_run_length": 0,
                "salience_run_length": 0,
                "sample_count": 30,
            }
        }
        profile_data = {"learning_state": {"relational_baseline": relational_baseline}}
        state = _make_state()
        evidence = _make_evidence(
            valence=0.05, arousal=0.0,
            entity_mentions={entity_hash: {"valence_delta": 0.05, "arousal_delta": 0.0, "salience_delta": 0.0}},
        )
        _, decision = journal_domain_step(state, {}, evidence, {}, profile_data=profile_data)
        assert decision["tier"] == "ok"
