from __future__ import annotations

import runpy
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _run_reference_script(script_name: str) -> None:
    script_path = _repo_root() / "reference-implementations" / script_name
    if not script_path.exists():
        raise FileNotFoundError(f"Missing reference script: {script_path}")
    runpy.run_path(str(script_path), run_name="__main__")


def api() -> None:
    _run_reference_script("lumina-api-server.py")


def verify() -> None:
    _run_reference_script("verify-repo-integrity.py")


def orchestrator_demo() -> None:
    _run_reference_script("dsa-orchestrator-demo.py")


def ctl_validate() -> None:
    _run_reference_script("ctl-commitment-validator.py")


def security_freeze() -> None:
    _run_reference_script("lumina-security-freeze.py")


def yaml_convert() -> None:
    _run_reference_script("yaml-to-json-converter.py")
