"""Template rendering utilities for tool-call policy payloads."""

from __future__ import annotations

import re
from typing import Any

_TPL_RE = re.compile(r"\{([^{}]+)\}")


def resolve_context_path(context: dict[str, Any], path_expr: str) -> Any:
    cur: Any = context
    for part in path_expr.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def render_template_value(value: Any, context: dict[str, Any]) -> Any:
    if isinstance(value, str):
        matches = _TPL_RE.findall(value)
        if not matches:
            return value

        # Single placeholder keeps source type (for numeric and boolean tool payloads).
        stripped = value.strip()
        if stripped.startswith("{") and stripped.endswith("}") and len(matches) == 1:
            return resolve_context_path(context, matches[0])

        rendered = value
        for match in matches:
            resolved = resolve_context_path(context, match)
            rendered = rendered.replace("{" + match + "}", "" if resolved is None else str(resolved))
        return rendered
    if isinstance(value, dict):
        return {k: render_template_value(v, context) for k, v in value.items()}
    if isinstance(value, list):
        return [render_template_value(v, context) for v in value]
    return value


# Backward-compat private aliases
_TPL_RE = _TPL_RE
_resolve_context_path = resolve_context_path
_render_template_value = render_template_value
