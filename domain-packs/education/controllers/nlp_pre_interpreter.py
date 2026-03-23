"""Deterministic NLP pre-interpreter for education domain.

Runs lightweight pattern-based extractors on student messages BEFORE
the LLM turn interpreter, producing structured anchors that are injected
into the LLM prompt as grounding context.
"""

from __future__ import annotations

import re
from typing import Any

# ── Answer-match extractor ──────────────────────────────────

_ANSWER_X_EQ = re.compile(r"[A-Za-z]\s*=\s*([+-]?\d+(?:\.\d+)?)\s*$", re.MULTILINE)
_ANSWER_IS = re.compile(r"(?:answer\s+is|equals?)\s+([+-]?\d+(?:\.\d+)?)", re.IGNORECASE)
_BARE_NUMBER = re.compile(r"^\s*([+-]?\d+(?:\.\d+)?)\s*$")


def _try_parse_number(s: str) -> float | None:
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def extract_answer_match(
    input_text: str,
    expected_answer: str | None,
) -> dict[str, Any]:
    """Extract the student's numeric answer and compare to expected."""
    candidates: list[str] = []

    for pattern in (_ANSWER_X_EQ, _ANSWER_IS, _BARE_NUMBER):
        for m in pattern.finditer(input_text):
            candidates.append(m.group(1))

    if not candidates:
        return {"correctness": None, "confidence": 0.0}

    student_value = _try_parse_number(candidates[-1])
    if student_value is None:
        return {"correctness": None, "confidence": 0.0}

    if expected_answer is None:
        return {
            "correctness": None,
            "confidence": 0.0,
            "extracted_answer": student_value,
        }

    expected_value = _try_parse_number(expected_answer)
    if expected_value is None:
        # Try extracting numeric value from forms like "x = 4"
        eq_match = re.search(r"=\s*([+-]?\d+\.?\d*)", expected_answer)
        if eq_match:
            expected_value = _try_parse_number(eq_match.group(1))
    if expected_value is None:
        return {
            "correctness": None,
            "confidence": 0.0,
            "extracted_answer": student_value,
        }

    if abs(student_value - expected_value) < 1e-9:
        return {
            "correctness": "correct",
            "confidence": 0.95,
            "extracted_answer": student_value,
        }
    return {
        "correctness": "incorrect",
        "confidence": 0.90,
        "extracted_answer": student_value,
    }


# ── Frustration-marker extractor ────────────────────────────

_FRUSTRATION_KEYWORDS = [
    r"i\s+don'?t\s+get\s+it",
    r"i\s+don'?t\s+understand",
    r"i\s+can'?t",
    r"i\s+give\s+up",
    r"this\s+is\s+stupid",
    r"this\s+is\s+hard",
    r"this\s+is\s+impossible",
    r"this\s+makes\s+no\s+sense",
    r"\bugh+\b",
    r"\bargh+\b",
]
_FRUSTRATION_RE = re.compile(
    "|".join(f"({p})" for p in _FRUSTRATION_KEYWORDS),
    re.IGNORECASE,
)
_EXCESSIVE_PUNCT = re.compile(r"[!?]{3,}")


def extract_frustration_markers(input_text: str) -> dict[str, Any]:
    """Detect frustration signals via keywords, caps, and punctuation."""
    markers: list[str] = []

    for m in _FRUSTRATION_RE.finditer(input_text):
        markers.append(m.group(0).strip())

    alpha_chars = [c for c in input_text if c.isalpha()]
    if len(alpha_chars) >= 4:
        upper_ratio = sum(1 for c in alpha_chars if c.isupper()) / len(alpha_chars)
        if upper_ratio > 0.5:
            markers.append("ALL_CAPS")

    if _EXCESSIVE_PUNCT.search(input_text):
        markers.append("excessive_punctuation")

    stripped = input_text.strip()
    if len(stripped) < 5 and re.search(r"[!?]", stripped):
        markers.append("short_frustrated")

    return {
        "frustration_marker_count": len(markers),
        "markers": markers,
    }


# ── Hint-request extractor ──────────────────────────────────

_HINT_PATTERNS = [
    r"give\s+me\s+a\s+hint",
    r"hint\s+please",
    r"can\s+i\s+(?:get|have)\s+a\s+hint",
    r"\bhelp\s+me\b",
    r"\bhelp\b",
    r"i'?m\s+stuck",
    r"i\s+need\s+help",
    r"what\s+(?:do\s+i\s+do|should\s+i\s+do)",
    r"how\s+do\s+i",
]
_HINT_RE = re.compile("|".join(f"({p})" for p in _HINT_PATTERNS), re.IGNORECASE)


