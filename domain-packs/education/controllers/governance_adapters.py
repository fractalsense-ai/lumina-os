"""Education governance adapters — state builder and domain step for non-learning roles.

Governance roles (domain_authority, teacher, teaching_assistant, guardian) use
these adapters instead of the learning-specific ZPD/fluency monitors.  The
pattern mirrors the system domain's ``build_system_state`` /
``system_domain_step`` in domain-packs/system/controllers/runtime_adapters.py.

See also:
    docs/7-concepts/llm-assisted-governance-adapters.md
    docs/7-concepts/slm-compute-distribution.md
    docs/7-concepts/domain-adapter-pattern.md
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
# See: docs/7-concepts/nlp-semantic-router.md
_READ_VERBS = frozenset({"show", "list", "get", "check", "view", "what", "status", "display", "find"})
_ASSIGN_VERBS = frozenset({"assign", "grant", "give"})
_REVOKE_VERBS = frozenset({"remove", "revoke", "delete"})
_INGEST_VERBS = frozenset({"ingest", "upload", "import"})
_INVITE_VERBS = frozenset({"invite", "create", "add", "onboard"})
_MODIFY_VERBS = frozenset({"modify", "update", "change", "edit"})
_DEACTIVATE_VERBS = frozenset({"deactivate", "disable", "suspend"})
_USER_NOUNS = frozenset({"user", "users", "student", "students", "teacher", "teachers",
                         "ta", "assistant", "parent", "guardian"})
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
    # See: docs/7-concepts/command-execution-pipeline.md
    # See: docs/7-concepts/domain-role-hierarchy.md
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
        if any(w in tokens for w in ("user", "users")):
            return {"operation": "list_users", "params": {}}
        if any(w in tokens for w in ("role", "roles")):
            return {"operation": "list_domain_rbac_roles", "params": {}}
        if any(w in tokens for w in ("physics",)):
            _dm = _DOMAIN_MENTION.search(input_text)
            _p: dict[str, Any] = {}
            if _dm:
                _p["domain_id"] = _dm.group(1)
            return {"operation": "get_domain_physics", "params": _p}
        return {"operation": "list_commands", "params": {}}

    # ── Invite / create user ──────────────────────────────────
    # See: docs/7-concepts/domain-role-hierarchy.md
    # See: docs/7-concepts/domain-adapter-pattern.md
    if first_verb in _INVITE_VERBS or any(v in tokens for v in _INVITE_VERBS):
        if any(w in tokens for w in _USER_NOUNS):
            _dm = _DOMAIN_MENTION.search(input_text)
            _p: dict[str, Any] = {}
            if _dm:
                _p["domain_id"] = _dm.group(1)
            return {"operation": "invite_user", "params": _p}

    # ── Modify user role ──────────────────────────────────────
    if first_verb in _MODIFY_VERBS or any(v in tokens for v in _MODIFY_VERBS):
        if any(w in tokens for w in ("role", "roles")) or any(w in tokens for w in _USER_NOUNS):
            return {"operation": "assign_domain_role", "params": {}}

    # ── Deactivate user ───────────────────────────────────────
    if first_verb in _DEACTIVATE_VERBS or any(v in tokens for v in _DEACTIVATE_VERBS):
        if any(w in tokens for w in _USER_NOUNS):
            return {"operation": "deactivate_user", "params": {}}

    if first_verb in _ASSIGN_VERBS:
        return {"operation": "assign_domain_role", "params": {}}
    if first_verb in _REVOKE_VERBS:
        return {"operation": "revoke_domain_role", "params": {}}

    # ── Ingestion operations ──────────────────────────────────
    if first_verb in _INGEST_VERBS or any(v in tokens for v in _INGEST_VERBS):
        if any(w in tokens for w in ("document", "file", "doc", "pdf", "upload")):
            return {"operation": "list_ingestions", "params": {}}
        return {"operation": "list_ingestions", "params": {}}
    if any(w in tokens for w in ("ingestion", "ingestions", "ingested")):
        if any(w in tokens for w in ("approve", "accept")):
            return {"operation": "approve_interpretation", "params": {}}
        if any(w in tokens for w in ("reject", "deny")):
            return {"operation": "reject_ingestion", "params": {}}
        if any(w in tokens for w in ("review",)):
            return {"operation": "review_ingestion", "params": {}}
        return {"operation": "list_ingestions", "params": {}}

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
    # Governance turn classification is a LOW-weight task — prefer the
    # local SLM when available to avoid unnecessary LLM round-trips.
    # See: docs/7-concepts/slm-compute-distribution.md
    _classify = call_slm or call_llm
    raw_response = _classify(
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


# ─────────────────────────────────────────────────────────────
# LLM-assisted physics patch extraction
# ─────────────────────────────────────────────────────────────

_PHYSICS_PATCH_SYSTEM_PROMPT = """\
You are a domain-physics patch generator for Project Lumina.
Given the operator's natural-language instruction and a snapshot of the
current domain-physics.json, produce a JSON object with these fields:

