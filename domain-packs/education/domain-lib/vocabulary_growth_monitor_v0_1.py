"""
vocabulary-growth-monitor-v0.1.py — Project Lumina Vocabulary Growth Tracker

Version: 0.1.0
Domain: education (Student Commons and all student profiles)

Description:
    Passive vocabulary complexity monitor.  Receives a structured
    complexity score from the client-side analyzer (no transcript
    content), updates the student profile's vocabulary tracking state,
    and produces a growth delta.

Design constraints:
    - No ML models; score computation happens client-side
    - No transcript content is processed or stored server-side
    - Only structured metrics flow through this module
    - Growth delta is always non-negative (no punishment)
    - Baseline locks after N sessions to provide a stable reference
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


# ── Default parameters ──────────────────────────────────────

DEFAULT_PARAMS: dict[str, Any] = {
    "measurement_window_turns": 20,
    "min_turns_for_measurement": 10,
    "baseline_lock_sessions": 3,
    "session_history_max": 50,
}


# ── State helpers ───────────────────────────────────────────

def _build_default_vocab_state() -> dict[str, Any]:
    """Return default vocabulary tracking state."""
    return {
        "baseline_complexity": None,
        "current_complexity": None,
        "growth_delta": 0.0,
        "domain_vocabulary": {},
        "measurement_window_turns": DEFAULT_PARAMS["measurement_window_turns"],
        "baseline_sessions_remaining": DEFAULT_PARAMS["baseline_lock_sessions"],
        "baseline_samples": [],
        "last_measured_utc": None,
        "session_history": [],
    }


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


# ── Core step function ──────────────────────────────────────

def vocabulary_growth_step(
    state: dict[str, Any],
    evidence: dict[str, Any],
    params: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Process a vocabulary complexity measurement and update tracking state.

    Parameters
    ----------
    state : dict
        The ``vocabulary_tracking`` section of the student's session state.
        If empty or missing keys, defaults are applied.
    evidence : dict
        Must contain at minimum:
        - ``vocabulary_complexity_score`` (float 0..1): composite score
          from client-side analysis.
        Optional:
        - ``lexical_diversity`` (float): type-token ratio
        - ``avg_word_length`` (float): average word length
        - ``embedding_spread`` (float): cosine distance spread
        - ``domain_terms_detected`` (list[str]): domain vocabulary
          terms found in the student's expression
        - ``buffer_turns`` (int): number of turns analyzed
        - ``measurement_valid`` (bool): whether the client had
          enough data for a meaningful measurement
    params : dict | None
        Override default parameters.

    Returns
    -------
    tuple[dict, dict]
        (updated_state, decision)
        decision keys: vocab_growth_delta, domain_terms_acquired,
        measurement_valid, reward_weight_contribution
    """
    p = {**DEFAULT_PARAMS, **(params or {})}

    # ── Ensure state has all keys ─────────────────────────
    defaults = _build_default_vocab_state()
    for key, val in defaults.items():
        state.setdefault(key, val)

    # ── Extract evidence ──────────────────────────────────
    score = evidence.get("vocabulary_complexity_score")
    valid = evidence.get("measurement_valid", True)
    buffer_turns = evidence.get("buffer_turns", 0)
    domain_terms = evidence.get("domain_terms_detected") or []

    # If no score or explicitly invalid, return no-op decision
    if score is None or not valid:
        return state, {
            "vocab_growth_delta": 0.0,
            "domain_terms_acquired": 0,
            "measurement_valid": False,
            "reward_weight_contribution": 0.0,
        }

    score = _clamp(float(score), 0.0, 1.0)
    now_utc = datetime.now(timezone.utc).isoformat()

    # ── Check minimum turns ───────────────────────────────
    min_turns = int(p.get("min_turns_for_measurement", 10))
    if buffer_turns < min_turns:
        return state, {
            "vocab_growth_delta": 0.0,
            "domain_terms_acquired": 0,
            "measurement_valid": False,
            "reward_weight_contribution": 0.0,
        }

    # ── Update current complexity ─────────────────────────
    state["current_complexity"] = score
    state["last_measured_utc"] = now_utc

    # ── Baseline management ───────────────────────────────
    sessions_remaining = int(state.get("baseline_sessions_remaining", 0))
    baseline_samples = state.get("baseline_samples") or []

    if sessions_remaining > 0:
        # Still collecting baseline samples
        baseline_samples.append(score)
        state["baseline_samples"] = baseline_samples
        sessions_remaining -= 1
        state["baseline_sessions_remaining"] = sessions_remaining

        if sessions_remaining == 0:
            # Lock baseline as average of collected samples
            state["baseline_complexity"] = sum(baseline_samples) / len(baseline_samples)
        else:
            # Provisional baseline from samples so far
            state["baseline_complexity"] = sum(baseline_samples) / len(baseline_samples)

    baseline = state.get("baseline_complexity")
    if baseline is None:
        # Should not happen after first sample, but guard anyway
        state["baseline_complexity"] = score
        baseline = score

    # ── Compute growth delta (always non-negative) ────────
    raw_delta = score - baseline
    growth_delta = max(0.0, raw_delta)
    state["growth_delta"] = growth_delta

    # ── Domain vocabulary tracking ────────────────────────
    domain_vocab = state.get("domain_vocabulary") or {}
    new_domain_terms = 0
    for term in domain_terms:
        # Terms are tagged with their source module by the client
        # Format: "module_id:term" or just "term" (commons-global)
        if ":" in term:
            module_id, _term = term.split(":", 1)
        else:
            module_id = "_commons"
            _term = term

        if module_id not in domain_vocab:
            domain_vocab[module_id] = {"terms_acquired": 0, "complexity_delta": 0.0}

        entry = domain_vocab[module_id]
        entry["terms_acquired"] = entry.get("terms_acquired", 0) + 1
        entry["complexity_delta"] = max(
            entry.get("complexity_delta", 0.0), growth_delta
        )
        new_domain_terms += 1

    state["domain_vocabulary"] = domain_vocab

    # ── Session history (rolling) ─────────────────────────
    history = state.get("session_history") or []
    history.append({
        "complexity": score,
        "delta": growth_delta,
        "measured_utc": now_utc,
    })
    max_history = int(p.get("session_history_max", 50))
    if len(history) > max_history:
        history = history[-max_history:]
    state["session_history"] = history

    # ── Reward weight contribution ────────────────────────
    # Positive growth → positive reward contribution (proportional)
    # Stagnation → 0 contribution (never negative)
    reward_weight = growth_delta * 0.5  # scaling factor TBD by reward system

    return state, {
        "vocab_growth_delta": growth_delta,
        "domain_terms_acquired": new_domain_terms,
        "measurement_valid": True,
        "reward_weight_contribution": reward_weight,
    }
