"""Freeform-module adapters for the education domain pack.

Contains the state builder, domain step, and turn interpreter for
the Student Commons (general-education) module.  No ZPD monitoring,
fluency tracking, or academic grading — journaling and reflection only.

Vocabulary growth tracking is wired in as a passive subsystem: the
client-side analyzer posts a complexity score which flows through
evidence into ``freeform_domain_step`` and is processed by
``vocabulary_growth_step()``.
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any, Callable


# ── Load vocabulary growth monitor from domain-lib ─────────────
def _load_vocab_monitor() -> Any:
    """Load the vocabulary growth monitor module via importlib (same
    pattern as the ZPD monitor shim)."""
    lib_path = (
        Path(__file__).resolve().parent.parent
        / "domain-lib"
        / "vocabulary_growth_monitor_v0_1.py"
    )
    mod_name = "vocabulary_growth_monitor_v0_1"
    if mod_name in sys.modules:
        return sys.modules[mod_name]
    spec = importlib.util.spec_from_file_location(mod_name, str(lib_path))
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


_vocab_mod = _load_vocab_monitor()
vocabulary_growth_step = _vocab_mod.vocabulary_growth_step
_build_default_vocab_state = _vocab_mod._build_default_vocab_state


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

    Three-tier state priority:
      1. DB-backed ``module_state`` (returning student)
      2. ``initial_module_state`` from runtime-config (first time in module)
      3. Profile / empty fallback (backward-compat)
    """
    _module_state = kwargs.get("module_state")
    if isinstance(_module_state, dict) and _module_state:
        _src = _module_state
    elif isinstance(kwargs.get("initial_module_state"), dict) and kwargs.get("initial_module_state"):
        _src = dict(kwargs["initial_module_state"])
    else:
        _modules = profile.get("modules")
        _src = (_modules if isinstance(_modules, dict) else {}).get(
            profile.get("domain_id", ""), {}
        )
    return {
        "turn_count": 0,
        "journaling_entry_count": int(
            _src.get("journaling_entry_count", 0)
        ),
        "last_reflection_utc": _src.get("last_reflection_utc"),
        "vocabulary_tracking": _src.get(
            "vocabulary_tracking",
            _build_default_vocab_state(),
        ),
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

    decision: dict[str, Any] = {
        "tier": "ok",
        "action": action,
        "should_escalate": False,
    }

    # ── Baseline-before-escalation gate (vocabulary subsystem) ─
    # While the vocabulary baseline is still priming, suppress any
    # metric-driven escalation.  The vocabulary growth monitor tracks
    # ``baseline_sessions_remaining``; deltas are meaningless until it
    # reaches zero and the baseline locks.
    vocab_state = state.get("vocabulary_tracking") or {}
    if int(vocab_state.get("baseline_sessions_remaining", 3)) > 0:
        decision["escalation_eligible"] = False

    # ── Vocabulary growth tracking (passive subsystem) ────────
    vocab_score = evidence.get("vocabulary_complexity_score")
    if vocab_score is not None:
        vocab_state = state.get("vocabulary_tracking") or _build_default_vocab_state()
        # Extract vocabulary-relevant evidence subset
        vocab_evidence = {
            "vocabulary_complexity_score": vocab_score,
            "measurement_valid": evidence.get("measurement_valid", True),
            "buffer_turns": evidence.get("buffer_turns", 0),
            "domain_terms_detected": evidence.get("domain_terms_detected"),
            "lexical_diversity": evidence.get("lexical_diversity"),
            "avg_word_length": evidence.get("avg_word_length"),
            "embedding_spread": evidence.get("embedding_spread"),
        }
        vocab_params = params.get("vocabulary_monitor") if params else None
        vocab_state, vocab_decision = vocabulary_growth_step(
            vocab_state, vocab_evidence, vocab_params,
        )
        state["vocabulary_tracking"] = vocab_state
        decision["vocabulary"] = vocab_decision

    return state, decision


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
