"""Assistant domain — Runtime adapters.

Provides the three REQUIRED callables that the runtime loader expects:

    build_initial_state(profile) → state dict
    domain_step(state, task_spec, evidence, params) → (new_state, decision)
    interpret_turn_input(call_llm, input_text, task_context, prompt_text,
                         default_fields, tool_fns) → evidence dict

Intent-based per-turn routing: the turn interpreter classifies intent and
the domain_step shifts the active module accordingly.
"""

from __future__ import annotations

import json
import sys
import os
from typing import Any, Callable

# Import the affect monitor from domain-lib (sibling directory).
_DOMAIN_LIB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "domain-lib")
if _DOMAIN_LIB_DIR not in sys.path:
    sys.path.insert(0, _DOMAIN_LIB_DIR)

from affect_monitor import (  # noqa: E402
    AffectState,
    AffectBaseline,
    update_affect,
    update_baseline,
    compute_drift,
)
from persona_engine import (  # noqa: E402
    PersonaState,
    PersonaOverlay,
    build_overlay,
    update_persona,
    apply_intensity_cap,
    is_safe_persona,
)

# Intent → module ID mapping for routing decisions.
INTENT_TO_MODULE: dict[str, str] = {
    "general": "domain/asst/conversation/v1",
    "weather": "domain/asst/weather/v1",
    "calendar": "domain/asst/calendar/v1",
    "search": "domain/asst/search/v1",
    "creative": "domain/asst/creative-writing/v1",
    "planning": "domain/asst/planning/v1",
    "trip": "domain/asst/trip/v1",
    "governance": "domain/asst/domain-authority/v1",
    "persona": "domain/asst/persona-craft/v1",
}

# Trip-specific state fields that are carried forward across turns.
TRIP_CARRY_FIELDS: tuple[str, ...] = (
    "trip_destination",
    "trip_origin_airport",
    "trip_date_start",
    "trip_date_end",
    "trip_activity_preferences",
    "trip_budget_usd",
    "trip_accommodation_style",
    "trip_party_size",
)


def _compute_trip_days(date_start: str | None, date_end: str | None) -> int | None:
    """Return trip duration in days, or None if either date is absent/unparseable."""
    if not date_start or not date_end:
        return None
    try:
        from datetime import date as _date
        d0 = _date.fromisoformat(date_start)
        d1 = _date.fromisoformat(date_end)
        return max(1, (d1 - d0).days + 1)
    except (ValueError, TypeError):
        return None


# ── 1. State Builder ─────────────────────────────────────────────────

def build_initial_state(profile: dict[str, Any]) -> dict[str, Any]:
    """Build the initial session state from an entity profile.

    Called once at session start.  The returned dict becomes the `state`
    argument to every subsequent `domain_step` call.
    """
    entity_state = profile.get("entity_state") or {}
    affect_data = entity_state.get("affect_baseline") or {}

    return {
        "turn_count": 0,
        "idle_turn_count": 0,
        "active_intent": "general",
        "active_task_id": entity_state.get("active_task_id"),
        "active_task_type": entity_state.get("active_task_type"),
        "task_history": [],
        "intent_window": [],  # Last N intents for switch-counting
        "affect": AffectState(
            salience=float(affect_data.get("salience", 0.5)),
            valence=float(affect_data.get("valence", 0.0)),
            arousal=float(affect_data.get("arousal", 0.5)),
        ),
        "affect_baseline": AffectBaseline.from_dict(affect_data),
        "persona": PersonaState.from_dict(entity_state.get("persona")),
        "persona_overlay": build_overlay(
            PersonaState.from_dict(entity_state.get("persona"))
        ),
    }


# ── 2. Domain Step ───────────────────────────────────────────────────

