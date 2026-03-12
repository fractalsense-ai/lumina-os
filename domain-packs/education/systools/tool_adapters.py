from __future__ import annotations

import re
from typing import Any


# ─────────────────────────────────────────────────────────────
# Algebra Step Parser — deterministic tool adapter
# ─────────────────────────────────────────────────────────────
#
# Pure-Python parser for linear equations of the form  ax + b = c.
# Provides ground-truth evidence for step_count, equivalence_preserved,
# and substitution_check — reducing LLM extraction variance.
# ─────────────────────────────────────────────────────────────

# Regex: captures  <coeff>x <op> <const> = <rhs>  and similar forms.
_EQ_RE = re.compile(
    r"^\s*"
    r"(?P<lhs>[^=]+)"
    r"=\s*"
    r"(?P<rhs>[^=]+)"
    r"\s*$"
)

_VARIABLE_RE = re.compile(r"[a-zA-Z]")

# Matches a single linear term:  optional sign, optional coefficient, variable
_LINEAR_TERM_RE = re.compile(
    r"([+-]?\s*\d*\.?\d*)\s*([a-zA-Z])"
)


def _parse_linear_equation(
    equation_str: str, variable: str = "x"
) -> tuple[float, float, float] | None:
    """Parse  ax + b = c  into (a, b, c).  Returns None on failure."""
    m = _EQ_RE.match(equation_str.strip())
    if not m:
        return None
    lhs_str = m.group("lhs").strip()
    rhs_str = m.group("rhs").strip()

    def _eval_side(side: str) -> tuple[float, float] | None:
        """Return (coefficient_of_variable, constant) for one side."""
        coeff = 0.0
        const = 0.0
        # Normalise implicit leading +
        s = side.replace(" ", "")
        if s and s[0] not in "+-":
            s = "+" + s

        pos = 0
        while pos < len(s):
            # Find next term boundary
            sign_char = s[pos]
            if sign_char not in "+-":
                return None
            sign = 1.0 if sign_char == "+" else -1.0
            pos += 1

            # Collect digits / decimal / variable
            num_str = ""
            found_var = False
            while pos < len(s) and s[pos] not in "+-":
                ch = s[pos]
                if ch == variable:
                    found_var = True
                elif ch.isdigit() or ch == ".":
                    num_str += ch
                else:
                    # Unknown character — skip whitespace, fail on others
                    if not ch.isspace():
                        return None
                pos += 1

            magnitude = float(num_str) if num_str else (1.0 if found_var else 0.0)
            if found_var:
                coeff += sign * magnitude
            else:
                const += sign * magnitude

        return coeff, const

    lhs_parsed = _eval_side(lhs_str)
    rhs_parsed = _eval_side(rhs_str)
    if lhs_parsed is None or rhs_parsed is None:
        return None

    # Move everything to the left:  (a_l - a_r)x + (b_l - b_r) = 0
    # Rewrite as  a_net * x + b_net = 0  →  a_net * x = -b_net  →  rhs_effective = rhs const
    a_net = lhs_parsed[0] - rhs_parsed[0]
    b_net = lhs_parsed[1] - rhs_parsed[1]

    # Express as  a_net * x = -(b_net)  i.e.  a*x + b = c  where c = rhs_parsed[1]
    # Keep original form:  lhs_a * x + lhs_b = rhs_b  (assuming rhs has no variable)
    return lhs_parsed[0], lhs_parsed[1], rhs_parsed[1]


def _solve_linear(a: float, b: float, c: float) -> float | None:
    """Solve  ax + b = c  → x = (c - b) / a.  Returns None if a == 0."""
    if abs(a) < 1e-12:
        return None
    return (c - b) / a


def _check_substitution(equation_str: str, variable: str, value: float) -> bool:
    """Check whether substituting `value` for `variable` satisfies the equation."""
    parsed = _parse_linear_equation(equation_str, variable)
    if parsed is None:
        return False
    a, b, c = parsed
    lhs_val = a * value + b
    return abs(lhs_val - c) < 1e-9


def _detect_steps(student_work: str) -> list[str]:
    """Split student free-text into individual step segments.

    Uses core NLP sentence splitting (spaCy sentencizer + regex fallback).
    """
    from lumina.core.nlp import split_sentences as _split_sentences
    return _split_sentences(student_work)


_OPERATION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("subtract", re.compile(r"subtract|minus|take away|\b-\s*\d", re.IGNORECASE)),
    ("add", re.compile(r"\badd\b|\bplus\b|\+\s*\d", re.IGNORECASE)),
    ("divide", re.compile(r"\bdivide\b|÷|/\s*\d", re.IGNORECASE)),
    ("multiply", re.compile(r"\bmultiply\b|\btimes\b|×|\*\s*\d", re.IGNORECASE)),
    ("simplify", re.compile(r"\bsimplif|combine|collect", re.IGNORECASE)),
    ("substitute", re.compile(r"\bsubstitut|plug\s*in|check|verify", re.IGNORECASE)),
    ("isolate", re.compile(r"\bisolat|move|bring|rearrang", re.IGNORECASE)),
]


