"""Education domain escalation-context hook.

Supplies actor identity fields for escalation cards so that the
system pipeline does not need to hard-code profile key names.

Called by ``pipeline.response.build_escalation_content`` via the
``escalation_context_fn`` hook point.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("lumina.education.escalation-context")


def education_escalation_context(
    *,
    orchestrator: Any,
    domain_id: str,
) -> dict[str, Any]:
    """Return actor identity context for an escalation card.

    Reads the student/subject pseudonym from the orchestrator profile
    using education-specific field names.
    """
    actor_pseudonym = ""
    if hasattr(orchestrator, "_writer"):
        profile = orchestrator._writer._profile
        actor_pseudonym = profile.get(
            "subject_id",
            profile.get("student_id", ""),
        )
    return {
        "domain_id": domain_id,
        "actor_pseudonym": actor_pseudonym,
    }
