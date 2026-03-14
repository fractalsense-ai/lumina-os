"""
interpreter.py — SLM-driven document interpretation for the ingestion pipeline.

Generates one or more structured YAML interpretation variants from
extracted document text, using the SLM Extractor role.  When the source
material is unambiguous, a single ``default`` interpretation is returned.
When ambiguous, up to ``max_interpretations`` variants are generated
(strict, loose, hierarchical) with confidence scores and notes.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

log = logging.getLogger("lumina-ingestion")


# ── SLM Extractor system prompt ───────────────────────────────

_EXTRACTOR_SYSTEM_PROMPT = (
    "You are a structured document interpreter for a domain-driven orchestration system. "
    "Given raw document text and domain context (domain physics, glossary, module boundaries), "
    "produce one or more YAML interpretations that map the document content into the domain's "
    "module structure.\n\n"
    "Rules:\n"
    "1. If the content maps unambiguously to a single module structure, return ONE interpretation "
    "   with label 'default' and confidence >= 0.9.\n"
    "2. If the content is ambiguous (multiple valid module structures, unclear prerequisites, "
    "   uncertain boundaries), return 2-3 interpretations:\n"
    "   - 'strict': Most conservative mapping with tightest prerequisite chains.\n"
    "   - 'loose': Most permissive mapping with fewest constraints.\n"
    "   - 'hierarchical': Maps content as nested submodules when applicable.\n"
    "3. Each interpretation must include valid YAML content, a confidence score (0-1), "
    "   and ambiguity_notes explaining the interpretation choice.\n"
    "4. Extract glossary terms, invariants, standing orders, and artifacts where identifiable.\n"
    "5. Never fabricate domain knowledge — flag gaps as ambiguity_notes.\n\n"
    "Respond in JSON only with this structure:\n"
    "{\n"
    '  "interpretations": [\n'
    "    {\n"
    '      "label": "default|strict|loose|hierarchical",\n'
    '      "yaml_content": "...valid YAML string...",\n'
    '      "confidence": 0.0-1.0,\n'
    '      "ambiguity_notes": "explanation of interpretation choices"\n'
    "    }\n"
    "  ]\n"
    "}"
)


def generate_interpretations(
    extracted_text: str,
    domain_physics: dict[str, Any],
    glossary: list[dict[str, Any]] | None = None,
    module_context: dict[str, Any] | None = None,
    max_interpretations: int = 3,
    call_slm_fn: Any = None,
) -> list[dict[str, Any]]:
    """Generate SLM interpretation variants from extracted document text.

    Parameters
    ----------
    extracted_text:
        Plain text extracted from the uploaded document.
    domain_physics:
        The target domain's physics document (invariants, standing orders, etc.).
    glossary:
        Domain glossary entries for contextual grounding.
    module_context:
        Optional context about the target module (id, version, existing structure).
    max_interpretations:
        Maximum number of variants to generate (from ingestion_config).
    call_slm_fn:
        Callable to invoke the SLM.  If None, uses ``lumina.core.slm.call_slm``.

    Returns
    -------
    list[dict]
        List of interpretation dicts with keys: id, label, yaml_content,
        confidence, ambiguity_notes.
    """
    if call_slm_fn is None:
        from lumina.core.slm import call_slm
        call_slm_fn = call_slm

    # Build context payload for SLM
    context = {
        "document_text": extracted_text[:8000],  # Truncate for SLM context window
        "domain_id": domain_physics.get("id", ""),
        "domain_description": domain_physics.get("description", ""),
        "existing_invariants": [
            inv.get("id") for inv in (domain_physics.get("invariants") or [])
        ],
        "existing_standing_orders": [
            so.get("id") for so in (domain_physics.get("standing_orders") or [])
        ],
        "glossary_terms": [
            entry.get("term") for entry in (glossary or [])
        ],
        "max_interpretations": max_interpretations,
    }
    if module_context:
        context["target_module"] = module_context

    user_payload = json.dumps(context, indent=2, ensure_ascii=False)

    try:
        raw = call_slm_fn(system=_EXTRACTOR_SYSTEM_PROMPT, user=user_payload)

        # Strip markdown fences if present
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1]
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]

        result = json.loads(text.strip())
        if not isinstance(result, dict):
            return _fallback_interpretation(extracted_text)

        raw_interps = result.get("interpretations") or []
        if not isinstance(raw_interps, list) or len(raw_interps) == 0:
            return _fallback_interpretation(extracted_text)

        interpretations: list[dict[str, Any]] = []
        for interp in raw_interps[:max_interpretations]:
            interpretations.append({
                "id": str(uuid.uuid4()),
                "label": interp.get("label", "default"),
                "yaml_content": str(interp.get("yaml_content", "")),
                "confidence": float(interp.get("confidence", 0.5)),
                "ambiguity_notes": str(interp.get("ambiguity_notes", "")),
            })

        return interpretations

    except Exception as exc:
        log.warning("SLM interpretation failed (%s); returning fallback", exc)
        return _fallback_interpretation(extracted_text)


def _fallback_interpretation(text: str) -> list[dict[str, Any]]:
    """Return a single default interpretation when SLM fails."""
    return [
        {
            "id": str(uuid.uuid4()),
            "label": "default",
            "yaml_content": f"# SLM extraction unavailable — raw text preserved\n"
                            f"# Manual review required\n"
                            f"raw_content: |\n"
                            + "\n".join(f"  {line}" for line in text[:4000].split("\n")),
            "confidence": 0.0,
            "ambiguity_notes": "SLM was unavailable; raw text preserved for manual review.",
        }
    ]