def domain_step(
    state: dict[str, Any],
    task_spec: dict[str, Any],
    evidence: dict[str, Any],
    params: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run one domain tick: state × evidence → (new_state, decision).

    Intent-based routing: reads intent_type from evidence and decides
    whether to suggest a module switch. Tracks task lifecycle,
    idle-turn counting, and SVA affect state with EWMA baseline.
    Drift velocity is the primary escalation signal.
    """
    new_state = dict(state)
    new_state["turn_count"] = new_state.get("turn_count", 0) + 1

    intent = str(evidence.get("intent_type", "general"))
    task_status = str(evidence.get("task_status", "n/a"))

    # Track intent for routing
    new_state["active_intent"] = intent

    # Intent window for switch-counting (last 5 turns)
    intent_window = list(new_state.get("intent_window") or [])
    intent_window.append(intent)
    intent_window = intent_window[-5:]
    new_state["intent_window"] = intent_window

    # Count intent switches in window
    switches = sum(
        1 for i in range(1, len(intent_window))
        if intent_window[i] != intent_window[i - 1]
    )

    # Idle turn tracking for conversation commons
    if intent == "general" and task_status == "n/a":
        new_state["idle_turn_count"] = new_state.get("idle_turn_count", 0) + 1
    else:
        new_state["idle_turn_count"] = 0

    # Task lifecycle tracking
    if task_status == "completed":
        task_record = {
            "task_id": new_state.get("active_task_id"),
            "task_type": new_state.get("active_task_type"),
            "status": "completed",
            "turn": new_state["turn_count"],
        }
        history = list(new_state.get("task_history") or [])
        history.append(task_record)
        new_state["task_history"] = history
        new_state["active_task_id"] = None
        new_state["active_task_type"] = None
    elif task_status == "open" and new_state.get("active_task_type") != intent:
        new_state["active_task_type"] = intent
        new_state["active_task_id"] = f"task-{intent}-{new_state['turn_count']}"

    # ── Pending tool-call carry-forward tracking ─────────────────────dwa
    # Store whether a tool call is pending so the next turn can carry it
    # forward if the user's follow-up message is classified as "general"
    # (e.g. "I wanted to go to Okinawa" after "what's the weather?").
    if bool(evidence.get("tool_call_requested")):
        new_state["pending_tool_call"] = True
        new_state["pending_tool_intent"] = intent
    elif task_status in ("completed", "abandoned", "deferred"):
        new_state["pending_tool_call"] = False
        new_state["pending_tool_intent"] = None

    # ── SVA Affect Update ────────────────────────────────────────────
    prev_affect = new_state.get("affect")
    if not isinstance(prev_affect, AffectState):
        prev_affect = AffectState()

    # Inject computed intent_switches into evidence for affect estimator
    affect_evidence = dict(evidence)
    affect_evidence["intent_switches_in_window"] = switches

    new_affect = update_affect(prev_affect, affect_evidence, params)
    new_state["affect"] = new_affect

    # ── EWMA Baseline Update ─────────────────────────────────────────
    baseline = new_state.get("affect_baseline")
    if not isinstance(baseline, AffectBaseline):
        baseline = AffectBaseline()

    target_module = INTENT_TO_MODULE.get(intent, "domain/asst/conversation/v1")
    new_baseline = update_baseline(baseline, new_affect, module_id=target_module, params=params)
    new_state["affect_baseline"] = new_baseline

    # ── Drift Velocity Detection ─────────────────────────────────────
    drift = compute_drift(new_baseline, params)

    # Determine tier from idle count + drift velocity
    idle_count = new_state.get("idle_turn_count", 0)
    window = int(params.get("drift_threshold_turns", 3))

    if drift.is_fast_drift:
        tier = "minor"
        action = "affect_drift_alert"
    elif idle_count >= window:
        tier = "minor"
        action = "idle_prompt_offer"
    else:
        tier = "ok"
        action = None

    # ── Weather tool routing ─────────────────────────────────────────
    # When the weather module is active and a tool call is needed,
    # route to weather_lookup (location present) or resolve_location
    # (location missing) so apply_tool_call_policy fires the right tool.
    if intent == "weather" and bool(evidence.get("tool_call_requested")):
        location = evidence.get("location")
        if location:
            action = "weather_lookup"
            tier = "ok"
        else:
            action = "resolve_location"
            tier = "ok"

    # ── Search tool routing ──────────────────────────────────────────
    # Route to web_search when query is resolved; ask for it otherwise.
    if intent == "search" and bool(evidence.get("tool_call_requested")):
        query = evidence.get("query")
        if query:
            action = "web_search"
            tier = "ok"
        else:
            action = "refine_query"
            tier = "ok"

    # ── Planning tool routing ────────────────────────────────────────
    # Build a synthesis brief once the goal is known; clarify if not.
    if intent == "planning" and bool(evidence.get("tool_call_requested")):
        goal = evidence.get("goal")
        if goal:
            action = "planning_create"
            tier = "ok"
        else:
            action = "clarify_goal"
            tier = "ok"

    # ── Calendar tool routing ────────────────────────────────────────
    # Route to calendar_query when date_start is known; ask otherwise.
    if intent == "calendar" and bool(evidence.get("tool_call_requested")):
        date_start = evidence.get("date_start")
        if date_start:
            action = "calendar_query"
            tier = "ok"
        else:
            action = "request_date_range"
            tier = "ok"

    # ── Trip planning routing ────────────────────────────────────────
    # Carry forward any trip fields extracted this turn (evidence wins
    # over accumulated state for non-null values).
    if intent == "trip":
        for _field in TRIP_CARRY_FIELDS:
            if evidence.get(_field) is not None:
                new_state[_field] = evidence[_field]

        _dest    = new_state.get("trip_destination")
        _origin  = new_state.get("trip_origin_airport")
        _d_start = new_state.get("trip_date_start")
        _d_end   = new_state.get("trip_date_end")
        _prefs   = new_state.get("trip_activity_preferences")
        _budget  = new_state.get("trip_budget_usd")
        _accom   = new_state.get("trip_accommodation_style")

        _missing_hard = [
            label for label, val in [
                ("destination",      _dest),
                ("travel dates",     _d_start),
                ("departure airport", _origin),
            ] if not val
        ]

        if _missing_hard:
            new_state["hard_fields_complete"] = False
            new_state["trip_missing_hard"] = _missing_hard
            action = "gather_trip_hard_invariants"
            tier = "ok"
        else:
            new_state["hard_fields_complete"] = True
            new_state["trip_missing_hard"] = []
            _trip_days = _compute_trip_days(_d_start, _d_end)
            _unknown_soft = sum([
                _prefs is None,
                _budget is None,
                _accom is None,
            ])
            if _trip_days is not None and _trip_days > 3 and _unknown_soft >= 2:
                new_state["trip_missing_soft"] = [
                    label for label, val in [
                        ("activity preferences", _prefs),
                        ("budget",               _budget),
                        ("accommodation style",  _accom),
                    ] if val is None
                ]
                action = "gather_trip_soft_details"
                tier = "ok"
            else:
                new_state["trip_missing_soft"] = []
                action = "trip_plan_create"
                tier = "ok"

    # ── Persona Update (if intent is persona, apply update_dict) ────
    current_persona = new_state.get("persona")
    if not isinstance(current_persona, PersonaState):
        current_persona = PersonaState()

    persona_update = evidence.get("persona_update")
    if intent == "persona" and persona_update:
        safe, _ = is_safe_persona(
            PersonaState.from_dict({**current_persona.to_dict(), **persona_update})
        )
        if safe:
            current_persona = update_persona(current_persona, persona_update)

    # Re-cap intensity for the active module
    module_persona = apply_intensity_cap(current_persona, target_module)
    persona_overlay = build_overlay(module_persona)

    new_state["persona"] = current_persona
    new_state["persona_overlay"] = persona_overlay

    return new_state, {
        "tier": tier,
        "action": action,
        "frustration": drift.is_fast_drift and drift.drift_axis == "valence",
        "suggested_module": target_module,
        "intent_type": intent,
        "affect": new_affect.to_dict(),
        "drift": drift.to_dict(),
        "persona": current_persona.to_dict(),
        "persona_overlay": persona_overlay.to_dict(),
    }


# ── 3. Turn Interpreter ─────────────────────────────────────────────

def _strip_markdown_fences(raw: str) -> str:
    """Remove ```json fences the SLM sometimes wraps around output."""
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[: cleaned.rfind("```")]
    return cleaned.strip()


def interpret_turn_input(
    call_llm: Callable[[str, str, str | None], str],
    input_text: str,
    task_context: dict[str, Any],
    prompt_text: str,
    default_fields: dict[str, Any] | None = None,
    tool_fns: dict[str, Callable[..., Any]] | None = None,
) -> dict[str, Any]:
    """Call the LLM to parse raw user text into structured evidence.

    Classifies intent and extracts task status, tool requirements,
    and satisfaction signals.
    """
    raw_response = call_llm(
        system=prompt_text,
        user=f"User message: {input_text}",
        model=None,
    )

    try:
        evidence = json.loads(_strip_markdown_fences(raw_response))
    except (json.JSONDecodeError, IndexError):
        evidence = {}

    # Merge defaults for any missing fields
    defaults = dict(default_fields or {})
    if not defaults:
        defaults = {
            "intent_type": "general",
            "task_status": "n/a",
            "tool_call_requested": False,
            "off_task_ratio": 0.0,
            "response_latency_sec": 5.0,
            "satisfaction_signal": "unknown",
        }

    for key, default_val in defaults.items():
        if key not in evidence or evidence[key] is None:
            evidence[key] = default_val

    # Validate intent_type
    valid_intents = {"general", "weather", "calendar", "search", "creative", "planning", "governance", "persona"}
    if evidence.get("intent_type") not in valid_intents:
        evidence["intent_type"] = "general"

    # Validate task_status
    valid_statuses = {"open", "completed", "abandoned", "deferred", "n/a"}
    if evidence.get("task_status") not in valid_statuses:
        evidence["task_status"] = "n/a"

    # Validate satisfaction_signal
    valid_signals = {"positive", "neutral", "negative", "unknown"}
    if evidence.get("satisfaction_signal") not in valid_signals:
        evidence["satisfaction_signal"] = "unknown"

    return evidence


# ── 4. Multi-Task Turn Interpreter ──────────────────────────────────────

def interpret_multi_task_input(
    call_llm: Callable[[str, str, str | None], str],
    input_text: str,
    task_context: dict[str, Any],
    prompt_text: str,
    default_fields: dict[str, Any] | None = None,
    tool_fns: dict[str, Callable[..., Any]] | None = None,
) -> dict[str, Any]:
    """Call the LLM to parse raw user text into a multi-task graph.

    Returns a dict with a ``tasks`` key containing a list of task nodes
    conforming to turn-task-graph-schema-v1.  Falls back to a one-node
    degenerate graph when the SLM does not emit a valid tasks array,
    preserving full backward compatibility with the single-task path.
    """
    raw_response = call_llm(
        system=prompt_text,
        user=f"User message: {input_text}",
        model=None,
    )

    try:
        result = json.loads(_strip_markdown_fences(raw_response))
    except (json.JSONDecodeError, IndexError):
        result = {}

    defaults = dict(default_fields or {})
    if not defaults:
        defaults = {
            "intent_type": "general",
            "task_status": "n/a",
            "tool_call_requested": False,
            "off_task_ratio": 0.0,
            "response_latency_sec": 5.0,
            "satisfaction_signal": "unknown",
        }

    valid_intents = {"general", "weather", "calendar", "search", "creative", "planning", "governance", "persona"}
    valid_statuses = {"open", "completed", "abandoned", "deferred", "n/a"}
    valid_signals = {"positive", "neutral", "negative", "unknown"}

    if isinstance(result.get("tasks"), list) and result["tasks"]:
        validated: list[dict[str, Any]] = []
        for i, task in enumerate(result["tasks"]):
            if not isinstance(task, dict):
                continue
            td: dict[str, Any] = dict(task.get("turn_data") or {})
            for key, val in defaults.items():
                if key not in td or td[key] is None:
                    td[key] = val
            if td.get("intent_type") not in valid_intents:
                td["intent_type"] = str(task.get("intent", "general"))
            if td.get("task_status") not in valid_statuses:
                td["task_status"] = "open"
            if td.get("satisfaction_signal") not in valid_signals:
                td["satisfaction_signal"] = "unknown"
            validated.append({
                "task_id": int(task.get("task_id", i + 1)),
                "intent": str(task.get("intent", td.get("intent_type", "general"))),
                "status": "pending",
                "blocked_by": list(task.get("blocked_by") or []),
                "turn_data": td,
            })
        if validated:
            return {"tasks": validated}

    # Fallback: treat the raw result as a single-task evidence dict and wrap it
    # in a one-node graph so the framework's graph extraction still works.
    for key, val in defaults.items():
        if key not in result or result[key] is None:
            result[key] = val
    if result.get("intent_type") not in valid_intents:
        result["intent_type"] = "general"
    if result.get("task_status") not in valid_statuses:
        result["task_status"] = "n/a"
    if result.get("satisfaction_signal") not in valid_signals:
        result["satisfaction_signal"] = "unknown"
    return {
        "tasks": [{
            "task_id": 1,
            "intent": str(result.get("intent_type", "general")),
            "status": "pending",
            "blocked_by": [],
            "turn_data": result,
        }]
    }
