"""Journal domain step — cascading wellness intervention protocol.

Called by freeform_adapters.freeform_domain_step when journal evidence
(entity_mentions or sva_direct) is present in the evidence dict.

Tier architecture:
    Tier 1 — Single-turn arousal spike or valence drop.
              Action: offer a breathing/grounding exercise.
              No persistence beyond the module state counter.

    Tier 2 — Sustained elevation (N consecutive turns) or repeated
              relational concern signals.
              Action: ask the student whether they want to talk to a
              trusted adult (opt-in, never forced).

    Tier 3 — Cross-session pattern at a critical threshold AND
              a Safe Person has been designated and accepted the
              handshake.
              Action: create a wellness EscalationRecord and alert
              the Safe Person (or teacher as fallback).
              Evidence is AGGREGATE ONLY — no entity maps, no journal
              text, no entity hashes.

Privacy invariant (safe_person_escalation_aggregate_only):
    The evidence_summary sent in Tier 3 escalations MUST contain only:
        - sva_aggregate (mean/trend of SVA across affected sessions)
        - intervention_history (list of tier/count pairs)
        - sessions_affected (integer)
    Entity maps, entity hashes, and journal text are PROHIBITED.

Baseline warmup gate:
    During the first N sessions (configurable via
    ``baseline_warmup_sessions`` in domain_step_params), all intervention
    checks are suppressed.  The system silently builds an affect baseline
    before any tier can fire.  This prevents day-one false positives.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger("lumina-api.education.journal")

# ─────────────────────────────────────────────────────────────
# Default thresholds (overridden from domain-physics.json)
# ─────────────────────────────────────────────────────────────

_DEFAULT_THRESHOLDS: dict[str, Any] = {
    "tier1_arousal_spike": 0.35,
    "tier1_valence_drop": -0.30,
    "tier2_sustained_turns": 3,
    "tier2_relational_concern_turns": 2,
    "tier3_valence_floor": -0.60,
    "tier3_cross_session_count": 2,
    "baseline_warmup_sessions": 3,
}


# ─────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────


def journal_domain_step(
    state: dict[str, Any],
    task_spec: dict[str, Any],
    evidence: dict[str, Any],
    params: dict[str, Any] | None = None,
    profile_data: dict[str, Any] | None = None,
    persistence: Any | None = None,
    user_id: str | None = None,
    session_id: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run journal-specific SVA intervention logic.

    Args:
        state:        Current module state dict (mutated in-place).
        task_spec:    Domain task specification (not used here but kept for
                      signature parity with other domain steps).
        evidence:     Dict with ``entity_mentions`` and/or ``sva_direct``
                      from journal_nlp_pre_interpreter.
        params:       Domain step params (merged from domain-physics.json).
        profile_data: Actor profile dict (for Safe Person lookup).
        persistence:  Persistence adapter (for writing EscalationRecord).
        user_id:      Pseudonymous actor ID.
        session_id:   Current session UUID.

    Returns:
        ``(updated_state, decision)``

        ``decision`` keys:
            tier:    "ok" | "tier1" | "tier2" | "tier3"
            action:  None | action string for runtime dispatcher
            message: Optional human-readable note (not shown to student)
    """
    p = params or {}
    thresholds = {**_DEFAULT_THRESHOLDS, **dict(p.get("journal_intervention_thresholds") or {})}

    sva = dict(evidence.get("sva_direct") or {})
    entity_mentions = dict(evidence.get("entity_mentions") or {})

    valence = float(sva.get("valence", 0.0))
    arousal = float(sva.get("arousal", 0.0))
    salience = float(sva.get("salience", 0.0))

    # ── Accumulate entity signals into state ─────────────────
    state_entity_mentions: dict[str, Any] = dict(state.get("entity_mentions") or {})
    for h, signals in entity_mentions.items():
        if h not in state_entity_mentions:
            state_entity_mentions[h] = dict(signals)
            state_entity_mentions[h]["turn_count"] = 1
        else:
            prev = state_entity_mentions[h]
            n = prev.get("turn_count", 1) + 1
            prev["valence_delta"] = (prev.get("valence_delta", 0.0) * (n - 1) + float(signals.get("valence_delta", 0.0))) / n
            prev["arousal_delta"] = (prev.get("arousal_delta", 0.0) * (n - 1) + float(signals.get("arousal_delta", 0.0))) / n
            prev["turn_count"] = n
    state["entity_mentions"] = state_entity_mentions

    # ── Baseline warmup gate ──────────────────────────────────
    warmup_sessions = int(thresholds["baseline_warmup_sessions"])
    vocab = state.get("vocabulary_tracking") or {}
    baseline_sessions_remaining = int(
        vocab.get("baseline_sessions_remaining", warmup_sessions)
    )
    if baseline_sessions_remaining > 0:
        return state, {"tier": "ok", "action": None, "message": "warmup_gate_active"}

    # ── Tier 1 — single-turn spike ────────────────────────────
    tier1_arousal_spike = float(thresholds["tier1_arousal_spike"])
    tier1_valence_drop = float(thresholds["tier1_valence_drop"])

    is_tier1 = arousal > tier1_arousal_spike or valence < tier1_valence_drop

    if is_tier1:
        state["sustained_elevation_count"] = int(state.get("sustained_elevation_count", 0)) + 1
        state["tier1_triggered_count"] = int(state.get("tier1_triggered_count", 0)) + 1
    else:
        # Reset sustained counter when no spike this turn
        state["sustained_elevation_count"] = 0

    # Count relational concerns (entities with negative valence delta)
    relational_concern_count = sum(
        1 for sig in state_entity_mentions.values()
        if float(sig.get("valence_delta", 0.0)) < tier1_valence_drop
    )

    # ── Tier 2 — sustained elevation ─────────────────────────
    tier2_sustained = int(thresholds["tier2_sustained_turns"])
    tier2_relational = int(thresholds["tier2_relational_concern_turns"])
    sustained = int(state.get("sustained_elevation_count", 0))
    tier2_opt_in_pending = bool(state.get("tier2_opt_in_pending", False))

    is_tier2 = (
        not tier2_opt_in_pending
        and (sustained >= tier2_sustained or relational_concern_count >= tier2_relational)
    )

    # ── Tier 3 — cross-session critical ──────────────────────
    tier3_valence_floor = float(thresholds["tier3_valence_floor"])
    tier3_cross_session_count = int(thresholds["tier3_cross_session_count"])
    cross_session_count = int(state.get("cross_session_elevation_count", 0))
    safe_person_alerted = bool(state.get("safe_person_alerted", False))

    _assigned_safe_person_id: str | None = None
    _safe_person_handshake_accepted = False
    if profile_data:
        _assigned_safe_person_id = profile_data.get("assigned_safe_person_id")
        _safe_person_handshake_accepted = bool(profile_data.get("safe_person_handshake_accepted", False))

    is_tier3 = (
        not safe_person_alerted
        and valence < tier3_valence_floor
        and cross_session_count >= tier3_cross_session_count
        and bool(_assigned_safe_person_id)
        and _safe_person_handshake_accepted
    )

    # ── Decision cascade ──────────────────────────────────────
    if is_tier3:
        state["safe_person_alerted"] = True
        _create_wellness_escalation(
            state=state,
            valence=valence,
            arousal=arousal,
            salience=salience,
            cross_session_count=cross_session_count,
            assigned_safe_person_id=_assigned_safe_person_id,
            persistence=persistence,
            user_id=user_id,
            session_id=session_id,
        )
        return state, {
            "tier": "tier3",
            "action": "journal_tier3_safe_person_alert",
            "message": "tier3_wellness_escalation_created",
        }

    if is_tier2:
        state["tier2_opt_in_pending"] = True
        return state, {
            "tier": "tier2",
            "action": "journal_tier2_opt_in_ask",
            "message": "tier2_sustained_elevation_ask",
        }

    if is_tier1:
        return state, {
            "tier": "tier1",
            "action": "journal_tier1_breathing",
            "message": "tier1_arousal_spike_or_valence_drop",
        }

    return state, {"tier": "ok", "action": None, "message": None}


