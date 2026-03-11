"""Shared NLP utilities for the education domain.

Delegates to core NLP primitives (``reference-implementations/core_nlp.py``).
This module exists for backward compatibility; new code should import
from ``core_nlp`` directly.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any


def _ensure_core_nlp():
    """Lazy-load core_nlp module if not already imported."""
    if "core_nlp" in sys.modules:
        return sys.modules["core_nlp"]
    core_path = Path(__file__).resolve().parents[3] / "reference-implementations" / "core_nlp.py"
    spec = importlib.util.spec_from_file_location("core_nlp", str(core_path))
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    sys.modules["core_nlp"] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def get_nlp() -> Any | None:
    """Return a cached spaCy Language instance, or None if unavailable."""
    return _ensure_core_nlp().get_nlp()


def split_sentences(text: str) -> list[str]:
    """Split text into sentences using core NLP (spaCy + regex fallback)."""
    return _ensure_core_nlp().split_sentences(text)