def extract_hint_request(input_text: str) -> dict[str, Any]:
    """Detect whether the student is asking for a hint."""
    return {"hint_used": bool(_HINT_RE.search(input_text))}


# ── Off-task ratio extractor ────────────────────────────────

_MATH_VOCAB = frozenset([
    "add", "subtract", "multiply", "divide", "plus", "minus", "times",
    "equals", "equal", "equation", "solve", "solution", "variable",
    "both", "sides", "side", "isolate", "simplify", "combine",
    "coefficient", "constant", "term", "factor", "distribute",
    "inverse", "operation", "substitution", "substitute", "check",
    "verify", "answer", "result", "step", "work", "show",
    "linear", "quadratic", "expression",
])
_NUMBER_RE = re.compile(r"^[+-]?\d+(?:\.\d+)?$")
_OPERATOR_RE = re.compile(r"^[+\-*/=<>^]+$")
_VARIABLE_RE = re.compile(r"^[a-zA-Z]$")
# Fraction / division-step tokens: "72/8", "8/8x", "9/9x", "2*3x", "2*x"
_FRACTION_TOKEN_RE = re.compile(r"^\d+(?:\.\d+)?[*/]\d*(?:\.\d+)?[a-zA-Z]?$")
# Coefficient-variable tokens written without a space: "8x", "4x", "2x"
_COEFF_TOKEN_RE = re.compile(r"^\d+[a-zA-Z]$")


def _is_math_token(token: str) -> bool:
    lower = token.lower().rstrip(".,;:!?")
    if not lower:
        return False
    if lower in _MATH_VOCAB:
        return True
    if _NUMBER_RE.match(lower):
        return True
    if _OPERATOR_RE.match(lower):
        return True
    if _VARIABLE_RE.match(lower):
        return True
    if _FRACTION_TOKEN_RE.match(lower):
        return True
    if _COEFF_TOKEN_RE.match(lower):
        return True
    return False


def extract_off_task_ratio(input_text: str) -> dict[str, Any]:
    """Estimate how off-task a message is via math vocabulary overlap."""
    tokens = input_text.split()
    if not tokens:
        return {"off_task_ratio": 0.0}

    math_count = sum(1 for t in tokens if _is_math_token(t))
    ratio = 1.0 - (math_count / len(tokens))
    return {"off_task_ratio": max(0.0, min(1.0, round(ratio, 3)))}


# ── Main entry point ────────────────────────────────────────

def nlp_preprocess(input_text: str, task_context: dict[str, Any]) -> dict[str, Any]:
    """Run all NLP extractors and return a partial evidence dict.

    Parameters
    ----------
    input_text : str
        Raw student message.
    task_context : dict
        Current task context including ``current_problem`` with
        ``expected_answer``.

    Returns
    -------
    dict
        Partial evidence dict with ``_nlp_anchors`` metadata list.
    """
    current_problem = task_context.get("current_problem") or {}
    expected_answer = current_problem.get("expected_answer")

    answer_result = extract_answer_match(input_text, expected_answer)
    frustration_result = extract_frustration_markers(input_text)
    hint_result = extract_hint_request(input_text)
    off_task_result = extract_off_task_ratio(input_text)

    evidence: dict[str, Any] = {}
    anchors: list[dict[str, Any]] = []

    # Answer match
    if answer_result["correctness"] is not None:
        evidence["correctness"] = answer_result["correctness"]
        anchors.append({
            "field": "correctness",
            "value": answer_result["correctness"],
            "confidence": answer_result["confidence"],
            "detail": f"matched answer \"{answer_result.get('extracted_answer')}\" to expected \"{expected_answer}\"",
        })

    # Frustration
    evidence["frustration_marker_count"] = frustration_result["frustration_marker_count"]
    if frustration_result["frustration_marker_count"] > 0:
        anchors.append({
            "field": "frustration_marker_count",
            "value": frustration_result["frustration_marker_count"],
            "confidence": 1.0,
            "detail": ", ".join(frustration_result["markers"]),
        })

    # Hint
    evidence["hint_used"] = hint_result["hint_used"]
    if hint_result["hint_used"]:
        anchors.append({
            "field": "hint_used",
            "value": True,
            "confidence": 0.90,
        })

    # Off-task ratio
    evidence["off_task_ratio"] = off_task_result["off_task_ratio"]
    anchors.append({
        "field": "off_task_ratio",
        "value": off_task_result["off_task_ratio"],
        "confidence": 0.80,
    })

    evidence["_nlp_anchors"] = anchors
    return evidence
