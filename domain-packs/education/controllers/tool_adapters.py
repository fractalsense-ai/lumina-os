from __future__ import annotations

import re
from typing import Any

# SymPy is used for Laws 3, 4, and 6 deterministic checks (system verification,
# polynomial structure, and model transcription). Graceful fallback: if SymPy is
# not installed, the dependent helpers return None and the null-cleanup block in
# runtime_adapters removes the key so the orchestrator skips that invariant.
try:
    import sympy as _sympy
except ImportError:
    _sympy = None  # type: ignore[assignment]


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


# ─────────────────────────────────────────────────────────────
# Helpers for the 6 new deterministic diagnostic checks
# ─────────────────────────────────────────────────────────────

# Regex patterns reused across helpers
_FRACTION_RE = re.compile(r"([+-]?\d+)\s*\/\s*([+-]?\d+)")
_INEQ_LINE_RE = re.compile(
    r"([+-]?\s*\d*\.?\d*x?)\s*([<>]=?|≤|≥)\s*([+-]?\s*\d+\.?\d*)"
)
_COEFF_BEFORE_VAR_RE = re.compile(r"([+-]?\s*\d*\.?\d*)\s*([a-zA-Z])")


def _detect_step_order(
    equation: str, student_work: str, variable: str = "x"
) -> bool | None:
    """Check whether the student removed the constant before dividing out the coefficient.

    For a two-step equation ax+b=c the correct Law-2 ordering is:
      1. Remove constant (add/subtract b) → ax = c-b
      2. Divide coefficient              → x  = (c-b)/a

    If the student divides the coefficient first (producing a fractional intermediate)
    the ordering is wrong. Returns None for single-step equations (no constant term).
    """
    parsed = _parse_linear_equation(equation, variable)
    if parsed is None:
        return None
    a, b, _ = parsed
    if abs(b) < 1e-12:
        # No constant term — single-step equation, ordering not applicable
        return None

    # Use both NLP sentence splitting and newline splitting so that
    # equations written one-per-line are always seen as separate steps.
    raw_steps = _detect_steps(student_work)
    line_steps = [l.strip() for l in student_work.splitlines() if l.strip()]
    all_steps = list(dict.fromkeys(raw_steps + line_steps))  # deduplicate, keep order
    for step_text in all_steps:
        if not _step_has_equation(step_text):
            continue
        step_parsed = _parse_linear_equation(step_text, variable)
        if step_parsed is None:
            continue
        s_a, s_b, _ = step_parsed
        if abs(s_b) < 1e-12 and abs(s_a) > 1e-12:
            # Constant removed first (e.g. 3x = 21) → correct
            return True
        if abs(abs(s_a) - 1.0) < 1e-9:
            # Coefficient divided first (e.g. x - 7/3 = 14/3) → wrong order
            return False
    return None


def _detect_inequality_direction(
    inequality: str, student_work: str, variable: str = "x"
) -> bool | None:
    """Check that the student flipped the inequality symbol when dividing by a negative.

    Scans student_work for lines containing inequality symbols. Finds the step
    where the coefficient of the variable transitions from |a|>1 to 1 (the divide
    step). If the divisor is negative the symbol must flip; if positive it must not.
    Returns None when no negative-divisor step is detected.
    """
    lines = student_work.splitlines()
    inequality_lines: list[tuple[str, float, str]] = []  # (raw, coeff, symbol)
    for line in lines:
        m = _INEQ_LINE_RE.search(line)
        if not m:
            continue
        lhs_str, symbol = m.group(1), m.group(2)
        cm = _COEFF_BEFORE_VAR_RE.search(lhs_str)
        if not cm:
            continue
        coeff_str = cm.group(1).replace(" ", "").strip()
        try:
            coeff = float(coeff_str) if coeff_str not in ("", "+", "-") else (
                1.0 if coeff_str in ("", "+") else -1.0
            )
        except ValueError:
            coeff = 1.0
        inequality_lines.append((line, coeff, symbol))

    if not inequality_lines:
        return None

    # Look for the transition step: |coeff| goes from >1 to ≈1
    for i in range(1, len(inequality_lines)):
        prev_coeff = inequality_lines[i - 1][1]
        curr_coeff = inequality_lines[i][1]
        if abs(abs(prev_coeff) - 1.0) > 1e-9 and abs(abs(curr_coeff) - 1.0) < 1e-9:
            divisor = curr_coeff / prev_coeff if abs(prev_coeff) > 1e-12 else None
            if divisor is None:
                return None
            prev_sym = inequality_lines[i - 1][2]
            curr_sym = inequality_lines[i][2]
            _FLIP: dict[str, str] = {
                "<": ">", ">": "<", "<=": ">=", ">=": "<=", "≤": "≥", "≥": "≤"
            }
            if divisor < 0:
                return _FLIP.get(prev_sym, "") == curr_sym
            else:
                return prev_sym == curr_sym
    return None


