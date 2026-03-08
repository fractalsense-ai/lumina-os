from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent


def load_yaml(path: Path) -> dict[str, Any]:
    yaml_loader_path = REPO_ROOT / "reference-implementations" / "yaml-loader.py"
    spec = importlib.util.spec_from_file_location("integrity_yaml_loader", str(yaml_loader_path))
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load yaml-loader.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    parsed = mod.load_yaml(str(path))
    if not isinstance(parsed, dict):
        raise RuntimeError(f"YAML file did not parse as a mapping: {path}")
    return parsed


def parse_latest_changelog_version(changelog_path: Path) -> str:
    heading_re = re.compile(r"^##\s+v(\d+\.\d+\.\d+)\b")
    for line in changelog_path.read_text(encoding="utf-8").splitlines():
        m = heading_re.match(line.strip())
        if m:
            return m.group(1)
    raise RuntimeError(f"No version heading found in {changelog_path}")


def check_runtime_config_paths(errors: list[str]) -> None:
    runtime_cfg_path = REPO_ROOT / "domain-packs" / "education" / "runtime-config.yaml"
    cfg = load_yaml(runtime_cfg_path)

    runtime_cfg = cfg.get("runtime")
    if not isinstance(runtime_cfg, dict):
        errors.append("runtime-config.yaml: missing or invalid root.runtime mapping")
        return

    required_paths = [
        "domain_system_prompt_path",
        "turn_interpretation_prompt_path",
        "domain_physics_path",
        "subject_profile_path",
    ]

    for key in required_paths:
        value = runtime_cfg.get(key)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"runtime-config.yaml: runtime.{key} missing or invalid")
            continue
        target = REPO_ROOT / value
        if not target.exists():
            errors.append(f"runtime-config.yaml: runtime.{key} points to missing file: {value}")

    additional_specs = runtime_cfg.get("additional_specs", [])
    if additional_specs is not None and not isinstance(additional_specs, list):
        errors.append("runtime-config.yaml: runtime.additional_specs must be a list")
    elif isinstance(additional_specs, list):
        for idx, value in enumerate(additional_specs):
            path_value: str | None = None
            if isinstance(value, str):
                path_value = value
            elif isinstance(value, dict):
                raw = value.get("path")
                if isinstance(raw, str) and raw.strip():
                    path_value = raw.strip()

            if not path_value:
                errors.append(
                    f"runtime-config.yaml: runtime.additional_specs[{idx}] must be a string or mapping with 'path'"
                )
                continue

            target = REPO_ROOT / path_value
            if not target.exists():
                errors.append(
                    f"runtime-config.yaml: runtime.additional_specs[{idx}] missing file: {path_value}"
                )


def check_algebra_version_alignment(errors: list[str]) -> None:
    yaml_path = REPO_ROOT / "domain-packs" / "education" / "algebra-level-1" / "domain-physics.yaml"
    json_path = REPO_ROOT / "domain-packs" / "education" / "algebra-level-1" / "domain-physics.json"
    changelog_path = REPO_ROOT / "domain-packs" / "education" / "algebra-level-1" / "CHANGELOG.md"
    examples_path = REPO_ROOT / "examples" / "README.md"

    yaml_version = str(load_yaml(yaml_path).get("version", "")).strip()

    json_version = ""
    try:
        json_version = str(json.loads(json_path.read_text(encoding="utf-8")).get("version", "")).strip()
    except Exception as exc:
        errors.append(f"domain-physics.json parse error: {exc}")

    changelog_version = parse_latest_changelog_version(changelog_path)

    if yaml_version != changelog_version:
        errors.append(
            f"Version mismatch: domain-physics.yaml={yaml_version} but CHANGELOG latest=v{changelog_version}"
        )
    if json_version != changelog_version:
        errors.append(
            f"Version mismatch: domain-physics.json={json_version} but CHANGELOG latest=v{changelog_version}"
        )

    examples_text = examples_path.read_text(encoding="utf-8")
    expected = f"Algebra Level 1 v{changelog_version}"
    if expected not in examples_text:
        errors.append(f"examples/README.md does not reference latest domain version string: {expected}")


def _extract_md_links(text: str) -> list[str]:
    return re.findall(r"\]\(([^)]+)\)", text)


def _is_external_link(link: str) -> bool:
    prefixes = ("http://", "https://", "mailto:", "tel:")
    return link.startswith(prefixes)


def check_markdown_relative_links(errors: list[str]) -> None:
    excluded_parts = {"node_modules", ".git", "dist", "__pycache__", ".venv"}
    markdown_files = [
        p for p in REPO_ROOT.rglob("*.md") if not any(part in excluded_parts for part in p.parts)
    ]

    for md_path in markdown_files:
        text = md_path.read_text(encoding="utf-8", errors="replace")
        for raw_link in _extract_md_links(text):
            link = raw_link.strip()
            if not link or _is_external_link(link) or link.startswith("#"):
                continue

            link_no_anchor = link.split("#", 1)[0].strip()
            if not link_no_anchor:
                continue
            # Treat absolute-from-repo links as repo-relative, all others as file-relative.
            candidate = (REPO_ROOT / link_no_anchor.lstrip("/")) if link_no_anchor.startswith("/") else (md_path.parent / link_no_anchor)
            if not candidate.exists():
                rel_md = md_path.relative_to(REPO_ROOT)
                errors.append(f"Broken markdown link in {rel_md}: {raw_link}")


def check_frontend_essentials(errors: list[str]) -> None:
    frontend = REPO_ROOT / "front-end"
    required = [
        "package.json",
        "tsconfig.json",
        "vite.config.ts",
        "index.html",
        "src/main.tsx",
        "src/main.css",
    ]
    for rel in required:
        if not (frontend / rel).exists():
            errors.append(f"front-end missing required file: {rel}")


def main() -> int:
    errors: list[str] = []

    check_runtime_config_paths(errors)
    check_algebra_version_alignment(errors)
    check_markdown_relative_links(errors)
    check_frontend_essentials(errors)

    if errors:
        print("[FAIL] Repo integrity checks found issues:")
        for err in errors:
            print(f"  - {err}")
        return 1

    print("[PASS] Repo integrity checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
