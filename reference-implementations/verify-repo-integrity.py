from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent

PROVENANCE_RUNTIME_KEYS = [
    "domain_pack_id",
    "domain_pack_version",
    "domain_physics_hash",
    "global_prompt_hash",
    "domain_prompt_hash",
    "turn_interpretation_prompt_hash",
    "system_prompt_hash",
    "turn_data_hash",
    "prompt_contract_hash",
]

PROVENANCE_POST_PAYLOAD_KEYS = [
    "tool_results_hash",
    "llm_payload_hash",
    "response_hash",
]

PROVENANCE_STRICT_FILES = [
    Path("ledger/trace-event-schema.json"),
    Path("specs/dsa-framework-v1.md"),
    Path("specs/audit-log-spec-v1.md"),
    Path("specs/evaluation-harness-v1.md"),
]

PROVENANCE_ESCALATION_ADVISORY_FILE = Path("ledger/escalation-record-schema.json")


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
    yaml_path = REPO_ROOT / "domain-packs" / "education" / "modules" / "algebra-level-1" / "domain-physics.yaml"
    json_path = REPO_ROOT / "domain-packs" / "education" / "modules" / "algebra-level-1" / "domain-physics.json"
    changelog_path = REPO_ROOT / "domain-packs" / "education" / "modules" / "algebra-level-1" / "CHANGELOG.md"
    examples_path = REPO_ROOT / "examples" / "README.md"
    domain_packs_readme_path = REPO_ROOT / "domain-packs" / "README.md"

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

    domain_packs_text = domain_packs_readme_path.read_text(encoding="utf-8")
    expected_row = f"| Education — Algebra Level 1 | `education/modules/algebra-level-1` | {changelog_version} |"
    if expected_row not in domain_packs_text:
        errors.append(
            "domain-packs/README.md education version row is out of date; "
            f"expected: {expected_row}"
        )


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


