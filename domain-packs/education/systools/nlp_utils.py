"""Shared NLP utilities for the education domain.

Delegates to core NLP primitives in ``lumina.core.nlp``.
"""

from __future__ import annotations

from typing import Any

from lumina.core.nlp import get_nlp as _get_nlp
from lumina.core.nlp import split_sentences as _split_sentences


def get_nlp() -> Any | None:
    """Return a cached spaCy Language instance, or None if unavailable."""
    return _get_nlp()


def split_sentences(text: str) -> list[str]:
    """Split text into sentences using core NLP (spaCy + regex fallback)."""
    return _split_sentences(text)
