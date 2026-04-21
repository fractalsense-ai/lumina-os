"""Extended tests for lumina.core.nlp — get_nlp error paths and classify_domain similarity.

Covers lines 49–64 (ImportError, OSError, generic Exception in get_nlp)
and lines 185–196 (spaCy vector similarity pass in classify_domain).
"""
from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

import lumina.core.nlp as nlp_mod
from lumina.core.nlp import classify_domain, get_nlp


# ── get_nlp — ImportError path ────────────────────────────────────────────────


@pytest.mark.unit
def test_get_nlp_import_error_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_nlp() returns None and sets _spacy_available = False on ImportError."""
    monkeypatch.setattr(nlp_mod, "_spacy_available", None)
    monkeypatch.setattr(nlp_mod, "_nlp_instance", None)
    # Setting sys.modules["spacy"] = None causes `import spacy` to raise ImportError
    monkeypatch.setitem(sys.modules, "spacy", None)  # type: ignore[arg-type]
    result = get_nlp()
    assert result is None
    assert nlp_mod._spacy_available is False


# ── get_nlp — OSError path ────────────────────────────────────────────────────


@pytest.mark.unit
def test_get_nlp_ose_model_not_found_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_nlp() returns None when spacy.load raises OSError (model missing)."""
    monkeypatch.setattr(nlp_mod, "_spacy_available", None)
    monkeypatch.setattr(nlp_mod, "_nlp_instance", None)

    def _raise_ose(model: str, **kwargs: Any) -> Any:
        raise OSError(f"Model '{model}' not found")

    fake_spacy = SimpleNamespace(load=_raise_ose)
    monkeypatch.setitem(sys.modules, "spacy", fake_spacy)
    result = get_nlp()

    assert result is None
    assert nlp_mod._spacy_available is False


# ── get_nlp — generic Exception path ─────────────────────────────────────────


@pytest.mark.unit
def test_get_nlp_generic_exception_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_nlp() returns None when spacy.load raises an unexpected Exception."""
    monkeypatch.setattr(nlp_mod, "_spacy_available", None)
    monkeypatch.setattr(nlp_mod, "_nlp_instance", None)

    def _raise_unexpected(model: str, **kwargs: Any) -> Any:
        raise RuntimeError("unexpected loading failure")

    fake_spacy = SimpleNamespace(load=_raise_unexpected)
    monkeypatch.setitem(sys.modules, "spacy", fake_spacy)
    result = get_nlp()
    assert result is None
    assert nlp_mod._spacy_available is False


# ── classify_domain — spaCy similarity pass ──────────────────────────────────


@pytest.mark.unit
def test_classify_domain_spacy_similarity_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """When keyword matching fails, the spaCy similarity pass runs and returns a result."""
    # Build a mock nlp that has vector width > 0
    mock_doc = MagicMock()
    mock_doc.similarity.return_value = 0.75

    mock_nlp = MagicMock()
    mock_nlp.meta = {"vectors": {"width": 300}}
    mock_nlp.return_value = mock_doc  # nlp(any_text) → mock_doc

    # Inject the mock so get_nlp() returns it directly (skips loading)
    monkeypatch.setattr(nlp_mod, "_nlp_instance", mock_nlp)
    monkeypatch.setattr(nlp_mod, "_spacy_available", True)

    # Use keywords that won't match the input text — forces Pass 2
    domain_map = {
        "education": {
            "label": "Education",
            "description": "Learning and mathematics",
            "keywords": ["trigonometry", "calculus", "integration"],  # won't match "hello"
        }
    }
    result = classify_domain("hello world", domain_map)
    assert result is not None
    assert result["method"] == "similarity"
    assert result["domain_id"] == "education"
    assert result["confidence"] >= 0.6


@pytest.mark.unit
def test_classify_domain_spacy_similarity_below_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    """When similarity is below threshold, None is returned."""
    mock_doc = MagicMock()
    mock_doc.similarity.return_value = 0.1  # below 0.6 threshold

    mock_nlp = MagicMock()
    mock_nlp.meta = {"vectors": {"width": 300}}
    mock_nlp.return_value = mock_doc

    monkeypatch.setattr(nlp_mod, "_nlp_instance", mock_nlp)
    monkeypatch.setattr(nlp_mod, "_spacy_available", True)

    domain_map = {
        "education": {
            "label": "Education",
            "description": "Learning",
            "keywords": ["trigonometry"],  # won't match
        }
    }
    result = classify_domain("unrelated text", domain_map)
    assert result is None


@pytest.mark.unit
def test_classify_domain_no_vectors_skips_similarity(monkeypatch: pytest.MonkeyPatch) -> None:
    """When nlp has no vectors (width=0), similarity pass is skipped."""
    mock_nlp = MagicMock()
    mock_nlp.meta = {"vectors": {"width": 0}}

    monkeypatch.setattr(nlp_mod, "_nlp_instance", mock_nlp)
    monkeypatch.setattr(nlp_mod, "_spacy_available", True)

    domain_map = {
        "education": {
            "label": "Education",
            "description": "Learning",
            "keywords": ["trigonometry"],
        }
    }
    # No keyword match, no vector similarity → None
    result = classify_domain("hello world", domain_map)
    assert result is None
    # The mock_nlp should NOT have been called for similarity
    mock_nlp.assert_not_called()


@pytest.mark.unit
def test_classify_domain_accessible_domains_empty_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When accessible_domains filters out all domains, None is returned immediately."""
    monkeypatch.setattr(nlp_mod, "_spacy_available", False)
    monkeypatch.setattr(nlp_mod, "_nlp_instance", None)

    domain_map = {"education": {"label": "Education", "keywords": ["math"]}}
    result = classify_domain("math problem", domain_map, accessible_domains=["agriculture"])
    assert result is None
