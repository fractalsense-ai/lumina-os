"""Turn-data enrichment: SLM physics context, RAG grounding, telemetry.

These stages augment ``turn_data`` with additional context before the
orchestrator processes the turn.

Pre-enrichment (RAG retrieval) runs *before* turn interpretation so the
interpreter has domain context available.  Post-enrichment (SLM physics
context, telemetry) runs *after* interpretation once ``turn_data`` is
populated.

See also:
    docs/7-concepts/slm-compute-distribution.md
    docs/7-concepts/prompt-packet-assembly.md
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("lumina-api")


def pre_enrich_rag(
    input_text: str,
    resolved_domain_id: str,
    *,
    module_key: str | None = None,
) -> list[dict[str, Any]]:
    """Retrieve RAG context before turn interpretation.

    Returns a list of RAG hit dicts (may be empty).  This step only
    needs the raw ``input_text`` and ``resolved_domain_id`` — it has no
    dependency on ``turn_data``.
    """
    try:
        from lumina.core.nlp import search_domain as _search_domain

        _rag_hits = _search_domain(input_text, resolved_domain_id, k=3)
        if module_key and _rag_hits:
            _mod_seg = f"/modules/{module_key}/"
            _rag_hits = [
                h for h in _rag_hits
                if "/modules/" not in h.chunk.source_path
                or _mod_seg in h.chunk.source_path
            ]
        if _rag_hits:
            return [
                {
                    "text": hit.chunk.text[:500],
                    "source": hit.chunk.source_path,
                    "heading": hit.chunk.heading,
                    "score": round(hit.score, 4),
                }
                for hit in _rag_hits
            ]
    except Exception:
        pass  # Vector retrieval is optional — never blocks the pipeline
    return []


def enrich_turn_data(
    turn_data: dict[str, Any],
    input_text: str,
    domain_physics: dict[str, Any],
    glossary: list[dict[str, Any]],
    resolved_domain_id: str,
    actor_elapsed: float | None,
    deterministic_response: bool,
    *,
    module_key: str | None = None,
    slm_available_fn,
    slm_interpret_physics_context_fn,
    rag_context: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Enrich *turn_data* with SLM context, RAG grounding, and latency.

    If *rag_context* was already retrieved by ``pre_enrich_rag()``, it is
    injected directly.  Otherwise RAG retrieval runs inline (backward
    compat).

    Mutates and returns *turn_data*.
    """
    # ── SLM physics interpretation (context compression) ─────
    if not deterministic_response and slm_available_fn():
        slm_context = slm_interpret_physics_context_fn(
            incoming_signals=turn_data,
            domain_physics=domain_physics,
            glossary=glossary,
            actor_input=input_text,
        )
        turn_data["_slm_context"] = slm_context

    # ── Per-domain vector retrieval (RAG grounding) ───────────
    if rag_context is not None:
        # Pre-enrichment already ran; inject directly.
        if rag_context:
            turn_data["_rag_context"] = rag_context
    else:
        # Backward compat: inline retrieval if caller didn't pre-enrich.
        try:
            from lumina.core.nlp import search_domain as _search_domain

            _rag_hits = _search_domain(input_text, resolved_domain_id, k=3)
            if module_key and _rag_hits:
                _mod_seg = f"/modules/{module_key}/"
                _rag_hits = [
                    h for h in _rag_hits
                    if "/modules/" not in h.chunk.source_path
                    or _mod_seg in h.chunk.source_path
                ]
            if _rag_hits:
                turn_data["_rag_context"] = [
                    {
                        "text": hit.chunk.text[:500],
                        "source": hit.chunk.source_path,
                        "heading": hit.chunk.heading,
                        "score": round(hit.score, 4),
                    }
                    for hit in _rag_hits
                ]
        except Exception:
            pass  # Vector retrieval is optional — never blocks the pipeline

    # ── Response latency field ────────────────────────────────
    if actor_elapsed is not None:
        turn_data["response_latency_sec"] = actor_elapsed

    # ── Sliding-window daemon telemetry ───────────────────────
    try:
        from lumina.daemon import resource_monitor as _rm

        _status = _rm.get_status()
        if _status.get("enabled") and _status.get("telemetry_window"):
            turn_data["_system_telemetry"] = _status["telemetry_window"]
    except Exception:
        pass  # Telemetry is optional

    return turn_data
