"""
zpd-monitor-v0.2.py — Project Lumina ZPD Monitor Reference Implementation

Version: 0.2.0
Conforms to (paths relative to repository root):
    domain-packs/education/domain-lib/zpd-monitor-spec-v1.md
    domain-packs/education/domain-lib/compressed-state-estimators.md
  domain-packs/education/schemas/compressed-state-schema-v1.json

Description:
    Deterministic (no ML) implementation of the Zone of Proximal Development
    monitor. Takes structured evidence as input and produces an updated
    compressed learning state and a decision tier.

Design constraints:
    - No ML models; all heuristics are explicit arithmetic
    - No external dependencies (standard library only)
    - Evidence inputs are structured summaries only
      (correctness, hint_used, response_latency_sec, etc.)
    - No transcript content is processed or stored

Usage:
    from zpd_monitor_v0_2 import (
        AffectState, RecentWindow, LearningState,
        zpd_monitor_step, DEFAULT_PARAMS
    )
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any


# ─────────────────────────────────────────────────────────────
# Data Structures
# ─────────────────────────────────────────────────────────────

@dataclass
class AffectState:
    """SVA triad: Salience, Valence, Arousal."""
    salience: float = 0.5   # 0..1 (engagement/focus)
    valence: float = 0.0    # -1..1 (emotional tone)
    arousal: float = 0.5    # 0..1 (activation level)

    def __post_init__(self) -> None:
        self.salience = _clamp(self.salience, 0.0, 1.0)
        self.valence = _clamp(self.valence, -1.0, 1.0)
        self.arousal = _clamp(self.arousal, 0.0, 1.0)


@dataclass
class RecentWindow:
    """Rolling window state for ZPD drift detection."""
    window_turns: int = 10
    attempts: int = 0
    consecutive_incorrect: int = 0
    hint_count: int = 0
    outside_pct: float = 0.0
    consecutive_outside: int = 0
    outside_flags: list[bool] = field(default_factory=list)
    hint_flags: list[bool] = field(default_factory=list)


@dataclass
class LearningState:
    """Compressed learner state: affect + mastery + ZPD window."""
    affect: AffectState
    mastery: dict[str, float]              # skill_id → 0..1
    challenge_band: dict[str, float]           # min_challenge, max_challenge
    recent_window: RecentWindow
    challenge: float = 0.5                # 0..1
    uncertainty: float = 0.5              # 0..1

    def __post_init__(self) -> None:
        self.challenge = _clamp(self.challenge, 0.0, 1.0)
        self.uncertainty = _clamp(self.uncertainty, 0.0, 1.0)
        for k, v in self.mastery.items():
            self.mastery[k] = _clamp(v, 0.0, 1.0)


# ─────────────────────────────────────────────────────────────
# Default Parameters
# ─────────────────────────────────────────────────────────────

# Tolerance added to challenge-band boundaries to prevent floating-point jitter
# at the edges from falsely registering as outside-band.
_ZPD_TOLERANCE: float = 0.01

DEFAULT_PARAMS: dict[str, Any] = {
    "minor_drift_threshold": 0.3,
    "major_drift_threshold": 0.5,
    "persistence_required": 3,
    "window_turns": 10,
    "latency_threshold_sec": 60.0,
    # Mastery update deltas
    "mastery_correct_no_hint": 0.10,
    "mastery_correct_hint": 0.03,
    "mastery_partial_no_hint": 0.02,
    "mastery_partial_hint": 0.01,
    "mastery_incorrect": -0.05,
    "mastery_repeated_error": -0.08,
}


# ─────────────────────────────────────────────────────────────
# Helper
# ─────────────────────────────────────────────────────────────

def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


# ─────────────────────────────────────────────────────────────
# Estimators
# ─────────────────────────────────────────────────────────────

def estimate_frustration_flag(
    affect: AffectState,
    window: RecentWindow,
    evidence: dict[str, Any],
) -> bool:
    """
    Returns True if the learner shows acute frustration signals.

    Inputs are structural (window state + affect + evidence summary)
    — never raw conversation content.
    """
    consecutive_incorrect = window.consecutive_incorrect
    hint_count = window.hint_count
    frustration_marker_count = int(evidence.get("frustration_marker_count", 0) or 0)
    repeated_error = bool(evidence.get("repeated_error", False))

    return bool(
        consecutive_incorrect >= 3
        or hint_count >= 3
        or frustration_marker_count >= 2
        or (repeated_error and consecutive_incorrect >= 2)
    )


def estimate_uncertainty(
    prev_uncertainty: float,
    evidence: dict[str, Any],
) -> float:
    """
    Updates orchestrator uncertainty about learner state.

    Uncertainty decays with consistent evidence and grows with
    contradictory or ambiguous evidence.
    """
    correctness = evidence.get("correctness", None)
    hint_used = bool(evidence.get("hint_used", False))
    repeated_error = bool(evidence.get("repeated_error", False))

    if correctness == "correct" and not hint_used:
        delta = -0.10
    elif correctness == "incorrect" and repeated_error:
        delta = +0.05
    elif correctness == "partial":
        delta = +0.02
    elif correctness == "correct" and hint_used:
        delta = -0.05
    elif correctness == "incorrect":
        delta = -0.02
    else:
        delta = -0.03

    return _clamp(prev_uncertainty + delta, 0.0, 1.0)


def estimate_challenge(
    task_spec: dict[str, Any],
    student_mastery: dict[str, float],
    uncertainty: float,
    params: dict[str, Any] | None = None,
) -> float:
    """
    Estimates the challenge level of a task for this student.

    Uses the task's nominal difficulty adjusted by the student's
    mastery on the required skills and current uncertainty.
    """
    nominal = float(task_spec.get("nominal_difficulty", 0.5))
    skills = list(task_spec.get("skills_required", []))

    if skills and student_mastery:
        relevant_mastery = [
            student_mastery.get(s, 0.5) for s in skills
        ]
        mean_mastery = sum(relevant_mastery) / len(relevant_mastery)
    else:
        mean_mastery = 0.5

    mastery_adjustment = (0.5 - mean_mastery) * 0.4
    uncertainty_adjustment = uncertainty * 0.1

    return _clamp(nominal + mastery_adjustment + uncertainty_adjustment, 0.0, 1.0)


def update_affect(
    prev: AffectState,
    evidence: dict[str, Any],
    params: dict[str, Any] | None = None,
) -> AffectState:
    """
    Updates the SVA affect state from structured evidence.

    Evidence inputs: correctness, hint_used, response_latency_sec,
    frustration_marker_count, off_task_ratio.
    No raw text or conversation content is used.
    """
    p = params or DEFAULT_PARAMS
    correctness = evidence.get("correctness", None)
    hint_used = bool(evidence.get("hint_used", False))
    latency = float(evidence.get("response_latency_sec", 30.0) or 30.0)
    frustration_markers = int(evidence.get("frustration_marker_count", 0) or 0)
    off_task = float(evidence.get("off_task_ratio", 0.0) or 0.0)
    latency_threshold = float(p.get("latency_threshold_sec", 60.0))

    # Salience
    d_salience = 0.0
    if off_task > 0.5:
        d_salience -= 0.10
    if latency > latency_threshold:
        d_salience -= 0.05
    if correctness == "correct" and not hint_used:
        d_salience += 0.05

    # Valence
    d_valence = 0.0
    if correctness == "correct" and not hint_used:
        d_valence += 0.10
    elif correctness == "correct" and hint_used:
        d_valence += 0.03
    elif correctness == "incorrect":
        d_valence -= 0.08
    elif correctness == "partial":
        d_valence -= 0.02
    if frustration_markers >= 2:
        d_valence -= 0.10

    # Arousal
    d_arousal = 0.0
    if latency < 3.0:
        d_arousal += 0.05
    elif latency > 30.0:
        d_arousal -= 0.10
    if frustration_markers >= 2:
        d_arousal += 0.15

    return AffectState(
        salience=_clamp(prev.salience + d_salience, 0.0, 1.0),
        valence=_clamp(prev.valence + d_valence, -1.0, 1.0),
        arousal=_clamp(prev.arousal + d_arousal, 0.0, 1.0),
    )


def update_mastery(
    prev_mastery: dict[str, float],
    task_spec: dict[str, Any],
    evidence: dict[str, Any],
    params: dict[str, Any] | None = None,
) -> dict[str, float]:
    """
    Updates per-skill mastery estimates from task evidence.

    Only skills listed in task_spec['skills_required'] are updated.
    Skills not exercised by this task are unchanged.
    """
    p = params or DEFAULT_PARAMS
    correctness = evidence.get("correctness", None)
    hint_used = bool(evidence.get("hint_used", False))
    repeated_error = bool(evidence.get("repeated_error", False))
    skills = list(task_spec.get("skills_required", []))

    if correctness == "correct" and not hint_used:
        delta = float(p["mastery_correct_no_hint"])
    elif correctness == "correct" and hint_used:
        delta = float(p["mastery_correct_hint"])
    elif correctness == "partial" and not hint_used:
        delta = float(p["mastery_partial_no_hint"])
    elif correctness == "partial" and hint_used:
        delta = float(p["mastery_partial_hint"])
    elif correctness == "incorrect" and repeated_error:
        delta = float(p["mastery_repeated_error"])
    elif correctness == "incorrect":
        delta = float(p["mastery_incorrect"])
    else:
        delta = 0.0

    new_mastery = dict(prev_mastery)
    for skill in skills:
        prev = new_mastery.get(skill, 0.0)
        new_mastery[skill] = _clamp(prev + delta, 0.0, 1.0)

    return new_mastery


def update_zpd_window(
    recent: RecentWindow,
    outside_band: bool,
    evidence: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> RecentWindow:
    """
    Updates the rolling ZPD window with the result of the current turn.

    outside_band: whether the current task's challenge was outside [min, max].
    """
    p = params or DEFAULT_PARAMS
    window_turns = int(p.get("window_turns", recent.window_turns))
    hint_used = bool((evidence or {}).get("hint_used", False))
    correctness = (evidence or {}).get("correctness", None)

    # Off-task turns (greetings, meta-questions) should not count against the
    # ZPD window — the student hasn't attempted anything, so recording
    # outside_band=True would unfairly accumulate toward drift detection.
    off_task_ratio = float((evidence or {}).get("off_task_ratio", 0.0))
    if off_task_ratio >= 0.8:
        outside_band = False

    # Update outside_flags rolling window (most recent first)
    new_flags = [outside_band] + list(recent.outside_flags)
    new_flags = new_flags[:window_turns]

    outside_pct = sum(new_flags) / max(len(new_flags), 1)
    consecutive_outside = (recent.consecutive_outside + 1) if outside_band else 0

    consecutive_incorrect = (
        recent.consecutive_incorrect + 1
        if correctness == "incorrect"
        else 0
    )

    # Track hint usage within the rolling window
    new_hint_flags = [hint_used] + list(recent.hint_flags)
    new_hint_flags = new_hint_flags[:window_turns]
    windowed_hint_count = sum(new_hint_flags)

    return RecentWindow(
        window_turns=window_turns,
        attempts=recent.attempts + 1,
        consecutive_incorrect=consecutive_incorrect,
        hint_count=windowed_hint_count,
        outside_pct=outside_pct,
        consecutive_outside=consecutive_outside,
        outside_flags=new_flags,
        hint_flags=new_hint_flags,
    )


def _detect_drift(
    window: RecentWindow,
    frustration: bool,
    params: dict[str, Any],
) -> dict[str, Any]:
    """
    Converts window state into a decision tier.

    Returns a decision dict with tier, action, and supporting data.
    """
    minor_threshold = float(params.get("minor_drift_threshold", 0.3))
    major_threshold = float(params.get("major_drift_threshold", 0.5))
    persistence = int(params.get("persistence_required", 3))
    min_turns_before_escalation = int(params.get("min_turns_before_escalation", 2))

    # Frustration alone cannot trigger a major escalation until the student
    # has had at least min_turns_before_escalation attempts.  This prevents
    # a single emotive statement on turn 1 from immediately locking the session.
    escalation_eligible_frustration = frustration and window.attempts >= min_turns_before_escalation

    is_major = (
        window.outside_pct >= major_threshold
        or window.consecutive_outside >= persistence
        or escalation_eligible_frustration
    )
    is_minor = window.outside_pct >= minor_threshold or (frustration and not escalation_eligible_frustration)

    if is_major:
        return {
            "tier": "major",
            "action": "zpd_intervene_or_escalate",
            "should_escalate": True,
            "frustration": frustration,
            "drift_pct": window.outside_pct,
            "reason": "major_zpd_drift_or_frustration",
        }
    elif is_minor:
        return {
            "tier": "minor",
            "action": "zpd_scaffold",
            "frustration": frustration,
            "drift_pct": window.outside_pct,
            "reason": "minor_zpd_drift",
        }
    else:
        return {
            "tier": "ok",
            "action": None,
            "frustration": frustration,
            "drift_pct": window.outside_pct,
            "reason": "within_zpd",
        }


# ─────────────────────────────────────────────────────────────
# Main Entry Point
# ─────────────────────────────────────────────────────────────

def zpd_monitor_step(
    state: LearningState,
    task_spec: dict[str, Any],
    evidence: dict[str, Any],
    params: dict[str, Any] | None = None,
) -> tuple[LearningState, dict[str, Any]]:
    """
    Process one session turn through the ZPD monitor.

    Args:
        state:     Current compressed learning state
        task_spec: Current task specification from the domain pack
                   Expected keys: nominal_difficulty (0..1),
                                  skills_required (list of skill IDs)
        evidence:  Structured evidence summary from this turn.
                   Expected keys: correctness, hint_used,
                   response_latency_sec, frustration_marker_count,
                   repeated_error, off_task_ratio.
                   MUST NOT contain raw text or transcript content.
        params:    Optional parameter overrides (see DEFAULT_PARAMS)

    Returns:
        (updated_state, decision)
        decision keys: tier, action, frustration, challenge,
                       outside_band, drift_pct, reason
    """
    p = {**DEFAULT_PARAMS, **(params or {})}

    # 1. Update mastery
    new_mastery = update_mastery(state.mastery, task_spec, evidence, p)

    # 2. Estimate challenge
    new_challenge = estimate_challenge(task_spec, new_mastery, state.uncertainty, p)

    # 3. Update affect
    new_affect = update_affect(state.affect, evidence, p)

    # 4. Update uncertainty
    new_uncertainty = estimate_uncertainty(state.uncertainty, evidence)

    # 5. Determine if challenge is outside the challenge band
    zpd_min = float(state.challenge_band.get("min_challenge", 0.3))
    zpd_max = float(state.challenge_band.get("max_challenge", 0.7))
    outside_band = (
        new_challenge < zpd_min - _ZPD_TOLERANCE
        or new_challenge > zpd_max + _ZPD_TOLERANCE
    )

    # 6. Update ZPD rolling window
    new_window = update_zpd_window(state.recent_window, outside_band, evidence, p)

    # 7. Estimate frustration
    frustration = estimate_frustration_flag(new_affect, new_window, evidence)

    # 8. Detect drift and produce decision
    decision = _detect_drift(new_window, frustration, p)
    decision["challenge"] = new_challenge
    decision["outside_band"] = outside_band

    # 9. Assemble updated state
    new_state = LearningState(
        affect=new_affect,
        mastery=new_mastery,
        challenge_band=state.challenge_band,
        recent_window=new_window,
        challenge=new_challenge,
        uncertainty=new_uncertainty,
    )

    return new_state, decision
