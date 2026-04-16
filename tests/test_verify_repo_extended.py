"""Extended tests for lumina.systools.verify_repo: runtime config and algebra alignment."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

import lumina.systools.verify_repo as verify_mod
from lumina.systools.verify_repo import (
    check_algebra_version_alignment,
    check_runtime_config_paths,
)


def _patch_root(tmp_path: Path):
    return patch.object(verify_mod, "REPO_ROOT", tmp_path)


# ── load_yaml (local wrapper) ─────────────────────────────────────────────────


@pytest.mark.unit
def test_load_yaml_returns_dict(tmp_path: Path) -> None:
    from lumina.systools.verify_repo import load_yaml
    f = tmp_path / "test.yaml"
    f.write_text("key: value\n", encoding="utf-8")
    result = load_yaml(f)
    assert result["key"] == "value"


@pytest.mark.unit
def test_load_yaml_valid_dict(tmp_path: Path) -> None:
    from lumina.systools.verify_repo import load_yaml
    f = tmp_path / "test.yaml"
    f.write_text("foo: bar\nbaz: 42\n", encoding="utf-8")
    result = load_yaml(f)
    assert result["foo"] == "bar"


# ── check_runtime_config_paths ────────────────────────────────────────────────


def _make_runtime_config(tmp_path: Path, extra_fields: dict | None = None) -> None:
    """Create a domain-packs/education/runtime-config.yaml with required fields."""
    edu_dir = tmp_path / "domain-packs" / "education"
    edu_dir.mkdir(parents=True, exist_ok=True)

    # Create the target files
    (tmp_path / "specs" / "domain-system-prompt.md").parent.mkdir(parents=True, exist_ok=True)
    for rel in [
        "specs/domain-system-prompt.md",
        "specs/turn-interpretation-prompt.md",
        "domain-packs/education/domain-physics.json",
        "domain-packs/education/profiles/student.yaml",
    ]:
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("content", encoding="utf-8")

    runtime_cfg = {
        "runtime": {
            "domain_system_prompt_path": "specs/domain-system-prompt.md",
            "turn_interpretation_prompt_path": "specs/turn-interpretation-prompt.md",
            "domain_physics_path": "domain-packs/education/domain-physics.json",
            "subject_profile_path": "domain-packs/education/profiles/student.yaml",
        }
    }
    if extra_fields:
        runtime_cfg["runtime"].update(extra_fields)

    import yaml as _yaml_module
    try:
        import yaml
        content = yaml.dump(runtime_cfg)
    except ImportError:
        # Write minimal YAML manually
        content = (
            "runtime:\n"
            "  domain_system_prompt_path: specs/domain-system-prompt.md\n"
            "  turn_interpretation_prompt_path: specs/turn-interpretation-prompt.md\n"
            "  domain_physics_path: domain-packs/education/domain-physics.json\n"
            "  subject_profile_path: domain-packs/education/profiles/student.yaml\n"
        )
    (edu_dir / "runtime-config.yaml").write_text(content, encoding="utf-8")


@pytest.mark.unit
def test_check_runtime_config_paths_all_ok(tmp_path: Path) -> None:
    _make_runtime_config(tmp_path)
    errors: list[str] = []
    with _patch_root(tmp_path):
        check_runtime_config_paths(errors)
    assert errors == []


@pytest.mark.unit
def test_check_runtime_config_paths_missing_runtime_key(tmp_path: Path) -> None:
    edu_dir = tmp_path / "domain-packs" / "education"
    edu_dir.mkdir(parents=True, exist_ok=True)
    (edu_dir / "runtime-config.yaml").write_text("other: value\n", encoding="utf-8")

    errors: list[str] = []
    with _patch_root(tmp_path):
        check_runtime_config_paths(errors)
    assert any("missing or invalid" in e for e in errors)


@pytest.mark.unit
def test_check_runtime_config_paths_missing_target_file(tmp_path: Path) -> None:
    edu_dir = tmp_path / "domain-packs" / "education"
    edu_dir.mkdir(parents=True, exist_ok=True)
    (edu_dir / "runtime-config.yaml").write_text(
        "runtime:\n"
        "  domain_system_prompt_path: specs/missing-file.md\n"
        "  turn_interpretation_prompt_path: specs/missing-turn.md\n"
        "  domain_physics_path: domain-packs/education/missing-physics.json\n"
        "  subject_profile_path: domain-packs/education/profiles/missing.yaml\n",
        encoding="utf-8",
    )
    errors: list[str] = []
    with _patch_root(tmp_path):
        check_runtime_config_paths(errors)
    assert any("missing file" in e for e in errors)


@pytest.mark.unit
def test_check_runtime_config_paths_with_additional_specs(tmp_path: Path) -> None:
    _make_runtime_config(tmp_path)
    # Write an additional_specs entry that exists
    edu_dir = tmp_path / "domain-packs" / "education"
    spec_file = tmp_path / "specs" / "extra-spec.md"
    spec_file.parent.mkdir(parents=True, exist_ok=True)
    spec_file.write_text("# extra", encoding="utf-8")

    runtime_cfg_path = edu_dir / "runtime-config.yaml"
    content = runtime_cfg_path.read_text(encoding="utf-8")
    # Append additional_specs
    content += "  additional_specs:\n    - specs/extra-spec.md\n"
    runtime_cfg_path.write_text(content, encoding="utf-8")

    errors: list[str] = []
    with _patch_root(tmp_path):
        check_runtime_config_paths(errors)
    assert errors == []


@pytest.mark.unit
def test_check_runtime_config_paths_additional_specs_missing(tmp_path: Path) -> None:
    _make_runtime_config(tmp_path)
    edu_dir = tmp_path / "domain-packs" / "education"
    runtime_cfg_path = edu_dir / "runtime-config.yaml"
    content = runtime_cfg_path.read_text(encoding="utf-8")
    content += "  additional_specs:\n    - specs/nonexistent-spec.md\n"
    runtime_cfg_path.write_text(content, encoding="utf-8")

    errors: list[str] = []
    with _patch_root(tmp_path):
        check_runtime_config_paths(errors)
    assert any("missing file" in e for e in errors)


@pytest.mark.unit
def test_check_runtime_config_paths_additional_specs_plain_string(tmp_path: Path) -> None:
    """Test additional_specs with a plain string path entry."""
    _make_runtime_config(tmp_path)
    edu_dir = tmp_path / "domain-packs" / "education"
    spec_file = tmp_path / "specs" / "extra-spec-2.md"
    spec_file.parent.mkdir(parents=True, exist_ok=True)
    spec_file.write_text("# extra 2", encoding="utf-8")

    runtime_cfg_path = edu_dir / "runtime-config.yaml"
    content = runtime_cfg_path.read_text(encoding="utf-8")
    content += "  additional_specs:\n    - specs/extra-spec-2.md\n"
    runtime_cfg_path.write_text(content, encoding="utf-8")

    errors: list[str] = []
    with _patch_root(tmp_path):
        check_runtime_config_paths(errors)
    assert errors == []


# ── check_algebra_version_alignment ──────────────────────────────────────────


def _make_algebra_module(
    tmp_path: Path,
    version: str = "3.1.0",
    examples_mention: bool = True,
    domain_packs_row: bool = True,
) -> None:
    """Create all files required by check_algebra_version_alignment."""
    alg_dir = tmp_path / "domain-packs" / "education" / "modules" / "algebra-level-1"
    alg_dir.mkdir(parents=True, exist_ok=True)

    # domain-physics.json is the sole source of truth
    (alg_dir / "domain-physics.json").write_text(
        json.dumps({"id": "algebra-level-1", "version": version}), encoding="utf-8"
    )

    # CHANGELOG.md
    (alg_dir / "CHANGELOG.md").write_text(
        f"# Changelog\n\n## v{version}\n\n- Changes...\n", encoding="utf-8"
    )

    # examples/README.md
    examples_dir = tmp_path / "examples"
    examples_dir.mkdir(parents=True, exist_ok=True)
    if examples_mention:
        (examples_dir / "README.md").write_text(
            f"# Examples\n\nAlgebra Level 1 v{version}\n", encoding="utf-8"
        )
    else:
        (examples_dir / "README.md").write_text("# Examples\n\nNo mentions.\n", encoding="utf-8")

    # domain-packs/README.md
    dp_dir = tmp_path / "domain-packs"
    dp_dir.mkdir(parents=True, exist_ok=True)
    if domain_packs_row:
        row = f"| Education — Algebra Level 1 | `education/modules/algebra-level-1` | {version} |"
        (dp_dir / "README.md").write_text(f"# Domain Packs\n\n{row}\n", encoding="utf-8")
    else:
        (dp_dir / "README.md").write_text("# Domain Packs\n\n| Old row |\n", encoding="utf-8")


@pytest.mark.unit
def test_check_algebra_version_alignment_all_ok(tmp_path: Path) -> None:
    _make_algebra_module(tmp_path, version="3.1.0")
    errors: list[str] = []
    with _patch_root(tmp_path):
        check_algebra_version_alignment(errors)
    assert errors == [], f"Unexpected errors: {errors}"


@pytest.mark.unit
def test_check_algebra_version_alignment_json_mismatch(tmp_path: Path) -> None:
    _make_algebra_module(tmp_path, version="3.1.0")
    # Override domain-physics.json with wrong version
    alg_dir = tmp_path / "domain-packs" / "education" / "modules" / "algebra-level-1"
    (alg_dir / "domain-physics.json").write_text(
        json.dumps({"id": "algebra-level-1", "version": "2.0.0"}), encoding="utf-8"
    )
    errors: list[str] = []
    with _patch_root(tmp_path):
        check_algebra_version_alignment(errors)
    assert any("mismatch" in e.lower() and "json" in e.lower() for e in errors)


@pytest.mark.unit
def test_check_algebra_version_alignment_examples_missing_reference(tmp_path: Path) -> None:
    _make_algebra_module(tmp_path, version="3.1.0", examples_mention=False)
    errors: list[str] = []
    with _patch_root(tmp_path):
        check_algebra_version_alignment(errors)
    assert any("examples" in e.lower() for e in errors)


@pytest.mark.unit
def test_check_algebra_version_alignment_domain_packs_readme_stale(tmp_path: Path) -> None:
    _make_algebra_module(tmp_path, version="3.1.0", domain_packs_row=False)
    errors: list[str] = []
    with _patch_root(tmp_path):
        check_algebra_version_alignment(errors)
    assert any("domain-packs" in e.lower() or "readme" in e.lower() for e in errors)


# ── check_markdown_relative_links with absolute-from-repo link ───────────────


@pytest.mark.unit
def test_check_markdown_relative_links_absolute_from_repo(tmp_path: Path) -> None:
    from lumina.systools.verify_repo import check_markdown_relative_links
    # Create a file referenced with absolute-from-repo path /docs/file.md
    target = tmp_path / "docs" / "file.md"
    target.parent.mkdir(parents=True)
    target.write_text("# File", encoding="utf-8")

    md = tmp_path / "README.md"
    md.write_text("[Link](/docs/file.md)", encoding="utf-8")

    errors: list[str] = []
    with _patch_root(tmp_path):
        check_markdown_relative_links(errors)
    assert errors == []


@pytest.mark.unit
def test_check_markdown_relative_links_absolute_missing(tmp_path: Path) -> None:
    from lumina.systools.verify_repo import check_markdown_relative_links
    md = tmp_path / "README.md"
    md.write_text("[Link](/docs/missing.md)", encoding="utf-8")

    errors: list[str] = []
    with _patch_root(tmp_path):
        check_markdown_relative_links(errors)
    assert any("missing.md" in e for e in errors)


@pytest.mark.unit
def test_check_markdown_relative_links_anchor_only_ignored(tmp_path: Path) -> None:
    from lumina.systools.verify_repo import check_markdown_relative_links
    md = tmp_path / "README.md"
    md.write_text("[anchor](#section)\n", encoding="utf-8")

    errors: list[str] = []
    with _patch_root(tmp_path):
        check_markdown_relative_links(errors)
    assert errors == []


@pytest.mark.unit
def test_check_markdown_relative_links_with_anchor_suffix(tmp_path: Path) -> None:
    """File with anchor suffix should resolve correctly to the base file."""
    from lumina.systools.verify_repo import check_markdown_relative_links
    target = tmp_path / "doc.md"
    target.write_text("# doc", encoding="utf-8")
    md = tmp_path / "README.md"
    md.write_text("[Link](doc.md#section-1)", encoding="utf-8")

    errors: list[str] = []
    with _patch_root(tmp_path):
        check_markdown_relative_links(errors)
    assert errors == []
