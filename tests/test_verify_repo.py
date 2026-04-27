"""Tests for lumina.systools.verify_repo — repo integrity checker functions."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import lumina.systools.verify_repo as verify_mod
from lumina.systools.verify_repo import (
    _extract_md_links,
    _is_external_link,
    check_auth_infrastructure,
    check_docs_structure,
    check_domain_tool_adapter_linkage,
    check_frontend_essentials,
    check_markdown_relative_links,
    check_provenance_contract_consistency,
    main,
    parse_latest_changelog_version,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


# ── parse_latest_changelog_version ────────────────────────────────────────────


@pytest.mark.unit
def test_parse_latest_changelog_version_success(tmp_path: Path) -> None:
    cl = tmp_path / "CHANGELOG.md"
    cl.write_text("# Changelog\n\n## v2.3.1\n\n- Some change\n", encoding="utf-8")
    assert parse_latest_changelog_version(cl) == "2.3.1"


@pytest.mark.unit
def test_parse_latest_changelog_version_returns_first_match(tmp_path: Path) -> None:
    cl = tmp_path / "CHANGELOG.md"
    cl.write_text("## v3.0.0\n\n## v2.0.0\n", encoding="utf-8")
    assert parse_latest_changelog_version(cl) == "3.0.0"


@pytest.mark.unit
def test_parse_latest_changelog_version_no_match_raises(tmp_path: Path) -> None:
    cl = tmp_path / "CHANGELOG.md"
    cl.write_text("# No versions here\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="No version heading"):
        parse_latest_changelog_version(cl)


# ── _extract_md_links ─────────────────────────────────────────────────────────


@pytest.mark.unit
def test_extract_md_links_basic() -> None:
    text = "See [docs](README.md) and [schema](standards/schema.json)."
    links = _extract_md_links(text)
    assert "README.md" in links
    assert "standards/schema.json" in links


@pytest.mark.unit
def test_extract_md_links_empty() -> None:
    assert _extract_md_links("no links here") == []


@pytest.mark.unit
def test_extract_md_links_mixed() -> None:
    text = "[anchor](#section) [external](https://example.com) [local](file.md)"
    links = _extract_md_links(text)
    assert "#section" in links
    assert "https://example.com" in links
    assert "file.md" in links


# ── _is_external_link ─────────────────────────────────────────────────────────


@pytest.mark.unit
def test_is_external_link_http() -> None:
    assert _is_external_link("http://example.com") is True


@pytest.mark.unit
def test_is_external_link_https() -> None:
    assert _is_external_link("https://example.com") is True


@pytest.mark.unit
def test_is_external_link_mailto() -> None:
    assert _is_external_link("mailto:user@example.com") is True


@pytest.mark.unit
def test_is_external_link_tel() -> None:
    assert _is_external_link("tel:+1234567890") is True


@pytest.mark.unit
def test_is_external_link_relative() -> None:
    assert _is_external_link("docs/README.md") is False


@pytest.mark.unit
def test_is_external_link_anchor() -> None:
    assert _is_external_link("#section") is False


# ── check_docs_structure ──────────────────────────────────────────────────────


@pytest.mark.unit
def test_check_docs_structure_pass(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "README.md").write_text("", encoding="utf-8")
    sections = ["1-commands", "2-syscalls", "3-functions", "4-formats", "5-standards", "6-examples", "7-concepts", "8-admin"]
    for s in sections:
        section_dir = docs / s
        section_dir.mkdir()
        (section_dir / "README.md").write_text("", encoding="utf-8")

    errors: list[str] = []
    with __import__("unittest.mock", fromlist=["patch"]).patch.object(verify_mod, "REPO_ROOT", tmp_path):
        check_docs_structure(errors)
    assert errors == []


@pytest.mark.unit
def test_check_docs_structure_missing_docs_dir(tmp_path: Path) -> None:
    errors: list[str] = []
    with __import__("unittest.mock", fromlist=["patch"]).patch.object(verify_mod, "REPO_ROOT", tmp_path):
        check_docs_structure(errors)
    assert any("missing" in e.lower() for e in errors)


@pytest.mark.unit
def test_check_docs_structure_missing_section(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "README.md").write_text("", encoding="utf-8")
    # Only create some sections
    (docs / "1-commands").mkdir()
    (docs / "1-commands" / "README.md").write_text("", encoding="utf-8")

    errors: list[str] = []
    with __import__("unittest.mock", fromlist=["patch"]).patch.object(verify_mod, "REPO_ROOT", tmp_path):
        check_docs_structure(errors)
    assert any("2-syscalls" in e for e in errors)


@pytest.mark.unit
def test_check_docs_structure_section_missing_readme(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "README.md").write_text("", encoding="utf-8")
    sections = ["1-commands", "2-syscalls", "3-functions", "4-formats", "5-standards", "6-examples", "7-concepts", "8-admin"]
    for s in sections:
        section_dir = docs / s
        section_dir.mkdir()
        if s != "3-functions":
            (section_dir / "README.md").write_text("", encoding="utf-8")

    errors: list[str] = []
    with __import__("unittest.mock", fromlist=["patch"]).patch.object(verify_mod, "REPO_ROOT", tmp_path):
        check_docs_structure(errors)
    assert any("3-functions" in e for e in errors)


# ── check_frontend_essentials ─────────────────────────────────────────────────


@pytest.mark.unit
def test_check_frontend_essentials_pass(tmp_path: Path) -> None:
    web = tmp_path / "src" / "web"
    web.mkdir(parents=True)
    (web / "package.json").write_text("{}", encoding="utf-8")
    (web / "tsconfig.json").write_text("{}", encoding="utf-8")
    (web / "vite.config.ts").write_text("", encoding="utf-8")
    (web / "index.html").write_text("", encoding="utf-8")
    src = web / "src"
    src.mkdir()
    (src / "main.tsx").write_text("", encoding="utf-8")
    (src / "main.css").write_text("", encoding="utf-8")

    errors: list[str] = []
    with __import__("unittest.mock", fromlist=["patch"]).patch.object(verify_mod, "REPO_ROOT", tmp_path):
        check_frontend_essentials(errors)
    assert errors == []


@pytest.mark.unit
def test_check_frontend_essentials_missing_file(tmp_path: Path) -> None:
    web = tmp_path / "src" / "web"
    web.mkdir(parents=True)
    (web / "package.json").write_text("{}", encoding="utf-8")
    # Missing other files

    errors: list[str] = []
    with __import__("unittest.mock", fromlist=["patch"]).patch.object(verify_mod, "REPO_ROOT", tmp_path):
        check_frontend_essentials(errors)
    assert len(errors) > 0


# ── check_provenance_contract_consistency ─────────────────────────────────────


@pytest.mark.unit
def test_check_provenance_contract_consistency_missing_files(tmp_path: Path) -> None:
    errors: list[str] = []
    with __import__("unittest.mock", fromlist=["patch"]).patch.object(verify_mod, "REPO_ROOT", tmp_path):
        check_provenance_contract_consistency(errors)
    assert len(errors) > 0  # All required files will be missing


@pytest.mark.unit
def test_check_provenance_contract_consistency_passes_with_all_keys(tmp_path: Path) -> None:
    from lumina.systools.verify_repo import (
        PROVENANCE_POST_PAYLOAD_KEYS,
        PROVENANCE_RUNTIME_KEYS,
        PROVENANCE_STRICT_FILES,
        PROVENANCE_ESCALATION_ADVISORY_FILE,
    )

    all_keys = PROVENANCE_RUNTIME_KEYS + PROVENANCE_POST_PAYLOAD_KEYS
    full_content = " ".join(all_keys) + " provenance hash"

    for rel_path in PROVENANCE_STRICT_FILES:
        abs_path = tmp_path / rel_path
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_text(full_content, encoding="utf-8")

    advisory_path = tmp_path / PROVENANCE_ESCALATION_ADVISORY_FILE
    advisory_path.parent.mkdir(parents=True, exist_ok=True)
    advisory_path.write_text("provenance hash lineage", encoding="utf-8")

    errors: list[str] = []
    with __import__("unittest.mock", fromlist=["patch"]).patch.object(verify_mod, "REPO_ROOT", tmp_path):
        check_provenance_contract_consistency(errors)
    assert errors == []


# ── check_auth_infrastructure ─────────────────────────────────────────────────


@pytest.mark.unit
def test_check_auth_infrastructure_with_real_repo() -> None:
    errors: list[str] = []
    check_auth_infrastructure(errors)
    # The real repo should have all auth files.
    assert errors == [], f"Unexpected auth errors: {errors}"


@pytest.mark.unit
def test_check_auth_infrastructure_missing_all(tmp_path: Path) -> None:
    errors: list[str] = []
    with __import__("unittest.mock", fromlist=["patch"]).patch.object(verify_mod, "REPO_ROOT", tmp_path):
        check_auth_infrastructure(errors)
    # All required files are missing
    assert len(errors) > 0


# ── check_domain_tool_adapter_linkage ─────────────────────────────────────────


@pytest.mark.unit
def test_check_domain_tool_adapter_linkage_no_domain_packs(tmp_path: Path) -> None:
    domain_packs = tmp_path / "model-packs"
    domain_packs.mkdir()
    errors: list[str] = []
    with __import__("unittest.mock", fromlist=["patch"]).patch.object(verify_mod, "REPO_ROOT", tmp_path):
        check_domain_tool_adapter_linkage(errors)
    assert errors == []


@pytest.mark.unit
def test_check_domain_tool_adapter_linkage_no_declared_adapters(tmp_path: Path) -> None:
    mod_dir = tmp_path / "model-packs" / "edu" / "module-1"
    mod_dir.mkdir(parents=True)
    physics = mod_dir / "domain-physics.json"
    physics.write_text(json.dumps({"id": "edu-1", "version": "1.0.0", "tool_adapters": []}), encoding="utf-8")

    errors: list[str] = []
    with __import__("unittest.mock", fromlist=["patch"]).patch.object(verify_mod, "REPO_ROOT", tmp_path):
        check_domain_tool_adapter_linkage(errors)
    assert errors == []


@pytest.mark.unit
def test_check_domain_tool_adapter_linkage_missing_adapter(tmp_path: Path) -> None:
    mod_dir = tmp_path / "model-packs" / "edu" / "module-1"
    mod_dir.mkdir(parents=True)
    physics = mod_dir / "domain-physics.json"
    physics.write_text(
        json.dumps({"id": "edu-1", "version": "1.0.0", "tool_adapters": ["my-tool"]}),
        encoding="utf-8",
    )

    errors: list[str] = []
    with __import__("unittest.mock", fromlist=["patch"]).patch.object(verify_mod, "REPO_ROOT", tmp_path):
        check_domain_tool_adapter_linkage(errors)
    assert any("my-tool" in e or "tool-adapters" in e for e in errors)


# ── check_markdown_relative_links ─────────────────────────────────────────────


@pytest.mark.unit
def test_check_markdown_relative_links_valid_link(tmp_path: Path) -> None:
    md = tmp_path / "README.md"
    target = tmp_path / "doc.md"
    target.write_text("# doc", encoding="utf-8")
    md.write_text("[See doc](doc.md)", encoding="utf-8")

    errors: list[str] = []
    with __import__("unittest.mock", fromlist=["patch"]).patch.object(verify_mod, "REPO_ROOT", tmp_path):
        check_markdown_relative_links(errors)
    assert errors == []


@pytest.mark.unit
def test_check_markdown_relative_links_broken_link(tmp_path: Path) -> None:
    md = tmp_path / "README.md"
    md.write_text("[missing](nonexistent-file.md)", encoding="utf-8")

    errors: list[str] = []
    with __import__("unittest.mock", fromlist=["patch"]).patch.object(verify_mod, "REPO_ROOT", tmp_path):
        check_markdown_relative_links(errors)
    assert any("nonexistent-file.md" in e for e in errors)


@pytest.mark.unit
def test_check_markdown_relative_links_external_ignored(tmp_path: Path) -> None:
    md = tmp_path / "README.md"
    md.write_text("[External](https://example.com)", encoding="utf-8")

    errors: list[str] = []
    with __import__("unittest.mock", fromlist=["patch"]).patch.object(verify_mod, "REPO_ROOT", tmp_path):
        check_markdown_relative_links(errors)
    assert errors == []


# ── main ───────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_main_returns_0_when_no_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """main() should return 0 when all checkers produce no errors."""
    from unittest.mock import patch
    noop = lambda errors: None
    with (
        patch.object(verify_mod, "check_runtime_config_paths", noop),
        patch.object(verify_mod, "check_algebra_version_alignment", noop),
        patch.object(verify_mod, "check_markdown_relative_links", noop),
        patch.object(verify_mod, "check_frontend_essentials", noop),
        patch.object(verify_mod, "check_domain_tool_adapter_linkage", noop),
        patch.object(verify_mod, "check_provenance_contract_consistency", noop),
        patch.object(verify_mod, "check_auth_infrastructure", noop),
        patch.object(verify_mod, "check_docs_structure", noop),
    ):
        result = main()
    assert result == 0


@pytest.mark.unit
def test_main_returns_1_when_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """main() should return 1 when any checker appends an error."""
    from unittest.mock import patch
    def add_error(errors: list) -> None:
        errors.append("Test failure message")
    noop = lambda errors: None
    with (
        patch.object(verify_mod, "check_runtime_config_paths", add_error),
        patch.object(verify_mod, "check_algebra_version_alignment", noop),
        patch.object(verify_mod, "check_markdown_relative_links", noop),
        patch.object(verify_mod, "check_frontend_essentials", noop),
        patch.object(verify_mod, "check_domain_tool_adapter_linkage", noop),
        patch.object(verify_mod, "check_provenance_contract_consistency", noop),
        patch.object(verify_mod, "check_auth_infrastructure", noop),
        patch.object(verify_mod, "check_docs_structure", noop),
    ):
        result = main()
    assert result == 1
