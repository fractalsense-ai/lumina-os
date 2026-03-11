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

    Loads ``en_core_web_sm`` on first call and caches globally.
    Returns None (no exception) when spaCy or the model is absent.
    """
    global _nlp_instance, _spacy_available

    if _spacy_available is False:
        return None
    if _nlp_instance is not None:
        return _nlp_instance

    try:
        import spacy

        _nlp_instance = spacy.load("en_core_web_sm")
        _spacy_available = True
        log.info("spaCy model en_core_web_sm loaded (core NLP)")
        return _nlp_instance
    except ImportError:
        _spacy_available = False
        log.info("spaCy not installed — core NLP using regex fallbacks")
        return None
    except OSError:
        _spacy_available = False
        log.info("spaCy model en_core_web_sm not found — core NLP using regex fallbacks")
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
