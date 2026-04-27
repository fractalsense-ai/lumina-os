"""Adapter Indexer — zero-AI-compute directory scanner for tool adapters.

Walks ``model-packs/*/modules/*/tool-adapters/`` directories and reads
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

import json
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


@dataclass(frozen=True)
class GroupLibraryEntry:
    """Metadata for a shared Group Library declared in a physics file."""

    library_id: str
    domain_id: str
    path: str              # Relative to domain pack root
    description: str
    shared_with_modules: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "library_id": self.library_id,
            "domain_id": self.domain_id,
            "path": self.path,
            "description": self.description,
            "shared_with_modules": list(self.shared_with_modules),
        }


@dataclass(frozen=True)
class GroupToolEntry:
    """Metadata for a shared Group Tool declared in a physics file."""

    tool_id: str
    domain_id: str
    path: str              # Relative to domain pack root
    description: str
    call_types: tuple[str, ...]
    shared_with_modules: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_id": self.tool_id,
            "domain_id": self.domain_id,
            "path": self.path,
            "description": self.description,
            "call_types": list(self.call_types),
            "shared_with_modules": list(self.shared_with_modules),
        }


@dataclass
class RouterIndex:
    """Aggregated index of all discovered adapters across domain packs."""

    adapters: dict[str, AdapterEntry] = field(default_factory=dict)
    runtime_adapter_modules: dict[str, str] = field(default_factory=dict)
    tool_adapter_modules: dict[str, str] = field(default_factory=dict)
    group_libraries: dict[str, GroupLibraryEntry] = field(default_factory=dict)
    group_tools: dict[str, GroupToolEntry] = field(default_factory=dict)

    @property
    def adapter_ids(self) -> frozenset[str]:
        return frozenset(self.adapters)

    def to_dict(self) -> dict[str, Any]:
        return {
            "adapters": {k: v.to_dict() for k, v in self.adapters.items()},
            "runtime_adapter_modules": dict(self.runtime_adapter_modules),
            "tool_adapter_modules": dict(self.tool_adapter_modules),
            "group_libraries": {k: v.to_dict() for k, v in self.group_libraries.items()},
            "group_tools": {k: v.to_dict() for k, v in self.group_tools.items()},
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
        Root of a single domain pack (e.g. ``model-packs/education``).

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


def _load_physics(physics_path: Path) -> dict[str, Any] | None:
    """Load a domain-physics file (JSON or YAML) and return the parsed dict."""
    try:
        if physics_path.suffix == ".json":
            return json.loads(physics_path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]
        return load_yaml(physics_path)  # type: ignore[return-value]
    except Exception as exc:
        log.warning("Could not parse physics file %s: %s", physics_path.name, exc)
        return None


def scan_group_resources(
    domain_pack_path: Path,
) -> tuple[dict[str, GroupLibraryEntry], dict[str, GroupToolEntry]]:
    """Discover group_libraries and group_tools from physics files.

    Reads every ``modules/*/domain-physics.{json,yaml}`` file and extracts
    the ``group_libraries`` and ``group_tools`` arrays.

    Returns
    -------
    (group_libraries, group_tools) dicts keyed by ``{pack_name}/{id}``.
    """
    libraries: dict[str, GroupLibraryEntry] = {}
    tools: dict[str, GroupToolEntry] = {}
    modules_dir = domain_pack_path / "modules"
    if not modules_dir.is_dir():
        return libraries, tools

    pack_name = domain_pack_path.name

    for module_dir in sorted(modules_dir.iterdir()):
        if not module_dir.is_dir():
            continue
        for suffix in (".json", ".yaml"):
            physics_path = module_dir / f"domain-physics{suffix}"
            if not physics_path.is_file():
                continue
            data = _load_physics(physics_path)
            if not isinstance(data, dict):
                continue

            for lib in data.get("group_libraries") or []:
                if not isinstance(lib, dict) or "id" not in lib:
                    continue
                lib_id = str(lib["id"])
                key = f"{pack_name}/{lib_id}"
                if key not in libraries:
                    libraries[key] = GroupLibraryEntry(
                        library_id=lib_id,
                        domain_id=pack_name,
                        path=str(lib.get("path", "")),
                        description=str(lib.get("description", "")),
                        shared_with_modules=tuple(lib.get("shared_with_modules") or []),
                    )

            for tool in data.get("group_tools") or []:
                if not isinstance(tool, dict) or "id" not in tool:
                    continue
                tool_id = str(tool["id"])
                key = f"{pack_name}/{tool_id}"
                if key not in tools:
                    tools[key] = GroupToolEntry(
                        tool_id=tool_id,
                        domain_id=pack_name,
                        path=str(tool.get("path", "")),
                        description=str(tool.get("description", "")),
                        call_types=tuple(tool.get("call_types") or []),
                        shared_with_modules=tuple(tool.get("shared_with_modules") or []),
                    )

    return libraries, tools


def build_router_index(domain_packs_root: Path) -> RouterIndex:
    """Aggregate all domain packs' adapters into a single ``RouterIndex``.

    Parameters
    ----------
    domain_packs_root : Path
        The ``model-packs/`` directory.

    Returns
    -------
    RouterIndex with all discovered tool adapters, runtime modules,
    group libraries, and group tools.
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
            index.runtime_adapter_modules[qualified_key] = f"model-packs/{pack_name}/{rel_path}"

        # Group libraries and group tools
        libs, grp_tools = scan_group_resources(pack_dir)
        index.group_libraries.update(libs)
        index.group_tools.update(grp_tools)

    log.info(
        "Adapter index built: %d tool adapters, %d runtime modules, "
        "%d group libraries, %d group tools",
        len(index.adapters),
        len(index.runtime_adapter_modules),
        len(index.group_libraries),
        len(index.group_tools),
    )
    return index
