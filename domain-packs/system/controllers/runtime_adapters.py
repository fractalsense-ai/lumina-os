from __future__ import annotations

import json
import logging
from typing import Any, Callable

log = logging.getLogger("lumina-system-adapter")

# Ordered mapping: query_type → resolved action name.
_QUERY_TYPE_ACTION_MAP: dict[str, str] = {
    "admin_command": "system_command",
    "status_query": "system_status",
    "diagnostic": "system_diagnostic",
    "config_review": "system_config_review",
    "out_of_domain": "out_of_domain",
    "glossary_lookup": "system_general",
    "general": "system_general",
}

# query_types that are candidates for structured command dispatch.
# Only write/mutation intents route to slm_parse_admin_command — read-only
# query types (status_query, diagnostic) must not trigger mutation dispatch.
_COMMAND_DISPATCH_TYPES: frozenset[str] = frozenset(
    {"admin_command", "config_review"}
)


def build_system_state(
    entity_profile: dict[str, Any],
    runtime_ctx: dict[str, Any] | None = None,
    session_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the initial (or restored) session state for a system-domain session.

    The system domain does not track learning curves, affect, or ZPD — the state
    is intentionally minimal: just a turn counter and the operator's profile fields.
    """
    prior = dict(session_state or {})
    return {
        "turn_count": int(prior.get("turn_count", 0)),
        "operator_id": entity_profile.get("operator_id", ""),
        "domain_id": entity_profile.get("domain_id", "domain/sys/system-core/v1"),
    }


def system_domain_step(
    state: dict[str, Any],
    task_spec: dict[str, Any],
    evidence: dict[str, Any],
    params: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Advance the system-domain session state by one turn.

    Maps the classified query_type to a concrete action code so the orchestrator
    can select the appropriate prompt template instead of defaulting to
    ``task_presentation``.
    """
    new_state = dict(state)
    new_state["turn_count"] = int(new_state.get("turn_count", 0)) + 1

    query_type: str = evidence.get("query_type") or "general"
    has_command_dispatch = bool(evidence.get("command_dispatch"))

    # A resolved structured command dispatch takes precedence over query_type.
    if has_command_dispatch:
        resolved_action = "system_command"
    else:
        resolved_action = _QUERY_TYPE_ACTION_MAP.get(query_type, "system_general")

    action: dict[str, Any] = {
        "tier": "ok",
        "action": resolved_action,
        "query_type": query_type,
        "target_component": evidence.get("target_component"),
        "command_dispatch": evidence.get("command_dispatch"),
    }
    return new_state, action


def _strip_markdown_fences(raw: str) -> str:
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
    call_slm: Callable[..., Any] | None = None,
    nlp_pre_interpreter_fn: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Classify the operator's message into a structured evidence dict.

    ``call_llm`` is expected to be the SLM callable for local-only domains;
    ``call_slm`` is accepted as an alias and also used for command dispatch.
    If ``nlp_pre_interpreter_fn`` is provided it is called before the SLM and
    its anchors are injected into the prompt as grounding context.
    """
    # ── NLP pre-interpreter (deterministic anchors) ───────────────────────
    context_hint = ""
    if nlp_pre_interpreter_fn is not None:
        try:
            nlp_evidence = nlp_pre_interpreter_fn(input_text, task_context)
        except Exception:  # noqa: BLE001
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
                lines.append("Use these as starting values. Override if your analysis disagrees.")
                context_hint = "\n" + "\n".join(lines)

            # Compound command: help the SLM pick a single operation
            if nlp_evidence.get("is_compound_command"):
                context_hint += (
                    "\nCompound command detected: pick only the single most"
                    " specific mutation operation."
                )

    raw_response = call_llm(
        system=prompt_text,
        user=f"Operator message: {input_text}{context_hint}",
        model=None,
    )

    try:
        evidence = json.loads(_strip_markdown_fences(raw_response))
    except (json.JSONDecodeError, IndexError):
        evidence = {}

    defaults: dict[str, Any] = dict(default_fields or {}) or {
        "query_type": "general",
        "target_component": None,
        "response_latency_sec": 5.0,
    }
    for key, default_val in defaults.items():
        if key not in evidence or evidence[key] is None:
            evidence[key] = default_val

    # Attempt structured command dispatch for query types that warrant it.
    # Prefer call_slm alias when provided so the caller can pass the same fn
    # without duplicating it; fall back to the _slm module helper.
    _dispatch_callable = call_slm or call_llm
    if evidence.get("query_type") in _COMMAND_DISPATCH_TYPES:
        try:
            from lumina.core.slm import slm_available, slm_parse_admin_command  # noqa: PLC0415

            if slm_available():
                evidence["command_dispatch"] = slm_parse_admin_command(input_text)
            else:
                evidence["command_dispatch"] = None
        except Exception:  # noqa: BLE001
            log.debug("command dispatch unavailable for input %r", input_text[:80])
            evidence["command_dispatch"] = None
    else:
        evidence["command_dispatch"] = None

    return evidence
