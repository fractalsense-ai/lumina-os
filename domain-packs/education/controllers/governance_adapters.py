"""Education governance adapters — state builder and domain step for non-learning roles.

Governance roles (domain_authority, teacher, teaching_assistant, guardian) use
these adapters instead of the learning-specific ZPD/fluency monitors.  The
pattern mirrors the system domain's ``build_system_state`` /
``system_domain_step`` in domain-packs/system/controllers/runtime_adapters.py.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable

log = logging.getLogger("lumina-education-governance-adapter")

# query_type → resolved action name for governance roles.
_QUERY_TYPE_ACTION_MAP: dict[str, str] = {
    "admin_command": "governance_command",
    "status_query": "governance_status",
    "progress_review": "governance_progress",
    "module_management": "governance_management",
    "escalation_review": "governance_escalation",
    "out_of_domain": "out_of_domain",
    "general": "governance_general",
}

# query_types routed to structured command dispatch.
_COMMAND_DISPATCH_TYPES: frozenset[str] = frozenset(
    {"admin_command", "module_management"}
)

# ── Deterministic fallback command parser ─────────────────────────────────
_READ_VERBS = frozenset({"show", "list", "get", "check", "view", "what", "status", "display", "find"})
_ASSIGN_VERBS = frozenset({"assign", "grant", "give"})
_REVOKE_VERBS = frozenset({"remove", "revoke", "delete"})
_DOMAIN_MENTION = re.compile(
    r"\b(?:in|to|for|from|of)\s+(?:the\s+)?(\w+)\s+domain\b", re.IGNORECASE,
)


def _strip_markdown_fences(text: str) -> str:
    """Remove markdown code fences from SLM output."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[: cleaned.rfind("```")]
    return cleaned.strip()


def _deterministic_command_fallback(
    input_text: str,
    nlp_evidence: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Build a command_dispatch dict from NLP anchors when SLM fails."""
    if nlp_evidence is None:
        return None
    tokens = input_text.lower().split()
    first_verb = tokens[0] if tokens else ""

    if first_verb in _READ_VERBS or any(v in tokens for v in _READ_VERBS):
        # Classify read operations
        if any(w in tokens for w in ("command", "commands")):
            return {"operation": "list_commands", "params": {}}
        if any(w in tokens for w in ("escalation", "escalations")):
            return {"operation": "list_escalations", "params": {}}
        if any(w in tokens for w in ("module", "modules")):
            return {"operation": "list_modules", "params": {}}
        if any(w in tokens for w in ("domain", "domains")):
            return {"operation": "list_domains", "params": {}}
        if any(w in tokens for w in ("role", "roles")):
            return {"operation": "list_domain_rbac_roles", "params": {}}
        if any(w in tokens for w in ("user", "users")):
            return {"operation": "list_domain_rbac_roles", "params": {}}
        return {"operation": "list_commands", "params": {}}

    if first_verb in _ASSIGN_VERBS:
        return {"operation": "assign_domain_role", "params": {}}
    if first_verb in _REVOKE_VERBS:
        return {"operation": "revoke_domain_role", "params": {}}

    return None


def build_governance_state(
    entity_profile: dict[str, Any],
    **kwargs: Any,
) -> dict[str, Any]:
    """Build session state for a governance role.

    No learning curves, affect tracking, or ZPD — just a minimal state dict
    with turn counter and operator identity.
    """
    return {
        "turn_count": 0,
        "operator_id": entity_profile.get("operator_id", entity_profile.get("subject_id", "")),
        "domain_id": entity_profile.get("domain_id", ""),
        "role": entity_profile.get("role", ""),
    }


def governance_domain_step(
    state: dict[str, Any],
    task_spec: dict[str, Any],
    evidence: dict[str, Any],
    params: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Advance governance session state by one turn.

    Maps the classified query_type to a concrete action code so the
    orchestrator produces a governance prompt template instead of falling
    back to ``task_presentation``.
    """
    new_state = dict(state)
    new_state["turn_count"] = int(new_state.get("turn_count", 0)) + 1

    query_type: str = evidence.get("query_type") or "general"
    has_command_dispatch = bool(evidence.get("command_dispatch"))

    if has_command_dispatch:
        resolved_action = "governance_command"
    else:
        resolved_action = _QUERY_TYPE_ACTION_MAP.get(query_type, "governance_general")

    action: dict[str, Any] = {
        "tier": "ok",
        "action": resolved_action,
        "query_type": query_type,
        "target_component": evidence.get("target_component"),
        "command_dispatch": evidence.get("command_dispatch"),
    }
    return new_state, action


# ─────────────────────────────────────────────────────────────
# Governance turn interpreter
# ─────────────────────────────────────────────────────────────

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
    """Classify the operator's governance message into structured evidence.

    Unlike the education learning interpreter, this does NOT build algebra
    context hints, run equation parsers, or inject world-sim state.  It
    produces governance-shaped evidence: query_type, command_dispatch,
    target_component, urgency.
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
                lines.append("Use these as starting values. Override if your analysis disagrees.")
                context_hint = "\n" + "\n".join(lines)

    # ── SLM classification ────────────────────────────────────
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
        "urgency": "routine",
        "response_latency_sec": 5.0,
        "off_task_ratio": 0.0,
    }
    for key, default_val in defaults.items():
        if key not in evidence or evidence[key] is None:
            evidence[key] = default_val

    # ── Structured command dispatch ───────────────────────────
    # For admin_command / module_management query types, run the SLM
    # command parser to get a structured operation dict.
    if evidence.get("query_type") in _COMMAND_DISPATCH_TYPES:
        try:
            from lumina.core.slm import slm_available, slm_parse_admin_command

            if slm_available():
                evidence["command_dispatch"] = slm_parse_admin_command(input_text)
            else:
                evidence["command_dispatch"] = None
        except Exception:
            log.debug("command dispatch unavailable for input %r", input_text[:80])
            evidence["command_dispatch"] = None

        # Deterministic fallback when SLM parsing fails
        if evidence["command_dispatch"] is None and nlp_evidence is not None:
            evidence["command_dispatch"] = _deterministic_command_fallback(
                input_text, nlp_evidence,
            )
    else:
        evidence["command_dispatch"] = None

    return evidence
