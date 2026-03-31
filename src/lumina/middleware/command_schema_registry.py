"""Command Schema Registry — Default Deny validation for admin commands.

Loads JSON Schema definitions from ``standards/admin-command-schemas/``
at first use and validates parsed admin commands against them.  Any
command whose operation does not have a matching schema is **denied by
default**.

Public API
----------
validate_command(operation, params, target="")
    → (approved: bool, violations: list[str])
list_operations() → frozenset[str]
reload()          — re-read schemas from disk (mainly for tests)
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level registry (populated lazily on first call)
# ---------------------------------------------------------------------------

_schemas: dict[str, dict[str, Any]] = {}
_loaded: bool = False

# Default location of the schema files relative to the project root.
_DEFAULT_SCHEMA_DIR: Path = (
    Path(__file__).resolve().parents[3] / "standards" / "admin-command-schemas"
)


def _resolve_schema_dir() -> Path:
    """Return the schema directory, allowing override for tests."""
    return _DEFAULT_SCHEMA_DIR


def reload(schema_dir: Path | None = None) -> int:
    """(Re-)load all command schemas from *schema_dir*.

    Returns the number of schemas loaded.  Called automatically on first
    use; also useful in tests to point at a temp directory.
    """
    global _loaded  # noqa: PLW0603
    target = schema_dir or _resolve_schema_dir()
    _schemas.clear()
    if not target.is_dir():
        log.warning("Command schema directory does not exist: %s", target)
        _loaded = True
        return 0

    for path in sorted(target.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("Skipping invalid schema file %s: %s", path.name, exc)
            continue

        # Derive the operation name from the schema title or the filename.
        op_name = data.get("title") or path.stem.replace("-", "_")
        _schemas[op_name] = data

    _loaded = True
    log.info("Loaded %d admin command schemas", len(_schemas))
    return len(_schemas)


def _ensure_loaded() -> None:
    if not _loaded:
        reload()


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def list_operations() -> frozenset[str]:
    """Return the set of operations that have registered schemas."""
    _ensure_loaded()
    return frozenset(_schemas)


def get_schema(operation: str) -> dict[str, Any] | None:
    """Return the raw schema dict for *operation*, or ``None``."""
    _ensure_loaded()
    return _schemas.get(operation)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_command(
    operation: str,
    params: dict[str, Any] | None = None,
    target: str = "",
) -> tuple[bool, list[str]]:
    """Validate a parsed admin command against its registered schema.

    Parameters
    ----------
    operation : str
        The operation name (e.g. ``"update_user_role"``).
    params : dict
        The ``params`` object produced by the SLM parser.
    target : str, optional
        The optional ``target`` field from the parsed command.

    Returns
    -------
    (approved, violations) : tuple[bool, list[str]]
        *approved* is ``True`` when the command is structurally valid.
        *violations* is a list of human-readable reasons when denied.
    """
    _ensure_loaded()

    if params is None:
        params = {}

    # --- Default Deny: unknown operations are rejected outright -----------
    schema = _schemas.get(operation)
    if schema is None:
        return False, [f"Unknown operation: {operation!r} (no schema registered)"]

    violations: list[str] = []

    # --- Validate the params sub-object against schema.properties.params --
    params_schema = (schema.get("properties") or {}).get("params", {})
    _validate_object(params, params_schema, "params", violations)

    return (len(violations) == 0), violations


# ---------------------------------------------------------------------------
# Lightweight schema validator (subset of JSON Schema Draft 2020-12)
#
# We intentionally avoid pulling in ``jsonschema`` as a runtime dependency.
# The schemas are simple enough that a hand-rolled validator suffices.
# ---------------------------------------------------------------------------


def _validate_object(
    value: Any,
    schema: dict[str, Any],
    path: str,
    violations: list[str],
) -> None:
    """Validate *value* against an ``object``-type schema node."""
    if schema.get("type") == "object" and not isinstance(value, dict):
        violations.append(f"{path}: expected object, got {type(value).__name__}")
        return

    if not isinstance(value, dict):
        return  # nothing more to check if there's no object type constraint

    properties = schema.get("properties", {})
    required = set(schema.get("required", []))

    # Required fields
    for key in required:
        if key not in value:
            violations.append(f"{path}.{key}: required field missing")

    # Additional properties
    if schema.get("additionalProperties") is False:
        extra = set(value) - set(properties)
        for key in sorted(extra):
            violations.append(f"{path}.{key}: unexpected field")

    # Per-property validation
    for key, prop_schema in properties.items():
        if key not in value:
            continue
        if value[key] is None and key not in required:
            continue
        _validate_value(value[key], prop_schema, f"{path}.{key}", violations)


def _validate_value(
    value: Any,
    schema: dict[str, Any],
    path: str,
    violations: list[str],
) -> None:
    """Validate *value* against a property schema node."""
    expected_type = schema.get("type")

    if expected_type is not None:
        if not _type_matches(value, expected_type):
            violations.append(
                f"{path}: expected {expected_type}, got {type(value).__name__}"
            )
            return

    # const
    if "const" in schema and value != schema["const"]:
        violations.append(f"{path}: must be {schema['const']!r}, got {value!r}")

    # enum
    if "enum" in schema and value not in schema["enum"]:
        violations.append(
            f"{path}: must be one of {schema['enum']}, got {value!r}"
        )

    # minLength / maxLength (strings)
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            violations.append(
                f"{path}: string too short (min {schema['minLength']})"
            )
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            violations.append(
                f"{path}: string too long (max {schema['maxLength']})"
            )

    # Nested object
    if expected_type == "object" and isinstance(value, dict):
        _validate_object(value, schema, path, violations)

    # Array items
    if expected_type == "array" and isinstance(value, list):
        items_schema = schema.get("items", {})
        for i, item in enumerate(value):
            _validate_value(item, items_schema, f"{path}[{i}]", violations)


def _type_matches(value: Any, expected: str) -> bool:
    """Check whether *value* matches the JSON Schema *expected* type."""
    mapping = {
        "string": str,
        "integer": int,
        "number": (int, float),
        "boolean": bool,
        "array": list,
        "object": dict,
    }
    py_type = mapping.get(expected)
    if py_type is None:
        return True  # unknown type → permissive
    # bool is a subclass of int in Python; JSON Schema treats them separately.
    if expected == "integer" and isinstance(value, bool):
        return False
    if expected == "number" and isinstance(value, bool):
        return False
    return isinstance(value, py_type)
