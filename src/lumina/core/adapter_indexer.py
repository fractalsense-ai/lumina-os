"""Adapter Indexer — zero-AI-compute directory scanner for tool adapters.

Walks ``domain-packs/*/modules/*/tool-adapters/`` directories and reads
YAML adapter definitions, building an index keyed by adapter ID.  Also
discovers ``controllers/runtime_adapters.py`` and ``controllers/tool_adapters.py``
by naming convention.

Explicit adapter declarations in ``runtime-config.yaml`` always take
precedence over auto-discovered entries.

Public API
----------
scan_tool_adapters(domain_pack_path)   → dict[str, AdapterEntry]
scan_runtime_adapters(domain_pack_path) → dict[str, str]
build_router_index(domain_packs_root)  → RouterIndex
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lumina.core.yaml_loader import load_yaml

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AdapterEntry:
    """Metadata for a single discovered tool adapter."""

    adapter_id: str
    domain_id: str
    module_path: str          # Relative path within the domain pack (e.g. "modules/algebra-level-1")
    tool_name: str
    version: str
    call_types: tuple[str, ...]
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    source_file: str          # Relative path to the YAML file

    def to_dict(self) -> dict[str, Any]:
        return {
            "adapter_id": self.adapter_id,
            "domain_id": self.domain_id,
            "module_path": self.module_path,
            "tool_name": self.tool_name,
            "version": self.version,
            "call_types": list(self.call_types),
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
            "source_file": self.source_file,
        }


@dataclass
class RouterIndex:
    """Aggregated index of all discovered adapters across domain packs."""

    adapters: dict[str, AdapterEntry] = field(default_factory=dict)
    runtime_adapter_modules: dict[str, str] = field(default_factory=dict)
    tool_adapter_modules: dict[str, str] = field(default_factory=dict)

    @property
    def adapter_ids(self) -> frozenset[str]:
        return frozenset(self.adapters)

    def to_dict(self) -> dict[str, Any]:
        return {
            "adapters": {k: v.to_dict() for k, v in self.adapters.items()},
            "runtime_adapter_modules": dict(self.runtime_adapter_modules),
            "tool_adapter_modules": dict(self.tool_adapter_modules),
        }


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------

_ADAPTER_YAML_GLOB = "*-adapter-v*.yaml"


def scan_tool_adapters(domain_pack_path: Path) -> dict[str, AdapterEntry]:
    """Discover tool adapter YAML files under ``modules/*/tool-adapters/``.

    Parameters
    ----------
    domain_pack_path : Path
        Root of a single domain pack (e.g. ``domain-packs/education``).

    Returns
    -------
    dict mapping ``adapter_id`` → ``AdapterEntry``.
    """
    result: dict[str, AdapterEntry] = {}
    modules_dir = domain_pack_path / "modules"
    if not modules_dir.is_dir():
        return result

    for module_dir in sorted(modules_dir.iterdir()):
        if not module_dir.is_dir():
            continue
        ta_dir = module_dir / "tool-adapters"
        if not ta_dir.is_dir():
            continue

        for yaml_path in sorted(ta_dir.glob(_ADAPTER_YAML_GLOB)):
            try:
                data = load_yaml(yaml_path)
            except Exception as exc:
                log.warning("Skipping unparseable adapter file %s: %s", yaml_path.name, exc)
                continue

            if not isinstance(data, dict):
                log.warning("Adapter file %s did not parse to a mapping — skipping", yaml_path.name)
                continue

            adapter_id = data.get("id", "")
            if not adapter_id:
                log.warning("Adapter file %s missing 'id' field — skipping", yaml_path.name)
                continue

            entry = AdapterEntry(
                adapter_id=str(adapter_id),
                domain_id=str(data.get("domain_id", "")),
                module_path=str(module_dir.relative_to(domain_pack_path)),
                tool_name=str(data.get("tool_name", yaml_path.stem)),
                version=str(data.get("version", "0.0.0")),
                call_types=tuple(data.get("call_types") or []),
                input_schema=data.get("input_schema") or {},
                output_schema=data.get("output_schema") or {},
                source_file=str(yaml_path.relative_to(domain_pack_path)),
            )
            result[entry.adapter_id] = entry

    return result


def scan_runtime_adapters(domain_pack_path: Path) -> dict[str, str]:
    """Discover ``controllers/runtime_adapters.py`` and ``controllers/tool_adapters.py``.

    Returns a dict mapping a short key (``"runtime_adapters"`` /
    ``"tool_adapters"``) to the relative path within the domain pack.
    """
    result: dict[str, str] = {}
    controllers = domain_pack_path / "controllers"
    if not controllers.is_dir():
        return result

    for name in ("runtime_adapters.py", "tool_adapters.py"):
        candidate = controllers / name
        if candidate.is_file():
            result[name.removesuffix(".py")] = str(candidate.relative_to(domain_pack_path))

    return result


def build_router_index(domain_packs_root: Path) -> RouterIndex:
    """Aggregate all domain packs' adapters into a single ``RouterIndex``.

    Parameters
    ----------
    domain_packs_root : Path
        The ``domain-packs/`` directory.

    Returns
    -------
    RouterIndex with all discovered tool adapters and runtime modules.
    """
    index = RouterIndex()
    if not domain_packs_root.is_dir():
        log.warning("Domain packs root does not exist: %s", domain_packs_root)
        return index

    for pack_dir in sorted(domain_packs_root.iterdir()):
        if not pack_dir.is_dir():
            continue

        # Skip non-domain-pack directories (e.g. README.md files)
        if not (pack_dir / "cfg").is_dir() and not (pack_dir / "modules").is_dir():
            continue

        pack_name = pack_dir.name

        # Tool adapters
        for adapter_id, entry in scan_tool_adapters(pack_dir).items():
            if adapter_id in index.adapters:
                log.warning(
                    "Duplicate adapter ID %r in %s (already from %s) — keeping first",
                    adapter_id, pack_name, index.adapters[adapter_id].source_file,
                )
                continue
            index.adapters[adapter_id] = entry

        # Runtime/tool adapter modules
        for key, rel_path in scan_runtime_adapters(pack_dir).items():
            qualified_key = f"{pack_name}/{key}"
            index.runtime_adapter_modules[qualified_key] = f"domain-packs/{pack_name}/{rel_path}"

    log.info(
        "Adapter index built: %d tool adapters, %d runtime modules",
        len(index.adapters),
        len(index.runtime_adapter_modules),
    )
    return index
