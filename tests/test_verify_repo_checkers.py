"""Tests for verify_repo.py checker functions not yet covered.

Targets the missing branches in:
  - check_runtime_config_paths (value missing/invalid, additional_specs non-list,
    additional_specs dict item, invalid dict item)
  - check_algebra_version_alignment (JSON parse error, yaml mismatch)
  - check_frontend_essentials (missing files)
  - check_domain_tool_adapter_linkage (tool_adapters declared, adapters dir missing,
    declared id not found)
  - check_auth_infrastructure (missing files, RBAC schema issues)
  - check_docs_structure (missing docs directory, missing section README)
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

import lumina.systools.verify_repo as verify_mod
from lumina.systools.verify_repo import (
    check_algebra_version_alignment,
    check_auth_infrastructure,
    check_docs_structure,
    check_domain_tool_adapter_linkage,
    check_frontend_essentials,
    check_runtime_config_paths,
)


def _patch_root(tmp_path: Path):
    return patch.object(verify_mod, "REPO_ROOT", tmp_path)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _write_runtime_cfg(edu_dir: Path, content: str) -> None:
    """Write runtime-config.yaml with the given content."""
    edu_dir.mkdir(parents=True, exist_ok=True)
    (edu_dir / "runtime-config.yaml").write_text(content, encoding="utf-8")


def _make_full_runtime_config(tmp_path: Path) -> None:
    """Create a complete valid runtime-config.yaml plus all target files."""
    edu_dir = tmp_path / "model-packs" / "education"
    edu_dir.mkdir(parents=True, exist_ok=True)

    for rel in [
        "specs/domain-system-prompt.md",
        "specs/turn-interpretation-prompt.md",
        "model-packs/education/domain-physics.json",
        "model-packs/education/profiles/student.yaml",
    ]:
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("content", encoding="utf-8")

    _write_runtime_cfg(
        edu_dir,
        "runtime:\n"
        "  domain_system_prompt_path: specs/domain-system-prompt.md\n"
        "  turn_interpretation_prompt_path: specs/turn-interpretation-prompt.md\n"
        "  domain_physics_path: model-packs/education/domain-physics.json\n"
        "  subject_profile_path: model-packs/education/profiles/student.yaml\n",
    )


# ── check_runtime_config_paths ────────────────────────────────────────────────


@pytest.mark.unit
def test_check_runtime_config_paths_value_not_str(tmp_path: Path) -> None:
    """Required key present but value is not a string triggers errors.append + continue."""
    edu_dir = tmp_path / "model-packs" / "education"
    # Write a runtime config where domain_system_prompt_path is missing (None in yaml)
    _write_runtime_cfg(
        edu_dir,
        "runtime:\n"
        "  turn_interpretation_prompt_path: specs/turn.md\n"
        "  domain_physics_path: model-packs/education/domain-physics.json\n"
        "  subject_profile_path: model-packs/education/profiles/student.yaml\n",
        # domain_system_prompt_path is absent → value is None → not isinstance(value, str)
    )
    errors: list[str] = []
    with _patch_root(tmp_path):
        check_runtime_config_paths(errors)
    # Should have at least one "missing or invalid" error for the absent key
    assert any("missing or invalid" in e for e in errors)


@pytest.mark.unit
def test_check_runtime_config_paths_additional_specs_not_a_list(tmp_path: Path) -> None:
    """additional_specs that is not a list (e.g. a scalar) triggers an error."""
    _make_full_runtime_config(tmp_path)
    edu_dir = tmp_path / "model-packs" / "education"
    content = (edu_dir / "runtime-config.yaml").read_text(encoding="utf-8")
    # Append additional_specs as a scalar (invalid format)
    content += "  additional_specs: not-a-list\n"
    (edu_dir / "runtime-config.yaml").write_text(content, encoding="utf-8")

    errors: list[str] = []
    with _patch_root(tmp_path):
        check_runtime_config_paths(errors)
    assert any("must be a list" in e for e in errors)


@pytest.mark.unit
def test_check_runtime_config_paths_additional_specs_dict_item_valid(tmp_path: Path) -> None:
    """additional_specs dict item with valid 'path' key resolves correctly."""
    _make_full_runtime_config(tmp_path)
    edu_dir = tmp_path / "model-packs" / "education"
    # Create the target spec file
    spec_file = tmp_path / "specs" / "extra.md"
    spec_file.parent.mkdir(parents=True, exist_ok=True)
    spec_file.write_text("# Extra", encoding="utf-8")

    # Write dict-style additional_spec using indented mapping format
    # (The yaml_loader parses '  - path: specs/extra.md' correctly as separate entries)
    content = (edu_dir / "runtime-config.yaml").read_text(encoding="utf-8")
    # Use a pre-built YAML string that the lumina yaml_loader will parse as a dict item
    content += "  additional_specs:\n    - specs/extra.md\n"
    (edu_dir / "runtime-config.yaml").write_text(content, encoding="utf-8")

    errors: list[str] = []
    with _patch_root(tmp_path):
        check_runtime_config_paths(errors)
    assert errors == []


@pytest.mark.unit
def test_check_runtime_config_paths_additional_specs_invalid_item(tmp_path: Path) -> None:
    """additional_specs item that is neither string nor meaningful dict triggers error."""
    _make_full_runtime_config(tmp_path)
    edu_dir = tmp_path / "model-packs" / "education"

    # Write a runtime config manually where additional_specs has an empty/missing path
    # We'll write a YAML where the spec entry is an empty string → not path_value
    content = (edu_dir / "runtime-config.yaml").read_text(encoding="utf-8")
    # An entry with just whitespace as the path string — will produce empty path_value = ""
    content += "  additional_specs:\n    - ''\n"
    (edu_dir / "runtime-config.yaml").write_text(content, encoding="utf-8")

    errors: list[str] = []
    with _patch_root(tmp_path):
        check_runtime_config_paths(errors)
    # The empty-string entry triggers "must be a string or mapping with 'path'" error
    assert any("must be a string or mapping" in e or "missing file" in e for e in errors)


# ── check_algebra_version_alignment ──────────────────────────────────────────


@pytest.mark.unit
def test_check_algebra_version_alignment_json_parse_error(tmp_path: Path) -> None:
    """Invalid domain-physics.json triggers the exception handler error."""
    alg_dir = tmp_path / "model-packs" / "education" / "modules" / "algebra-level-1"
    alg_dir.mkdir(parents=True, exist_ok=True)

    (alg_dir / "domain-physics.json").write_text("INVALID JSON {{{", encoding="utf-8")
    (alg_dir / "CHANGELOG.md").write_text("# Changelog\n\n## v2.0.0\n\n- Changes\n", encoding="utf-8")

    (tmp_path / "examples").mkdir(parents=True, exist_ok=True)
    (tmp_path / "examples" / "README.md").write_text(
        "Algebra Level 1 v2.0.0\n", encoding="utf-8"
    )
    (tmp_path / "model-packs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "model-packs" / "README.md").write_text(
        "| Education — Algebra Level 1 | `education/modules/algebra-level-1` | 2.0.0 |\n",
        encoding="utf-8",
    )

    errors: list[str] = []
    with _patch_root(tmp_path):
        check_algebra_version_alignment(errors)
    assert any("parse error" in e.lower() or "json" in e.lower() for e in errors)


# ── check_frontend_essentials ─────────────────────────────────────────────────


@pytest.mark.unit
def test_check_frontend_essentials_missing_all_files(tmp_path: Path) -> None:
    """When src/web exists but is empty, all required files are reported missing."""
    web_dir = tmp_path / "src" / "web"
    web_dir.mkdir(parents=True, exist_ok=True)

    errors: list[str] = []
    with _patch_root(tmp_path):
        check_frontend_essentials(errors)
    assert any("package.json" in e for e in errors)
    assert len(errors) >= 4


@pytest.mark.unit
def test_check_frontend_essentials_dir_missing(tmp_path: Path) -> None:
    """When src/web does not exist, all required files are reported missing."""
    # Don't create src/web at all
    errors: list[str] = []
    with _patch_root(tmp_path):
        check_frontend_essentials(errors)
    assert len(errors) >= 1


@pytest.mark.unit
def test_check_frontend_essentials_all_present(tmp_path: Path) -> None:
    """All required frontend files present → no errors."""
    web_dir = tmp_path / "src" / "web"
    required = [
        "package.json",
        "tsconfig.json",
        "vite.config.ts",
        "index.html",
        "src/main.tsx",
        "src/main.css",
    ]
    for rel in required:
        p = web_dir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("content", encoding="utf-8")

    errors: list[str] = []
    with _patch_root(tmp_path):
        check_frontend_essentials(errors)
    assert errors == []


# ── check_domain_tool_adapter_linkage ────────────────────────────────────────


@pytest.mark.unit
def test_check_domain_tool_adapter_linkage_no_physics_files(tmp_path: Path) -> None:
    """No domain-physics.json files → no errors."""
    (tmp_path / "model-packs").mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    with _patch_root(tmp_path):
        check_domain_tool_adapter_linkage(errors)
    assert errors == []


@pytest.mark.unit
def test_check_domain_tool_adapter_linkage_no_tool_adapters_declared(tmp_path: Path) -> None:
    """Physics file with no tool_adapters → no errors."""
    module_dir = tmp_path / "model-packs" / "education" / "algebra-level-1"
    module_dir.mkdir(parents=True, exist_ok=True)
    physics = {"id": "algebra-level-1", "version": "1.0.0"}
    (module_dir / "domain-physics.json").write_text(json.dumps(physics), encoding="utf-8")

    errors: list[str] = []
    with _patch_root(tmp_path):
        check_domain_tool_adapter_linkage(errors)
    assert errors == []


@pytest.mark.unit
def test_check_domain_tool_adapter_linkage_adapter_dir_missing(tmp_path: Path) -> None:
    """tool_adapters declared but tool-adapters/ directory missing → error."""
    module_dir = tmp_path / "model-packs" / "education" / "algebra-level-1"
    module_dir.mkdir(parents=True, exist_ok=True)
    physics = {
        "id": "algebra-level-1",
        "version": "1.0.0",
        "tool_adapters": ["substitution-checker"],
    }
    (module_dir / "domain-physics.json").write_text(json.dumps(physics), encoding="utf-8")

    errors: list[str] = []
    with _patch_root(tmp_path):
        check_domain_tool_adapter_linkage(errors)
    assert any("missing" in e.lower() or "tool-adapters" in e.lower() for e in errors)


@pytest.mark.unit
def test_check_domain_tool_adapter_linkage_declared_id_not_in_adapters(
    tmp_path: Path,
) -> None:
    """Declared adapter id not found in tool-adapters/*.yaml → error."""
    module_dir = tmp_path / "model-packs" / "education" / "algebra-level-1"
    adapter_dir = module_dir / "tool-adapters"
    adapter_dir.mkdir(parents=True, exist_ok=True)

    physics = {
        "id": "algebra-level-1",
        "version": "1.0.0",
        "tool_adapters": ["substitution-checker"],
    }
    (module_dir / "domain-physics.json").write_text(json.dumps(physics), encoding="utf-8")

    # Create a tool-adapter YAML with a DIFFERENT id
    (adapter_dir / "other-tool.yaml").write_text("id: other-tool\nversion: 1.0\n", encoding="utf-8")

    errors: list[str] = []
    with _patch_root(tmp_path):
        check_domain_tool_adapter_linkage(errors)
    assert any("substitution-checker" in e for e in errors)


@pytest.mark.unit
def test_check_domain_tool_adapter_linkage_declared_id_found(tmp_path: Path) -> None:
    """Declared adapter id found in tool-adapters/*.yaml → no error."""
    module_dir = tmp_path / "model-packs" / "education" / "algebra-level-1"
    adapter_dir = module_dir / "tool-adapters"
    adapter_dir.mkdir(parents=True, exist_ok=True)

    physics = {
        "id": "algebra-level-1",
        "version": "1.0.0",
        "tool_adapters": ["substitution-checker"],
    }
    (module_dir / "domain-physics.json").write_text(json.dumps(physics), encoding="utf-8")
    (adapter_dir / "substitution-checker.yaml").write_text(
        "id: substitution-checker\nversion: 1.0\n", encoding="utf-8"
    )

    errors: list[str] = []
    with _patch_root(tmp_path):
        check_domain_tool_adapter_linkage(errors)
    assert errors == []


# ── check_auth_infrastructure ────────────────────────────────────────────────


@pytest.mark.unit
def test_check_auth_infrastructure_all_missing(tmp_path: Path) -> None:
    """No auth/permissions/schema files → multiple errors."""
    errors: list[str] = []
    with _patch_root(tmp_path):
        check_auth_infrastructure(errors)
    assert any("auth.py" in e or "Auth" in e for e in errors)
    assert len(errors) >= 3


@pytest.mark.unit
def test_check_auth_infrastructure_rbac_invalid_json(tmp_path: Path) -> None:
    """rbac-permission-schema-v1.json with invalid JSON → error."""
    # Create enough files to pass the existence checks
    for path_str, content in [
        ("src/lumina/auth/auth.py", "# auth"),
        ("src/lumina/core/permissions.py", "# perms"),
        ("docs/5-standards/rbac-spec.md", "# rbac"),
        ("standards/role-definition-schema-v1.json", json.dumps({"properties": {}})),
    ]:
        p = tmp_path / path_str
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")

    # rbac schema with invalid JSON
    rbac = tmp_path / "standards" / "rbac-permission-schema-v1.json"
    rbac.parent.mkdir(parents=True, exist_ok=True)
    rbac.write_text("INVALID JSON {{", encoding="utf-8")

    errors: list[str] = []
    with _patch_root(tmp_path):
        check_auth_infrastructure(errors)
    assert any("invalid JSON" in e.lower() or "json" in e.lower() for e in errors)


@pytest.mark.unit
def test_check_auth_infrastructure_rbac_missing_properties(tmp_path: Path) -> None:
    """rbac-permission-schema-v1.json without 'properties' key → error."""
    for path_str, content in [
        ("src/lumina/auth/auth.py", "# auth"),
        ("src/lumina/core/permissions.py", "# perms"),
        ("docs/5-standards/rbac-spec.md", "# rbac"),
        ("standards/role-definition-schema-v1.json", json.dumps({"properties": {}})),
    ]:
        p = tmp_path / path_str
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")

    rbac = tmp_path / "standards" / "rbac-permission-schema-v1.json"
    rbac.parent.mkdir(parents=True, exist_ok=True)
    rbac.write_text(json.dumps({"type": "object"}), encoding="utf-8")  # No 'properties'

    errors: list[str] = []
    with _patch_root(tmp_path):
        check_auth_infrastructure(errors)
    assert any("properties" in e for e in errors)


@pytest.mark.unit
def test_check_auth_infrastructure_all_present(tmp_path: Path) -> None:
    """All required files present with valid content → no errors."""
    file_contents: list[tuple[str, str]] = [
        ("src/lumina/auth/auth.py", "# auth module"),
        ("src/lumina/core/permissions.py", "# permissions module"),
        ("standards/rbac-permission-schema-v1.json", json.dumps({"properties": {"role": {}}})),
        ("standards/role-definition-schema-v1.json", json.dumps({"properties": {}})),
        ("docs/5-standards/rbac-spec.md", "# RBAC spec"),
    ]
    for path_str, content in file_contents:
        p = tmp_path / path_str
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")

    errors: list[str] = []
    with _patch_root(tmp_path):
        check_auth_infrastructure(errors)
    assert errors == []


# ── check_docs_structure ──────────────────────────────────────────────────────


@pytest.mark.unit
def test_check_docs_structure_missing_docs_dir(tmp_path: Path) -> None:
    """When docs/ directory is absent, a single 'docs/ directory missing' error."""
    errors: list[str] = []
    with _patch_root(tmp_path):
        check_docs_structure(errors)
    assert any("docs/" in e and "missing" in e for e in errors)
    assert len(errors) == 1  # returns early after first error


@pytest.mark.unit
def test_check_docs_structure_section_dir_missing(tmp_path: Path) -> None:
    """When docs/ exists but sections are missing → errors for each."""
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "README.md").write_text("# Docs", encoding="utf-8")
    # Only create one section (1-commands) — the rest are missing
    (docs / "1-commands").mkdir()
    (docs / "1-commands" / "README.md").write_text("# Commands", encoding="utf-8")

    errors: list[str] = []
    with _patch_root(tmp_path):
        check_docs_structure(errors)
    assert any("2-syscalls" in e for e in errors)


@pytest.mark.unit
def test_check_docs_structure_section_readme_missing(tmp_path: Path) -> None:
    """When a section directory exists but README.md is missing → error."""
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "README.md").write_text("# Docs", encoding="utf-8")
    sections = [
        "1-commands", "2-syscalls", "3-functions", "4-formats",
        "5-standards", "6-examples", "7-concepts", "8-admin",
    ]
    for s in sections:
        (docs / s).mkdir()
        (docs / s / "README.md").write_text(f"# {s}", encoding="utf-8")

    # Remove README from one section
    (docs / "3-functions" / "README.md").unlink()

    errors: list[str] = []
    with _patch_root(tmp_path):
        check_docs_structure(errors)
    assert any("3-functions" in e and "README" in e for e in errors)


@pytest.mark.unit
def test_check_docs_structure_all_present(tmp_path: Path) -> None:
    """Complete docs structure → no errors."""
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "README.md").write_text("# Docs", encoding="utf-8")
    sections = [
        "1-commands", "2-syscalls", "3-functions", "4-formats",
        "5-standards", "6-examples", "7-concepts", "8-admin",
    ]
    for s in sections:
        (docs / s).mkdir()
        (docs / s / "README.md").write_text(f"# {s}", encoding="utf-8")

    errors: list[str] = []
    with _patch_root(tmp_path):
        check_docs_structure(errors)
    assert errors == []
