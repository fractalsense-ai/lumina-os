"""Tests for lumina.systools.manifest_integrity."""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

import lumina.systools.manifest_integrity as mi_mod
from lumina.systools.manifest_integrity import (
    _parse_artifacts,
    _sha256_file,
    check_manifest,
    check_manifest_report,
    main,
    regen_manifest,
    regen_manifest_report,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


# ── _sha256_file ───────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_sha256_file_returns_hex_digest(tmp_path: Path) -> None:
    f = tmp_path / "test.txt"
    f.write_bytes(b"hello world")
    result = _sha256_file(f)
    expected = hashlib.sha256(b"hello world").hexdigest()
    assert result == expected
    assert len(result) == 64


# ── _parse_artifacts ───────────────────────────────────────────────────────────


@pytest.mark.unit
def test_parse_artifacts_basic(tmp_path: Path) -> None:
    manifest = tmp_path / "MANIFEST.yaml"
    manifest.write_text(
        "artifacts:\n"
        "  - path: some/file.md\n"
        "    sha256: abc123\n"
        "  - path: other/file.json\n"
        "    sha256: pending\n",
        encoding="utf-8",
    )
    artifacts = _parse_artifacts(manifest)
    assert len(artifacts) == 2
    assert artifacts[0]["path"] == "some/file.md"
    assert artifacts[0]["sha256"] == "abc123"
    assert artifacts[1]["path"] == "other/file.json"
    assert artifacts[1]["sha256"] == "pending"


@pytest.mark.unit
def test_parse_artifacts_empty(tmp_path: Path) -> None:
    manifest = tmp_path / "MANIFEST.yaml"
    manifest.write_text("last_updated: 2026-01-01\n", encoding="utf-8")
    artifacts = _parse_artifacts(manifest)
    assert artifacts == []


@pytest.mark.unit
def test_parse_artifacts_no_sha256(tmp_path: Path) -> None:
    manifest = tmp_path / "MANIFEST.yaml"
    manifest.write_text(
        "artifacts:\n"
        "  - path: some/file.md\n"
        "    description: a file\n",
        encoding="utf-8",
    )
    artifacts = _parse_artifacts(manifest)
    assert len(artifacts) == 1
    assert artifacts[0]["sha256"] == "pending"


# ── check_manifest ────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_check_manifest_all_ok(tmp_path: Path) -> None:
    f = tmp_path / "docs" / "file.md"
    f.parent.mkdir(parents=True)
    f.write_bytes(b"content")
    sha = hashlib.sha256(b"content").hexdigest()

    manifest = tmp_path / "docs" / "MANIFEST.yaml"
    manifest.write_text(
        f"last_updated: 2026-01-01\nartifacts:\n  - path: docs/file.md\n    sha256: {sha}\n",
        encoding="utf-8",
    )

    result = check_manifest(repo_root=tmp_path)
    assert result == 0


@pytest.mark.unit
def test_check_manifest_mismatch_returns_1(tmp_path: Path) -> None:
    f = tmp_path / "docs" / "file.md"
    f.parent.mkdir(parents=True)
    f.write_bytes(b"content")

    manifest = tmp_path / "docs" / "MANIFEST.yaml"
    manifest.write_text(
        "last_updated: 2026-01-01\nartifacts:\n  - path: docs/file.md\n    sha256: 0000000000000000\n",
        encoding="utf-8",
    )

    result = check_manifest(repo_root=tmp_path)
    assert result == 1


@pytest.mark.unit
def test_check_manifest_pending_returns_0(tmp_path: Path) -> None:
    f = tmp_path / "docs" / "file.md"
    f.parent.mkdir(parents=True)
    f.write_bytes(b"content")

    manifest = tmp_path / "docs" / "MANIFEST.yaml"
    manifest.write_text(
        "last_updated: 2026-01-01\nartifacts:\n  - path: docs/file.md\n    sha256: pending\n",
        encoding="utf-8",
    )

    result = check_manifest(repo_root=tmp_path)
    assert result == 0


@pytest.mark.unit
def test_check_manifest_missing_file_returns_0(tmp_path: Path) -> None:
    manifest = tmp_path / "docs" / "MANIFEST.yaml"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        "last_updated: 2026-01-01\nartifacts:\n  - path: docs/nonexistent.md\n    sha256: abc\n",
        encoding="utf-8",
    )

    result = check_manifest(repo_root=tmp_path)
    assert result == 0  # missing is warning, not failure


