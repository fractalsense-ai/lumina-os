"""Freeform-module adapters for the education domain pack.

Contains the state builder, domain step, and turn interpreter for
the Student Commons (general-education) module.  No ZPD monitoring,
fluency tracking, or academic grading — journaling and reflection only.
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable


def _strip_markdown_fences(raw: str) -> str:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[: cleaned.rfind("```")]
    return cleaned.strip()


def freeform_build_initial_state(
    profile: dict[str, Any],
    **kwargs: Any,
) -> dict[str, Any]:
    """Build session state for a free-form module (e.g. Student Commons).

    No learning curves, affect tracking, ZPD, fluency, or mastery — just
    minimal state for journaling / reflection tracking.  Shape matches
    ``module_state_schema.custom_fields`` in general-education physics.
    """
    # Module-keyed state takes priority over flat learning_state
    _modules = profile.get("modules")
    _module_state = (_modules if isinstance(_modules, dict) else {}).get(
        profile.get("domain_id", ""), {}
    )
    return {
        "turn_count": 0,
        "journaling_entry_count": int(
            _module_state.get("journaling_entry_count", 0)
        ),
        "last_reflection_utc": _module_state.get("last_reflection_utc"),
    }


def freeform_domain_step(
    state: Any,
    task_spec: dict[str, Any],
    evidence: dict[str, Any],
    params: dict[str, Any],
) -> tuple[Any, dict[str, Any]]:
    """Domain-lib step for free-form modules (e.g. Student Commons).

    Skips ZPD monitoring, fluency tracking, and academic grading entirely.
    Maps the turn interpreter's ``intent_type`` to a ``resolved_action`` so
    that user commands route through command dispatch and tool requests
    route through ``apply_tool_call_policy()``.
    """
    intent = evidence.get("intent_type")
    if intent == "command":
        action = "user_command"
    elif intent == "tool_request":
        action = "tool_request"
    else:
        action = None
    return state, {"tier": "ok", "action": action, "should_escalate": False}


# ── User-command detection (deterministic) ─────────────────────
_USER_COMMAND_PATTERNS: dict[str, re.Pattern[str]] = {
    "request_module_assignment": re.compile(
        r"\b(assign|enroll|start|begin|join|take|register)\b.*\b(module|course|class|subject)\b"
        r"|\b(module|course|class|subject)\b.*\b(assign|enroll|start|begin|join|take|register)\b",
        re.IGNORECASE,
    ),
    "view_available_modules": re.compile(
        r"\b(list|show|what|available|browse|see)\b.*\b(module|course|class|subject)s?\b"
        r"|\bmodules?\b.*\b(available|can i take|options)\b",
        re.IGNORECASE,
    ),
    "view_my_profile": re.compile(
        r"\b(my|show|view|see)\b.*\b(profile|account|info|progress|stats)\b"
        r"|\bprofile\b",
        re.IGNORECASE,
    ),
}


def _detect_user_command(
    input_text: str,
) -> dict[str, Any] | None:
    """Return a command_dispatch dict if the input matches a user command."""
    for cmd_name, pattern in _USER_COMMAND_PATTERNS.items():
        if pattern.search(input_text):
            return {"operation": cmd_name}
    return None


# ── Freeform turn interpreter ──────────────────────────────────

def freeform_interpret_turn_input(
    call_llm: Callable[[str, str, str | None], str],
    input_text: str,
    task_context: dict[str, Any],
    prompt_text: str,
    default_fields: dict[str, Any] | None = None,
    tool_fns: dict[str, Callable[..., Any]] | None = None,
    call_slm: Callable[..., Any] | None = None,
    nlp_pre_interpreter_fn: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Classify a free-form student message into structured evidence.

    Unlike the learning ``interpret_turn_input``, this does NOT build
    algebra context hints, call ``algebra_parser`` proactively, or inject
    world-sim/MUD state.  It produces conversational evidence:
    ``intent_type``, ``off_task_ratio``, ``frustration_marker_count``,
    ``response_latency_sec``, plus optional ``command_dispatch`` for
    student commands (request_module_assignment, view_available_modules,
    view_my_profile).

    Tools remain available through the policy-driven
    ``apply_tool_call_policy()`` path — they are not stripped, just not
    called proactively here.
    """
    # ── NLP pre-interpreter (deterministic anchors) ───────────
    context_hint = ""
    nlp_evidence: dict[str, Any] | None = None
    if nlp_pre_interpreter_fn is not None:
        try:
            nlp_evidence = nlp_pre_interpreter_fn(input_text, task_context)
        except Exception:
            nlp_evidence = None

        if nlp_evidence is not None:
            anchors = nlp_evidence.get("_nlp_anchors") or []
            if anchors:
                lines = ["\nNLP pre-analysis (deterministic):"]
                for a in anchors:
                    line = f"- {a['field']}: {a['value']}"
                    if "confidence" in a:
                        line += f" (confidence: {a['confidence']})"
                    if "detail" in a:
                        line += f" — {a['detail']}"
                    lines.append(line)
                lines.append(
                    "Use these as starting values. Override if your analysis disagrees."
                )
                context_hint = "\n" + "\n".join(lines)

    # ── SLM classification (lightweight) ──────────────────────
    _classify = call_slm or call_llm
    raw_response = _classify(
        system=prompt_text,
        user=f"Student message: {input_text}{context_hint}",
        model=None,
    )

    try:
        evidence = json.loads(_strip_markdown_fences(raw_response))
    except (json.JSONDecodeError, IndexError):
        evidence = {}

    # ── Merge defaults ────────────────────────────────────────
    defaults: dict[str, Any] = dict(default_fields or {}) or {
        "intent_type": "journaling",
        "off_task_ratio": 0.0,
        "frustration_marker_count": 0,
        "response_latency_sec": 5.0,
        "correctness": "n/a",
        "problem_solved": False,
    }
    for key, default_val in defaults.items():
        if key not in evidence or evidence[key] is None:
            evidence[key] = default_val

    # ── Deterministic user-command detection ─────────────────
    cmd = _detect_user_command(input_text)
    if cmd is not None:
        evidence["intent_type"] = "command"
        evidence["command_dispatch"] = cmd
    else:
        evidence.setdefault("command_dispatch", None)

    # ── Preserve tool_expression for policy routing ─────────
    evidence.setdefault("tool_expression", None)

    return evidence
