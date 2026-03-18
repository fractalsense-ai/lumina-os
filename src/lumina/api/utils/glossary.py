"""Glossary query detection with per-domain index caching."""

from __future__ import annotations

import re
import threading
from typing import Any

_GLOSSARY_QUERY_RE = re.compile(
    r"(?:what\s+(?:is|are|does)\s+(?:a|an|the)?\s*)"
    r"|(?:what\s+does\s+.+?\s+mean)"
    r"|(?:define\s+)"
    r"|(?:meaning\s+of\s+)"
    r"|(?:what(?:'s| is)\s+)",
    re.IGNORECASE,
)

_ARTICLE_RE = re.compile(r"^(?:a|an|the)\s+", re.IGNORECASE)

# Per-domain glossary index cache: domain_id → {lowered_term → glossary_entry}
_glossary_index_cache: dict[str, dict[str, dict[str, Any]]] = {}
_cache_lock = threading.Lock()


def _build_glossary_index(glossary: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Build a lookup index: lowered term/alias → glossary entry."""
    index: dict[str, dict[str, Any]] = {}
    for entry in glossary:
        key = str(entry.get("term", "")).lower().strip()
        if key:
            index[key] = entry
        for alias in entry.get("aliases") or []:
            akey = str(alias).lower().strip()
            if akey:
                index[akey] = entry
                stripped = _ARTICLE_RE.sub("", akey).strip()
                if stripped and stripped != akey:
                    index[stripped] = entry
    return index


def invalidate_glossary_cache(domain_id: str | None = None) -> None:
    """Clear cached glossary index for a domain, or all if domain_id is None."""
    with _cache_lock:
        if domain_id is None:
            _glossary_index_cache.clear()
        else:
            _glossary_index_cache.pop(domain_id, None)


def detect_glossary_query(
    message: str,
    glossary: list[dict[str, Any]],
    domain_id: str | None = None,
) -> dict[str, Any] | None:
    """Match a student message against the domain glossary.

    Returns the matched glossary entry dict or None.
    Matching is case-insensitive against ``term`` and ``aliases``.

    When *domain_id* is provided the glossary index is cached per-domain
    so subsequent calls avoid rebuilding it on every message.
    """
    if not glossary:
        return None

    text = message.strip()
    if not _GLOSSARY_QUERY_RE.search(text):
        return None

    # Retrieve or build the index (thread-safe).
    index: dict[str, dict[str, Any]] | None = None
    if domain_id is not None:
        with _cache_lock:
            index = _glossary_index_cache.get(domain_id)
    if index is None:
        index = _build_glossary_index(glossary)
        if domain_id is not None:
            with _cache_lock:
                _glossary_index_cache[domain_id] = index

    # Normalise the question to extract the candidate term.
    candidate = text.lower()
    # Strip trailing punctuation
    candidate = re.sub(r"[?.!]+$", "", candidate).strip()
    # Strip common question prefixes
    candidate = re.sub(
        r"^(?:what\s+(?:is|are|does)\s+(?:an|a|the)?\s*"
        r"|what\s+does\s+|what(?:'s| is)\s+(?:an|a|the)?\s*"
        r"|define\s+|meaning\s+of\s+)",
        "",
        candidate,
        flags=re.IGNORECASE,
    ).strip()
    # Strip trailing "mean" from "what does X mean"
    candidate = re.sub(r"\s+mean$", "", candidate).strip()

    if not candidate:
        return None

    # Exact match
    if candidate in index:
        return index[candidate]

    # Plural fallback: strip trailing 's'
    if candidate.endswith("s") and candidate[:-1] in index:
        return index[candidate[:-1]]

    return None


# Backward-compat alias: tests access _detect_glossary_query via server module
_detect_glossary_query = detect_glossary_query
