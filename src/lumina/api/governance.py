"""Governance config loader and domain operation handler registry.

Canonical source: domain-packs/system/modules/system-core/domain-physics.json
→ subsystem_configs.admin_operations  (operation_ids, hitl_policy)
→ subsystem_configs.governance        (role_hierarchy, min_role_policy, domain_role_aliases)

The path is discovered via the domain registry ("system" domain) or by
the well-known convention if the registry is unavailable.  There are no
hardcoded fallback operation lists — the JSON is the single source of
truth.  If the file is missing, an empty set of operations is used and
a critical warning is logged.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from lumina.api import config as _cfg
from lumina.core.yaml_loader import load_yaml

log = logging.getLogger("lumina-api")

# ── Governance Config Cache ───────────────────────────────────

_governance_cache: dict[str, Any] | None = None


def _load_governance_config() -> dict[str, Any]:
    """Load governance policies from system domain physics with fallback."""
    global _governance_cache
    if _governance_cache is not None:
        return _governance_cache

    repo_root = Path(os.environ.get(
        "LUMINA_REPO_ROOT", Path(__file__).resolve().parents[3],
    ))

    # ── Discover system physics path via domain registry ──────
    physics_path: Path | None = None
    try:
        if _cfg.DOMAIN_REGISTRY is not None:
            for mod in _cfg.DOMAIN_REGISTRY.list_modules_for_domain("system"):
                dp = mod.get("domain_physics_path", "")
                if dp:
                    candidate = repo_root / dp
                    if candidate.is_file():
                        physics_path = candidate
                        break
    except Exception:
        pass

    # Well-known convention fallback
    if physics_path is None:
        physics_path = repo_root / "domain-packs" / "system" / "modules" / "system-core" / "domain-physics.json"

    # Minimal empty defaults — used only when the JSON is unreadable.
    result: dict[str, Any] = {
        "known_operations": frozenset(),
        "hitl_exempt": frozenset(),
        "role_hierarchy": {"root": 100, "user": 20},
        "min_role_policy": {},
        "domain_role_aliases": {},
    }

    if physics_path.is_file():
        try:
            import json as _json
            data = _json.loads(physics_path.read_text(encoding="utf-8"))
            sub = data.get("subsystem_configs") or {}

            # Admin operations block
            admin_ops = sub.get("admin_operations") or {}
            op_ids = admin_ops.get("operation_ids")
            if isinstance(op_ids, list) and op_ids:
                result["known_operations"] = frozenset(op_ids)

            hitl = admin_ops.get("hitl_policy") or {}
            exempt = hitl.get("system_exempt")
            if isinstance(exempt, list):
                result["hitl_exempt"] = frozenset(exempt)

            # Governance block
            gov = sub.get("governance") or {}
            rh = gov.get("role_hierarchy")
            if isinstance(rh, dict) and rh:
                result["role_hierarchy"] = rh

            mrp = gov.get("min_role_policy")
            if isinstance(mrp, dict) and mrp:
                result["min_role_policy"] = mrp

            dra = gov.get("domain_role_aliases")
            if isinstance(dra, dict) and dra:
                result["domain_role_aliases"] = dra

            log.info("Loaded governance config from %s", physics_path)
        except Exception as exc:
            log.critical("Failed to load governance config from %s: %s", physics_path, exc)
    else:
        log.critical("System domain physics not found at %s — governance policies unavailable", physics_path)

    _governance_cache = result
    return result


# ── Accessor Functions ────────────────────────────────────────


def _get_known_operations() -> frozenset[str]:
    base = _load_governance_config()["known_operations"]
    domain_ops = _get_domain_handler_ops()
    return base | domain_ops if domain_ops else base


def _get_domain_scoped_operations(domain_id: str | None = None) -> frozenset[str]:
    """Return operations visible in a specific domain context.

    System-level operations (from governance config) are always included.
    Domain-pack operations are included only when *domain_id* matches the
    handler's owning domain.  When *domain_id* is None or ``"system"``,
    only base system operations are returned.
    """
    base = _load_governance_config()["known_operations"]
    if not domain_id or domain_id == "system":
        return base
    domain_handlers = _load_domain_operation_handlers()
    domain_ops = frozenset(
        op for op, cfg in domain_handlers.items()
        if cfg.get("domain_id") == domain_id
    )
    return base | domain_ops if domain_ops else base


def _get_hitl_exempt_ops() -> frozenset[str]:
    base = _load_governance_config()["hitl_exempt"]
    domain_handlers = _load_domain_operation_handlers()
    domain_exempt = frozenset(
        op for op, cfg in domain_handlers.items() if cfg.get("hitl_exempt")
    )
    return base | domain_exempt if domain_exempt else base


def _get_min_role_policy() -> dict[str, str]:
    base = dict(_load_governance_config()["min_role_policy"])
    domain_handlers = _load_domain_operation_handlers()
    for op, cfg in domain_handlers.items():
        if op not in base:
            base[op] = cfg.get("min_role", "user")
    return base


def _get_role_hierarchy() -> dict[str, int]:
    return _load_governance_config()["role_hierarchy"]


def _get_domain_role_aliases() -> dict[str, str]:
    """Dynamically aggregate domain role → system role mappings.

    Scans all modules across all domains, reading the ``domain_roles.roles``
    block for ``maps_to_system_role``.  Falls back to the static governance
    config ``domain_role_aliases`` if no dynamic roles are found.
    """
    aliases: dict[str, str] = {}
    try:
        _doms = _cfg.DOMAIN_REGISTRY.list_domains()
        if not _doms and _cfg.DOMAIN_REGISTRY.default_domain_id:
            _doms = [{"domain_id": _cfg.DOMAIN_REGISTRY.default_domain_id}]
        for dom in _doms:
            dom_id = dom.get("domain_id", "")
            if not dom_id:
                continue
            modules = _cfg.DOMAIN_REGISTRY.list_modules_for_domain(dom_id)
            for mod in modules:
                dp_path = mod.get("domain_physics_path", "")
                if not dp_path:
                    continue
                try:
                    dp_full = Path(_cfg.DOMAIN_REGISTRY._repo_root) / dp_path
                    dp_data = json.loads(dp_full.read_text(encoding="utf-8"))
                    for role in dp_data.get("domain_roles", {}).get("roles", []):
                        if isinstance(role, dict) and role.get("role_id"):
                            aliases[role["role_id"]] = role.get(
                                "maps_to_system_role", "user"
                            )
                except Exception:
                    continue
    except Exception:
        pass
    # Fall back to static governance config if nothing found dynamically
    if not aliases:
        try:
            aliases = _load_governance_config().get("domain_role_aliases", {})
        except Exception:
            pass
    return aliases


def _get_domain_role_level(domain_id: str, role_id: str) -> int | None:
    """Return the ``hierarchy_level`` for *role_id* in any module of *domain_id*.

    Scans domain-physics.json files for the domain's modules and returns the
    first matching ``hierarchy_level``, or ``None`` if not found.
    """
    try:
        resolved = _cfg.DOMAIN_REGISTRY.resolve_domain_id(domain_id)
    except Exception:
        return None
    for mod in _cfg.DOMAIN_REGISTRY.list_modules_for_domain(resolved):
        dp_path = mod.get("domain_physics_path", "")
        if not dp_path:
            continue
        try:
            dp_full = Path(_cfg.DOMAIN_REGISTRY._repo_root) / dp_path
            dp_data = json.loads(dp_full.read_text(encoding="utf-8"))
            for role in dp_data.get("domain_roles", {}).get("roles", []):
                if isinstance(role, dict) and role.get("role_id") == role_id:
                    lvl = role.get("hierarchy_level")
                    if lvl is not None:
                        return int(lvl)
        except Exception:
            continue
    return None


# ── Domain Operation Handler Registry ─────────────────────────
# Domain packs can declare operation_handlers in their runtime-config.yaml.
# Each entry maps an operation name to a handler module/callable plus
# metadata (hitl_exempt, min_role).  These are loaded once and cached.
#
# See docs/7-concepts/domain-adapter-pattern.md

_domain_handler_cache: dict[str, Any] | None = None
_domain_handler_cache_registry_id: int | None = None


def _load_domain_operation_handlers() -> dict[str, dict[str, Any]]:
    """Scan all domains for ``operation_handlers`` in runtime-config.yaml.

    Returns ``{operation_name: {"callable": fn, "hitl_exempt": bool, "min_role": str}}``.
    """
    global _domain_handler_cache, _domain_handler_cache_registry_id
    reg = _cfg.DOMAIN_REGISTRY
    reg_id = id(reg) if reg is not None else None
    if _domain_handler_cache is not None and _domain_handler_cache_registry_id == reg_id:
        return _domain_handler_cache

    from lumina.core.runtime_loader import _load_callable

    handlers: dict[str, dict[str, Any]] = {}
    repo_root = Path(os.environ.get(
        "LUMINA_REPO_ROOT", Path(__file__).resolve().parents[3],
    ))

    if _cfg.DOMAIN_REGISTRY is None:
        # Don't cache the empty result — DOMAIN_REGISTRY may be set later
        return handlers

    for dom in _cfg.DOMAIN_REGISTRY.list_domains():
        dom_id = dom.get("domain_id", "")
        if not dom_id:
            continue
        cfg_path = dom.get("runtime_config_path", "")
        if not cfg_path:
            continue
        try:
            cfg_data = load_yaml(Path(repo_root / cfg_path))
        except Exception:
            continue
        op_handlers = cfg_data.get("operation_handlers")
        if not isinstance(op_handlers, dict):
            continue
        for op_name, op_cfg in op_handlers.items():
            if not isinstance(op_cfg, dict):
                continue
            mod_path = op_cfg.get("module_path", "")
            callable_name = op_cfg.get("callable", "")
            if not mod_path or not callable_name:
                continue
            try:
                fn = _load_callable(repo_root, mod_path, callable_name)
                handlers[op_name] = {
                    "callable": fn,
                    "hitl_exempt": bool(op_cfg.get("hitl_exempt", False)),
                    "min_role": str(op_cfg.get("min_role", "user")),
                    "domain_id": dom_id,
                }
            except Exception as exc:
                log.warning("Failed to load operation handler %s from %s: %s", op_name, mod_path, exc)

    _domain_handler_cache = handlers
    _domain_handler_cache_registry_id = reg_id
    return handlers


def _get_domain_handler_ops() -> frozenset[str]:
    """Return the set of operation names handled by domain packs."""
    return frozenset(_load_domain_operation_handlers().keys())
