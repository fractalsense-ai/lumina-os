"""Tests for glossary query detection in the API server."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

# ── Load the _detect_glossary_query function from lumina-api-server ──

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_detect_fn():
    # Ensure server module can initialize (needs at least one domain config path)
    os.environ.setdefault("LUMINA_RUNTIME_CONFIG_PATH", "model-packs/education/cfg/runtime-config.yaml")
    module_path = _REPO_ROOT / "src" / "lumina" / "api" / "server.py"
    spec = importlib.util.spec_from_file_location("lumina.api.server", str(module_path))
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load lumina-api-server module")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["lumina.api.server"] = mod
    spec.loader.exec_module(mod)
    return mod._detect_glossary_query


_detect_glossary_query = _load_detect_fn()


# ── Sample glossary (matches algebra-level-1 structure) ──────

GLOSSARY = [
    {
        "term": "coefficient",
        "definition": "The number multiplied by a variable.",
        "aliases": ["coefficients", "the number in front of x", "number before the variable"],
        "related_terms": ["variable", "constant", "term"],
        "example_in_context": "In 4x = 28, the coefficient of x is 4.",
    },
    {
        "term": "variable",
        "definition": "A letter that stands for an unknown number.",
        "aliases": ["variables", "unknown", "unknowns", "the letter"],
        "related_terms": ["constant", "coefficient", "expression"],
        "example_in_context": "In x + 7 = 15, the variable is x.",
    },
    {
        "term": "inverse operation",
        "definition": "The opposite operation that undoes another.",
        "aliases": ["inverse operations", "opposite operation", "undo operation"],
        "related_terms": ["isolate", "equation"],
        "example_in_context": "To undo '+ 7', use '- 7'.",
    },
    {
        "term": "like terms",
        "definition": "Terms that have the same variable raised to the same power.",
        "aliases": ["combining like terms", "combine like terms", "similar terms"],
        "related_terms": ["term", "coefficient", "variable"],
        "example_in_context": "2x and 3x are like terms.",
    },
]


# ── Exact term match ─────────────────────────────────────────


class TestExactMatch:

    def test_what_is_a_coefficient(self):
        result = _detect_glossary_query("What is a coefficient?", GLOSSARY)
        assert result is not None
        assert result["term"] == "coefficient"

    def test_what_is_a_variable(self):
        result = _detect_glossary_query("what is a variable?", GLOSSARY)
        assert result is not None
        assert result["term"] == "variable"

    def test_define_coefficient(self):
        result = _detect_glossary_query("define coefficient", GLOSSARY)
        assert result is not None
        assert result["term"] == "coefficient"

    def test_what_does_variable_mean(self):
        result = _detect_glossary_query("what does variable mean?", GLOSSARY)
        assert result is not None
        assert result["term"] == "variable"

    def test_meaning_of_coefficient(self):
        result = _detect_glossary_query("meaning of coefficient", GLOSSARY)
        assert result is not None
        assert result["term"] == "coefficient"

    def test_whats_a_variable(self):
        result = _detect_glossary_query("what's a variable?", GLOSSARY)
        assert result is not None
        assert result["term"] == "variable"


# ── Alias match ──────────────────────────────────────────────


class TestAliasMatch:

    def test_alias_the_number_in_front_of_x(self):
        result = _detect_glossary_query("what is the number in front of x?", GLOSSARY)
        assert result is not None
        assert result["term"] == "coefficient"

    def test_alias_unknown(self):
        result = _detect_glossary_query("what is an unknown?", GLOSSARY)
        assert result is not None
        assert result["term"] == "variable"

    def test_alias_opposite_operation(self):
        result = _detect_glossary_query("what is an opposite operation?", GLOSSARY)
        assert result is not None
        assert result["term"] == "inverse operation"


# ── Case insensitivity ───────────────────────────────────────


class TestCaseInsensitivity:

    def test_all_caps(self):
        result = _detect_glossary_query("WHAT IS A COEFFICIENT?", GLOSSARY)
        assert result is not None
        assert result["term"] == "coefficient"

    def test_mixed_case(self):
        result = _detect_glossary_query("Define Variable", GLOSSARY)
        assert result is not None
        assert result["term"] == "variable"


# ── Multi-word terms ─────────────────────────────────────────


class TestMultiWordTerms:

    def test_inverse_operation(self):
        result = _detect_glossary_query("what is an inverse operation?", GLOSSARY)
        assert result is not None
        assert result["term"] == "inverse operation"

    def test_like_terms(self):
        result = _detect_glossary_query("what are like terms?", GLOSSARY)
        assert result is not None
        assert result["term"] == "like terms"

    def test_combining_like_terms_alias(self):
        result = _detect_glossary_query("what is combining like terms?", GLOSSARY)
        assert result is not None
        assert result["term"] == "like terms"


# ── No match cases ───────────────────────────────────────────


class TestNoMatch:

    def test_unknown_term_returns_none(self):
        result = _detect_glossary_query("what is a flurblesnork?", GLOSSARY)
        assert result is None

    def test_non_question_returns_none(self):
        result = _detect_glossary_query("I think x = 5", GLOSSARY)
        assert result is None

    def test_empty_string_returns_none(self):
        result = _detect_glossary_query("", GLOSSARY)
        assert result is None

    def test_empty_glossary_returns_none(self):
        result = _detect_glossary_query("what is a coefficient?", [])
        assert result is None

    def test_unrelated_question_returns_none(self):
        result = _detect_glossary_query("what is the answer to number 5?", GLOSSARY)
        assert result is None


# ── Plural fallback ──────────────────────────────────────────


class TestPluralFallback:

    def test_coefficients_plural(self):
        result = _detect_glossary_query("what are coefficients?", GLOSSARY)
        assert result is not None
        assert result["term"] == "coefficient"


# ── Return structure ─────────────────────────────────────────


class TestReturnStructure:

    def test_returns_full_entry(self):
        result = _detect_glossary_query("what is a coefficient?", GLOSSARY)
        assert result is not None
        assert "definition" in result
        assert "aliases" in result
        assert "related_terms" in result
        assert "example_in_context" in result
