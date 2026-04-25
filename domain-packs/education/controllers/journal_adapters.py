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
    # Z-score gates against the actor's learned envelope (per-entity and global).
    # k=2.0 → ~5% one-sided false-positive rate at steady state if residuals
    #         are roughly normal; k=3.0 → ~0.3%. Tuned against student data.
    "k_sigma_tier1": 2.0,
    "k_sigma_tier3": 3.0,
    "min_samples_for_zscore": 5,
    "min_variance_floor": 0.001,

    # Shape (rhythm) gates — Phase F heartbeat-shape detection. Catches
    # sustained one-direction drift INSIDE the amplitude envelope. k_shape
    # multiplies the actor's expected mean run length (1 / crossing_rate),
    # so the threshold auto-scales to each actor's natural oscillation.
    "k_shape_tier1": 2.0,
    "k_shape_tier3": 3.0,
    "min_samples_for_shape": 10,
    "min_crossing_rate": 0.05,

    # Cold-start fallback: used while baselines are still warming up
    # (sample_count < min_samples_for_zscore). Once envelope is mature these
    # constants no longer drive escalation — the actor's own oscillation
    # pattern does.
    "fallback_tier1_arousal_spike": 0.35,
    "fallback_tier1_valence_drop": -0.30,
    "fallback_tier3_valence_floor": -0.60,

    # Tier-2 / Tier-3 cross-window counters (independent of envelope check)
    "tier2_sustained_turns": 3,
    "tier2_relational_concern_turns": 2,
    "tier3_cross_session_count": 2,
    "baseline_warmup_sessions": 3,
}


# ─────────────────────────────────────────────────────────────
# Phase G.5 — chronic spectral advisory surface
# ─────────────────────────────────────────────────────────────
#
# The daemon task ``rhythm_fft_analysis`` writes advisory entries into
# ``profile.learning_state.spectral_advisories`` whenever it detects a
# chronic drift pattern. The journal session-start surface (and the
# first-turn piggyback path inside ``journal_domain_step``) reads those
# entries and projects them into ``decision["advisory"]`` so the web
# banner can render them. Each advisory carries its own TTL so the UI
# never has to call back to clear it.

# Priority order when multiple advisories are active simultaneously.
# Lower index = higher priority. Valence drift is the most clinically
# meaningful signal, and slow baseline shifts (dc_drift) outrank the
# rhythm bands.
_ADVISORY_AXIS_PRIORITY = ("valence", "arousal", "salience")
_ADVISORY_BAND_PRIORITY = ("dc_drift", "circaseptan", "ultradian")