def check_domain_tool_adapter_linkage(errors: list[str]) -> None:
    module_physics_files = list((REPO_ROOT / "domain-packs").glob("*/*/domain-physics.json"))

    for physics_path in module_physics_files:
        try:
            physics = json.loads(physics_path.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append(f"{physics_path.relative_to(REPO_ROOT)} parse error: {exc}")
            continue

        declared = physics.get("tool_adapters") or []
        if not isinstance(declared, list):
            errors.append(f"{physics_path.relative_to(REPO_ROOT)}: tool_adapters must be a list")
            continue

        declared_ids = [str(x) for x in declared if isinstance(x, str) and x.strip()]
        if not declared_ids:
            continue

        module_dir = physics_path.parent
        adapter_dir = module_dir / "tool-adapters"
        if not adapter_dir.exists():
            errors.append(
                f"{physics_path.relative_to(REPO_ROOT)} declares tool_adapters but {adapter_dir.relative_to(REPO_ROOT)} is missing"
            )
            continue

        available_ids: set[str] = set()
        for adapter_file in adapter_dir.glob("*.yaml"):
            try:
                adapter_cfg = load_yaml(adapter_file)
            except Exception as exc:
                errors.append(f"{adapter_file.relative_to(REPO_ROOT)} parse error: {exc}")
                continue

            adapter_id = adapter_cfg.get("id")
            if isinstance(adapter_id, str) and adapter_id.strip():
                available_ids.add(adapter_id.strip())

        for adapter_id in declared_ids:
            if adapter_id not in available_ids:
                errors.append(
                    f"{physics_path.relative_to(REPO_ROOT)} declares missing adapter id: {adapter_id}"
                )


def check_provenance_contract_consistency(errors: list[str]) -> None:
    required_keys = PROVENANCE_RUNTIME_KEYS + PROVENANCE_POST_PAYLOAD_KEYS

    for rel_path in PROVENANCE_STRICT_FILES:
        abs_path = REPO_ROOT / rel_path
        if not abs_path.exists():
            errors.append(f"Missing provenance contract file: {rel_path}")
            continue

        text = abs_path.read_text(encoding="utf-8", errors="replace")
        for key in required_keys:
            if key not in text:
                errors.append(
                    f"Provenance contract drift: {rel_path} missing key '{key}'"
                )

    advisory_abs = REPO_ROOT / PROVENANCE_ESCALATION_ADVISORY_FILE
    if not advisory_abs.exists():
        errors.append(f"Missing provenance advisory file: {PROVENANCE_ESCALATION_ADVISORY_FILE}")
        return

    advisory_text = advisory_abs.read_text(encoding="utf-8", errors="replace").lower()
    if "provenance" not in advisory_text:
        errors.append(
            "Escalation schema advisory drift: "
            f"{PROVENANCE_ESCALATION_ADVISORY_FILE} should include provenance guidance text"
        )
    if "hash" not in advisory_text:
        errors.append(
            "Escalation schema advisory drift: "
            f"{PROVENANCE_ESCALATION_ADVISORY_FILE} should include hash-lineage guidance text"
        )


def check_auth_infrastructure(errors: list[str]) -> None:
    """Verify auth module, permissions module, and RBAC schemas exist and import."""
    auth_path = REPO_ROOT / "reference-implementations" / "auth.py"
    perms_path = REPO_ROOT / "reference-implementations" / "permissions.py"
    rbac_schema = REPO_ROOT / "standards" / "rbac-permission-schema-v1.json"
    role_schema = REPO_ROOT / "standards" / "role-definition-schema-v1.json"
    rbac_spec = REPO_ROOT / "specs" / "rbac-spec-v1.md"

    for p, label in [
        (auth_path, "auth.py"),
        (perms_path, "permissions.py"),
        (rbac_schema, "rbac-permission-schema-v1.json"),
        (role_schema, "role-definition-schema-v1.json"),
        (rbac_spec, "rbac-spec-v1.md"),
    ]:
        if not p.exists():
            errors.append(f"Auth infrastructure missing: {label}")

    # Validate RBAC permission schema parses as JSON
    if rbac_schema.exists():
        try:
            data = json.loads(rbac_schema.read_text(encoding="utf-8"))
            if "properties" not in data:
                errors.append("rbac-permission-schema-v1.json: missing 'properties' key")
        except json.JSONDecodeError as exc:
            errors.append(f"rbac-permission-schema-v1.json: invalid JSON — {exc}")

    # Verify domain-physics files include permissions block
    edu_dp = REPO_ROOT / "domain-packs" / "education" / "modules" / "algebra-level-1" / "domain-physics.yaml"
    agr_dp = REPO_ROOT / "domain-packs" / "agriculture" / "modules" / "operations-level-1" / "domain-physics.json"
    if edu_dp.exists():
        edu_text = edu_dp.read_text(encoding="utf-8")
        if "permissions:" not in edu_text:
            errors.append("education domain-physics.yaml: missing permissions block")
    if agr_dp.exists():
        try:
            agr_data = json.loads(agr_dp.read_text(encoding="utf-8"))
            if "permissions" not in agr_data:
                errors.append("agriculture domain-physics.json: missing permissions block")
        except json.JSONDecodeError as exc:
            errors.append(f"agriculture domain-physics.json: invalid JSON — {exc}")


def check_docs_structure(errors: list[str]) -> None:
    """Verify docs/ man-page directory structure exists."""
    docs_root = REPO_ROOT / "docs"
    if not docs_root.is_dir():
        errors.append("docs/ directory missing")
        return

    expected_sections = [
        "1-commands",
        "2-syscalls",
        "3-functions",
        "4-formats",
        "5-standards",
        "6-examples",
        "7-concepts",
        "8-admin",
    ]
    for section in expected_sections:
        section_dir = docs_root / section
        if not section_dir.is_dir():
            errors.append(f"docs/{section}/ directory missing")
        elif not (section_dir / "README.md").exists():
            errors.append(f"docs/{section}/README.md missing")

    if not (docs_root / "README.md").exists():
        errors.append("docs/README.md master index missing")


def main() -> int:
    errors: list[str] = []

    check_runtime_config_paths(errors)
    check_algebra_version_alignment(errors)
    check_markdown_relative_links(errors)
    check_frontend_essentials(errors)
    check_domain_tool_adapter_linkage(errors)
    check_provenance_contract_consistency(errors)
    check_auth_infrastructure(errors)
    check_docs_structure(errors)

    if errors:
        print("[FAIL] Repo integrity checks found issues:")
        for err in errors:
            print(f"  - {err}")
        return 1

    print("[PASS] Repo integrity checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
