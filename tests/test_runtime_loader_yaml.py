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
        "daemon:\n  enabled: true\n  interval_hours: 8\n",
        encoding="utf-8",
    )
    result = load_yaml(f)
    assert result["daemon"]["enabled"] is True
    assert result["daemon"]["interval_hours"] == 8


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


# ─────────────────────────────────────────────────────────────
# ui-config.yaml auto-discovery
# ─────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_ui_config_auto_discovery(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """ui-config.yaml in the same directory as runtime-config.yaml is
    merged into cfg before the loader processes ui_manifest / ui keys."""
    from lumina.core import runtime_loader as _rl

    # Write a minimal runtime-config.yaml WITHOUT ui_manifest or ui.
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()
    (cfg_dir / "runtime-config.yaml").write_text(
        "runtime:\n"
        "  domain_system_prompt_path: p.md\n"
        "  turn_interpretation_prompt_path: t.md\n"
        "  domain_physics_path: dp.json\n"
        "  subject_profile_path: sp.yaml\n"
        "  default_task_spec:\n"
        "    task_id: t1\n"
        "adapters:\n"
        "  state_builder: {module_path: m.py, callable: f}\n"
        "  domain_step: {module_path: m.py, callable: f}\n"
        "  turn_interpreter: {module_path: m.py, callable: f}\n",
        encoding="utf-8",
    )

    # Write ui-config.yaml with ui_manifest and ui keys.
    (cfg_dir / "ui-config.yaml").write_text(
        "ui_manifest:\n"
        "  title: From UI Config\n"
        "  subtitle: Test\n"
        "ui:\n"
        "  plugin_bundle: test/plugin.js\n",
        encoding="utf-8",
    )

    # Intercept load_yaml to capture the cfg dict after merge but before
    # the rest of load_runtime_context tries to read prompt files.
    merged_cfg: dict = {}

    original_validate = _rl._validate_runtime_config

    def capture_validate(repo_root, cfg, cfg_path):
        merged_cfg.update(cfg)
        return original_validate(repo_root, cfg, cfg_path)

    monkeypatch.setattr(_rl, "_validate_runtime_config", capture_validate)

    # Call will raise because prompt files don't exist — that's fine;
    # we only care about the merged cfg dict.
    try:
        _rl.load_runtime_context(tmp_path, "cfg/runtime-config.yaml")
    except (RuntimeError, FileNotFoundError, OSError):
        pass

    assert merged_cfg.get("ui_manifest") == {"title": "From UI Config", "subtitle": "Test"}
    assert merged_cfg.get("ui") == {"plugin_bundle": "test/plugin.js"}


@pytest.mark.unit
def test_ui_config_inline_takes_precedence(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Inline ui_manifest in runtime-config.yaml takes precedence over
    ui-config.yaml (backward compatible)."""
    from lumina.core import runtime_loader as _rl

    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()
    (cfg_dir / "runtime-config.yaml").write_text(
        "runtime:\n"
        "  domain_system_prompt_path: p.md\n"
        "  turn_interpretation_prompt_path: t.md\n"
        "  domain_physics_path: dp.json\n"
        "  subject_profile_path: sp.yaml\n"
        "  default_task_spec:\n"
        "    task_id: t1\n"
        "adapters:\n"
        "  state_builder: {module_path: m.py, callable: f}\n"
        "  domain_step: {module_path: m.py, callable: f}\n"
        "  turn_interpreter: {module_path: m.py, callable: f}\n"
        "ui_manifest:\n"
        "  title: Inline Wins\n",
        encoding="utf-8",
    )

    (cfg_dir / "ui-config.yaml").write_text(
        "ui_manifest:\n"
        "  title: Should Be Ignored\n",
        encoding="utf-8",
    )

    merged_cfg: dict = {}
    original_validate = _rl._validate_runtime_config

    def capture_validate(repo_root, cfg, cfg_path):
        merged_cfg.update(cfg)
        return original_validate(repo_root, cfg, cfg_path)

    monkeypatch.setattr(_rl, "_validate_runtime_config", capture_validate)

    try:
        _rl.load_runtime_context(tmp_path, "cfg/runtime-config.yaml")
    except (RuntimeError, FileNotFoundError, OSError):
        pass

    assert merged_cfg["ui_manifest"]["title"] == "Inline Wins"


# ─────────────────────────────────────────────────────────────
# load_yaml: daemon config pattern (server.py use-case)
# ─────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_load_yaml_daemon_config(tmp_path: pathlib.Path) -> None:
    """load_yaml correctly reads a daemon section from a runtime config."""
    cfg = tmp_path / "system-runtime-config.yaml"
    cfg.write_text(
        "daemon:\n"
        "  enabled: true\n"
        "  hour: 2\n"
        "  timezone: UTC\n",
        encoding="utf-8",
    )
    result = load_yaml(cfg)
    dc = result.get("daemon", {})
    assert dc["enabled"] is True
    assert dc["hour"] == 2


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


# ─────────────────────────────────────────────────────────────
# Phase 4: compile_execution_routes is importable and callable
# ─────────────────────────────────────────────────────────────


def test_compile_execution_routes_importable() -> None:
    """Route compiler module exists and compile_execution_routes is callable."""
    from lumina.core.route_compiler import compile_execution_routes
    assert callable(compile_execution_routes)
