"""
domain_registry.py — Multi-domain registry for Project Lumina

Loads a domain-registry YAML that maps domain_id -> runtime-config path,
caches loaded runtime contexts per domain, and resolves domain selection
for incoming requests.

Backward compatible: when no registry is configured, falls back to the
single-domain LUMINA_RUNTIME_CONFIG_PATH behavior.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any, Callable

from lumina.core.yaml_loader import load_yaml

log = logging.getLogger("lumina-api.domain-registry")


class DomainRegistry:
    """Thread-safe registry mapping domain IDs to runtime contexts."""

    def __init__(
        self,
        repo_root: Path,
        registry_path: str | None = None,
        single_config_path: str | None = None,
        load_runtime_context_fn: Callable[..., dict[str, Any]] | None = None,
    ) -> None:
        self._repo_root = repo_root
        self._load_runtime_context = load_runtime_context_fn
        self._lock = threading.Lock()
        self._cache: dict[str, dict[str, Any]] = {}

        # Registry data
        self._domains: dict[str, dict[str, Any]] = {}
        self._default_domain: str | None = None
        self._multi_domain = False
        # Role-based defaults: maps role name → domain_id
        self._role_defaults: dict[str, str] = {}
        # module_prefix → domain_id reverse map (for admin resolution)
        self._prefix_to_domain: dict[str, str] = {}
        # Landing domain for unauthenticated sessions (distinct from default_domain)
        self._unauthenticated_domain: str | None = None

        if registry_path:
            self._multi_domain = True
            self._load_registry(registry_path)
        elif single_config_path:
            # Backward-compatible single-domain mode
            self._domains["_default"] = {"runtime_config_path": single_config_path}
            self._default_domain = "_default"
        else:
            raise RuntimeError(
                "No domain configuration. Set LUMINA_DOMAIN_REGISTRY_PATH for multi-domain "
                "or LUMINA_RUNTIME_CONFIG_PATH for single-domain mode."
            )

    def _load_registry(self, registry_path: str) -> None:
        data = load_yaml(str(self._repo_root / registry_path))
        if not isinstance(data, dict):
            raise RuntimeError(f"Domain registry must be a mapping: {registry_path}")

        domains_raw = data.get("domains")
        if not isinstance(domains_raw, dict) or not domains_raw:
            raise RuntimeError(f"Domain registry must contain a non-empty 'domains' mapping: {registry_path}")

        for domain_id, entry in domains_raw.items():
            if not isinstance(entry, dict) or "runtime_config_path" not in entry:
                raise RuntimeError(
                    f"Domain '{domain_id}' must have a 'runtime_config_path' key"
                )
            cfg_path = entry["runtime_config_path"]
            full_path = self._repo_root / cfg_path
            if not full_path.exists():
                raise RuntimeError(
                    f"Runtime config for domain '{domain_id}' not found: {cfg_path}"
                )

        self._domains = dict(domains_raw)
        self._default_domain = data.get("default_domain")
        self._multi_domain = True

        if self._default_domain and self._default_domain not in self._domains:
            raise RuntimeError(
                f"default_domain '{self._default_domain}' not found in domains"
            )

        # Optional separate landing domain for unauthenticated sessions
        unauthenticated_domain = data.get("unauthenticated_domain")
        if unauthenticated_domain and unauthenticated_domain not in self._domains:
            raise RuntimeError(
                f"unauthenticated_domain '{unauthenticated_domain}' not found in domains"
            )
        self._unauthenticated_domain = unauthenticated_domain

        # Load optional role_defaults mapping
        role_defaults_raw = data.get("role_defaults") or {}
        if not isinstance(role_defaults_raw, dict):
            raise RuntimeError("'role_defaults' must be a mapping of role → domain_id")
        for role, target in role_defaults_raw.items():
            if target not in self._domains:
                raise RuntimeError(
                    f"role_defaults['{role}'] references unknown domain '{target}'"
                )
        self._role_defaults = dict(role_defaults_raw)

        # Build prefix → domain_id reverse map from module_prefix entries
        self._prefix_to_domain = {
            entry["module_prefix"]: domain_id
            for domain_id, entry in self._domains.items()
            if "module_prefix" in entry
        }

        log.info(
            "Loaded domain registry: %d domain(s), default=%s, unauthenticated=%s, role_defaults=%s",
            len(self._domains),
            self._default_domain or "(none)",
            self._unauthenticated_domain or f"→ {self._default_domain or '(none)'}",
            self._role_defaults or "(none)",
        )

    # ── Public API ────────────────────────────────────────────

    @property
    def is_multi_domain(self) -> bool:
        return self._multi_domain

    @property
    def default_domain_id(self) -> str | None:
        return self._default_domain

    def list_domains(self) -> list[dict[str, Any]]:
        """Return catalog of available domains (no runtime internals)."""
        result = []
        for domain_id, entry in self._domains.items():
            if domain_id == "_default" and not self._multi_domain:
                continue
            result.append({
                "domain_id": domain_id,
                "label": entry.get("label", domain_id),
                "description": entry.get("description", ""),
                "runtime_config_path": entry.get("runtime_config_path", ""),
                "is_default": domain_id == self._default_domain,
            })
        return result

    def list_modules_for_domain(self, domain_id: str) -> list[dict[str, Any]]:
        """Return module catalog for a domain.

        Reads the runtime config to discover the default module and any
        entries in ``module_map``.  Each returned dict contains at minimum
        ``module_id`` and ``domain_physics_path``.
        """
        entry = self._domains.get(domain_id)
        if entry is None:
            raise DomainNotFoundError(domain_id, list(self._domains.keys()))

        cfg_path = self._repo_root / entry["runtime_config_path"]
        raw = load_yaml(str(cfg_path))
        runtime_block = raw.get("runtime") or raw

        modules: list[dict[str, Any]] = []
        seen_ids: set[str] = set()

        # Collect modules from module_map
        module_map = runtime_block.get("module_map") or {}
        for mod_id, mod_cfg in module_map.items():
            if mod_id in seen_ids:
                continue
            seen_ids.add(mod_id)
            modules.append({
                "module_id": mod_id,
                "domain_physics_path": mod_cfg.get("domain_physics_path", ""),
                "local_only": bool(mod_cfg.get("local_only")),
            })

        # Also include the default domain_physics_path module (if not already listed)
        default_dp_path = runtime_block.get("domain_physics_path", "")
        if default_dp_path:
            # Read the id field from the domain-physics file
            try:
                import json as _json
                dp_full = self._repo_root / default_dp_path
                dp_data = _json.loads(dp_full.read_text(encoding="utf-8"))
                default_mod_id = dp_data.get("id", "")
            except Exception:
                default_mod_id = ""
            if default_mod_id and default_mod_id not in seen_ids:
                modules.append({
                    "module_id": default_mod_id,
                    "domain_physics_path": default_dp_path,
                })

        return modules

    def get_domain_routing_map(self) -> dict[str, dict[str, Any]]:
        """Return domain metadata for semantic routing.

        Returns ``{domain_id: {"label": str, "description": str, "keywords": list[str]}}``.
        """
        routing_map: dict[str, dict[str, Any]] = {}
        for domain_id, entry in self._domains.items():
            if domain_id == "_default" and not self._multi_domain:
                continue
            routing_map[domain_id] = {
                "label": entry.get("label", domain_id),
                "description": entry.get("description", ""),
                "keywords": entry.get("keywords") or [],
            }
        return routing_map

    def resolve_default_for_user(self, user: dict[str, Any] | None) -> str:
        """Return the default domain_id for *user* when NLP routing finds no match.

        Resolution order:
        1. If user is None (unauthenticated) → unauthenticated_domain, then
           global default_domain.
        2. If user role is listed in role_defaults → that domain.
        3. If user has governed_modules (any role) → extract the module-prefix
           segment from the first module path (``domain/<prefix>/…``) and map
           to the corresponding domain_id.  This ensures invited users land in
           the domain they were onboarded to regardless of their system role.
        4. Fallthrough → global default_domain.
        """
        if not self._multi_domain:
            return self._default_domain or "_default"

        if user is None:
            return (
                self._unauthenticated_domain
                or self._default_domain
                or next(iter(self._domains))
            )

        role = user.get("role", "")

        # Step 2 — explicit role_default
        if role in self._role_defaults:
            return self._role_defaults[role]

        # Step 3 — infer from governed_modules (works for any role)
        governed: list[str] = user.get("governed_modules") or []
        if governed:
            # Module paths are shaped like "domain/<prefix>/…".
            # Split out the prefix segment (index 1).
            parts = governed[0].strip("/").split("/")
            if len(parts) >= 2:
                prefix = parts[1]
                inferred = self._prefix_to_domain.get(prefix)
                if inferred:
                    return inferred

        # Step 4 — global fallback
        return self._default_domain or next(iter(self._domains))

    def resolve_domain_id(self, requested: str | None) -> str:
        """Map a request-level domain_id to a validated registry key.

        Handles exact matches, prefix lookups (e.g. "edu" → "education"),
        and path-style domain IDs (e.g. "domain/edu" → "education").
        """
        if requested and requested in self._domains:
            return requested

        if not requested:
            # Fall back to the configured default domain
            if self._default_domain:
                return self._default_domain
            return None  # type: ignore[return-value]

        if requested not in self._domains:
            # Try prefix lookup (e.g. "edu" → "education")
            resolved = self._prefix_to_domain.get(requested)
            if resolved:
                return resolved

            # Try stripping "domain/" path prefix (e.g. "domain/edu" → "edu")
            stripped = requested
            if stripped.startswith("domain/"):
                stripped = stripped[len("domain/"):]
            # Strip trailing segments (e.g. "domain/edu/algebra" → "edu")
            stripped = stripped.split("/")[0]
            if stripped != requested:
                # Check direct match after stripping
                if stripped in self._domains:
                    return stripped
                # Check prefix map
                resolved = self._prefix_to_domain.get(stripped)
                if resolved:
                    return resolved

            raise DomainNotFoundError(requested, list(self._domains.keys()))

    def get_default_module_id(
        self, domain_id: str, domain_role: str | None = None,
    ) -> str | None:
        """Return the default module ID for a domain, optionally scoped by role.

        Resolution order:
        1. If *domain_role* is given and the runtime config contains a
           ``role_to_default_module`` mapping with that role, return the
           mapped module ID (if it exists in ``module_map``).
        2. Otherwise, read ``default_module`` from the domain's
           ``pack.yaml`` and search ``module_map`` for the matching module.
        Returns ``None`` if no default module is configured.
        """
        entry = self._domains.get(domain_id)
        if entry is None:
            return None

        # Derive pack.yaml path from runtime_config_path
        cfg_path = entry.get("runtime_config_path", "")
        if not cfg_path:
            return None

        # Load runtime config (needed for both role and fallback paths)
        runtime_raw = load_yaml(str(self._repo_root / cfg_path))
        runtime_block = runtime_raw.get("runtime") or runtime_raw
        module_map = runtime_block.get("module_map") or {}

        # Step 1 — role-based routing
        if domain_role:
            role_map = runtime_block.get("role_to_default_module") or {}
            role_mod_id = role_map.get(domain_role)
            if role_mod_id and role_mod_id in module_map:
                return role_mod_id

        # Step 2 — pack.yaml default_module fallback
        cfg_dir = Path(cfg_path).parent.parent  # go up from cfg/ to domain root
        pack_path = self._repo_root / cfg_dir / "pack.yaml"
        if not pack_path.exists():
            return None

        try:
            pack_data = load_yaml(str(pack_path))
            default_module_name = pack_data.get("default_module")
            if not default_module_name:
                return None
        except Exception:
            return None

        # Find the full module ID in module_map that contains the default_module name
        for mod_id in module_map:
            # Match by module name segment, e.g. "general-education" in
            # "domain/edu/general-education/v1"
            if default_module_name in mod_id:
                return mod_id

        return None

    def get_runtime_context(self, domain_id: str) -> dict[str, Any]:
        """Return (cached) runtime context for a domain. Thread-safe."""
        with self._lock:
            if domain_id in self._cache:
                return self._cache[domain_id]

        # Load outside lock (I/O heavy), then store under lock
        entry = self._domains.get(domain_id)
        if entry is None:
            raise DomainNotFoundError(domain_id, list(self._domains.keys()))

        if self._load_runtime_context is None:
            raise RuntimeError("load_runtime_context function not set on DomainRegistry")

        ctx = self._load_runtime_context(
            self._repo_root,
            runtime_config_path=entry["runtime_config_path"],
        )

        with self._lock:
            # Double-check: another thread may have loaded it concurrently
            if domain_id not in self._cache:
                self._cache[domain_id] = ctx
            return self._cache[domain_id]


class DomainNotFoundError(Exception):
    """Raised when a requested domain_id is not in the registry."""

    def __init__(self, domain_id: str, available: list[str]) -> None:
        self.domain_id = domain_id
        self.available = available
        super().__init__(
            f"Domain '{domain_id}' not found. "
            f"Available: {', '.join(available)}"
        )
