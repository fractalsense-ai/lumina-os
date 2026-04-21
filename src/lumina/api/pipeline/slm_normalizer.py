"""SLM command normalization and domain normalizer hook discovery.

Normalises SLM-produced command dicts so they match admin-command-schemas.
Domain-specific normalization (role alias mapping, intended_domain_role
inference) is delegated to ``slm_normalizer`` adapter hooks declared in
each domain pack's runtime-config.yaml.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from lumina.api import config as _cfg
from lumina.api.governance import _get_domain_role_aliases
from lumina.auth.auth import VALID_ROLES

log = logging.getLogger("lumina-api")


# ── Domain SLM normalizer hook discovery ──────────────────────

_domain_normalizer_cache: list[Any] | None = None
_domain_normalizer_cache_registry_id: int | None = None


def _load_domain_slm_normalizers() -> list[Any]:
    """Discover ``slm_normalizer_fn`` callables from all domain runtime contexts."""
    global _domain_normalizer_cache, _domain_normalizer_cache_registry_id
    reg = _cfg.DOMAIN_REGISTRY
    reg_id = id(reg) if reg is not None else None
    if _domain_normalizer_cache is not None and _domain_normalizer_cache_registry_id == reg_id:
        return _domain_normalizer_cache

    normalizers: list[Any] = []
    if reg is None:
        return normalizers

    domains = reg.list_domains()
    # Single-domain fallback (same pattern as _mount_domain_api_routes)
    if not domains and reg.default_domain_id:
        domains = [{"domain_id": reg.default_domain_id}]

    for dom in domains:
        dom_id = dom.get("domain_id", "")
        if not dom_id:
            continue
        try:
            ctx = reg.get_runtime_context(dom_id)
        except Exception:
            continue
        fn = ctx.get("slm_normalizer_fn")
        if fn is not None:
            normalizers.append(fn)

    _domain_normalizer_cache = normalizers
    _domain_normalizer_cache_registry_id = reg_id
    return normalizers


# ── SLM Command Normalization ─────────────────────────────────


def _normalize_slm_command(parsed_command: dict[str, Any], original_instruction: str = "") -> dict[str, Any]:
    """Normalise SLM-produced command dicts so they match admin-command-schemas.

    The SLM is probabilistic --- it may return ``"Domain Authority"`` instead of
    ``"domain_authority"``, put the user name in ``target`` instead of
    ``params.user_id``, or include extra keys like ``governed_modules`` at the
    top level rather than inside ``params``.  This function applies best-effort
    structural mapping **before** schema validation.

    Domain-specific normalization (role alias mapping, intended_domain_role
    inference) is delegated to ``slm_normalizer`` adapter hooks declared in
    each domain pack's runtime-config.yaml.
    """
    cmd = {k: v for k, v in parsed_command.items()}  # shallow copy
    _raw_params = cmd.get("params")
    if isinstance(_raw_params, list):
        # SLM sometimes returns params as a list of strings; coerce to dict
        params: dict[str, Any] = {str(p): True for p in _raw_params}
    else:
        params = dict(_raw_params or {})
    target = cmd.get("target", "")
    operation = cmd.get("operation", "")

    if operation in ("update_user_role", "invite_user"):
        # ── user_id / username fallback: SLM often puts the name in 'target' ──
        if operation == "update_user_role":
            if not params.get("user_id") and target:
                params["user_id"] = target
        elif operation == "invite_user":
            if not params.get("username") and target:
                params["username"] = target

        # ── new_role / role normalisation: "Domain Authority" → "domain_authority" ──
        role_key = "new_role" if operation == "update_user_role" else "role"
        raw_role = params.get(role_key, "")
        if raw_role and not re.fullmatch(r"[a-z_]+", raw_role):
            params[role_key] = re.sub(r"[\s-]+", "_", raw_role.strip()).lower()

        cmd["params"] = params

        # ── Domain normalizer hooks (role alias, intended_domain_role) ──
        # Each domain pack may declare an ``slm_normalizer`` adapter that
        # handles domain-specific role alias mapping, prefix stripping, and
        # intended_domain_role inference.
        _domain_ids: list[str] = []
        try:
            if _cfg.DOMAIN_REGISTRY is not None:
                _doms = _cfg.DOMAIN_REGISTRY.list_domains()
                if not _doms and _cfg.DOMAIN_REGISTRY.default_domain_id:
                    _doms = [{"domain_id": _cfg.DOMAIN_REGISTRY.default_domain_id}]
                _domain_ids = [
                    d["domain_id"]
                    for d in _doms
                    if d.get("domain_id")
                ]
        except Exception:
            pass
        for _normalizer_fn in _load_domain_slm_normalizers():
            try:
                cmd = _normalizer_fn(
                    cmd,
                    original_instruction,
                    valid_roles=VALID_ROLES,
                    domain_role_aliases=_get_domain_role_aliases(),
                    domain_ids=_domain_ids,
                )
            except Exception:
                log.debug("Domain SLM normalizer failed", exc_info=True)
        params = cmd.get("params") or {}

        if operation == "invite_user":
            # ── Infer domain_id from target or instruction context ──
            # If the SLM didn't set domain_id, check whether any registered
            # domain ID appears in the target field.
            if not params.get("domain_id") and _cfg.DOMAIN_REGISTRY is not None:
                _search_text = f"{target or ''} {original_instruction}".lower()
                try:
                    for _dom in _cfg.DOMAIN_REGISTRY.list_domains():
                        _did = _dom.get("domain_id", "")
                        if _did and _did.lower() in _search_text:
                            params["domain_id"] = _did
                            break
                except Exception:
                    pass

            # ── Strip governed_modules for non-DA roles ──
            if params.get(role_key) != "admin":
                params.pop("governed_modules", None)

        # ── governed_modules: may appear at top level or inside params ──
        if "governed_modules" not in params and cmd.get("governed_modules"):
            params["governed_modules"] = cmd.pop("governed_modules")

        # Normalise governed_modules to a list when a single string is provided
        gm = params.get("governed_modules")
        if isinstance(gm, str):
            params["governed_modules"] = [gm]

        # ── Expand "all": SLM may output governed_modules: "all" or ["all"] ──
        gm_list = params.get("governed_modules")
        if isinstance(gm_list, list) and any(
            isinstance(m, str) and m.lower() == "all" for m in gm_list
        ):
            # Determine domain from context — use target field or the first
            # module_prefix hint in existing governed_modules
            _domain_hint = cmd.get("target", "") or params.get("domain_id", "")
            try:
                if _domain_hint and _cfg.DOMAIN_REGISTRY is not None:
                    # Resolve prefixes (e.g. "edu" → "education") before lookup
                    _domain_hint = _cfg.DOMAIN_REGISTRY._prefix_to_domain.get(_domain_hint, _domain_hint)
                    _resolved_domain = _cfg.DOMAIN_REGISTRY.resolve_domain_id(_domain_hint)
                    _mod_list = _cfg.DOMAIN_REGISTRY.list_modules_for_domain(_resolved_domain)
                    if _mod_list:
                        params["governed_modules"] = [m["module_id"] for m in _mod_list]
            except Exception:
                # If we can't resolve, leave as-is — graceful degradation
                # will catch it downstream
                pass

        # ── Expand wildcard patterns: "domain/edu/*" → actual module IDs ──
        gm_list = params.get("governed_modules")
        if isinstance(gm_list, list) and _cfg.DOMAIN_REGISTRY is not None:
            expanded: list[str] = []
            changed = False
            for mod_id in gm_list:
                if isinstance(mod_id, str) and ("*" in mod_id or mod_id.endswith("/")):
                    _parts = mod_id.replace("*", "").rstrip("/").split("/")
                    _hint = _parts[-1] if _parts else ""
                    if not _hint:
                        _hint = _parts[-2] if len(_parts) > 1 else ""
                    try:
                        # Resolve prefixes (e.g. "edu" → "education") before lookup
                        _hint = _cfg.DOMAIN_REGISTRY._prefix_to_domain.get(_hint, _hint)
                        _resolved = _cfg.DOMAIN_REGISTRY.resolve_domain_id(_hint)
                        _mods = _cfg.DOMAIN_REGISTRY.list_modules_for_domain(_resolved)
                        if _mods:
                            expanded.extend(m["module_id"] for m in _mods)
                            changed = True
                            continue
                    except Exception:
                        pass
                    expanded.append(mod_id)
                else:
                    expanded.append(mod_id)
            if changed:
                params["governed_modules"] = expanded

    elif operation in ("assign_domain_role", "revoke_domain_role"):
        # Similar user_id fallback for role assignment operations
        if not params.get("user_id") and target:
            params["user_id"] = target

    elif operation in ("list_users", "list_escalations", "list_modules"):
        # ── Infer domain_id from target or instruction context ──
        # Follow the same pattern as invite_user: when the SLM didn't
        # set domain_id, check whether any registered domain ID appears
        # in the target field or the original instruction.
        if not params.get("domain_id") and _cfg.DOMAIN_REGISTRY is not None:
            _search_text = f"{target or ''} {original_instruction}".lower()
            try:
                for _dom in _cfg.DOMAIN_REGISTRY.list_domains():
                    _did = _dom.get("domain_id", "")
                    if _did and _did.lower() in _search_text:
                        params["domain_id"] = _did
                        break
            except Exception:
                pass

    cmd["params"] = params
    return cmd
