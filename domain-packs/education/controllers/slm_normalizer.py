"""Education-domain SLM command normalizer.

Registered as the ``slm_normalizer`` adapter in runtime-config.yaml and
called by the system-level ``_normalize_slm_command()`` after generic
structural normalization.  Handles education-specific role alias mapping,
domain-prefix stripping, and ``intended_domain_role`` / ``domain_id``
inference from instruction text.
"""

from __future__ import annotations

import re
from typing import Any

# Education-domain role aliases — used as defaults when the system layer
# provides no dynamic aliases (e.g. single-domain mode without
# maps_to_system_role entries in domain-physics.json).
_EDUCATION_ROLE_ALIASES: dict[str, str] = {
    "student": "user",
    "teacher": "user",
    "teaching_assistant": "user",
    "parent": "user",
}


def normalize_slm_command(
    parsed_command: dict[str, Any],
    original_instruction: str = "",
    *,
    valid_roles: frozenset[str] | set[str] = frozenset(),
    domain_role_aliases: dict[str, str] | None = None,
    domain_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Apply education-specific normalization to an SLM-produced command.

    Parameters
    ----------
    parsed_command:
        Shallow-copied command dict (already structurally normalised by the
        system layer).
    original_instruction:
        The raw teacher/admin instruction text (used for fuzzy inference).
    valid_roles:
        Set of valid *system* roles (e.g. ``{"user", "domain_authority", ...}``).
    domain_role_aliases:
        Mapping of domain-specific role names to system roles, loaded
        dynamically from domain-physics.json by the system layer.
    domain_ids:
        List of registered domain IDs (used for prefix stripping).

    Returns the (mutated) *parsed_command*.
    """
    cmd = parsed_command
    params: dict[str, Any] = cmd.get("params") or {}
    target = cmd.get("target", "")
    operation = cmd.get("operation", "")
    # Merge: system-provided aliases override domain defaults.
    aliases = {**_EDUCATION_ROLE_ALIASES, **(domain_role_aliases or {})}

    if operation not in ("update_user_role", "invite_user"):
        return cmd

    role_key = "new_role" if operation == "update_user_role" else "role"
    normalised_role = params.get(role_key, "")

    # ── Domain-prefix stripping ───────────────────────────────
    # The SLM sometimes invents prefixed roles like "education_user",
    # "agriculture_domain_authority".  Strip known domain-ID prefixes
    # dynamically instead of hard-coding domain names.
    if normalised_role and normalised_role not in valid_roles:
        _prefixes = domain_ids or []
        if _prefixes:
            _pattern = r"^(" + "|".join(re.escape(p) for p in _prefixes) + r")_?(domain_?)?"
            _stripped = re.sub(_pattern, "", normalised_role)
            if _stripped and _stripped in valid_roles:
                params["intended_domain_role"] = normalised_role
                params[role_key] = _stripped
                normalised_role = _stripped

    # ── Domain-role alias table ───────────────────────────────
    # Map domain-specific roles (student, teacher, field_operator, …) to
    # their system-role equivalent and preserve the original as
    # intended_domain_role for downstream chaining.
    normalised_role = params.get(role_key, "")
    if normalised_role and normalised_role not in valid_roles:
        if normalised_role in aliases:
            params["intended_domain_role"] = normalised_role
            params[role_key] = aliases[normalised_role]
        else:
            # Fuzzy substring match against known system roles
            matched = [vr for vr in valid_roles if vr in normalised_role]
            if matched:
                params["intended_domain_role"] = normalised_role
                params[role_key] = max(matched, key=len)

    # ── invite_user: reject system roles leaked into intended_domain_role ──
    if operation == "invite_user":
        _idr_raw = params.get("intended_domain_role", "")
        if _idr_raw and _idr_raw in valid_roles:
            params["intended_domain_role"] = None

        # ── Infer role from intended_domain_role when missing ──
        if not params.get(role_key):
            _idr = params.get("intended_domain_role", "")
            if _idr and _idr in aliases:
                params[role_key] = aliases[_idr]
            elif _idr:
                params[role_key] = "user"
            else:
                params[role_key] = "user"

        # ── Recover intended_domain_role from instruction text ──
        if not params.get("intended_domain_role"):
            _search_text = f"{target or ''} {original_instruction}".lower()
            for _alias in aliases:
                if _alias in _search_text:
                    params["intended_domain_role"] = _alias
                    break


    cmd["params"] = params
    return cmd
