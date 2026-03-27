"""
core_nlp.py — Core NLP primitives for Project Lumina

Provides system-wide text processing utilities and semantic domain routing.
Domain packs consume these primitives but own all semantic interpretation.

- split_sentences(text) — sentence splitting (spaCy sentencizer + regex fallback)
- tokenize(text) — word-level tokenization (spaCy + str.split fallback)
- classify_domain(text, domain_map, accessible_domains) — semantic routing

spaCy is a soft dependency: all functions degrade gracefully to regex/keyword
fallbacks when spaCy or its models are not installed.
"""

from __future__ import annotations

import logging
import re
from typing import Any

log = logging.getLogger("lumina.core-nlp")

# ── Lazy spaCy loader ────────────────────────────────────────

_nlp_instance: Any = None
_spacy_available: bool | None = None


def get_nlp() -> Any | None:
    """Return a cached spaCy Language instance, or None if unavailable.

    Loads ``en_core_web_md`` on first call and caches globally.
    Returns None (no exception) when spaCy or the model is absent.
    """
    global _nlp_instance, _spacy_available

    if _spacy_available is False:
        return None
    if _nlp_instance is not None:
        return _nlp_instance

    try:
        import spacy

        _nlp_instance = spacy.load("en_core_web_md")
        _spacy_available = True
        log.info("spaCy model en_core_web_md loaded (core NLP)")
        return _nlp_instance
    except ImportError:
        _spacy_available = False
        log.info("spaCy not installed — core NLP using regex fallbacks")
        return None
    except OSError:
        _spacy_available = False
        log.info("spaCy model en_core_web_md not found — core NLP using regex fallbacks")
        return None
    except Exception as exc:
        _spacy_available = False
        log.warning(
            "spaCy failed to load (%s: %s) — core NLP using regex fallbacks",
            type(exc).__name__,
            exc,
        )
        return None


# ── Text primitives ──────────────────────────────────────────


def split_sentences(text: str) -> list[str]:
    """Split text into sentences using spaCy, with regex fallback.

    Returns a list of non-empty sentence strings.
    """
    nlp = get_nlp()
    if nlp is not None:
        doc = nlp(text)
        sentences = [sent.text.strip() for sent in doc.sents if sent.text.strip()]
        if sentences:
            return sentences

    # Regex fallback: split on sentence-ending punctuation followed by
    # whitespace, or on natural-language connectors.
    parts: list[str] = []
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        fragments = re.split(
            r"[;,]\s*(?=[A-Za-z])"
            r"|(?<=\d)\.\s+(?=[A-Z])"
            r"|(?<=[a-z])\.\s+(?=[A-Z])"
            r"|\bso\s+that\s+(?:means?\s+)?"
            r"|\bso\b\s+"
            r"|\bthen\b\s+"
            r"|\bmeaning\b\s+"
            r"|\btherefore\b\s+"
            r"|\bafter\s+(?:that\s+)?"
            r"|\bwhich\s+means\b\s+"
            r"|\bnow\b\s+",
            stripped,
            flags=re.IGNORECASE,
        )
        for part in fragments:
            part = part.strip()
            if part:
                parts.append(part)
    return parts


def tokenize(text: str) -> list[str]:
    """Tokenize text into words using spaCy, with whitespace fallback."""
    nlp = get_nlp()
    if nlp is not None:
        doc = nlp(text)
        return [token.text for token in doc if not token.is_space]
    return text.split()


# ── Semantic domain routing ──────────────────────────────────

_CONFIDENCE_THRESHOLD = 0.6

# Singleton KnowledgeIndex reference — set by server startup.
_knowledge_index: Any = None

# Singleton VectorStoreRegistry — set by server startup for domain-scoped search.
_vector_registry: Any = None
_doc_embedder: Any = None


def set_knowledge_index(index: Any) -> None:
    """Inject the global :class:`KnowledgeIndex` for glossary-based routing."""
    global _knowledge_index
    _knowledge_index = index


def set_vector_registry(registry: Any, embedder: Any = None) -> None:
    """Inject the :class:`VectorStoreRegistry` and optional embedder."""
    global _vector_registry, _doc_embedder
    _vector_registry = registry
    _doc_embedder = embedder


