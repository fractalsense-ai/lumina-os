"""Tests for lumina.cli.cli — entry-point wrappers."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

import lumina.cli.cli as cli_mod
from lumina.cli.cli import (
    _repo_root,
    _run_systool,
    api,
    system_log_validate,
    integrity_check,
    manifest_regen,
    orchestrator_demo,
    security_freeze,
    verify,
    yaml_convert,
)


# ── _repo_root ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_repo_root_returns_path() -> None:
    root = _repo_root()
    assert isinstance(root, Path)
    assert root.is_dir()
    # cli.py is in src/lumina/cli/, so repo root is 3 levels up.
    assert (root / "pyproject.toml").exists()


# ── _run_systool ───────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_run_systool_missing_file_raises() -> None:
    with pytest.raises(FileNotFoundError, match="Missing systool"):
        _run_systool("nonexistent_script_xyz.py")


@pytest.mark.unit
def test_run_systool_runs_valid_script(tmp_path: Path) -> None:
    # Use runpy to run a tiny script placed next to the real systools.
    script = tmp_path / "dummy_tool.py"
    script.write_text("pass\n", encoding="utf-8")

    # Patch _repo_root to return a fake root that puts our script in the right place.
    root = tmp_path / "src" / "lumina" / "systools"
    root.mkdir(parents=True)
    real_script = root / "dummy_tool.py"
    real_script.write_text("pass\n", encoding="utf-8")

    with patch.object(cli_mod, "_repo_root", return_value=tmp_path):
        # Should not raise
        _run_systool("dummy_tool.py")


# ── api() ──────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_api_raises_if_server_missing(tmp_path: Path) -> None:
    with patch.object(cli_mod, "_repo_root", return_value=tmp_path):
        with pytest.raises(FileNotFoundError, match="Missing API server"):
            api()


# ── verify() ──────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_verify_delegates_to_systool(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(cli_mod, "_run_systool", lambda s: calls.append(s))
    verify()
    assert calls == ["verify_repo.py"]


# ── orchestrator_demo() ────────────────────────────────────────────────────────


@pytest.mark.unit
def test_orchestrator_demo_delegates(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(cli_mod, "_run_systool", lambda s: calls.append(s))
    orchestrator_demo()
    assert calls == ["ppa_demo.py"]


# ── system_log_validate() ────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_system_log_validate_delegates(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(cli_mod, "_run_systool", lambda s: calls.append(s))
    system_log_validate()
    assert calls == ["system_log_validator.py"]


# ── security_freeze() ─────────────────────────────────────────────────────────


@pytest.mark.unit
def test_security_freeze_delegates(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(cli_mod, "_run_systool", lambda s: calls.append(s))
    security_freeze()
    assert calls == ["security_freeze.py"]


# ── yaml_convert() ────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_yaml_convert_delegates(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(cli_mod, "_run_systool", lambda s: calls.append(s))
    yaml_convert()
    assert calls == ["yaml_converter.py"]


# ── integrity_check() ─────────────────────────────────────────────────────────


@pytest.mark.unit
def test_integrity_check_patches_argv_and_delegates(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    argv_seen: list[list[str]] = []

    def fake_run_systool(script: str) -> None:
        argv_seen.append(sys.argv[:])

    monkeypatch.setattr(cli_mod, "_run_systool", fake_run_systool)
    integrity_check()
    assert argv_seen[0][1] == "check"


@pytest.mark.unit
def test_integrity_check_restores_argv_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    original_argv = sys.argv[:]

    def raise_fn(script: str) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(cli_mod, "_run_systool", raise_fn)
    with pytest.raises(RuntimeError, match="boom"):
        integrity_check()
    assert sys.argv == original_argv


# ── manifest_regen() ──────────────────────────────────────────────────────────


@pytest.mark.unit
def test_manifest_regen_patches_argv_with_regen(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    argv_seen: list[list[str]] = []

    def fake_run_systool(script: str) -> None:
        argv_seen.append(sys.argv[:])

    monkeypatch.setattr(cli_mod, "_run_systool", fake_run_systool)
    manifest_regen()
    assert argv_seen[0][1] == "regen"