def _classify_step(step_text: str) -> str:
    """Return the detected operation name for a step, or 'unknown'."""
    for name, pattern in _OPERATION_PATTERNS:
        if pattern.search(step_text):
            return name
    # If the step contains an equation (=), treat it as an algebraic statement
    if "=" in step_text:
        return "equation_statement"
    return "unknown"


def _step_has_equation(step_text: str) -> bool:
    return "=" in step_text


def algebra_parser_tool(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Deterministic algebra step parser.

    Supports call_types:
      - parse_steps:  Parse student work, count steps, check equivalence
      - check_equivalence:  Verify two equation forms are equivalent
      - verify_solution_substitution:  Plug value into equation
    """
    call_type = str(payload.get("call_type", "parse_steps"))
    equation = str(payload.get("equation", "")).strip()
    variable = str(payload.get("target_variable", "x")).strip()
    student_work = str(payload.get("student_work", "")).strip()
    expected_answer = str(payload.get("expected_answer", "")).strip()

    if call_type == "verify_solution_substitution":
        proposed = payload.get("proposed_value")
        if proposed is None and expected_answer:
            # Try to extract numeric value from expected_answer like "x = 4"
            ans_match = re.search(r"=\s*([+-]?\d+\.?\d*)", expected_answer)
            if ans_match:
                proposed = float(ans_match.group(1))
        if proposed is None:
            return {"ok": False, "error": "proposed_value or expected_answer is required"}
        if not equation:
            return {"ok": False, "error": "equation is required"}
        try:
            proposed_f = float(proposed)
        except (TypeError, ValueError):
            return {"ok": False, "error": "proposed_value must be numeric"}
        result = _check_substitution(equation, variable, proposed_f)
        return {"ok": True, "substitution_check": result}

    if call_type == "check_equivalence":
        eq1 = equation
        eq2 = student_work or expected_answer
        if not eq1 or not eq2:
            return {"ok": False, "error": "two equations required for equivalence check"}
        p1 = _parse_linear_equation(eq1, variable)
        p2 = _parse_linear_equation(eq2, variable)
        if p1 is None or p2 is None:
            return {"ok": True, "equivalence_preserved": None, "error": "could not parse one or both equations"}
        sol1 = _solve_linear(*p1)
        sol2 = _solve_linear(*p2)
        if sol1 is None or sol2 is None:
            return {"ok": True, "equivalence_preserved": None, "error": "degenerate equation"}
        equiv = abs(sol1 - sol2) < 1e-9
        return {"ok": True, "equivalence_preserved": equiv}

    # Default: parse_steps
    if not student_work:
        return {
            "ok": True,
            "step_count": 0,
            "equivalence_preserved": True,
            "substitution_check": False,
            "method_recognized": None,
            "parsed_steps": [],
        }

    raw_steps = _detect_steps(student_work)

    # Parse the original equation to get expected solution
    original_parsed = _parse_linear_equation(equation, variable) if equation else None
    expected_solution = _solve_linear(*original_parsed) if original_parsed else None

    parsed_steps: list[dict[str, Any]] = []
    equations_seen: list[tuple[float, float, float]] = []
    if original_parsed:
        equations_seen.append(original_parsed)

    methods_detected: set[str] = set()
    all_equiv = True

    for step_text in raw_steps:
        operation = _classify_step(step_text)
        if operation not in ("unknown", "equation_statement"):
            methods_detected.add(operation)

        valid = True
        # If this step contains an equation, try to parse and check equivalence
        if _step_has_equation(step_text):
            step_parsed = _parse_linear_equation(step_text, variable)
            if step_parsed is not None and expected_solution is not None:
                step_sol = _solve_linear(*step_parsed)
                if step_sol is not None:
                    if abs(step_sol - expected_solution) > 1e-9:
                        valid = False
                        all_equiv = False
                    equations_seen.append(step_parsed)
                else:
                    valid = False
                    all_equiv = False

        parsed_steps.append({
            "raw": step_text,
            "operation": operation,
            "valid": valid,
        })

    # Count meaningful steps (not unknown text without equations)
    meaningful_steps = [
        s for s in parsed_steps
        if s["operation"] != "unknown" or _step_has_equation(s["raw"])
    ]
    step_count = len(meaningful_steps)

    # Check substitution if we have expected answer
    sub_check = False
    if expected_solution is not None and equation:
        sub_check = _check_substitution(equation, variable, expected_solution)

    # Determine method
    method = None
    if "subtract" in methods_detected or "add" in methods_detected:
        method = "balancing"
    if "isolate" in methods_detected:
        method = "isolation"
    if "substitute" in methods_detected:
        method = "substitution"
    if not method and methods_detected:
        method = sorted(methods_detected)[0]

    return {
        "ok": True,
        "step_count": step_count,
        "equivalence_preserved": all_equiv,
        "substitution_check": sub_check,
        "method_recognized": method,
        "parsed_steps": parsed_steps,
    }


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
