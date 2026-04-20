"""Assistant domain escalation-context hook.

Supplies actor identity fields for escalation cards so that the
system pipeline does not need to hard-code profile key names.

Called by ``pipeline.response.build_escalation_content`` via the
``escalation_context_fn`` hook point.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("lumina.assistant.escalation-context")


def assistant_escalation_context(
    *,
    orchestrator: Any,
    domain_id: str,
) -> dict[str, Any]:
    """Return actor identity context for an escalation card.

    Reads the user pseudonym from the orchestrator profile
    using assistant-specific field names.
    """
    actor_pseudonym = ""
    active_task_id = ""
    active_intent = ""
    if hasattr(orchestrator, "_writer"):
        profile = orchestrator._writer._profile
        actor_pseudonym = profile.get("user_id", profile.get("entity_id", ""))
        entity_state = profile.get("entity_state", {})
        active_task_id = entity_state.get("active_task_id", "")
        active_intent = entity_state.get("active_task_type", "")
    return {
        "domain_id": domain_id,
        "actor_pseudonym": actor_pseudonym,
        "active_task_id": active_task_id,
        "active_intent": active_intent,
    }
