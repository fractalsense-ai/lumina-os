"""Domain Roles core helper.

Provides:
- ``get_default_role_defs()`` — load the built-in tier defaults from standards/
- ``get_domain_role_def()`` — look up a specific role definition by role_id
- ``check_scoped_capability()`` — verify whether a user's domain role grants
  a specific capability within a module

The default tier hierarchy (Supervisor → Employee → User Member → Guest) is
defined in ``standards/framework-tier-defaults.yaml`` and can be overridden by
domain packs via their ``domain_roles`` block in domain-physics.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from lumina.core.yaml_loader import load_yaml

# ─────────────────────────────────────────────────────────────
# Locate defaults file relative to the repo root
# ─────────────────────────────────────────────────────────────

_SRC_ROOT = Path(__file__).resolve().parents[3]  # project-lumina/
_DEFAULTS_PATH = _SRC_ROOT / "standards" / "framework-tier-defaults.yaml"

_cached_defaults: list[dict[str, Any]] | None = None


def get_default_role_defs(*, reload: bool = False) -> list[dict[str, Any]]:
    """Return the built-in domain role tier definitions (cached)."""
    global _cached_defaults
    if _cached_defaults is None or reload:
        data = load_yaml(str(_DEFAULTS_PATH))
        _cached_defaults = data.get("framework_tier_defaults") or []
    return list(_cached_defaults)


def get_domain_role_def(role_id: str) -> dict[str, Any] | None:
    """Return the built-in definition for *role_id*, or None if not found."""
    for defn in get_default_role_defs():
        if defn.get("role_id") == role_id:
            return defn
    return None


def get_active_role_defs(domain_physics: dict[str, Any]) -> list[dict[str, Any]]:
    """Return role definitions active for a module.

    Merges domain-physics ``domain_roles.roles`` overrides on top of the
    built-in defaults.  Domain packs may add extra roles or override labels;
    they may not remove built-in tiers.

    Returns a list ordered by ``tier_level`` ascending.
    """
    defaults = {d["role_id"]: dict(d) for d in get_default_role_defs()}
    overrides: list[dict[str, Any]] = (
        (domain_physics.get("domain_roles") or {}).get("roles") or []
    )
    for override in overrides:
        rid = override.get("role_id")
        if rid:
            if rid in defaults:
                defaults[rid].update(override)
            else:
                defaults[rid] = dict(override)
    result = sorted(defaults.values(), key=lambda d: d.get("tier_level", 99))
    return result


def check_scoped_capability(
    domain_role: str,
    capability: str,
    domain_physics: dict[str, Any],
) -> bool:
    """Return True if *domain_role* grants *capability* in *domain_physics*.

    *capability* is a single permission character: ``r``, ``w``, ``x``, ``i``.

    Checks (in order):
    1. Built-in ``default_access`` for the role tier.
    2. Overrides in the domain-physics ``domain_roles.roles`` block.
    3. Explicit ``role_acl`` entries in the ``domain_roles`` block.
    """
    active = {d["role_id"]: d for d in get_active_role_defs(domain_physics)}
    role_def = active.get(domain_role)
    if role_def is None:
        return False

    default_access = role_def.get("default_access", "")
    if capability in default_access:
        return True

    # Check role_acl block
    domain_roles_block = domain_physics.get("domain_roles") or {}
    for entry in domain_roles_block.get("role_acl") or []:
        if entry.get("role_id") == domain_role:
            if capability in entry.get("access", ""):
                return True

    return False
