"""Response assembly: escalation cards, holodeck data, result dict.

See also:
    docs/7-concepts/zero-trust-architecture.md
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("lumina-api")


# ---------------------------------------------------------------------------
# Escalation card
# ---------------------------------------------------------------------------

def build_escalation_content(
    session_id: str,
    orchestrator: Any,
    resolved_domain_id: str,
    runtime: dict[str, Any],
    active_mod: dict[str, Any],
) -> tuple[bool, dict[str, Any] | None]:
    """Detect escalation and build card if raised this turn.

    Returns ``(escalated, structured_content)``.  ``structured_content``
    is *None* when no escalation occurred.
    """
    escalated = any(
        r.get("record_type") == "EscalationRecord"
        and r.get("session_id") == session_id
        for r in orchestrator.log_records[-2:]
    )
    if not escalated:
        return False, None

    from lumina.api.structured_content import build_escalation_card

    esc_records = [
        r
        for r in orchestrator.log_records[-2:]
        if r.get("record_type") == "EscalationRecord"
        and r.get("session_id") == session_id
    ]
    if not esc_records:
        return True, None

    # ── Domain hook for actor identity context ────────────────
    # Domains declare an escalation_context_fn to supply actor pseudonym
    # and other identity fields without hard-coding profile paths.
    _esc_ctx_fn = active_mod.get("escalation_context_fn") or runtime.get(
        "escalation_context_fn",
    )
    if _esc_ctx_fn is not None:
        session_ctx = _esc_ctx_fn(
            orchestrator=orchestrator,
            domain_id=resolved_domain_id,
        )
    else:
        # Generic fallback: extract actor_pseudonym from orchestrator profile
        _actor_pseudonym = ""
        if hasattr(orchestrator, "_writer"):
            _actor_pseudonym = orchestrator._writer._profile.get(
                "subject_id",
                orchestrator._writer._profile.get("student_id", ""),
            )
        session_ctx = {
            "domain_id": resolved_domain_id,
            "actor_pseudonym": _actor_pseudonym,
        }

    content = build_escalation_card(esc_records[-1], session_context=session_ctx)
    return True, content


# ---------------------------------------------------------------------------
# Holodeck evidence attachment
# ---------------------------------------------------------------------------

def attach_holodeck_data(
    result: dict[str, Any],
    orchestrator: Any,
    turn_data: dict[str, Any],
    inspection_result: Any,
    world_sim_theme: dict[str, Any],
    mud_world_state: dict[str, Any],
) -> dict[str, Any]:
    """Attach raw structured holodeck evidence to the result dict.

    Mutates and returns *result*.
    """
    import dataclasses as _dc

    state_obj = orchestrator.state
    if _dc.is_dataclass(state_obj) and not isinstance(state_obj, type):
        state_snap = _dc.asdict(state_obj)
    elif isinstance(state_obj, dict):
        state_snap = dict(state_obj)
    else:
        state_snap = {}

    holodeck_data: dict[str, Any] = {
        "state_snapshot": state_snap,
        "inspection_result": inspection_result.to_dict(),
        "invariant_checks": inspection_result.invariant_results,
        "evidence": turn_data,
        "world_sim_active": bool(mud_world_state.get("zone")),
        "mud_world_state": mud_world_state or None,
    }

    if result.get("structured_content") is None:
        result["structured_content"] = {}
    result["structured_content"]["holodeck"] = holodeck_data
    return result


# ---------------------------------------------------------------------------
# Result dict builder
# ---------------------------------------------------------------------------

def build_result(
    llm_response: str,
    resolved_action: str,
    prompt_contract: dict[str, Any],
    escalated: bool,
    tool_results: dict[str, Any] | None,
    resolved_domain_id: str,
    structured_content: dict[str, Any] | None,
    session_id: str,
    session_containers: dict,
    seal: str | None,
    seal_meta: dict[str, Any] | None,
    transcript: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Assemble the final response dict returned by process_message."""
    result: dict[str, Any] = {
        "response": llm_response,
        "action": resolved_action,
        "prompt_type": prompt_contract.get("prompt_type", "task_presentation"),
        "escalated": escalated,
        "tool_results": tool_results,
        "domain_id": resolved_domain_id,
    }

    # Override action when the session was auto-frozen during this turn
    if escalated:
        container = session_containers.get(session_id)
        if container is not None and container.frozen:
            result["action"] = "session_frozen"

    if seal is not None:
        result["transcript_seal"] = seal
        result["transcript_seal_metadata"] = seal_meta
        result["transcript_snapshot"] = transcript

    if structured_content is not None:
        result["structured_content"] = structured_content

    return result
