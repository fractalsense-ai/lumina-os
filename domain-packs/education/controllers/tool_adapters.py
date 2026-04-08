"""Global education-domain tool adapters.

Contains lightweight tools shared across modules (calculator, substitution
checker).  Module-specific tools live in their own files (algebra_tools.py,
etc.).
"""
from __future__ import annotations

from typing import Any


# ─────────────────────────────────────────────────────────────
# Calculator — simple arithmetic evaluator
# ─────────────────────────────────────────────────────────────


def calculator_tool(payload: dict[str, Any]) -> dict[str, Any]:
    expr = str(payload.get("expression", "")).strip()
    if not expr:
        return {"ok": False, "error": "expression is required"}

    allowed = set("0123456789+-*/(). ")
    if any(ch not in allowed for ch in expr):
        return {"ok": False, "error": "unsupported characters in expression"}

    try:
        result = eval(expr, {"__builtins__": {}}, {})
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    return {"ok": True, "result": result}


def substitution_checker_tool(payload: dict[str, Any]) -> dict[str, Any]:
    left_value = payload.get("left_value")
    right_value = payload.get("right_value")
    if left_value is None or right_value is None:
        return {"ok": False, "error": "left_value and right_value are required"}
    return {"ok": True, "equal": left_value == right_value}
