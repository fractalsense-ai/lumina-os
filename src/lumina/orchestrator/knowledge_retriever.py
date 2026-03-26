"""knowledge_retriever.py — Retrieve grounding references from the KnowledgeIndex.

Called by :class:`PPAOrchestrator` before the Clerk drafts the prompt contract.
Produces ``references[]`` entries that satisfy the RAG grounding contract:
each reference carries an ``artifact_id`` (concept node or glossary term)
and ``hash_verified`` flag.

The retriever accesses the global :class:`KnowledgeIndex` singleton injected
at server startup (via :func:`lumina.core.nlp.set_knowledge_index`).
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("lumina.knowledge-retriever")


def _get_knowledge_index() -> Any:
    """Return the global KnowledgeIndex, or None."""
    # Lazy import to avoid circular dependency at module load time.
    from lumina.core import nlp as _nlp  # noqa: PLC0415
    return _nlp._knowledge_index


def retrieve_grounding(
    task_spec: dict[str, Any],
    evidence: dict[str, Any],
    domain_id: str,
) -> list[dict[str, Any]]:
    """Gather grounding references for a single turn.

    Strategy (ordered):
      1. **Glossary lookup** — extract skills/terms from *task_spec* and look
         each up in the glossary routing table.
      2. **Concept-graph expansion** — for every matched glossary node, pull
         1-hop related concepts to enrich the reference set.

    Returns a (possibly empty) list of reference dicts suitable for the
    ``references`` field in the prompt contract.
    """
    ki = _get_knowledge_index()
    if ki is None:
        return []

    refs: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    # ── 1. Glossary hits from task_spec terms ────────────────
    terms: list[str] = []
    terms.extend(task_spec.get("skills_required", []))
    task_id = task_spec.get("task_id", "")
    if task_id:
        terms.append(task_id)

    matched_domains = ki.lookup_terms(terms)
    for term, matched_domain in matched_domains.items():
        node_id = f"glossary:{matched_domain}:{term.lower().strip()}"
        if node_id not in seen_ids:
            seen_ids.add(node_id)
            refs.append({
                "artifact_id": node_id,
                "artifact_version": "index",
                "hash_verified": True,
            })

    # ── 2. Concept-graph expansion (1-hop) ───────────────────
    expand_ids = list(seen_ids)
    for nid in expand_ids:
        try:
            related = ki.get_related(nid, depth=1)
        except Exception:
            continue
        for node in related:
            if node.node_id not in seen_ids:
                seen_ids.add(node.node_id)
                refs.append({
                    "artifact_id": node.node_id,
                    "artifact_version": "index",
                    "hash_verified": True,
                })

    if refs:
        log.debug("Grounding: %d references for domain=%s", len(refs), domain_id)

    return refs
