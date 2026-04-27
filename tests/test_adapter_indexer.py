"""Tests for the Adapter Indexer — zero-AI-compute directory scanner."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from lumina.core.adapter_indexer import (
    AdapterEntry,
    GroupLibraryEntry,
    GroupToolEntry,
    RouterIndex,
    build_router_index,
    scan_group_resources,
    scan_runtime_adapters,
    scan_tool_adapters,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_ADAPTER_YAML = """\
id: adapter/test/sample/v1
version: "1.0.0"
tool_name: "Sample Tool"
description: "A test adapter."
domain_id: domain/test/module-1/v1
call_types:
  - do_thing
  - check_thing
input_schema:
  type: object
  required: [call_type]
  properties:
    call_type:
      type: string
output_schema:
  type: object
  properties:
    ok:
      type: boolean
"""


def _write_yaml(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_py(path: Path, content: str = "# placeholder\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


@pytest.fixture()
def fake_domain_pack(tmp_path: Path) -> Path:
    """Build a minimal domain pack structure under tmp_path."""
    pack = tmp_path / "test-domain"

    # Module with one adapter matching the naming convention
    _write_yaml(
        pack / "modules" / "module-1" / "tool-adapters" / "sample-adapter-v1.yaml",
        SAMPLE_ADAPTER_YAML,
    )

    # A second adapter in the same module
    _write_yaml(
        pack / "modules" / "module-1" / "tool-adapters" / "other-adapter-v2.yaml",
        SAMPLE_ADAPTER_YAML.replace("adapter/test/sample/v1", "adapter/test/other/v2")
        .replace("Sample Tool", "Other Tool"),
    )

    # A file that does NOT match the naming convention (should be ignored)
    _write_yaml(
        pack / "modules" / "module-1" / "tool-adapters" / "notes.yaml",
        "just: notes\n",
    )

    # Runtime adapter modules
    _write_py(pack / "controllers" / "runtime_adapters.py")
    _write_py(pack / "controllers" / "tool_adapters.py")

    # cfg dir (so build_router_index considers it a domain pack)
    (pack / "cfg").mkdir(parents=True, exist_ok=True)

    # domain-physics with group_libraries and group_tools
    physics = {
        "domain_id": "domain/test/module-1/v1",
        "group_libraries": [
            {
                "id": "test_helpers",
                "path": "domain-lib/test_helpers.py",
                "description": "Shared test helpers.",
                "shared_with_modules": ["module-1"],
            }
        ],
        "group_tools": [
            {
                "id": "test_validator",
                "path": "domain-lib/test_validator.py",
                "description": "Validates test artefacts.",
                "call_types": ["validate"],
                "shared_with_modules": ["module-1"],
            }
        ],
    }
    physics_path = pack / "modules" / "module-1" / "domain-physics.json"
    physics_path.write_text(json.dumps(physics, indent=2), encoding="utf-8")

    return pack


@pytest.fixture()
def fake_domain_packs_root(fake_domain_pack: Path) -> Path:
    """Return the parent of the fake domain pack (acts as model-packs/)."""
    return fake_domain_pack.parent


# ===================================================================
# Test: scan_tool_adapters
# ===================================================================


class TestScanToolAdapters:
    def test_discovers_matching_adapters(self, fake_domain_pack: Path):
        result = scan_tool_adapters(fake_domain_pack)
        assert len(result) == 2
        assert "adapter/test/sample/v1" in result
        assert "adapter/test/other/v2" in result

    def test_returns_adapter_entry(self, fake_domain_pack: Path):
        result = scan_tool_adapters(fake_domain_pack)
        entry = result["adapter/test/sample/v1"]
        assert isinstance(entry, AdapterEntry)
        assert entry.adapter_id == "adapter/test/sample/v1"
        assert entry.tool_name == "Sample Tool"
        assert entry.version == "1.0.0"
        assert "do_thing" in entry.call_types
        assert "check_thing" in entry.call_types
        assert entry.module_path == "modules\\module-1" or entry.module_path == "modules/module-1"

    def test_ignores_non_matching_files(self, fake_domain_pack: Path):
        result = scan_tool_adapters(fake_domain_pack)
        # notes.yaml does not match *-adapter-v*.yaml
        ids = set(result.keys())
        assert not any("notes" in aid for aid in ids)

    def test_empty_domain_pack(self, tmp_path: Path):
        result = scan_tool_adapters(tmp_path)
        assert result == {}

    def test_no_modules_dir(self, tmp_path: Path):
        (tmp_path / "cfg").mkdir()
        result = scan_tool_adapters(tmp_path)
        assert result == {}

    def test_skips_adapter_without_id(self, tmp_path: Path):
        _write_yaml(
            tmp_path / "modules" / "m1" / "tool-adapters" / "bad-adapter-v1.yaml",
            "tool_name: No ID\n",
        )
        result = scan_tool_adapters(tmp_path)
        assert len(result) == 0

    def test_to_dict(self, fake_domain_pack: Path):
        result = scan_tool_adapters(fake_domain_pack)
        entry = result["adapter/test/sample/v1"]
        d = entry.to_dict()
        assert d["adapter_id"] == "adapter/test/sample/v1"
        assert isinstance(d["call_types"], list)


# ===================================================================
# Test: scan_tool_adapters against real domain packs
# ===================================================================


class TestScanRealDomainPacks:
    """Verify the scanner discovers the 4 known adapters in the real codebase."""

    @pytest.fixture()
    def repo_root(self) -> Path:
        return Path(__file__).resolve().parents[1]

    def test_education_adapters(self, repo_root: Path):
        edu = repo_root / "model-packs" / "education"
        if not edu.is_dir():
            pytest.skip("Education domain pack not found")
        result = scan_tool_adapters(edu)
        assert len(result) >= 3
        ids = set(result.keys())
        assert "adapter/edu/calculator/v1" in ids
        assert "adapter/edu/algebra-parser/v1" in ids
        assert "adapter/edu/substitution-checker/v1" in ids

    def test_agriculture_adapter(self, repo_root: Path):
        agri = repo_root / "model-packs" / "agriculture"
        if not agri.is_dir():
            pytest.skip("Agriculture domain pack not found")
        result = scan_tool_adapters(agri)
        assert len(result) >= 1
        assert "adapter/agri/collar-sensor/v1" in set(result.keys())


# ===================================================================
# Test: scan_runtime_adapters
# ===================================================================


class TestScanRuntimeAdapters:
    def test_discovers_both_modules(self, fake_domain_pack: Path):
        result = scan_runtime_adapters(fake_domain_pack)
        assert "runtime_adapters" in result
        assert "tool_adapters" in result

    def test_missing_controllers(self, tmp_path: Path):
        result = scan_runtime_adapters(tmp_path)
        assert result == {}

    def test_partial_modules(self, tmp_path: Path):
        _write_py(tmp_path / "controllers" / "runtime_adapters.py")
        result = scan_runtime_adapters(tmp_path)
        assert "runtime_adapters" in result
        assert "tool_adapters" not in result


# ===================================================================
# Test: build_router_index
# ===================================================================


class TestBuildRouterIndex:
    def test_aggregates_adapters(self, fake_domain_packs_root: Path):
        index = build_router_index(fake_domain_packs_root)
        assert isinstance(index, RouterIndex)
        assert len(index.adapters) == 2

    def test_adapter_ids_property(self, fake_domain_packs_root: Path):
        index = build_router_index(fake_domain_packs_root)
        assert isinstance(index.adapter_ids, frozenset)
        assert "adapter/test/sample/v1" in index.adapter_ids

    def test_runtime_modules_discovered(self, fake_domain_packs_root: Path):
        index = build_router_index(fake_domain_packs_root)
        # Keys are qualified: "{pack_name}/runtime_adapters"
        assert any("runtime_adapters" in k for k in index.runtime_adapter_modules)
        assert any("tool_adapters" in k for k in index.runtime_adapter_modules)

    def test_to_dict(self, fake_domain_packs_root: Path):
        index = build_router_index(fake_domain_packs_root)
        d = index.to_dict()
        assert "adapters" in d
        assert "runtime_adapter_modules" in d

    def test_nonexistent_root(self, tmp_path: Path):
        index = build_router_index(tmp_path / "nope")
        assert len(index.adapters) == 0

    def test_real_domain_packs(self):
        repo_root = Path(__file__).resolve().parents[1]
        dp_root = repo_root / "model-packs"
        if not dp_root.is_dir():
            pytest.skip("model-packs not found")
        index = build_router_index(dp_root)
        assert len(index.adapters) >= 4  # 3 edu + 1 agri
        assert len(index.runtime_adapter_modules) >= 2

    def test_duplicate_id_keeps_first(self, tmp_path: Path):
        """Two domain packs with the same adapter ID — first wins (sorted order)."""
        for name in ("aaa-pack", "bbb-pack"):
            _write_yaml(
                tmp_path / name / "modules" / "m1" / "tool-adapters" / "dup-adapter-v1.yaml",
                SAMPLE_ADAPTER_YAML.replace("Sample Tool", f"Tool from {name}"),
            )
            (tmp_path / name / "cfg").mkdir(parents=True, exist_ok=True)

        index = build_router_index(tmp_path)
        entry = index.adapters["adapter/test/sample/v1"]
        # build_router_index iterates sorted — aaa-pack comes first
        assert entry.tool_name == "Tool from aaa-pack"


# ===================================================================
# Test: AdapterEntry
# ===================================================================


class TestAdapterEntry:
    def test_frozen(self):
        entry = AdapterEntry(
            adapter_id="x", domain_id="d", module_path="m",
            tool_name="t", version="1", call_types=("a",),
            input_schema={}, output_schema={}, source_file="f",
        )
        with pytest.raises(AttributeError):
            entry.adapter_id = "y"  # type: ignore[misc]


# ===================================================================
# Test: scan_group_resources integration with fake domain pack
# ===================================================================


class TestScanGroupResourcesIntegration:
    def test_scan_from_fake_pack(self, fake_domain_pack: Path):
        libs, tools = scan_group_resources(fake_domain_pack)
        assert any("test_helpers" in k for k in libs)
        assert any("test_validator" in k for k in tools)

    def test_build_router_index_includes_groups(self, fake_domain_packs_root: Path):
        index = build_router_index(fake_domain_packs_root)
        assert len(index.group_libraries) >= 1
        assert isinstance(next(iter(index.group_libraries.values())), GroupLibraryEntry)

    def test_router_index_to_dict_has_groups(self, fake_domain_packs_root: Path):
        d = build_router_index(fake_domain_packs_root).to_dict()
        assert "group_libraries" in d
        assert "group_tools" in d

    def test_real_agriculture_group_libraries(self):
        repo_root = Path(__file__).resolve().parents[1]
        agri = repo_root / "model-packs" / "agriculture"
        if not agri.is_dir():
            pytest.skip("Agriculture domain pack not found")
        libs, _ = scan_group_resources(agri)
        assert any("environmental_sensors" in k for k in libs)