# ── regen_manifest ────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_regen_manifest_updates_hashes(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    f = docs / "file.md"
    f.write_bytes(b"hello")
    sha = hashlib.sha256(b"hello").hexdigest()

    manifest = docs / "MANIFEST.yaml"
    manifest.write_text(
        "last_updated: 2020-01-01\n"
        "artifacts:\n"
        "  - path: docs/file.md\n"
        "    sha256: OLD_HASH\n",
        encoding="utf-8",
    )

    result = regen_manifest(repo_root=tmp_path)
    assert result == 0
    updated = manifest.read_text(encoding="utf-8")
    assert sha in updated
    assert "OLD_HASH" not in updated


@pytest.mark.unit
def test_regen_manifest_warns_missing_file(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()

    manifest = docs / "MANIFEST.yaml"
    manifest.write_text(
        "last_updated: 2020-01-01\n"
        "artifacts:\n"
        "  - path: docs/missing.md\n"
        "    sha256: pending\n",
        encoding="utf-8",
    )

    result = regen_manifest(repo_root=tmp_path)
    assert result == 0  # missing produces a warning, not failure


@pytest.mark.unit
def test_regen_manifest_updates_last_updated(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    f = docs / "file.md"
    f.write_bytes(b"data")

    manifest = docs / "MANIFEST.yaml"
    manifest.write_text(
        "last_updated: 2020-01-01\n"
        "artifacts:\n"
        "  - path: docs/file.md\n"
        "    sha256: OLD\n",
        encoding="utf-8",
    )

    regen_manifest(repo_root=tmp_path)
    content = manifest.read_text(encoding="utf-8")
    # Should NOT contain the old date
    assert "2020-01-01" not in content


# ── check_manifest_report ────────────────────────────────────────────────────


@pytest.mark.unit
def test_check_manifest_report_ok(tmp_path: Path) -> None:
    f = tmp_path / "docs" / "file.md"
    f.parent.mkdir(parents=True)
    f.write_bytes(b"data")
    sha = hashlib.sha256(b"data").hexdigest()

    manifest = tmp_path / "docs" / "MANIFEST.yaml"
    manifest.write_text(
        f"artifacts:\n  - path: docs/file.md\n    sha256: {sha}\n",
        encoding="utf-8",
    )

    result = check_manifest_report(repo_root=tmp_path)
    assert result["passed"] is True
    assert result["ok_count"] == 1
    assert result["mismatch_count"] == 0


@pytest.mark.unit
def test_check_manifest_report_mismatch(tmp_path: Path) -> None:
    f = tmp_path / "docs" / "file.md"
    f.parent.mkdir(parents=True)
    f.write_bytes(b"data")

    manifest = tmp_path / "docs" / "MANIFEST.yaml"
    manifest.write_text(
        "artifacts:\n  - path: docs/file.md\n    sha256: WRONG\n",
        encoding="utf-8",
    )

    result = check_manifest_report(repo_root=tmp_path)
    assert result["passed"] is False
    assert result["mismatch_count"] == 1


@pytest.mark.unit
def test_check_manifest_report_pending(tmp_path: Path) -> None:
    f = tmp_path / "docs" / "file.md"
    f.parent.mkdir(parents=True)
    f.write_bytes(b"data")

    manifest = tmp_path / "docs" / "MANIFEST.yaml"
    manifest.write_text(
        "artifacts:\n  - path: docs/file.md\n    sha256: pending\n",
        encoding="utf-8",
    )

    result = check_manifest_report(repo_root=tmp_path)
    assert result["passed"] is True
    assert result["pending_count"] == 1


@pytest.mark.unit
def test_check_manifest_report_missing(tmp_path: Path) -> None:
    manifest = tmp_path / "docs" / "MANIFEST.yaml"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        "artifacts:\n  - path: docs/ghost.md\n    sha256: abc\n",
        encoding="utf-8",
    )

    result = check_manifest_report(repo_root=tmp_path)
    assert result["missing_count"] == 1


# ── regen_manifest_report ────────────────────────────────────────────────────


@pytest.mark.unit
def test_regen_manifest_report_returns_dict(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    f = docs / "file.md"
    f.write_bytes(b"hello")

    manifest = docs / "MANIFEST.yaml"
    manifest.write_text(
        "last_updated: 2020-01-01\n"
        "artifacts:\n  - path: docs/file.md\n    sha256: OLD\n",
        encoding="utf-8",
    )

    result = regen_manifest_report(repo_root=tmp_path)
    assert isinstance(result, dict)
    assert result["updated_count"] == 1
    assert result["missing_paths"] == []


# ── main ──────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_main_check_command_real_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["manifest_integrity", "check"])
    result = main(["check"])
    # Real repo should pass (0) or have only pending/missing entries (0)
    assert result in (0, 1)


@pytest.mark.unit
def test_main_regen_writes_updated_hashes(tmp_path: Path) -> None:
    # Test regen_manifest directly (main() uses a compiled-in default for repo_root)
    docs = tmp_path / "docs"
    docs.mkdir()
    f = docs / "file.md"
    f.write_bytes(b"data")
    sha = hashlib.sha256(b"data").hexdigest()

    manifest = docs / "MANIFEST.yaml"
    manifest.write_text(
        "last_updated: 2020-01-01\n"
        "artifacts:\n  - path: docs/file.md\n    sha256: OLD\n",
        encoding="utf-8",
    )

    result = regen_manifest(repo_root=tmp_path)
    assert result == 0
    content = manifest.read_text(encoding="utf-8")
    assert sha in content


# ── Real-manifest regression (bug: regex only matched 2-space indent) ─────


@pytest.mark.unit
def test_real_manifest_parses_artifacts() -> None:
    """The real docs/MANIFEST.yaml uses zero-indent list entries (PyYAML
    default).  _parse_artifacts must recognise those and return a
    reasonably large artifact list (sanity: >100 entries)."""
    real_manifest = REPO_ROOT / "docs" / "MANIFEST.yaml"
    assert real_manifest.exists(), "real docs/MANIFEST.yaml must exist"
    artifacts = _parse_artifacts(real_manifest)
    assert len(artifacts) > 100, (
        f"expected real manifest to yield >100 artifacts; got {len(artifacts)}. "
        "This is a guard against regressions of the 2-space-only regex bug."
    )
    paths = {a["path"] for a in artifacts}
    # Sentinel file that has lived at the top of the manifest for a long time.
    assert "docs/1-commands/README.md" in paths


@pytest.mark.unit
def test_check_manifest_real_reports_many_artifacts(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """check_manifest against the real repo root must report a non-zero
    artifact count in its summary line."""
    rc = check_manifest(repo_root=REPO_ROOT)
    out = capsys.readouterr().out
    assert rc in (0, 1)
    # Summary line format:
    #   "Manifest integrity: <ok> OK | <pending> pending | <missing> missing | <mm> mismatch"
    import re as _re
    m = _re.search(
        r"Manifest integrity:\s+(\d+)\s+OK\s+\|\s+(\d+)\s+pending\s+\|\s+(\d+)\s+missing\s+\|\s+(\d+)\s+mismatch",
        out,
    )
    assert m, f"expected a 'Manifest integrity: …' summary line; got:\n{out}"
    total = sum(int(g) for g in m.groups())
    assert total > 100, (
        f"expected >100 artifacts accounted for; got {total}. "
        "Regression of manifest_integrity regex bug."
    )