{
  "target_section": "<invariants|standing_orders|escalation_triggers|subsystem_configs|glossary|artifacts|ingestion_config|tool_adapters|other>",
  "operation_type": "<add|modify|remove>",
  "proposed_patch": { "<field>": <new_value>, ... },
  "affected_ids": ["<id_of_affected_entry>", ...],
  "diff_summary": "<one-sentence human-readable summary of what changed>",
  "confidence": <0.0-1.0>
}

Rules:
- proposed_patch must be a dict whose keys are top-level domain-physics
  fields (e.g. "invariants", "standing_orders").  Values are the COMPLETE
  replacement for that field, not a partial merge.
- For list-typed sections (invariants, standing_orders, escalation_triggers,
  glossary, artifacts), include the FULL updated list with the change applied.
- For "add" operations, append the new entry to the existing list.
- For "modify" operations, include the full list with the target entry updated.
- For "remove" operations, include the full list with the target entry removed.
- affected_ids lists the IDs of entries that were added, modified, or removed.
- Keep confidence between 0.5 and 1.0.  Use lower values when the
  instruction is ambiguous.
- Return ONLY valid JSON.  No markdown fences.  No commentary.
"""


def extract_physics_patch(
    call_llm: Callable[[str, str, str | None], str],
    input_text: str,
    domain_physics: dict[str, Any],
) -> dict[str, Any]:
    """Use the LLM to interpret a natural-language physics edit instruction.

    Args:
        call_llm:       ``(system, user, model) -> str`` callable.
        input_text:     The operator's natural-language instruction.
        domain_physics: Current domain-physics.json dict.

    Returns:
        A proposal dict with ``target_section``, ``operation_type``,
        ``proposed_patch``, ``affected_ids``, ``diff_summary``, ``confidence``.
        On failure returns a minimal fallback with confidence 0.
    """
    # Build a compact physics snapshot — omit large sections the LLM
    # doesn't need (permissions, groups, execution_policy, etc.)
    _sections_for_context = (
        "invariants", "standing_orders", "escalation_triggers",
        "subsystem_configs", "glossary", "artifacts", "ingestion_config",
        "tool_adapters",
    )
    snapshot: dict[str, Any] = {
        "id": domain_physics.get("id", ""),
        "version": domain_physics.get("version", ""),
    }
    for section in _sections_for_context:
        if section in domain_physics:
            val = domain_physics[section]
            # Truncate large lists to keep token count manageable.
            if isinstance(val, list) and len(val) > 30:
                snapshot[section] = val[:30]
            else:
                snapshot[section] = val

    user_prompt = (
        f"Operator instruction: {input_text}\n\n"
        f"Current domain-physics.json (relevant sections):\n"
        f"{json.dumps(snapshot, indent=2, ensure_ascii=False)}"
    )

    try:
        raw = call_llm(_PHYSICS_PATCH_SYSTEM_PROMPT, user_prompt, None)
        proposal = json.loads(_strip_markdown_fences(raw))
    except (json.JSONDecodeError, Exception) as exc:
        log.warning("LLM physics patch extraction failed: %s", exc)
        proposal = {}

    # Apply defaults for missing fields.
    proposal.setdefault("target_section", "other")
    proposal.setdefault("operation_type", "modify")
    proposal.setdefault("proposed_patch", {})
    proposal.setdefault("affected_ids", [])
    proposal.setdefault("diff_summary", input_text[:200])
    proposal.setdefault("confidence", 0.0)

    return proposal


# ─────────────────────────────────────────────────────────────
# Novel synthesis detection for physics edits
# ─────────────────────────────────────────────────────────────

# Sections whose entries carry an ``id`` field — additions to these
# sections are potentially novel synthesis events.
_ID_BEARING_SECTIONS: frozenset[str] = frozenset(
    {"invariants", "standing_orders", "escalation_triggers", "glossary", "artifacts"}
)


def detect_novel_synthesis(
    proposal: dict[str, Any],
    domain_physics: dict[str, Any],
) -> list[str]:
    """Check whether a physics edit proposal introduces genuinely new entries.

    Returns a list of IDs that are new (not present in the current physics).
    An empty list means no novel synthesis detected.
    """
    if proposal.get("operation_type") != "add":
        return []

    target_section = proposal.get("target_section", "other")
    if target_section not in _ID_BEARING_SECTIONS:
        return []

    patch = proposal.get("proposed_patch", {})
    proposed_list = patch.get(target_section)
    if not isinstance(proposed_list, list):
        return []

    existing_list = domain_physics.get(target_section) or []
    existing_ids = {
        entry.get("id") or entry.get("term", "")
        for entry in existing_list
        if isinstance(entry, dict)
    }

    novel_ids: list[str] = []
    for entry in proposed_list:
        if not isinstance(entry, dict):
            continue
        entry_id = entry.get("id") or entry.get("term", "")
        if entry_id and entry_id not in existing_ids:
            novel_ids.append(entry_id)

    return novel_ids
