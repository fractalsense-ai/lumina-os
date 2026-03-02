"""
yaml-to-json-converter.py — Project Lumina Domain Pack Converter

Converts a domain-physics.yaml file to domain-physics.json and
optionally validates the result against the domain-physics-schema-v1.json.

Usage:
    # Convert only
    python reference-implementations/yaml-to-json-converter.py \\
        domain-packs/education/algebra-level-1/domain-physics.yaml

    # Convert and validate
    python reference-implementations/yaml-to-json-converter.py \\
        domain-packs/education/algebra-level-1/domain-physics.yaml \\
        --schema standards/domain-physics-schema-v1.json

    # Specify output path
    python reference-implementations/yaml-to-json-converter.py \\
        domain-packs/education/algebra-level-1/domain-physics.yaml \\
        --output /tmp/domain-physics-validated.json \\
        --schema standards/domain-physics-schema-v1.json

Dependencies: PyYAML (pip install pyyaml), jsonschema (pip install jsonschema)
Standard library: json, argparse, sys, pathlib, hashlib
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


def _require_import(module_name: str, install_name: str | None = None) -> object:
    """Import a module, printing a helpful message if missing."""
    import importlib
    try:
        return importlib.import_module(module_name)
    except ImportError:
        pkg = install_name or module_name
        print(f"ERROR: '{module_name}' is not installed. Run: pip install {pkg}", file=sys.stderr)
        sys.exit(1)


def load_yaml(path: Path) -> dict:
    """Load and parse a YAML file."""
    yaml = _require_import("yaml")
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)  # type: ignore[union-attr]


def validate_schema(data: dict, schema_path: Path) -> list[str]:
    """
    Validate data against a JSON Schema file.
    Returns a list of validation error messages (empty = valid).
    """
    jsonschema = _require_import("jsonschema")
    with open(schema_path, encoding="utf-8") as f:
        schema = json.load(f)

    validator_cls = jsonschema.Draft202012Validator  # type: ignore[attr-defined]
    errors = list(validator_cls(schema).iter_errors(data))
    return [f"{err.json_path}: {err.message}" for err in errors]


def compute_hash(data: dict) -> str:
    """Compute SHA-256 of canonical JSON (keys sorted, no whitespace)."""
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def convert(
    yaml_path: Path,
    output_path: Path | None = None,
    schema_path: Path | None = None,
    dry_run: bool = False,
) -> int:
    """
    Convert domain-physics.yaml → domain-physics.json.

    Returns 0 on success, 1 on validation error.
    """
    print(f"Loading: {yaml_path}")

    if not yaml_path.exists():
        print(f"ERROR: File not found: {yaml_path}", file=sys.stderr)
        return 1

    data = load_yaml(yaml_path)
    if not isinstance(data, dict):
        print(f"ERROR: YAML root must be a mapping/dict, got {type(data).__name__}", file=sys.stderr)
        return 1

    # Validate against schema if provided
    if schema_path:
        print(f"Validating against schema: {schema_path}")
        if not schema_path.exists():
            print(f"ERROR: Schema file not found: {schema_path}", file=sys.stderr)
            return 1
        errors = validate_schema(data, schema_path)
        if errors:
            print(f"VALIDATION FAILED — {len(errors)} error(s):", file=sys.stderr)
            for err in errors:
                print(f"  • {err}", file=sys.stderr)
            return 1
        print("  Validation: PASSED ✓")
    else:
        print("  (No schema provided — skipping validation)")

    # Compute hash of the JSON form
    content_hash = compute_hash(data)
    print(f"  Content hash (SHA-256): {content_hash}")

    # Determine output path
    if output_path is None:
        output_path = yaml_path.with_suffix(".json")

    if dry_run:
        print(f"  Dry run — would write to: {output_path}")
        print("  Dry run complete.")
        return 0

    # Write JSON
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")  # trailing newline

    print(f"  Written: {output_path}")
    print(f"  Size: {output_path.stat().st_size} bytes")
    print("Done.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert and validate a Project Lumina domain-physics.yaml file to JSON.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "yaml_file",
        type=Path,
        help="Path to the domain-physics.yaml file",
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=None,
        help="Output JSON file path (default: same dir as input, .json extension)",
    )
    parser.add_argument(
        "--schema", "-s",
        type=Path,
        default=None,
        help="Path to the domain-physics-schema-v1.json for validation",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and hash only; do not write output file",
    )

    args = parser.parse_args()
    sys.exit(convert(
        yaml_path=args.yaml_file,
        output_path=args.output,
        schema_path=args.schema,
        dry_run=args.dry_run,
    ))


if __name__ == "__main__":
    main()