def _verify_solution_in_system(
    system_equations: list[str],
    x_variable: str,
    x_val: float,
    y_variable: str,
    y_val: float,
) -> bool | None:
    """Substitute (x_val, y_val) into every equation; return True iff all satisfied.

    Uses SymPy for symbolic evaluation. Returns None when SymPy is unavailable
    or any equation fails to parse.
    """
    if _sympy is None:
        return None
    if not system_equations:
        return None
    try:
        x_sym = _sympy.Symbol(x_variable)
        y_sym = _sympy.Symbol(y_variable)
        for eq_str in system_equations:
            if "=" not in eq_str:
                return None
            lhs_str, rhs_str = eq_str.split("=", 1)
            expr = _sympy.sympify(lhs_str) - _sympy.sympify(rhs_str)
            result = expr.subs([(x_sym, x_val), (y_sym, y_val)])
            if _sympy.simplify(result) != 0:
                return False
        return True
    except Exception:
        return None


def _extract_slope_value(student_work: str) -> float | None:
    """Extract the first slope value from student work.

    Recognises fraction notation (e.g. '2/3', '-1/4') and keyword forms
    ('slope = 2', 'm = -3/4'). Returns a float or None.
    """
    # Explicit keyword form: slope = X  or  m = X
    kw_match = re.search(
        r"\b(?:slope|m)\s*(?:[=:]|\bis\b)\s*([+-]?\d+\.?\d*(?:/[+-]?\d+\.?\d*)?)",
        student_work,
        re.IGNORECASE,
    )
    if kw_match:
        raw = kw_match.group(1)
        if "/" in raw:
            num, den = raw.split("/", 1)
            try:
                return float(num) / float(den)
            except (ValueError, ZeroDivisionError):
                return None
        try:
            return float(raw)
        except ValueError:
            return None

    # Fraction in context: first fraction that looks like rise/run
    frac_match = _FRACTION_RE.search(student_work)
    if frac_match:
        try:
            return float(frac_match.group(1)) / float(frac_match.group(2))
        except (ValueError, ZeroDivisionError):
            return None
    return None


def _check_polynomial_structure_sympy(
    original_expr: str, student_expr: str
) -> bool | None:
    """Return True iff both expressions expand to the same polynomial via SymPy.

    Returns None when SymPy is unavailable or either expression is unparseable.
    """
    if _sympy is None:
        return None
    try:
        orig = _sympy.expand(_sympy.sympify(original_expr))
        student = _sympy.expand(_sympy.sympify(student_expr))
        return bool(orig == student)
    except Exception:
        return None


_MODEL_PARAM_BUILDERS: dict[str, str] = {
    # Each value is a Python expression using model_params keys; evaluated with
    # sympy.sympify on the assembled string.  The result is the canonical LHS
    # (i.e. canonical_lhs - canonical_rhs set equal to 0).
    "area_product":       "({factor1}) * ({factor2}) - {result}",
    "rate_time_distance": "{rate} * {time} - {distance}",
    "linear_growth":      "{initial} + {rate} * {time_var} - {total}",
}


def _build_and_check_model_sympy(
    model_params: dict[str, Any], student_equation_str: str, variable: str = "x"
) -> bool | None:
    """Build a canonical expression from model_params and compare to student's equation.

    The DA supplies *parameters* (a recipe), not the equation itself.  SymPy
    assembles the canonical form at evaluation time so the student cannot look up
    the answer.  Anti-cheat: student never sees the canonical form.

    Returns True iff student_equation_str is algebraically identical to the
    canonical form.  Returns None on any parse error or missing SymPy.
    """
    if _sympy is None:
        return None
    model_type = str(model_params.get("type", ""))
    template = _MODEL_PARAM_BUILDERS.get(model_type)
    if template is None:
        return None
    try:
        canonical_str = template.format(**{k: v for k, v in model_params.items() if k != "type"})
        canonical = _sympy.sympify(canonical_str)
    except Exception:
        return None
    if "=" not in student_equation_str:
        return None
    try:
        s_lhs, s_rhs = student_equation_str.split("=", 1)
        student_expr = _sympy.sympify(s_lhs) - _sympy.sympify(s_rhs)
        return bool(_sympy.simplify(student_expr - canonical) == 0)
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────
# Public tool: algebra_parser_tool  (unified dispatch)
# ─────────────────────────────────────────────────────────────

