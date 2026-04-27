"""Governance-specific NLP pre-interpreter for operator modules.

Detects governance command-discovery patterns, frustration signals, and
hint requests.  Does NOT run math vocabulary analysis (off-task ratio is
always 0.0 for governance sessions unless a command pattern is matched).
"""
from __future__ import annotations

import re
from typing import Any

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
    """Detect whether the operator is asking for help."""
    return {"hint_used": bool(_HINT_RE.search(input_text))}


# ── Governance command-discovery extractor ───────────────────

_GOV_COMMAND_DISCOVERY_RE = re.compile(
    r"\b(?:what|which|show|list|get|display|view|check)\b.*\b(?:command|commands|operation|operations)\b"
    r"|\bcommands?\s+(?:available|do\s+i\s+have|can\s+i|are\s+there)\b"
    r"|\b(?:available\s+commands?)\b",
    re.IGNORECASE,
)
_GOV_USER_LISTING_RE = re.compile(
    r"\b(?:what|which|show|list|get|display|view|who)\b.*\b(?:user|users|student|students|teacher|teachers)\b",
    re.IGNORECASE,
)
_GOV_MODULE_LISTING_RE = re.compile(
    r"\b(?:what|which|show|list|get|display|view)\b.*\b(?:module|modules)\b",
    re.IGNORECASE,
)
_GOV_ESCALATION_LISTING_RE = re.compile(
    r"\b(?:what|which|show|list|get|display|view|check)\b.*\b(?:escalation|escalations)\b",
    re.IGNORECASE,
)

_GOV_PATTERNS: list[tuple[re.Pattern[str], str, str]] = [
    (_GOV_COMMAND_DISCOVERY_RE, "admin_command", "list_commands"),
    (_GOV_USER_LISTING_RE, "admin_command", "list_users"),
    (_GOV_MODULE_LISTING_RE, "admin_command", "list_modules"),
    (_GOV_ESCALATION_LISTING_RE, "admin_command", "list_escalations"),
]


def extract_governance_signals(input_text: str) -> dict[str, Any]:
    """Detect governance command-discovery patterns in operator messages."""
    for pattern, qtype, operation in _GOV_PATTERNS:
        if pattern.search(input_text):
            return {
                "query_type": qtype,
                "suggested_operation": operation,
                "off_task_ratio": 0.0,
            }
    return {
        "query_type": None,
        "suggested_operation": None,
    }


# ── Main entry point ────────────────────────────────────────

def governance_nlp_preprocess(input_text: str, task_context: dict[str, Any]) -> dict[str, Any]:
    """Run governance-specific NLP extractors and return a partial evidence dict.

    Parameters
    ----------
    input_text : str
        Raw operator message.
    task_context : dict
        Current task context (unused for governance but kept for interface
        compatibility).

    Returns
    -------
    dict
        Partial evidence dict with ``_nlp_anchors`` metadata list.
    """
    frustration_result = extract_frustration_markers(input_text)
    hint_result = extract_hint_request(input_text)
    gov_result = extract_governance_signals(input_text)

    evidence: dict[str, Any] = {}
    anchors: list[dict[str, Any]] = []

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

    # Governance signals
    if gov_result.get("query_type") is not None:
        evidence["query_type"] = gov_result["query_type"]
        evidence["suggested_operation"] = gov_result["suggested_operation"]
        evidence["off_task_ratio"] = gov_result.get("off_task_ratio", 0.0)
        anchors.append({
            "field": "query_type",
            "value": gov_result["query_type"],
            "confidence": 0.95,
            "detail": f"governance pattern → {gov_result['suggested_operation']}",
        })

    evidence["_nlp_anchors"] = anchors
    return evidence
