"""Assistant domain — NLP pre-interpreter (Phase A deterministic extraction).

Runs before the LLM turn interpreter. Extracts keywords, locations, dates,
and intent hints from the raw user message using deterministic rules.
Results are merged into the LLM prompt context to improve classification.
"""

from __future__ import annotations

import re
from typing import Any

# Keyword → intent mapping (deterministic fast-path).
_INTENT_KEYWORDS: dict[str, list[str]] = {
    "weather": [
        "weather", "forecast", "temperature", "rain", "snow", "sunny",
        "cloudy", "wind", "humidity", "degrees", "celsius", "fahrenheit",
    ],
    "calendar": [
        "schedule", "calendar", "appointment", "meeting", "event",
        "reminder", "when is", "what time", "book", "reschedule", "cancel event",
    ],
    "search": [
        "search", "look up", "find", "what is", "who is", "define",
        "how does", "tell me about", "explain", "information about",
    ],
    "creative": [
        "write", "story", "poem", "creative", "brainstorm", "rewrite",
        "rephrase", "compose", "draft", "fiction", "imagine",
    ],
    "planning": [
        "plan", "todo", "to-do", "task list", "organize", "prioritize",
        "goal", "roadmap", "milestone", "project", "checklist",
    ],
}

# Simple date patterns.
_DATE_PATTERN = re.compile(
    r"\b("
    r"today|tomorrow|yesterday|"
    r"next\s+(?:week|month|monday|tuesday|wednesday|thursday|friday|saturday|sunday)|"
    r"\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?|"
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\s+\d{1,2}"
    r")\b",
    re.IGNORECASE,
)

# Simple location patterns (after "in", "at", "for").
_LOCATION_PATTERN = re.compile(
    r"\b(?:in|at|for|near)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)",
)


def nlp_preprocess(
    input_text: str,
    task_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Extract deterministic signals from raw user text.

    Returns a dict of extracted features that the turn interpreter
    can use to improve LLM classification accuracy.
    """
    text_lower = input_text.lower()
    result: dict[str, Any] = {}

    # Intent hint — scan keywords
    intent_scores: dict[str, int] = {}
    for intent, keywords in _INTENT_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in text_lower)
        if score > 0:
            intent_scores[intent] = score

    if intent_scores:
        best_intent = max(intent_scores, key=intent_scores.get)  # type: ignore[arg-type]
        result["intent_hint"] = best_intent
        result["intent_confidence"] = "high" if intent_scores[best_intent] >= 2 else "low"

    # Date extraction
    dates = _DATE_PATTERN.findall(input_text)
    if dates:
        result["extracted_dates"] = dates

    # Location extraction
    locations = _LOCATION_PATTERN.findall(input_text)
    if locations:
        result["extracted_locations"] = locations

    # Safety signal — quick heuristic (framework handles real safety)
    result["empty_input"] = len(input_text.strip()) == 0

    return result