# ─────────────────────────────────────────────────────────────
# Tier 3 escalation record creation
# ─────────────────────────────────────────────────────────────


def _create_wellness_escalation(
    *,
    state: dict[str, Any],
    valence: float,
    arousal: float,
    salience: float,
    cross_session_count: int,
    assigned_safe_person_id: str | None,
    persistence: Any | None,
    user_id: str | None,
    session_id: str | None,
) -> None:
    """Write a wellness_critical EscalationRecord.

    PRIVACY INVARIANT: evidence_summary contains ONLY aggregate statistics.
    No entity maps, entity hashes, or journal text are included.
    """
    if persistence is None:
        log.warning("[JOURNAL] Tier 3 triggered but no persistence adapter — escalation not written")
        return

    # Aggregate intervention history (no entity-level data)
    intervention_history = [
        {"tier": "tier1", "count": int(state.get("tier1_triggered_count", 0))},
        {"tier": "tier2", "count": 1 if state.get("tier2_opt_in_pending") else 0},
    ]

    evidence_summary: dict[str, Any] = {
        "sva_aggregate": {
            "valence": round(valence, 4),
            "arousal": round(arousal, 4),
            "salience": round(salience, 4),
        },
        "intervention_history": intervention_history,
        "sessions_affected": cross_session_count,
        # Explicitly absent: entity_map, entity_mentions, journal_text
    }

    target_id = assigned_safe_person_id or (
        f"teacher_fallback_{user_id}" if user_id else "teacher_fallback"
    )

    record: dict[str, Any] = {
        "record_type": "EscalationRecord",
        "record_id": str(uuid.uuid4()),
        "prev_record_hash": "genesis",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "session_id": session_id or str(uuid.uuid4()),
        "subject_id": user_id,
        "escalating_actor_id": "journal_domain_step",
        "target_meta_authority_id": target_id,
        "trigger": "Sustained wellness signal detected across sessions during journaling",
        "trigger_type": "wellness_critical",
        "trigger_standing_order_id": "journal_tier3_protocol",
        "trigger_invariant_id": None,
        "domain_pack_id": "domain/edu/general-education/v1",
        "domain_pack_version": "0.2.0",
        "evidence_summary": evidence_summary,
        "decision_trail_hashes": [],
        "proposed_action": "Please check in with this student — they may benefit from support.",
        "resolution_commitment_id": None,
        "status": "pending",
        "sla_deadline_utc": None,
        "metadata": {},
    }

    try:
        if session_id:
            persistence.append_log_record(
                session_id,
                record,
                ledger_path=persistence.get_system_ledger_path(session_id),
            )
            log.info("[JOURNAL] Tier 3 wellness escalation written for user=%s", user_id)
        else:
            log.warning("[JOURNAL] No session_id — escalation record not written")
    except Exception:
        log.exception("[JOURNAL] Failed to write Tier 3 escalation record")


# ─────────────────────────────────────────────────────────────
# Tool adapter: breathing regulation
# ─────────────────────────────────────────────────────────────


def breathing_regulation_tool(params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return a structured box-breathing exercise for Tier 1 delivery.

    The exercise is deterministic and returns structured data so the
    frontend can render it as a guided interactive card rather than
    plain text.
    """
    return {
        "ok": True,
        "technique": "box_breathing",
        "steps": [
            {"phase": "inhale",     "duration_seconds": 4, "cue": "Breathe in slowly through your nose"},
            {"phase": "hold",       "duration_seconds": 4, "cue": "Hold gently"},
            {"phase": "exhale",     "duration_seconds": 4, "cue": "Breathe out slowly through your mouth"},
            {"phase": "hold_empty", "duration_seconds": 4, "cue": "Rest before the next breath"},
        ],
        "cycles": 4,
        "duration_seconds": 128,
        "framing": "optional",
        "offer_text": "I noticed you might be carrying something heavy right now. Would you like to take a short breathing moment? It only takes 2 minutes.",
    }
