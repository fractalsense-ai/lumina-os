from __future__ import annotations

import runpy
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _run_systool(script_name: str) -> None:
    script_path = _repo_root() / "src" / "lumina" / "systools" / script_name
    if not script_path.exists():
        raise FileNotFoundError(f"Missing systool: {script_path}")
    runpy.run_path(str(script_path), run_name="__main__")


def api() -> None:
    script_path = _repo_root() / "src" / "lumina" / "api" / "server.py"
    if not script_path.exists():
        raise FileNotFoundError(f"Missing API server: {script_path}")
    runpy.run_path(str(script_path), run_name="__main__")


def verify() -> None:
    _run_systool("verify_repo.py")


def orchestrator_demo() -> None:
    _run_systool("dsa_demo.py")


def ctl_validate() -> None:
    _run_systool("ctl_validator.py")


def security_freeze() -> None:
    _run_systool("security_freeze.py")


def yaml_convert() -> None:
    _run_systool("yaml_converter.py")


def integrity_check() -> None:
    import sys

    _saved_argv = sys.argv[:]
    try:
        sys.argv = [sys.argv[0], "check"]
        _run_systool("manifest_integrity.py")
    finally:
        sys.argv = _saved_argv


def manifest_regen() -> None:
    import sys

    _saved_argv = sys.argv[:]
    try:
        sys.argv = [sys.argv[0], "regen"]
        _run_systool("manifest_integrity.py")
    finally:
        sys.argv = _saved_argv
