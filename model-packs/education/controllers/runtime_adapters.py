"""Global education-domain helpers shared across modules.

Contains world-sim theme selection, MUD-world generation, and small
shared utilities.  Module-specific adapters live in their own files
(learning_adapters.py, freeform_adapters.py, etc.).
"""
from __future__ import annotations

import re
from typing import Any


def select_world_sim_theme(
    entity_profile: dict[str, Any],
    world_sim_cfg: dict[str, Any] | None,
) -> dict[str, Any]:
    """Select the active world-sim theme for this session based on entity preferences.

    Returns the matched theme config dict, or {} if world_sim is disabled or absent.
    Selection order: first theme whose preference_keywords overlap with profile
    likes, skipping any theme whose keywords overlap with dislikes. Falls back
    to the default_theme when no preference match is found.
    """
    if not world_sim_cfg or not world_sim_cfg.get("enabled", False):
        return {}

    themes: dict[str, Any] = world_sim_cfg.get("themes") or {}
    default_theme_id: str = world_sim_cfg.get("default_theme", "")

    preferences = entity_profile.get("preferences") or {}
    # Accept both 'interests' (canonical) and 'likes' (legacy alias); merge into one set.
    _interests_raw = list(preferences.get("interests") or []) + list(preferences.get("likes") or [])
    likes: list[str] = [str(v).lower() for v in _interests_raw]
    dislikes: list[str] = [str(v).lower() for v in (preferences.get("dislikes") or [])]

    # Attempt preference-matched selection
    for theme_id, theme_cfg in themes.items():
        keywords: list[str] = [
            str(kw).lower() for kw in (theme_cfg.get("preference_keywords") or [])
        ]
        if not keywords:
            # Themes with no keywords are fallback-only; skip for active matching
            continue
        keyword_set = set(keywords)
        if keyword_set & set(dislikes):
            # Any overlap with dislikes disqualifies this theme
            continue
        if keyword_set & set(likes):
            return {"theme_id": theme_id, **theme_cfg}

    # Fall back to default_theme
    if default_theme_id and default_theme_id in themes:
        return {"theme_id": default_theme_id, **themes[default_theme_id]}

    return {}


def generate_mud_world(
    entity_profile: dict[str, Any],
    mud_world_cfg: dict[str, Any] | None,
) -> dict[str, Any]:
    """Generate and return the MUD World State for this session.

    Selects a template from ``mud_world_cfg["templates"]`` based on the
    entity's interest/likes profile.  Returns a dict containing the 8
    narrative constants (zone, protagonist, antagonist, guide_npc, macguffin,
    variable_skin, obstacle_theme, failure_state) plus ``template_id`` for
    audit traceability.  Returns ``{}`` if world builder is disabled or no
    templates list is provided.

    Selection algorithm:
    1. Skip templates whose ``preference_keywords`` overlap with dislikes.
    2. Return first template whose ``preference_keywords`` overlap with
       interests/likes (combined set).
    3. Fallback: return the first template with an empty ``preference_keywords``
       list (the general_math catch-all).
    4. Return ``{}`` if nothing matches.
    """
    if not mud_world_cfg or not mud_world_cfg.get("enabled", False):
        return {}

    templates: list[dict[str, Any]] = mud_world_cfg.get("templates") or []
    if not templates:
        return {}

    preferences = entity_profile.get("preferences") or {}
    # Accept both 'interests' (canonical) and 'likes' (legacy alias).
    _interests_raw = list(preferences.get("interests") or []) + list(preferences.get("likes") or [])
    interests: set[str] = {str(v).lower() for v in _interests_raw}
    dislikes: set[str] = {str(v).lower() for v in (preferences.get("dislikes") or [])}

    _NARRATIVE_FIELDS = {
        "zone", "protagonist", "antagonist", "guide_npc",
        "macguffin", "variable_skin", "obstacle_theme", "failure_state",
    }

    fallback: dict[str, Any] | None = None

    for template in templates:
        keywords: set[str] = {
            str(kw).lower() for kw in (template.get("preference_keywords") or [])
        }
        if not keywords:
            # Zero-keyword entry is the fallback; capture first one seen.
            if fallback is None:
                fallback = template
            continue
        if keywords & dislikes:
            continue
        if keywords & interests:
            result = {"template_id": template.get("id", "")}
            result.update({k: v for k, v in template.items() if k in _NARRATIVE_FIELDS})
            return result

    if fallback is not None:
        result = {"template_id": fallback.get("id", "")}
        result.update({k: v for k, v in fallback.items() if k in _NARRATIVE_FIELDS})
        return result

    return {}


def _strip_markdown_fences(raw: str) -> str:
    """Remove leading/trailing markdown code fences from a string."""
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[: cleaned.rfind("```")]
    return cleaned.strip()

