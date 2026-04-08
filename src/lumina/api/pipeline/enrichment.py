"""Turn-data enrichment: SLM physics context, RAG grounding, telemetry.

These stages augment ``turn_data`` with additional context before the
orchestrator processes the turn.

See also:
    docs/7-concepts/slm-compute-distribution.md
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("lumina-api")


def enrich_turn_data(
    turn_data: dict[str, Any],
    input_text: str,
    domain_physics: dict[str, Any],
    glossary: list[dict[str, Any]],
    resolved_domain_id: str,
    actor_elapsed: float | None,
    deterministic_response: bool,
    *,
    slm_available_fn,
    slm_interpret_physics_context_fn,
) -> dict[str, Any]:
    """Enrich *turn_data* with SLM context, RAG grounding, and latency.

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
    try:
        from lumina.core.nlp import search_domain as _search_domain

        _rag_hits = _search_domain(input_text, resolved_domain_id, k=3)
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