def classify_domain(
    text: str,
    domain_map: dict[str, dict[str, Any]],
    accessible_domains: list[str] | None = None,
) -> dict[str, Any] | None:
    """Infer the best-matching domain for a user message.

    Parameters
    ----------
    text:
        The user's message.
    domain_map:
        ``{domain_id: {"label": str, "description": str, "keywords": list[str]}}``.
    accessible_domains:
        When provided, only domains in this list are considered.

    Returns
    -------
    dict or None
        ``{"domain_id": str, "confidence": float, "method": str}`` if a
        match is found above the confidence threshold, else ``None``.
    """
    if not text or not domain_map:
        return None

    candidates = domain_map
    if accessible_domains is not None:
        candidates = {
            did: info
            for did, info in domain_map.items()
            if did in accessible_domains
        }
    if not candidates:
        return None

    text_lower = text.lower()

    # ── Pass 0: glossary routing via KnowledgeIndex ──────────
    if _knowledge_index is not None:
        words = text_lower.split()
        # Check multi-word then single-word terms against the glossary table
        domain_votes: dict[str, int] = {}
        for n in (3, 2, 1):
            for i in range(len(words) - n + 1):
                phrase = " ".join(words[i : i + n])
                hit = _knowledge_index.lookup_term(phrase)
                if hit and hit in candidates:
                    domain_votes[hit] = domain_votes.get(hit, 0) + 1
        if domain_votes:
            best_id = max(domain_votes, key=domain_votes.__getitem__)
            total_hits = domain_votes[best_id]
            confidence = min(total_hits * 0.35, 1.0)
            if confidence >= _CONFIDENCE_THRESHOLD:
                return {
                    "domain_id": best_id,
                    "confidence": round(confidence, 3),
                    "method": "glossary",
                }

    # ── Pass 1: keyword matching ─────────────────────────────
    scores: dict[str, float] = {}
    for domain_id, info in candidates.items():
        keywords = info.get("keywords") or []
        if not keywords:
            continue
        hits = sum(1 for kw in keywords if kw.lower() in text_lower)
        if hits > 0:
            scores[domain_id] = hits / len(keywords)

    if scores:
        best_id = max(scores, key=scores.__getitem__)
        confidence = min(scores[best_id] * 2.0, 1.0)  # scale up: 1 hit / 5 keywords = 0.4
        if confidence >= _CONFIDENCE_THRESHOLD:
            return {
                "domain_id": best_id,
                "confidence": round(confidence, 3),
                "method": "keyword",
            }

    # ── Pass 1.5: vector routing via global store ────────────
    if _vector_registry is not None and _doc_embedder is not None:
        try:
            global_store = _vector_registry.global_store
            if global_store.size > 0:
                q_vec = _doc_embedder.embed_query(text)
                hits = global_store.search(q_vec, k=5)
                # Tally domain_id votes from top results
                vec_votes: dict[str, float] = {}
                for h in hits:
                    did = getattr(h.chunk, "domain_id", "") or ""
                    if did and did in candidates:
                        vec_votes[did] = vec_votes.get(did, 0.0) + h.score
                if vec_votes:
                    best_id = max(vec_votes, key=vec_votes.__getitem__)
                    # Average score across hits for this domain
                    hit_count = sum(1 for h in hits if (getattr(h.chunk, "domain_id", "") or "") == best_id)
                    avg_score = vec_votes[best_id] / hit_count
                    if avg_score >= _CONFIDENCE_THRESHOLD:
                        return {
                            "domain_id": best_id,
                            "confidence": round(avg_score, 3),
                            "method": "vector",
                        }
        except Exception:
            log.debug("Vector routing pass failed, falling through", exc_info=True)

    # ── Pass 2: description similarity via spaCy vectors ─────
    nlp = get_nlp()
    if nlp is not None and nlp.meta.get("vectors", {}).get("width", 0) > 0:
        msg_doc = nlp(text)
        best_sim = -1.0
        best_sim_id = ""
        for domain_id, info in candidates.items():
            desc = f"{info.get('label', '')} {info.get('description', '')}"
            desc_doc = nlp(desc)
            sim = msg_doc.similarity(desc_doc)
            if sim > best_sim:
                best_sim = sim
                best_sim_id = domain_id
        if best_sim >= _CONFIDENCE_THRESHOLD and best_sim_id:
            return {
                "domain_id": best_sim_id,
                "confidence": round(best_sim, 3),
                "method": "similarity",
            }

    # ── Pass 3: description substring fallback ───────────────
    for domain_id, info in candidates.items():
        desc_lower = (info.get("description") or "").lower()
        label_lower = (info.get("label") or "").lower()
        # Check if any significant word from the message appears in the description
        words = text_lower.split()
        # Filter out very short/common words
        sig_words = [w for w in words if len(w) > 3]
        if sig_words:
            hits = sum(1 for w in sig_words if w in desc_lower or w in label_lower)
            if hits >= 2:
                confidence = min(hits / len(sig_words) * 1.5, 1.0)
                if confidence >= _CONFIDENCE_THRESHOLD:
                    return {
                        "domain_id": domain_id,
                        "confidence": round(confidence, 3),
                        "method": "description",
                    }

    return None


# ── Domain-scoped semantic search ────────────────────────────

def search_domain(
    text: str,
    domain_id: str,
    k: int = 5,
) -> list[Any]:
    """Search the per-domain vector store for *text*.

    Returns a list of :class:`SearchResult` from the domain's store,
    or an empty list if the registry/embedder is not configured.
    """
    if _vector_registry is None or _doc_embedder is None:
        return []
    store = _vector_registry.get(domain_id)
    if store.size == 0:
        store.load()
    if store.size == 0:
        return []
    q_vec = _doc_embedder.embed_query(text)
    return store.search(q_vec, k=k)
