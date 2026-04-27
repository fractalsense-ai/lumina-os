"""Fluency monitor — consecutive-success gate with time threshold.

Tracks whether a student has achieved procedural fluency on their
current difficulty tier before advancing.  Advancement requires
``target_consecutive_successes`` correct solves, each completed within
``time_threshold_seconds``.

This module conforms to the domain-state-lib contract (deterministic,
structured I/O, no free text, same inputs → same output).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ── State ─────────────────────────────────────────────────────


@dataclass
class FluencyState:
    """Per-session fluency tracking state."""

    consecutive_correct: int = 0
    current_tier: str = "tier_1"
    solve_times: list[float] = field(default_factory=list)


DEFAULT_PARAMS: dict[str, Any] = {
    "target_consecutive_successes": 3,
    "time_threshold_seconds": 45.0,
    "tier_progression": ["tier_1", "tier_2", "tier_3"],
}


# ── Core Step Function ────────────────────────────────────────


def fluency_monitor_step(
    state: FluencyState,
    task_spec: dict[str, Any],
    evidence: dict[str, Any],
    params: dict[str, Any] | None = None,
) -> tuple[FluencyState, dict[str, Any]]:
    """Evaluate one turn and return updated state + decision.

    Parameters
    ----------
    state:
        Current ``FluencyState``.
    task_spec:
        Active task specification (unused but accepted for interface
        consistency with domain-lib contract).
    evidence:
        Structured evidence from the turn interpreter.
        Expected keys: ``correctness`` (str), ``solve_elapsed_sec`` (float).
    params:
        Optional overrides for fluency monitor parameters.

    Returns
    -------
    (new_state, decision) where *decision* contains:
      * ``action``: ``None`` | ``"advance_tier"`` | ``"trigger_targeted_hint"``
      * ``fluency_bottleneck``: bool
      * ``consecutive_correct``: int
      * ``current_tier``: str
      * ``advanced``: bool
      * ``next_tier``: str | None
    """
    p = {**DEFAULT_PARAMS, **(params or {})}
    target = int(p["target_consecutive_successes"])
    threshold = float(p["time_threshold_seconds"])
    progression: list[str] = p["tier_progression"]

    correctness = str(evidence.get("correctness", "partial"))
    elapsed = float(evidence.get("solve_elapsed_sec", 0.0))

    new_consecutive = state.consecutive_correct
    new_tier = state.current_tier
    new_times = list(state.solve_times)

    action: str | None = None
    fluency_bottleneck = False
    advanced = False
    next_tier: str | None = None

    if correctness == "correct":
        new_times.append(elapsed)
        if elapsed <= threshold:
            # Fast correct solve — count it
            new_consecutive += 1
        else:
            # Correct but too slow — fluency bottleneck
            new_consecutive = 0
            fluency_bottleneck = True
            action = "trigger_targeted_hint"
    else:
        # Incorrect or partial — reset
        new_consecutive = 0
        new_times = []

    # Check for tier advancement
    if new_consecutive >= target:
        current_idx = _tier_index(progression, new_tier)
        if current_idx < len(progression) - 1:
            next_tier = progression[current_idx + 1]
            new_tier = next_tier
            action = "advance_tier"
            advanced = True
        # Reset counter regardless (start fresh in new tier or stay at top)
        new_consecutive = 0
        new_times = []

    new_state = FluencyState(
        consecutive_correct=new_consecutive,
        current_tier=new_tier,
        solve_times=new_times,
    )

    decision: dict[str, Any] = {
        "action": action,
        "fluency_bottleneck": fluency_bottleneck,
        "consecutive_correct": new_state.consecutive_correct,
        "current_tier": new_state.current_tier,
        "advanced": advanced,
        "next_tier": next_tier,
    }

    return new_state, decision


# ── Helpers ───────────────────────────────────────────────────


def _tier_index(progression: list[str], tier_id: str) -> int:
    """Return the index of *tier_id* in *progression*, defaulting to 0."""
    try:
        return progression.index(tier_id)
    except ValueError:
        return 0


def build_initial_fluency_state(
    nominal_difficulty: float,
    tiers: list[dict[str, Any]],
    tier_progression: list[str],
) -> FluencyState:
    """Create a starting ``FluencyState`` from the task's nominal difficulty.

    Maps *nominal_difficulty* to the matching tier in *tiers* and sets
    ``current_tier`` accordingly.
    """
    current_tier = tier_progression[0] if tier_progression else "tier_1"
    for tier in tiers:
        lo = float(tier.get("min_difficulty", 0.0))
        hi = float(tier.get("max_difficulty", 1.0))
        if lo <= nominal_difficulty < hi:
            current_tier = str(tier.get("tier_id", current_tier))
            break
    else:
        # nominal_difficulty >= all upper bounds → last tier
        if tiers:
            current_tier = str(tiers[-1].get("tier_id", current_tier))
    return FluencyState(current_tier=current_tier)