def algebra_parser_tool(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Deterministic algebra step parser.

    Supports call_types:
      - parse_steps:  Parse student work, count steps, check equivalence
      - check_equivalence:  Verify two equation forms are equivalent
      - verify_solution_substitution:  Plug value into equation
      - check_step_order:  Law 2 — constant removed before coefficient divided?
      - check_inequality_direction:  Law 2 — inequality symbol flipped correctly?
      - check_system_verification:  Law 3 — (x,y) satisfies all system equations?
      - check_slope_computation:  Law 5 — correct slope extracted from student work?
      - check_polynomial_structure:  Law 4 — student expression expands identically?
      - check_model_transcription:  Law 6 — student equation matches model_params canonical?
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

    if call_type == "check_step_order":
        result = _detect_step_order(equation, student_work, variable)
        return {"ok": True, "reversibility_order_correct": result}

    if call_type == "check_inequality_direction":
        ineq = str(payload.get("inequality", equation)).strip()
        result = _detect_inequality_direction(ineq, student_work, variable)
        return {"ok": True, "inequality_direction_correct": result}

    if call_type == "check_system_verification":
        system_eqs = payload.get("system_equations") or []
        x_var = str(payload.get("x_variable", "x"))
        y_var = str(payload.get("y_variable", "y"))
        x_val = payload.get("x_val")
        y_val = payload.get("y_val")
        if x_val is None or y_val is None:
            return {"ok": False, "error": "x_val and y_val are required"}
        try:
            x_val_f = float(x_val)
            y_val_f = float(y_val)
        except (TypeError, ValueError):
            return {"ok": False, "error": "x_val and y_val must be numeric"}
        result = _verify_solution_in_system(system_eqs, x_var, x_val_f, y_var, y_val_f)
        return {"ok": True, "substitution_valid": result}

    if call_type == "check_slope_computation":
        correct_slope = payload.get("correct_slope")
        table_data = payload.get("table_data")
        extracted = _extract_slope_value(student_work)
        if extracted is None:
            return {"ok": True, "relationship_correctly_mapped": None, "extracted_slope": None}
        # Compute correct slope from table_data if not provided explicitly
        if correct_slope is None and table_data and len(table_data) >= 2:
            try:
                dx = float(table_data[1]["x"]) - float(table_data[0]["x"])
                dy = float(table_data[1]["y"]) - float(table_data[0]["y"])
                correct_slope = dy / dx if abs(dx) > 1e-12 else None
            except (KeyError, TypeError, ValueError, ZeroDivisionError):
                correct_slope = None
        if correct_slope is None:
            return {"ok": True, "relationship_correctly_mapped": None, "extracted_slope": extracted}
        match = abs(extracted - float(correct_slope)) < 1e-9
        return {"ok": True, "relationship_correctly_mapped": match, "extracted_slope": extracted}

    if call_type == "check_polynomial_structure":
        original_expr = str(payload.get("original_expression", "")).strip()
        student_expr = str(payload.get("student_expression", student_work)).strip()
        if not original_expr or not student_expr:
            return {"ok": False, "error": "original_expression and student_expression are required"}
        result = _check_polynomial_structure_sympy(original_expr, student_expr)
        return {"ok": True, "structure_preserved": result}

    if call_type == "check_model_transcription":
        model_params = payload.get("model_params")
        student_eq = str(payload.get("student_equation", student_work)).strip()
        if not model_params:
            return {"ok": True, "model_accurately_transcribed": None}
        result = _build_and_check_model_sympy(model_params, student_eq, variable)
        return {"ok": True, "model_accurately_transcribed": result}

    # Default: parse_steps
    if not student_work:
        return {
            "ok": True,
            "step_count": 0,
            "equivalence_preserved": None,
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
    any_equation_parsed = False

    for step_text in raw_steps:
        operation = _classify_step(step_text)
        if operation not in ("unknown", "equation_statement"):
            methods_detected.add(operation)

        valid = True
        # If this step contains an equation, try to parse and check equivalence
        if _step_has_equation(step_text):
            step_parsed = _parse_linear_equation(step_text, variable)
            if step_parsed is not None and expected_solution is not None:
                any_equation_parsed = True
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

    # equivalence_preserved is True/False only when we successfully parsed at
    # least one equation step; None means "indeterminate" (all steps were
    # unparseable prose or complex notation the parser doesn't handle).
    equiv_result: bool | None = all_equiv if any_equation_parsed else None

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
        "equivalence_preserved": equiv_result,
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
