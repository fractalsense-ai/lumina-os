"""Structured content builders for chat action cards.

Factory functions that populate ``ChatResponse.structured_content``
(historically always ``None``).  Two card types are supported:

- **escalation** — surfaces an EscalationRecord to the session
  supervisor (teacher) or domain authority so they can approve / reject /
  defer directly in the chat interface.
- **command_proposal** — surfaces a staged HITL admin command so the
  authority can accept / reject / modify it inline.
"""

from __future__ import annotations

from typing import Any


# ── Action definitions ────────────────────────────────────────

_ESCALATION_ACTIONS: list[dict[str, str]] = [
    {"id": "approve", "label": "Approve", "style": "primary"},
    {"id": "reject", "label": "Reject", "style": "destructive"},
    {"id": "defer", "label": "Defer", "style": "ghost"},
]

_COMMAND_ACTIONS: list[dict[str, str]] = [
    {"id": "accept", "label": "Accept", "style": "primary"},
    {"id": "reject", "label": "Reject", "style": "destructive"},
    {"id": "modify", "label": "Modify", "style": "outline"},
]

_PHYSICS_EDIT_ACTIONS: list[dict[str, str]] = [
    {"id": "accept", "label": "Accept & Stage", "style": "primary"},
    {"id": "modify", "label": "Modify", "style": "outline"},
    {"id": "reject", "label": "Reject", "style": "destructive"},
]


# ── Builders ──────────────────────────────────────────────────

