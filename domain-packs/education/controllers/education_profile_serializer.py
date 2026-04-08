"""Education domain profile serializer hook.

Extracts education-specific profile persistence from the system pipeline:
- Fluency state extraction (current_tier, consecutive_correct)
- learning_state serialization from dataclass state
- Module-keyed two-tier state model

Called by processing.py via the ``profile_serializer_fn`` hook point.
"""

from __future__ import annotations

import dataclasses
import logging
from typing import Any

log = logging.getLogger("lumina.education.profile-serializer")


def education_serialize_profile(
    *,
    orch_state: Any,
    profile_data: dict[str, Any],
    module_key: str | None,
) -> dict[str, Any]:
    """Serialize education-specific orchestrator state into the profile dict.

    Handles both dataclass-based state (learning modules with fluency)
    and plain-dict state (governance/freeform modules).

    Returns the mutated profile_data dict.
    """
    if dataclasses.is_dataclass(orch_state):
        _ls_dict = dataclasses.asdict(orch_state)
        if hasattr(orch_state, "fluency"):
            _ls_dict["fluency"] = {
                "current_tier": orch_state.fluency.current_tier,
                "consecutive_correct": orch_state.fluency.consecutive_correct,
            }
        profile_data["learning_state"] = _ls_dict
        # Module-keyed state (two-tier model)
        if module_key:
            if not isinstance(profile_data.get("modules"), dict):
                profile_data["modules"] = {}
            profile_data["modules"][module_key] = _ls_dict
    else:
        _sd = orch_state if isinstance(orch_state, dict) else {}
        _state_snapshot = dict(_sd)
        profile_data["session_state"] = {
            "turn_count": int(_sd.get("turn_count", 0)),
            "operator_id": str(_sd.get("operator_id", "")),
        }
        # Module-keyed state (two-tier model)
        if module_key:
            if not isinstance(profile_data.get("modules"), dict):
                profile_data["modules"] = {}
            profile_data["modules"][module_key] = _state_snapshot

    return profile_data
