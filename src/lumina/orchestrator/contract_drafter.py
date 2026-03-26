"""
contract_drafter.py — ContractDrafter (the Clerk)

Owns prompt-contract assembly: takes a resolved action and formats the
ci_output_contract JSON object conforming to prompt-contract-schema.json.

Extracted from ppa_orchestrator.py so that profile data and domain metadata
are mixed with action data in one focused, testable place.
"""

from __future__ import annotations

from typing import Any

# Domain-agnostic action → prompt_type defaults.
# Unknown/domain-defined actions pass through as their own prompt_type string
# so domain packs can extend the vocabulary without modifying the engine.
_DEFAULT_ACTION_TO_PROMPT_TYPE: dict[str | None, str] = {
    None: "task_presentation",
}


class ContractDrafter:
    """
    Formats the final ci_output_contract for a turn.

    Responsibilities:
    - Maps the resolved action string to a ``prompt_type``.
    - Pulls subject preferences (interests/theme) from the profile.
    - Attaches standing-order trigger metadata.

    Public interface::

        drafter = ContractDrafter(domain_physics, subject_profile, action_prompt_type_map)
        contract = drafter.build(task_spec, action, domain_lib_decision, standing_order_trigger)
    """

    def __init__(
        self,
        domain_physics: dict[str, Any],
        subject_profile: dict[str, Any],
        action_prompt_type_map: dict[str, str] | None = None,
    ) -> None:
        self._domain = domain_physics
        self._profile = subject_profile
        self._action_prompt_type_map: dict[str | None, str] = dict(
            _DEFAULT_ACTION_TO_PROMPT_TYPE
        )
        for action, prompt_type in (action_prompt_type_map or {}).items():
            self._action_prompt_type_map[str(action)] = str(prompt_type)

    def build(
        self,
        task_spec: dict[str, Any],
        action: str | None,
        domain_lib_decision: dict[str, Any],
        standing_order_trigger: str | None,
        references: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """
        Build a prompt_contract dict conforming to prompt-contract-schema.json.

        Required schema fields: prompt_type, domain_pack_id, domain_pack_version,
        task_id.  Additional optional fields are populated where available.
        """
        prompt_type = self._action_prompt_type_map.get(
            action, action or "task_presentation"
        )

        preferences = self._profile.get("preferences", {})
        interests: list[str] = preferences.get("interests") or []
        theme: str | None = interests[0] if interests else None

        contract: dict[str, Any] = {
            "prompt_type": prompt_type,
            "domain_pack_id": self._domain.get("id", ""),
            "domain_pack_version": self._domain.get("version", ""),
            "task_id": task_spec.get("task_id", ""),
            "task_nominal_difficulty": float(
                task_spec.get(
                    "nominal_difficulty", domain_lib_decision.get("challenge", 0.5)
                )
            ),
            "skills_targeted": list(task_spec.get("skills_required", [])),
            "theme": theme,
            "standing_order_trigger": standing_order_trigger,
            "references": references or [],
            "grounded": bool(references),
        }

        if prompt_type == "hint":
            contract["hint_level"] = 1

        return contract
