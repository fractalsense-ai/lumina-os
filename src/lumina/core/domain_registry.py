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

        if registry_path:
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

        log.info(
            "Loaded domain registry: %d domain(s), default=%s",
            len(self._domains),
            self._default_domain or "(none)",
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
                "is_default": domain_id == self._default_domain,
            })
        return result

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

    def resolve_domain_id(self, requested: str | None) -> str:
        """Map a request-level domain_id to a validated registry key."""
        if requested and requested in self._domains:
            return requested

        if requested and requested not in self._domains:
            raise DomainNotFoundError(requested, list(self._domains.keys()))

        if self._default_domain:
            return self._default_domain

        # Single-domain legacy mode
        if "_default" in self._domains:
            return "_default"

        raise RuntimeError("No domain_id provided and no default_domain configured")

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
