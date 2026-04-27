"""Tests verifying schema_version + last_updated metadata on all versioned artifacts.

See also:
    docs/7-concepts/state-change-commit-policy.md — audit requirement for state mutations
    docs/7-concepts/domain-pack-anatomy.md        — domain pack structure & runtime state
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]


# ── Helpers ──────────────────────────────────────────────────────────────────

def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _collect_json_schemas(*dirs: str) -> list[Path]:
    paths: list[Path] = []
    for d in dirs:
        target = REPO_ROOT / d
        if target.is_dir():
            paths.extend(sorted(target.rglob("*.json")))
        elif target.is_file():
            paths.append(target)
    return paths


SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)


# ── JSON schema versioning ──────────────────────────────────────────────────

ALL_SCHEMA_DIRS = ["ledger", "standards", "standards/admin-command-schemas"]


@pytest.mark.unit
class TestJsonSchemaVersioning:
    """Every JSON schema must carry schema_version and last_updated."""

    @pytest.fixture(params=_collect_json_schemas(*ALL_SCHEMA_DIRS),
                    ids=lambda p: str(p.relative_to(REPO_ROOT)))
    def schema(self, request) -> dict:
        return _load_json(request.param)

    def test_has_schema_version(self, schema):
        assert "schema_version" in schema, "Missing schema_version field"

    def test_schema_version_is_semver(self, schema):
        assert SEMVER_RE.match(schema["schema_version"]), \
            f"schema_version '{schema['schema_version']}' is not valid SemVer"

    def test_has_last_updated(self, schema):
        assert "last_updated" in schema, "Missing last_updated field"

    def test_last_updated_is_date(self, schema):
        assert DATE_RE.match(schema["last_updated"]), \
            f"last_updated '{schema['last_updated']}' is not YYYY-MM-DD"


# ── Markdown frontmatter versioning ─────────────────────────────────────────

def _collect_docs_md() -> list[Path]:
    return sorted((REPO_ROOT / "docs").rglob("*.md"))


@pytest.mark.unit
class TestDocsFrontmatter:
    """Every markdown doc must carry YAML frontmatter with version + last_updated."""

    @pytest.fixture(params=_collect_docs_md(),
                    ids=lambda p: str(p.relative_to(REPO_ROOT)))
    def frontmatter(self, request) -> dict:
        text = request.param.read_text(encoding="utf-8")
        m = FRONTMATTER_RE.match(text)
        assert m, f"No YAML frontmatter in {request.param.name}"
        return yaml.safe_load(m.group(1))

    def test_has_version(self, frontmatter):
        assert "version" in frontmatter, "Missing version in frontmatter"

    def test_version_is_semver(self, frontmatter):
        v = str(frontmatter["version"])
        assert SEMVER_RE.match(v), f"version '{v}' is not valid SemVer"

    def test_has_last_updated(self, frontmatter):
        assert "last_updated" in frontmatter, "Missing last_updated in frontmatter"

    def test_last_updated_is_date(self, frontmatter):
        d = str(frontmatter["last_updated"])
        assert DATE_RE.match(d), f"last_updated '{d}' is not YYYY-MM-DD"


# ── MANIFEST coverage ───────────────────────────────────────────────────────

@pytest.mark.unit
class TestManifestCoverage:
    """MANIFEST.yaml must track all core artifacts and have valid metadata."""

    @pytest.fixture(scope="class")
    def manifest(self) -> dict:
        path = REPO_ROOT / "docs" / "MANIFEST.yaml"
        return yaml.safe_load(path.read_text(encoding="utf-8"))

    def test_has_schema_version(self, manifest):
        assert "schema_version" in manifest

    def test_has_last_updated(self, manifest):
        assert "last_updated" in manifest

    def test_all_json_schemas_tracked(self, manifest):
        tracked = {a["path"] for a in manifest["artifacts"]}
        on_disk = set()
        for d in ALL_SCHEMA_DIRS:
            target = REPO_ROOT / d
            if target.is_dir():
                for p in target.rglob("*.json"):
                    on_disk.add(str(p.relative_to(REPO_ROOT)).replace("\\", "/"))
        missing = on_disk - tracked
        assert not missing, f"Schemas not in MANIFEST: {missing}"

    def test_all_docs_tracked(self, manifest):
        tracked = {a["path"] for a in manifest["artifacts"]}
        on_disk = {
            str(p.relative_to(REPO_ROOT)).replace("\\", "/")
            for p in (REPO_ROOT / "docs").rglob("*.md")
            if p.name != "MANIFEST.yaml"
        }
        missing = on_disk - tracked
        assert not missing, f"Docs not in MANIFEST: {missing}"

    def test_all_config_yamls_tracked(self, manifest):
        """All YAML files in model-packs/ that affect system state must be tracked."""
        tracked = {a["path"] for a in manifest["artifacts"]}
        on_disk = set()
        for p in (REPO_ROOT / "model-packs").rglob("*.yaml"):
            rel = str(p.relative_to(REPO_ROOT)).replace("\\", "/")
            # Skip domain-pack doc manifests and directories outside state scope
            if "/docs/" in rel:
                continue
            on_disk.add(rel)
        missing = on_disk - tracked
        # See: docs/7-concepts/state-change-commit-policy.md
        assert not missing, f"Config YAMLs not in MANIFEST: {missing}"

    def test_no_pending_hashes(self, manifest):
        pending = [a["path"] for a in manifest["artifacts"]
                   if a.get("sha256") == "pending"]
        assert not pending, f"Artifacts with pending sha256: {pending}"

    def test_all_tracked_files_exist(self, manifest):
        missing = [a["path"] for a in manifest["artifacts"]
                   if not (REPO_ROOT / a["path"]).exists()]
        assert not missing, f"MANIFEST references missing files: {missing}"


# ── Config file versioning ──────────────────────────────────────────────────

# Auto-discover all YAML files in model-packs/ that affect system state.
# See: docs/7-concepts/domain-pack-anatomy.md
def _collect_config_yamls() -> list[str]:
    paths: list[str] = []
    for p in sorted((REPO_ROOT / "model-packs").rglob("*.yaml")):
        rel = str(p.relative_to(REPO_ROOT)).replace("\\", "/")
        if "/docs/" in rel:
            continue
        paths.append(rel)
    return paths


CONFIG_FILES = _collect_config_yamls()


@pytest.mark.unit
class TestConfigVersioning:
    """Config YAML files must have version comment headers."""

    @pytest.fixture(params=CONFIG_FILES)
    def config_text(self, request) -> str:
        return (REPO_ROOT / request.param).read_text(encoding="utf-8")

    def test_has_version_comment(self, config_text):
        assert re.search(r"#\s*version:\s*\d+\.\d+\.\d+", config_text), \
            "Missing # version: X.Y.Z comment"

    def test_has_last_updated_comment(self, config_text):
        assert re.search(r"#\s*last_updated:\s*\d{4}-\d{2}-\d{2}", config_text), \
            "Missing # last_updated: YYYY-MM-DD comment"
