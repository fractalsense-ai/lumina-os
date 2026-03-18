"""Type coercion and turn-data normalization utilities."""

from __future__ import annotations

from typing import Any


def coerce_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "y"}:
            return True
        if lowered in {"false", "0", "no", "n"}:
            return False
    return default


def coerce_int(value: Any, default: int = 0, minimum: int | None = None) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    if minimum is not None and parsed < minimum:
        return minimum
    return parsed


def coerce_float(
    value: Any, default: float = 0.0, minimum: float | None = None, maximum: float | None = None
) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    if minimum is not None and parsed < minimum:
        parsed = minimum
    if maximum is not None and parsed > maximum:
        parsed = maximum
    return parsed


def coerce_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


def normalize_turn_data(
    turn_data: dict[str, Any],
    turn_input_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply domain-owned schema rules; otherwise preserve values as-is."""
    normalized = dict(turn_data)
    schema = turn_input_schema or {}
    if not isinstance(schema, dict):
        return normalized

    for field, raw_cfg in schema.items():
        if not isinstance(raw_cfg, dict):
            continue

        field_type = str(raw_cfg.get("type", "")).strip().lower()
        has_field = field in normalized
        value = normalized.get(field)

        if (not has_field or value is None) and "default" in raw_cfg:
            value = raw_cfg.get("default")
            normalized[field] = value

        if value is None:
            continue

        if field_type == "bool":
            normalized[field] = coerce_bool(value, bool(raw_cfg.get("default", False)))
            continue

        if field_type == "int":
            minimum = raw_cfg.get("minimum")
            minimum_int = int(minimum) if isinstance(minimum, (int, float)) else None
            normalized[field] = coerce_int(value, int(raw_cfg.get("default", 0)), minimum_int)
            continue

        if field_type == "float":
            minimum = raw_cfg.get("minimum")
            maximum = raw_cfg.get("maximum")
            min_float = float(minimum) if isinstance(minimum, (int, float)) else None
            max_float = float(maximum) if isinstance(maximum, (int, float)) else None
            normalized[field] = coerce_float(value, float(raw_cfg.get("default", 0.0)), min_float, max_float)
            continue

        if field_type == "string":
            normalized[field] = coerce_str(value, str(raw_cfg.get("default", "")))
            continue

        if field_type == "enum":
            values = raw_cfg.get("values")
            if isinstance(values, list):
                allowed = [str(v) for v in values]
                rendered = str(value)
                if rendered not in allowed and "default" in raw_cfg:
                    rendered = str(raw_cfg.get("default"))
                normalized[field] = rendered
            continue

        if field_type == "list":
            if isinstance(value, list):
                normalized[field] = value
            elif "default" in raw_cfg and isinstance(raw_cfg.get("default"), list):
                normalized[field] = list(raw_cfg.get("default"))
            else:
                normalized[field] = []

    return normalized


# Backward-compat private aliases used by server.py re-export
_coerce_bool = coerce_bool
_coerce_int = coerce_int
_coerce_float = coerce_float
_coerce_str = coerce_str
_normalize_turn_data = normalize_turn_data
