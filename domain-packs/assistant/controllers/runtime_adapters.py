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
from typing import Any, Callable

# Intent → module ID mapping for routing decisions.
INTENT_TO_MODULE: dict[str, str] = {
    "general": "domain/asst/conversation/v1",
    "weather": "domain/asst/weather/v1",
    "calendar": "domain/asst/calendar/v1",
    "search": "domain/asst/search/v1",
    "creative": "domain/asst/creative-writing/v1",
    "planning": "domain/asst/planning/v1",
    "governance": "domain/asst/domain-authority/v1",
}


# ── 1. State Builder ─────────────────────────────────────────────────

def build_initial_state(profile: dict[str, Any]) -> dict[str, Any]:
    """Build the initial session state from an entity profile.

    Called once at session start.  The returned dict becomes the `state`
    argument to every subsequent `domain_step` call.
    """
    entity_state = profile.get("entity_state") or {}
    return {
        "turn_count": 0,
        "idle_turn_count": 0,
        "active_intent": "general",
        "active_task_id": entity_state.get("active_task_id"),
        "active_task_type": entity_state.get("active_task_type"),
        "task_history": [],
        "satisfaction_trend": [],
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
    whether to suggest a module switch. Tracks task lifecycle and
    idle-turn counting for the idle_prompt_offer standing order.
    """
    new_state = dict(state)
    new_state["turn_count"] = new_state.get("turn_count", 0) + 1

    intent = str(evidence.get("intent_type", "general"))
    task_status = str(evidence.get("task_status", "n/a"))
    satisfaction = str(evidence.get("satisfaction_signal", "unknown"))

    # Track intent for routing
    new_state["active_intent"] = intent

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

    # Satisfaction trend (keep last 10)
    trend = list(new_state.get("satisfaction_trend") or [])
    trend.append(satisfaction)
    new_state["satisfaction_trend"] = trend[-10:]

    # Determine tier
    idle_count = new_state.get("idle_turn_count", 0)
    window = int(params.get("drift_threshold_turns", 3))
    if idle_count >= window:
        tier = "minor"
        action = "idle_prompt_offer"
    else:
        tier = "ok"
        action = None

    # Module routing suggestion
    target_module = INTENT_TO_MODULE.get(intent, "domain/asst/conversation/v1")

    return new_state, {
        "tier": tier,
        "action": action,
        "frustration": False,
        "suggested_module": target_module,
        "intent_type": intent,
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
    valid_intents = {"general", "weather", "calendar", "search", "creative", "planning", "governance"}
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
