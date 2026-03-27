"""Tests for group libraries and group tools discovery (Phase 2)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lumina.core.adapter_indexer import (
    GroupLibraryEntry,
    GroupToolEntry,
    RouterIndex,
    build_router_index,
    scan_group_resources,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_physics(module_dir: Path, data: dict) -> None:
    module_dir.mkdir(parents=True, exist_ok=True)
    (module_dir / "domain-physics.json").write_text(
        json.dumps(data, indent=2), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def domain_pack_with_groups(tmp_path: Path) -> Path:
    """Fake domain pack with 2 modules sharing a group library + 1 group tool."""
    pack = tmp_path / "test-agri"

    # Module 1: declares env_sensors library + irrigation_validator tool
    _write_physics(pack / "modules" / "ops-1", {
        "domain_id": "agriculture/ops-1",
        "group_libraries": [
            {
                "id": "environmental_sensors",
                "path": "domain-lib/environmental_sensors.py",
                "description": "Sensor helpers.",
                "shared_with_modules": ["ops-1", "crop-planning"],
            },
        ],
        "group_tools": [
            {
                "id": "irrigation_validator",
                "path": "domain-lib/irrigation_validator.py",
                "description": "Validates irrigation schedules.",
                "call_types": ["validate", "dry_run"],
                "shared_with_modules": ["ops-1"],
            },
        ],
    })

    # Module 2: also declares env_sensors (same id → should dedup)
    _write_physics(pack / "modules" / "crop-planning", {
        "domain_id": "agriculture/crop-planning",
        "group_libraries": [
            {
                "id": "environmental_sensors",
                "path": "domain-lib/environmental_sensors.py",
                "description": "Sensor helpers.",
                "shared_with_modules": ["ops-1", "crop-planning"],
            },
        ],
    })

    # cfg dir so build_router_index considers it a domain pack
    (pack / "cfg").mkdir(parents=True, exist_ok=True)

    return pack


@pytest.fixture()
def empty_domain_pack(tmp_path: Path) -> Path:
    pack = tmp_path / "empty-pack"
    (pack / "cfg").mkdir(parents=True, exist_ok=True)
    return pack


# ===================================================================
# Test: scan_group_resources
# ===================================================================


class TestScanGroupResources:
    def test_discovers_libraries(self, domain_pack_with_groups: Path):
        libs, _ = scan_group_resources(domain_pack_with_groups)
        assert any("environmental_sensors" in k for k in libs)

    def test_discovers_tools(self, domain_pack_with_groups: Path):
        _, tools = scan_group_resources(domain_pack_with_groups)
        assert any("irrigation_validator" in k for k in tools)

    def test_library_entry_fields(self, domain_pack_with_groups: Path):
        libs, _ = scan_group_resources(domain_pack_with_groups)
        key = next(k for k in libs if "environmental_sensors" in k)
        entry = libs[key]
        assert isinstance(entry, GroupLibraryEntry)
        assert entry.library_id == "environmental_sensors"
        assert entry.domain_id == "test-agri"
        assert "environmental_sensors.py" in entry.path
        assert entry.description == "Sensor helpers."
        assert "ops-1" in entry.shared_with_modules

    def test_tool_entry_fields(self, domain_pack_with_groups: Path):
        _, tools = scan_group_resources(domain_pack_with_groups)
        key = next(k for k in tools if "irrigation_validator" in k)
        entry = tools[key]
        assert isinstance(entry, GroupToolEntry)
        assert entry.tool_id == "irrigation_validator"
        assert entry.domain_id == "test-agri"
        assert "validate" in entry.call_types
        assert "dry_run" in entry.call_types

    def test_deduplicates_across_modules(self, domain_pack_with_groups: Path):
        libs, _ = scan_group_resources(domain_pack_with_groups)
        env_keys = [k for k in libs if "environmental_sensors" in k]
        assert len(env_keys) == 1

    def test_empty_domain_pack(self, empty_domain_pack: Path):
        libs, tools = scan_group_resources(empty_domain_pack)
        assert libs == {}
        assert tools == {}

    def test_nonexistent_path(self, tmp_path: Path):
        libs, tools = scan_group_resources(tmp_path / "nope")
        assert libs == {}
        assert tools == {}

    def test_no_modules_dir(self, tmp_path: Path):
        (tmp_path / "cfg").mkdir()
        libs, tools = scan_group_resources(tmp_path)
        assert libs == {}
        assert tools == {}

    def test_skips_library_without_id(self, tmp_path: Path):
        _write_physics(tmp_path / "modules" / "m1", {
            "group_libraries": [{"description": "no id field"}],
        })
        libs, _ = scan_group_resources(tmp_path)
        assert libs == {}

    def test_skips_tool_without_id(self, tmp_path: Path):
        _write_physics(tmp_path / "modules" / "m1", {
            "group_tools": [{"description": "no id field"}],
        })
        _, tools = scan_group_resources(tmp_path)
        assert tools == {}

    def test_to_dict_library(self, domain_pack_with_groups: Path):
        libs, _ = scan_group_resources(domain_pack_with_groups)
        key = next(k for k in libs if "environmental_sensors" in k)
        d = libs[key].to_dict()
        assert d["library_id"] == "environmental_sensors"
        assert isinstance(d["shared_with_modules"], list)

    def test_to_dict_tool(self, domain_pack_with_groups: Path):
        _, tools = scan_group_resources(domain_pack_with_groups)
        key = next(k for k in tools if "irrigation_validator" in k)
        d = tools[key].to_dict()
        assert d["tool_id"] == "irrigation_validator"
        assert isinstance(d["call_types"], list)

    def test_frozen_library_entry(self, domain_pack_with_groups: Path):
        libs, _ = scan_group_resources(domain_pack_with_groups)
        entry = next(iter(libs.values()))
        with pytest.raises(AttributeError):
            entry.library_id = "x"  # type: ignore[misc]

    def test_frozen_tool_entry(self, domain_pack_with_groups: Path):
        _, tools = scan_group_resources(domain_pack_with_groups)
        entry = next(iter(tools.values()))
        with pytest.raises(AttributeError):
            entry.tool_id = "x"  # type: ignore[misc]


# ===================================================================
# Test: RouterIndex with group resources
# ===================================================================


class TestRouterIndexGroupResources:
    def test_index_contains_group_libraries(self, domain_pack_with_groups: Path):
        index = build_router_index(domain_pack_with_groups.parent)
        assert len(index.group_libraries) >= 1

    def test_index_contains_group_tools(self, domain_pack_with_groups: Path):
        index = build_router_index(domain_pack_with_groups.parent)
        assert len(index.group_tools) >= 1

    def test_to_dict_includes_groups(self, domain_pack_with_groups: Path):
        index = build_router_index(domain_pack_with_groups.parent)
        d = index.to_dict()
        assert "group_libraries" in d
        assert "group_tools" in d
        assert len(d["group_libraries"]) >= 1

    def test_empty_pack_has_empty_groups(self, empty_domain_pack: Path):
        index = build_router_index(empty_domain_pack.parent)
        assert index.group_libraries == {}
        assert index.group_tools == {}


# ===================================================================
# Test: Real agriculture domain pack group resources
# ===================================================================


class TestRealGroupResources:
    @pytest.fixture()
    def repo_root(self) -> Path:
        return Path(__file__).resolve().parents[1]

    def test_agriculture_has_group_library(self, repo_root: Path):
        agri = repo_root / "domain-packs" / "agriculture"
        if not agri.is_dir():
            pytest.skip("Agriculture domain pack not found")
        libs, _ = scan_group_resources(agri)
        assert any("environmental_sensors" in k for k in libs)

    def test_environmental_sensors_file_exists(self, repo_root: Path):
        sensors = repo_root / "domain-packs" / "agriculture" / "domain-lib" / "environmental_sensors.py"
        if not sensors.is_file():
            pytest.skip("environmental_sensors.py not found")
        content = sensors.read_text(encoding="utf-8")
        assert "SensorReading" in content or "sensor" in content.lower()