def _pull_active_advisory(
    profile_data: dict[str, Any] | None,
    now_utc: datetime | None = None,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Return (highest-priority active advisory | None, pruned list).

    Filters expired entries and returns the surviving list so callers can
    persist the prune. Picks the highest-priority advisory by
    (axis, band) using the constants above. The decision payload exposes
    only the user-facing fields, never the raw daemon detail.
    """
    if not profile_data:
        return None, []
    ls = profile_data.get("learning_state") or {}
    raw = ls.get("spectral_advisories") or []
    if not isinstance(raw, list):
        return None, []

    now = now_utc or datetime.now(timezone.utc)
    surviving: list[dict[str, Any]] = []
    for adv in raw:
        if not isinstance(adv, dict):
            continue
        exp = adv.get("expires_utc")
        if isinstance(exp, str):
            try:
                if datetime.fromisoformat(exp) <= now:
                    continue
            except ValueError:
                continue
        surviving.append(adv)

    if not surviving:
        return None, surviving

    def _rank(a: dict[str, Any]) -> tuple[int, int]:
        axis = str(a.get("axis", ""))
        band = str(a.get("band", ""))
        ax_rank = (
            _ADVISORY_AXIS_PRIORITY.index(axis)
            if axis in _ADVISORY_AXIS_PRIORITY
            else len(_ADVISORY_AXIS_PRIORITY)
        )
        bd_rank = (
            _ADVISORY_BAND_PRIORITY.index(band)
            if band in _ADVISORY_BAND_PRIORITY
            else len(_ADVISORY_BAND_PRIORITY)
        )
        return (ax_rank, bd_rank)

    best = min(surviving, key=_rank)
    return best, surviving


def _advisory_for_decision(adv: dict[str, Any]) -> dict[str, Any]:
    """Project a stored advisory into the user-facing decision payload."""
    return {
        "advisory_id": adv.get("advisory_id"),
        "axis": adv.get("axis"),
        "band": adv.get("band"),
        "direction": adv.get("direction"),
        "message": adv.get("message"),
        "expires_utc": adv.get("expires_utc"),
    }


def journal_session_start(
    state: dict[str, Any],
    profile_data: dict[str, Any] | None = None,
    persistence: Any | None = None,
    user_id: str | None = None,
    session_id: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run journal session-start checks and surface any active chronic advisory.

    Returns ``(updated_state, decision)`` where ``decision`` always has
    ``tier == "ok"`` (chronic advisories never gate the journal — they are
    informational) and an ``advisory`` field that is either ``None`` or a
    user-facing advisory payload. Expired advisories are pruned from the
    profile as a side-effect.

    Mark the session as having surfaced an advisory (via
    ``state["session_advisory_surfaced"] = True``) so the per-turn
    piggyback path inside ``journal_domain_step`` does not re-surface it.
    """
    advisory, surviving = _pull_active_advisory(profile_data)

    # Persist the pruned list back to the profile so expired entries don't
    # accumulate. Best-effort — failure to save shouldn't block the session.
    if profile_data is not None and persistence is not None and user_id:
        save_profile = getattr(persistence, "save_profile", None)
        ls = profile_data.get("learning_state") or {}
        prior = ls.get("spectral_advisories") or []
        if save_profile and surviving != prior:
            ls["spectral_advisories"] = surviving
            profile_data["learning_state"] = ls
            try:
                save_profile(user_id, "journal", profile_data)
            except Exception as exc:  # pragma: no cover - defensive
                log.warning("journal_session_start: save_profile failed: %s", exc)

    decision: dict[str, Any] = {
        "tier": "ok",
        "action": None,
        "message": None,
        "advisory": _advisory_for_decision(advisory) if advisory else None,
    }
    if advisory is not None:
        state["session_advisory_surfaced"] = True
    return state, decision


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

    # ── Phase G.5 piggyback: surface chronic advisory once per session ──
    # If a session-start adapter has already surfaced the advisory, the
    # ``session_advisory_surfaced`` flag is set on state and we skip.
    # Otherwise the FIRST per-turn step of the session pulls it.
    piggyback_advisory: dict[str, Any] | None = None
    if profile_data and not state.get("session_advisory_surfaced"):
        adv, surviving = _pull_active_advisory(profile_data)
        # Best-effort prune on first touch.
        if persistence is not None and user_id:
            save_profile = getattr(persistence, "save_profile", None)
            ls = profile_data.get("learning_state") or {}
            prior = ls.get("spectral_advisories") or []
            if save_profile and surviving != prior:
                ls["spectral_advisories"] = surviving
                profile_data["learning_state"] = ls
                try:
                    save_profile(user_id, "journal", profile_data)
                except Exception as exc:  # pragma: no cover - defensive
                    log.warning(
                        "journal_domain_step: advisory prune save failed: %s", exc,
                    )
        if adv is not None:
            piggyback_advisory = _advisory_for_decision(adv)
            state["session_advisory_surfaced"] = True

    def _attach_advisory(decision: dict[str, Any]) -> dict[str, Any]:
        """Inject the piggyback advisory into a decision payload (if any)."""
        if piggyback_advisory is not None and "advisory" not in decision:
            decision["advisory"] = piggyback_advisory
        return decision

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
        return state, _attach_advisory(
            {"tier": "ok", "action": None, "message": "warmup_gate_active"}
        )

    # ── Pull learned baselines for envelope checks ────────────
    # The actor's own oscillation envelope (per-entity + global) drives
    # Tier 1 / Tier 3 once enough samples exist. Absolute thresholds are
    # only the cold-start fallback.
    relational_baseline: dict[str, Any] = {}
    if profile_data:
        ls = profile_data.get("learning_state") or {}
        relational_baseline = dict(ls.get("relational_baseline") or {})

    k_sigma_tier1 = float(thresholds["k_sigma_tier1"])
    k_sigma_tier3 = float(thresholds["k_sigma_tier3"])
    min_samples_z = int(thresholds["min_samples_for_zscore"])
    min_var_floor = float(thresholds["min_variance_floor"])

    # ── Tier 1 — envelope deviation (z-score) with fallback ──
    # Strategy: if ANY entity referenced this turn has a mature baseline AND
    # the per-entity SVA reading is outside its envelope → Tier 1. Otherwise,
    # if we have a global SVA reading, check that against the actor's global
    # baseline. If no baseline anywhere is mature, fall back to absolute
    # thresholds so the system isn't completely blind on day one.
    fallback_arousal = float(thresholds["fallback_tier1_arousal_spike"])
    fallback_valence = float(thresholds["fallback_tier1_valence_drop"])

    is_tier1 = False
    tier1_reason = "within_envelope"
    any_mature_baseline = False
    worst_z_t1 = 0.0

    # Per-entity envelope checks
    try:
        from affect_monitor import check_relational_deviation  # type: ignore
    except ModuleNotFoundError:
        from domain_packs.assistant.domain_lib.affect_monitor import (  # type: ignore[no-redef]
            check_relational_deviation,
        )

    for h, signals in entity_mentions.items():
        baseline_entry = relational_baseline.get(h)
        # The per-entity affect reading for this turn = baseline mean + this turn's delta.
        if baseline_entry is not None:
            obs_v = float(baseline_entry.get("valence", 0.0)) + float(signals.get("valence_delta", 0.0))
            obs_a = float(baseline_entry.get("arousal", 0.5)) + float(signals.get("arousal_delta", 0.0))
            obs_s = float(baseline_entry.get("salience", 0.5)) + float(signals.get("salience_delta", 0.0))
        else:
            obs_v, obs_a, obs_s = valence, arousal, salience
        check = check_relational_deviation(
            baseline_entry, obs_v, obs_a, obs_s,
            k_sigma=k_sigma_tier1,
            min_samples=min_samples_z,
            min_variance_floor=min_var_floor,
        )
        if check["mature"]:
            any_mature_baseline = True
            if check["z_score"] > worst_z_t1:
                worst_z_t1 = float(check["z_score"])
            if check["triggered"]:
                is_tier1 = True
                tier1_reason = f"entity_envelope_{check['axis']}_z{check['z_score']}"
                break

    # Global SVA envelope check (covers entity-less journal turns too)
    if not is_tier1 and sva:
        try:
            from affect_monitor import check_global_deviation, AffectBaseline  # type: ignore
        except ModuleNotFoundError:
            from domain_packs.assistant.domain_lib.affect_monitor import (  # type: ignore[no-redef]
                check_global_deviation,
                AffectBaseline,
            )
        global_baseline_dict = (profile_data or {}).get("learning_state", {}).get("global_affect_baseline")
        global_baseline = AffectBaseline.from_dict(global_baseline_dict) if global_baseline_dict else None
        gcheck = check_global_deviation(
            global_baseline, valence, arousal, salience,
            k_sigma=k_sigma_tier1,
            min_samples=min_samples_z,
            min_variance_floor=min_var_floor,
        )
        if gcheck["mature"]:
            any_mature_baseline = True
            if gcheck["triggered"]:
                is_tier1 = True
                tier1_reason = f"global_envelope_{gcheck['axis']}_z{gcheck['z_score']}"

    # ── Tier 1 — shape (rhythm) check ────────────────────────
    # Even when amplitude stays inside the envelope, a sustained one-direction
    # run (or absent natural flips) signals the actor's normal rhythm is
    # broken. Heartbeat analogy: ST elevation or rate change inside the band.
    k_shape_tier1 = float(thresholds["k_shape_tier1"])
    min_samples_shape = int(thresholds["min_samples_for_shape"])
    min_crossing_rate = float(thresholds["min_crossing_rate"])

    try:
        from affect_monitor import check_shape_deviation  # type: ignore
    except ModuleNotFoundError:
        from domain_packs.assistant.domain_lib.affect_monitor import (  # type: ignore[no-redef]
            check_shape_deviation,
        )

    if not is_tier1:
        for h, _signals in entity_mentions.items():
            baseline_entry = relational_baseline.get(h)
            if not baseline_entry:
                continue
            sc = int(baseline_entry.get("sample_count", 0))
            for axis in ("valence", "arousal", "salience"):
                shape = check_shape_deviation(
                    crossing_rate=float(baseline_entry.get(f"{axis}_crossing_rate", 0.5)),
                    run_length=int(baseline_entry.get(f"{axis}_run_length", 0)),
                    sample_count=sc,
                    k_shape=k_shape_tier1,
                    min_samples=min_samples_shape,
                    min_crossing_rate=min_crossing_rate,
                )
                if shape["mature"]:
                    any_mature_baseline = True
                    if shape["triggered"]:
                        is_tier1 = True
                        tier1_reason = (
                            f"entity_shape_{axis}_run{shape['run_length']}"
                            f"_dir_{shape['direction']}"
                        )
                        break
            if is_tier1:
                break

    # Cold-start fallback (no mature baseline anywhere yet)
    if not is_tier1 and not any_mature_baseline:
        if arousal > fallback_arousal or valence < fallback_valence:
            is_tier1 = True
            tier1_reason = "fallback_absolute_threshold"

    if is_tier1:
        state["sustained_elevation_count"] = int(state.get("sustained_elevation_count", 0)) + 1
        state["tier1_triggered_count"] = int(state.get("tier1_triggered_count", 0)) + 1
    else:
        # Reset sustained counter when no spike this turn
        state["sustained_elevation_count"] = 0

    # Per-entity relational concern count (z-score, with fallback)
    tier2_relational = int(thresholds["tier2_relational_concern_turns"])
    relational_concern_count = 0
    for h, sig in state_entity_mentions.items():
        baseline_entry = relational_baseline.get(h)
        if baseline_entry and int(baseline_entry.get("sample_count", 0)) >= min_samples_z:
            obs_v = float(baseline_entry.get("valence", 0.0)) + float(sig.get("valence_delta", 0.0))
            obs_a = float(baseline_entry.get("arousal", 0.5)) + float(sig.get("arousal_delta", 0.0))
            obs_s = float(baseline_entry.get("salience", 0.5)) + float(sig.get("salience_delta", 0.0))
            chk = check_relational_deviation(
                baseline_entry, obs_v, obs_a, obs_s,
                k_sigma=k_sigma_tier1,
                min_samples=min_samples_z,
                min_variance_floor=min_var_floor,
            )
            if chk["triggered"] and chk["axis"] == "valence":
                relational_concern_count += 1
        else:
            # Fallback: legacy absolute drop
            if float(sig.get("valence_delta", 0.0)) < fallback_valence:
                relational_concern_count += 1

    # ── Tier 2 — sustained elevation ─────────────────────────
    tier2_sustained = int(thresholds["tier2_sustained_turns"])
    sustained = int(state.get("sustained_elevation_count", 0))
    tier2_opt_in_pending = bool(state.get("tier2_opt_in_pending", False))

    is_tier2 = (
        not tier2_opt_in_pending
        and (sustained >= tier2_sustained or relational_concern_count >= tier2_relational)
    )

    # ── Tier 3 — cross-session critical (envelope-gated) ─────
    fallback_tier3_floor = float(thresholds["fallback_tier3_valence_floor"])
    tier3_cross_session_count = int(thresholds["tier3_cross_session_count"])
    cross_session_count = int(state.get("cross_session_elevation_count", 0))
    safe_person_alerted = bool(state.get("safe_person_alerted", False))

    _assigned_safe_person_id: str | None = None
    _safe_person_handshake_accepted = False
    if profile_data:
        _assigned_safe_person_id = profile_data.get("assigned_safe_person_id")
        _safe_person_handshake_accepted = bool(profile_data.get("safe_person_handshake_accepted", False))

    # Tier 3 valence-floor check: prefer envelope-based (k_sigma_tier3) on the
    # most-mentioned entity baseline; fall back to absolute floor only when no
    # entity baseline is mature.
    valence_critical = False
    if relational_baseline:
        for h, signals in entity_mentions.items():
            baseline_entry = relational_baseline.get(h)
            if not baseline_entry or int(baseline_entry.get("sample_count", 0)) < min_samples_z:
                continue
            obs_v = float(baseline_entry.get("valence", 0.0)) + float(signals.get("valence_delta", 0.0))
            obs_a = float(baseline_entry.get("arousal", 0.5)) + float(signals.get("arousal_delta", 0.0))
            obs_s = float(baseline_entry.get("salience", 0.5)) + float(signals.get("salience_delta", 0.0))
            chk3 = check_relational_deviation(
                baseline_entry, obs_v, obs_a, obs_s,
                k_sigma=k_sigma_tier3,
                min_samples=min_samples_z,
                min_variance_floor=min_var_floor,
            )
            if chk3["triggered"] and chk3["axis"] == "valence" and obs_v < float(baseline_entry.get("valence", 0.0)):
                valence_critical = True
                break
    if not valence_critical and not any_mature_baseline:
        valence_critical = valence < fallback_tier3_floor

    # Tier 3 shape check: extreme sustained drift (k_shape_tier3 × expected
    # mean run length) on a mature baseline is a critical rhythm break, even
    # if the amplitude check didn't fire. Only treat as critical when valence
    # is the affected axis AND direction is negative (sustained downward).
    if not valence_critical:
        k_shape_tier3 = float(thresholds["k_shape_tier3"])
        for h, _signals in entity_mentions.items():
            be = relational_baseline.get(h)
            if not be:
                continue
            sc = int(be.get("sample_count", 0))
            shape_v = check_shape_deviation(
                crossing_rate=float(be.get("valence_crossing_rate", 0.5)),
                run_length=int(be.get("valence_run_length", 0)),
                sample_count=sc,
                k_shape=k_shape_tier3,
                min_samples=min_samples_shape,
                min_crossing_rate=min_crossing_rate,
            )
            if shape_v["triggered"] and shape_v["direction"] == "negative":
                valence_critical = True
                break

    is_tier3 = (
        not safe_person_alerted
        and valence_critical
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
        return state, _attach_advisory({
            "tier": "tier3",
            "action": "journal_tier3_safe_person_alert",
            "message": "tier3_wellness_escalation_created",
        })

    if is_tier2:
        state["tier2_opt_in_pending"] = True
        return state, _attach_advisory({
            "tier": "tier2",
            "action": "journal_tier2_opt_in_ask",
            "message": "tier2_sustained_elevation_ask",
        })

    if is_tier1:
        return state, _attach_advisory({
            "tier": "tier1",
            "action": "journal_tier1_breathing",
            "message": tier1_reason,
        })

    return state, _attach_advisory({"tier": "ok", "action": None, "message": None})


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
