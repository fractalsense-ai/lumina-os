"""Template domain — Deterministic NLP pre-interpreter (Phase A).

Runs lightweight pattern-based extractors on entity messages BEFORE
the LLM turn interpreter, producing structured anchors that are injected
into the LLM prompt as grounding context.

Phase A extractors are deterministic — they use regex, keyword matching,
or simple heuristics.  Their output is trusted over SLM estimates when
both produce a value for the same field.

HOW TO CUSTOMISE:
  1. Add extractor functions below (see examples).
  2. Wire them into `pre_interpret()` which the runtime calls.
  3. Return a dict of anchors — the runtime merges these into the
     evidence before calling the LLM turn interpreter.

WHEN TO USE:
  - Any field that can be reliably extracted with a regex or keyword list
  - Safety-critical fields (the SLM should not be the sole judge)
  - Domain-specific structured inputs (codes, IDs, measurements)

WHEN NOT TO USE:
  - Intent classification that requires nuance → leave to the SLM
  - Free-text sentiment → leave to the SLM
"""

from __future__ import annotations

import re
from typing import Any


# ── Example: keyword-based extractor ─────────────────────────────────

_HELP_KEYWORDS = re.compile(
    r"\b(help|stuck|confused|don'?t understand|hint)\b",
    re.IGNORECASE,
)

_FRUSTRATION_KEYWORDS = re.compile(
    r"\b(frustrated|angry|annoyed|this is stupid|hate this|give up|quit)\b",
    re.IGNORECASE,
)


def extract_help_request(input_text: str) -> dict[str, Any]:
    """Detect whether the entity is asking for help.

    TODO: Replace or extend with your domain's help-detection patterns.
    """
    return {"help_requested": bool(_HELP_KEYWORDS.search(input_text))}


def extract_frustration_markers(input_text: str) -> dict[str, Any]:
    """Count frustration-related keywords.

    TODO: Replace with domain-appropriate markers.
    """
    matches = _FRUSTRATION_KEYWORDS.findall(input_text)
    return {"frustration_marker_count": len(matches)}


# ── Master pre-interpreter entry point ───────────────────────────────

def pre_interpret(
    input_text: str,
    task_context: dict[str, Any],
) -> dict[str, Any]:
    """Run all Phase A extractors and return merged anchors.

    The runtime calls this before the LLM turn interpreter.  Returned
    keys are injected as grounding context into the LLM prompt and
    override SLM estimates when both produce the same field.

    Args:
        input_text:   Raw message from the entity.
        task_context: Current task context dict (may contain expected
                      answers, active problem state, etc.).

    Returns:
        Dict of deterministic anchor values.

    TODO: Wire in your domain-specific extractors below.
    """
    anchors: dict[str, Any] = {}

    anchors.update(extract_help_request(input_text))
    anchors.update(extract_frustration_markers(input_text))

    # TODO: Add more extractors:
    # anchors.update(extract_measurement(input_text, task_context))
    # anchors.update(extract_entity_id(input_text))

    return anchors