def build_escalation_card(
    escalation_record: dict[str, Any],
    session_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a structured action card for an escalation event.

    Args:
        escalation_record: The EscalationRecord dict from the System Log.
        session_context:   Optional dict with session summary info
                           (domain, student pseudonym, turn count).

    Returns:
        A dict conforming to the action-card-schema-v1 JSON Schema.
    """
    record_id = escalation_record.get("record_id", "")
    trigger = escalation_record.get("trigger", "unknown")
    sla = escalation_record.get("sla_minutes", 30)
    domain_decision = escalation_record.get("domain_lib_decision") or {}
    target_role = escalation_record.get("target_role", "domain_authority")

    ctx: dict[str, Any] = {
        "trigger": trigger,
        "sla_minutes": sla,
        "target_role": target_role,
        "session_id": escalation_record.get("session_id", ""),
        "actor_id": escalation_record.get("actor_id", ""),
        "domain_lib_tier": domain_decision.get("tier"),
        "domain_alert_flag": domain_decision.get("domain_alert_flag"),
    }
    if session_context:
        ctx["domain_id"] = session_context.get("domain_id", "")
        ctx["turn_count"] = session_context.get("turn_count")
        ctx["student_pseudonym"] = session_context.get("student_pseudonym", "")

    body = f"Escalation triggered: {trigger}"
    if sla:
        body += f" (SLA: {sla} min)"
    if domain_decision.get("domain_alert_flag"):
        body += f" — alert: {domain_decision['domain_alert_flag']}"

    return {
        "type": "action_card",
        "card_type": "escalation",
        "id": record_id,
        "title": "Escalation Alert",
        "body": body,
        "context": ctx,
        "actions": list(_ESCALATION_ACTIONS),
        "resolve_endpoint": f"/api/escalations/{record_id}/resolve",
        "metadata": {
            "timestamp_utc": escalation_record.get("timestamp_utc", ""),
            "task_id": escalation_record.get("task_id", ""),
            "assigned_room_id": escalation_record.get("assigned_room_id"),
            "escalation_target_id": escalation_record.get("escalation_target_id"),
        },
    }


def build_command_proposal_card(
    staged_command: dict[str, Any],
) -> dict[str, Any]:
    """Build a structured action card for a staged HITL command.

    Args:
        staged_command: The staged command entry from ``_STAGED_COMMANDS``.

    Returns:
        A dict conforming to the action-card-schema-v1 JSON Schema.
    """
    staged_id = staged_command.get("staged_id", "")
    parsed = staged_command.get("parsed_command") or {}
    operation = parsed.get("operation", "unknown")
    params = parsed.get("params") or {}
    original = staged_command.get("original_instruction", "")

    body = f"Admin command: {operation}"
    if original:
        body += f'\nInstruction: "{original[:200]}"'
    if params:
        summary_items = [f"{k}={v}" for k, v in list(params.items())[:5]]
        body += f"\nParams: {', '.join(summary_items)}"

    return {
        "type": "action_card",
        "card_type": "command_proposal",
        "id": staged_id,
        "title": "Command Proposal",
        "body": body,
        "context": {
            "operation": operation,
            "params": params,
            "target": parsed.get("target", ""),
            "original_instruction": original,
            "actor_id": staged_command.get("actor_id", ""),
            "expires_at": staged_command.get("expires_at"),
        },
        "actions": list(_COMMAND_ACTIONS),
        "resolve_endpoint": f"/api/admin/command/{staged_id}/resolve",
        "metadata": {
            "staged_at": staged_command.get("staged_at"),
            "expires_at": staged_command.get("expires_at"),
            "log_stage_record_id": staged_command.get("log_stage_record_id", ""),
        },
    }


def build_physics_edit_card(
    staged_command: dict[str, Any],
    proposal: dict[str, Any],
    domain_physics: dict[str, Any],
    requires_escalation: bool = False,
    escalation_record_id: str | None = None,
) -> dict[str, Any]:
    """Build a structured action card for an LLM-assisted physics edit proposal.

    Args:
        staged_command:       The staged command entry from ``_STAGED_COMMANDS``.
        proposal:             The LLM-generated proposal dict with keys
                              ``target_section``, ``operation_type``,
                              ``proposed_patch``, ``diff_summary``,
                              ``affected_ids``, ``confidence``.
        domain_physics:       Current domain-physics.json snapshot.
        requires_escalation:  Whether the proposing actor is below DA level.
        escalation_record_id: EscalationRecord ID for teacher/TA proposals.

    Returns:
        A dict conforming to the physics-edit-proposal-schema-v1 JSON Schema.
    """
    staged_id = staged_command.get("staged_id", "")
    parsed = staged_command.get("parsed_command") or {}
    original = staged_command.get("original_instruction", "")
    domain_id = (parsed.get("params") or {}).get("domain_id", "")
    target_section = proposal.get("target_section", "other")

    body = f"Proposed physics edit: {proposal.get('diff_summary', original[:200])}"
    if requires_escalation:
        body += "\n⚠ This proposal requires Domain Authority approval."

    # Snapshot the target section for diff rendering.
    current_snapshot: dict[str, Any] = {}
    if target_section != "other" and target_section in domain_physics:
        section_val = domain_physics[target_section]
        # For list sections, keep only the first 20 entries to bound card size.
        if isinstance(section_val, list):
            current_snapshot[target_section] = section_val[:20]
        elif isinstance(section_val, dict):
            current_snapshot[target_section] = section_val
        else:
            current_snapshot[target_section] = section_val

    ctx: dict[str, Any] = {
        "domain_id": domain_id,
        "target_section": target_section,
        "operation_type": proposal.get("operation_type", "modify"),
        "proposed_patch": proposal.get("proposed_patch", {}),
        "affected_ids": proposal.get("affected_ids") or [],
        "current_snapshot": current_snapshot,
        "diff_summary": proposal.get("diff_summary", ""),
        "confidence": proposal.get("confidence", 0.0),
        "actor_id": staged_command.get("actor_id", ""),
        "actor_role": staged_command.get("actor_role", ""),
        "requires_escalation": requires_escalation,
        "original_instruction": original,
    }
    if escalation_record_id:
        ctx["escalation_record_id"] = escalation_record_id

    return {
        "type": "action_card",
        "card_type": "physics_edit_proposal",
        "id": staged_id,
        "title": "Physics Edit Proposal",
        "body": body,
        "context": ctx,
        "actions": list(_PHYSICS_EDIT_ACTIONS),
        "resolve_endpoint": f"/api/admin/command/{staged_id}/resolve",
        "metadata": {
            "staged_at": staged_command.get("staged_at"),
            "expires_at": staged_command.get("expires_at"),
            "log_stage_record_id": staged_command.get("log_stage_record_id", ""),
        },
    }


# ── Ingestion review actions ─────────────────────────────────

_INGESTION_REVIEW_ACTIONS: list[dict[str, str]] = [
    {"id": "approve", "label": "Approve Interpretation", "style": "primary"},
    {"id": "reject", "label": "Reject", "style": "destructive"},
]


def build_ingestion_review_card(
    ingestion_record: dict[str, Any],
) -> dict[str, Any]:
    """Build a structured action card for reviewing an ingestion record.

    Args:
        ingestion_record: An IngestionRecord dict from the ingestion
                          service, expected to be in ``review_pending``
                          or ``extraction_complete`` status.

    Returns:
        A dict conforming to the action-card-schema-v1 JSON Schema
        with card_type ``ingestion_review``.
    """
    record_id = ingestion_record.get("document_id", ingestion_record.get("record_id", ""))
    filename = ingestion_record.get("original_filename", "unknown")
    status = ingestion_record.get("status", "unknown")
    domain_id = ingestion_record.get("domain_id", "")
    interpretations = ingestion_record.get("interpretations") or []

    body = f"Document: {filename} — status: {status}"
    if interpretations:
        labels = [i.get("label", "?") for i in interpretations]
        body += f"\nInterpretations: {', '.join(labels)}"
        best = max(interpretations, key=lambda i: float(i.get("confidence", 0)))
        body += f"\nRecommended: {best.get('label', '?')} (confidence: {best.get('confidence', 0):.0%})"

    ctx: dict[str, Any] = {
        "domain_id": domain_id,
        "filename": filename,
        "content_type": ingestion_record.get("content_type", ""),
        "content_hash": ingestion_record.get("content_hash", ""),
        "ingesting_actor_id": ingestion_record.get("ingesting_actor_id", ""),
        "interpretations": interpretations,
        "status": status,
    }

    return {
        "type": "action_card",
        "card_type": "ingestion_review",
        "id": record_id,
        "title": "Ingestion Review",
        "body": body,
        "context": ctx,
        "actions": list(_INGESTION_REVIEW_ACTIONS),
        "resolve_endpoint": f"/api/ingest/{record_id}/review",
        "metadata": {
            "timestamp_utc": ingestion_record.get("timestamp_utc", ""),
            "module_id": ingestion_record.get("module_id", ""),
        },
    }
