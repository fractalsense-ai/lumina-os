"""
Tests verifying that the codebase no longer relies on the optional PyYAML
package at runtime, and that lumina.core.yaml_loader.load_yaml correctly
handles all YAML patterns used by the project — including the block-mapping-
as-list-item pattern required by mud-world-templates.yaml.

Regression context:
    GET /api/domain-info and POST /api/domain-pack/commit raised
    "ModuleNotFoundError: No module named 'yaml'" on a fresh clone because
    src/lumina/core/runtime_loader.py and src/lumina/api/server.py contained
    deferred `import yaml as _yaml` calls (PyYAML) that were never listed in
    requirements.txt.  The fix replaces both call-sites with load_yaml() from
    lumina.core.yaml_loader, which is a stdlib-only implementation.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

from lumina.core.yaml_loader import load_yaml

_SRC_ROOT = pathlib.Path(__file__).resolve().parents[1] / "src"


# ─────────────────────────────────────────────────────────────
# Structural: no bare `import yaml` in source files
# ─────────────────────────────────────────────────────────────


def _assert_no_bare_yaml_import(src_file: pathlib.Path) -> None:
    """Raise AssertionError if ``import yaml`` appears as a top-level or
    deferred import in *src_file*."""
    # utf-8-sig strips a leading BOM (U+FEFF) present in some editors' output.
    tree = ast.parse(src_file.read_text(encoding="utf-8-sig"), filename=str(src_file))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name != "yaml", (
                    f"{src_file.relative_to(_SRC_ROOT)} still contains "
                    f"'import yaml' — use lumina.core.yaml_loader.load_yaml instead."
                )


@pytest.mark.unit
def test_no_pyyaml_import_in_runtime_loader() -> None:
    """runtime_loader.py must not contain a deferred PyYAML import."""
    _assert_no_bare_yaml_import(
        _SRC_ROOT / "lumina" / "core" / "runtime_loader.py"
    )


@pytest.mark.unit
def test_no_pyyaml_import_in_server() -> None:
    """server.py must not contain a deferred PyYAML import."""
    _assert_no_bare_yaml_import(
        _SRC_ROOT / "lumina" / "api" / "server.py"
    )


# ─────────────────────────────────────────────────────────────
# load_yaml: basic scalar / mapping / list behaviour
# ─────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_load_yaml_empty_file_returns_empty_dict(tmp_path: pathlib.Path) -> None:
    f = tmp_path / "empty.yaml"
    f.write_text("", encoding="utf-8")
    assert load_yaml(f) == {}


@pytest.mark.unit
def test_load_yaml_comment_only_returns_empty_dict(tmp_path: pathlib.Path) -> None:
    f = tmp_path / "comments.yaml"
    f.write_text("# comment\n# another comment\n", encoding="utf-8")
    assert load_yaml(f) == {}


@pytest.mark.unit
def test_load_yaml_flat_scalars(tmp_path: pathlib.Path) -> None:
    f = tmp_path / "flat.yaml"
    f.write_text(
        "enabled: true\ncount: 3\nname: lumina\n",
        encoding="utf-8",
    )
    result = load_yaml(f)
    assert result == {"enabled": True, "count": 3, "name": "lumina"}


@pytest.mark.unit
def test_load_yaml_nested_mapping(tmp_path: pathlib.Path) -> None:
    f = tmp_path / "nested.yaml"
    f.write_text(
        "night_cycle:\n  enabled: true\n  interval_hours: 8\n",
        encoding="utf-8",
    )
    result = load_yaml(f)
    assert result["night_cycle"]["enabled"] is True
    assert result["night_cycle"]["interval_hours"] == 8


@pytest.mark.unit
def test_load_yaml_simple_list(tmp_path: pathlib.Path) -> None:
    f = tmp_path / "list.yaml"
    f.write_text(
        "items:\n  - alpha\n  - beta\n  - gamma\n",
        encoding="utf-8",
    )
    result = load_yaml(f)
    assert result["items"] == ["alpha", "beta", "gamma"]


# ─────────────────────────────────────────────────────────────
# load_yaml: block-mapping-as-list-item (templates pattern)
# ─────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_load_yaml_block_mapping_list_items(tmp_path: pathlib.Path) -> None:
    """load_yaml must parse '- key: val / more_key: val' list items as dicts.

    This covers the mud-world-templates.yaml structure that previously
    required PyYAML.
    """
    f = tmp_path / "templates.yaml"
    f.write_text(
        "templates:\n"
        "  - id: forest_world\n"
        "    zone: The Enchanted Forest\n"
        "    protagonist: Junior Ranger\n"
        "    enabled: true\n"
        "  - id: space_world\n"
        "    zone: The Star Sector\n"
        "    protagonist: Mission Mathematician\n"
        "    enabled: false\n",
        encoding="utf-8",
    )
    result = load_yaml(f)

    assert "templates" in result
    templates = result["templates"]
    assert isinstance(templates, list)
    assert len(templates) == 2

    forest = templates[0]
    assert isinstance(forest, dict)
    assert forest["id"] == "forest_world"
    assert forest["zone"] == "The Enchanted Forest"
    assert forest["protagonist"] == "Junior Ranger"
    assert forest["enabled"] is True

    space = templates[1]
    assert isinstance(space, dict)
    assert space["id"] == "space_world"
    assert space["enabled"] is False


@pytest.mark.unit
def test_load_yaml_block_mapping_list_items_nested_list(tmp_path: pathlib.Path) -> None:
    """Dict-in-list items may themselves contain nested lists (preference_keywords)."""
    f = tmp_path / "templates.yaml"
    f.write_text(
        "templates:\n"
        "  - id: dungeon\n"
        "    preference_keywords:\n"
        "      - fantasy\n"
        "      - dnd\n"
        "    zone: The Dungeon\n"
        "  - id: general_math\n"
        "    preference_keywords:\n"
        "    zone: The Classroom\n",
        encoding="utf-8",
    )
    result = load_yaml(f)
    templates = result["templates"]
    assert len(templates) == 2

    dungeon = templates[0]
    assert dungeon["id"] == "dungeon"
    assert dungeon["preference_keywords"] == ["fantasy", "dnd"]
    assert dungeon["zone"] == "The Dungeon"

    general = templates[1]
    assert general["id"] == "general_math"
    assert general["zone"] == "The Classroom"


@pytest.mark.unit
def test_load_yaml_block_mapping_list_get_templates(tmp_path: pathlib.Path) -> None:
    """Simulate the exact runtime_loader.py templates_path resolution pattern."""
    tpl_path = tmp_path / "mud-world-templates.yaml"
    tpl_path.write_text(
        "version: '1.0.0'\n"
        "templates:\n"
        "  - id: quest_world\n"
        "    zone: The Quest Map\n"
        "    protagonist: Hero\n"
        "    preference_keywords:\n"
        "      - adventure\n"
        "      - rpg\n"
        "  - id: general_math\n"
        "    zone: The Classroom\n"
        "    protagonist: Student\n"
        "    preference_keywords:\n",
        encoding="utf-8",
    )

    tpl_data = load_yaml(tpl_path)
    templates = tpl_data.get("templates") or []

    assert isinstance(templates, list)
    assert len(templates) == 2
    assert templates[0]["id"] == "quest_world"
    assert templates[0]["preference_keywords"] == ["adventure", "rpg"]
    assert templates[0]["zone"] == "The Quest Map"
    assert templates[1]["id"] == "general_math"


# ─────────────────────────────────────────────────────────────
# load_yaml: night-cycle config pattern (server.py use-case)
# ─────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_load_yaml_night_cycle_config(tmp_path: pathlib.Path) -> None:
    """load_yaml correctly reads a night_cycle section from a runtime config."""
    cfg = tmp_path / "system-runtime-config.yaml"
    cfg.write_text(
        "night_cycle:\n"
        "  enabled: true\n"
        "  hour: 2\n"
        "  timezone: UTC\n",
        encoding="utf-8",
    )
    result = load_yaml(cfg)
    nc = result.get("night_cycle", {})
    assert nc["enabled"] is True
    assert nc["hour"] == 2


# ─────────────────────────────────────────────────────────────
# Regression: existing simple-list behaviour is unchanged
# ─────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_load_yaml_simple_string_list_unchanged(tmp_path: pathlib.Path) -> None:
    """Simple string lists (e.g. additional_specs) are still parsed correctly."""
    f = tmp_path / "config.yaml"
    f.write_text(
        "additional_specs:\n"
        "  - specs/global.md\n"
        "  - specs/domain.md\n",
        encoding="utf-8",
    )
    result = load_yaml(f)
    assert result["additional_specs"] == ["specs/global.md", "specs/domain.md"]
