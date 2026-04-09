"""Tests for the context_crawler night-cycle task."""

from __future__ import annotations

import json

import pytest
from lumina.daemon.report import Proposal, TaskResult
from lumina.daemon.tasks import context_crawler, get_task, list_tasks


# ── Fixtures ──────────────────────────────────────────────────

_PHYSICS_BASIC = {
    "modules": [
        {
            "module_id": "m_algebra",
            "name": "Algebra Basics",
            "artifacts": [{"name": "linear_equations"}, {"name": "quadratics"}],
        },
        {
            "module_id": "m_geometry",
            "name": "Geometry Foundations",
            "artifacts": [{"name": "triangles"}],
        },
    ],
    "invariants": [
        {
            "id": "inv_prereq",
            "description": "Prerequisite check",
            "severity": "error",
            "applies_to": ["m_algebra"],
        },
    ],
    "glossary": [
        {"term": "equation", "definition": "a mathematical statement"},
    ],
}


def _mock_slm(hints_per_module: int = 1):
    """Return a mock call_slm_fn that produces ``hints_per_module`` hints."""
    def _fn(system=None, user=None, **_):
        payload = json.loads(user)
        module_id = payload.get("module_id", "mod")
        hints = [
            {"hint_id": f"{module_id}-hint-{i}", "content": f"Hint {i} for {module_id}"}
            for i in range(hints_per_module)
        ]
        return json.dumps(hints)
    return _fn


def _mock_slm_error(**_):
    """SLM that always raises."""
    raise RuntimeError("SLM unavailable")


def _mock_slm_invalid_json(**_):
    """SLM that returns unparseable text."""
    return "not valid json {{"


def _mock_slm_empty(**_):
    """SLM that returns an empty list."""
    return json.dumps([])


# ── Registration ──────────────────────────────────────────────


class TestContextCrawlerRegistration:
    def test_registered_in_task_registry(self):
        assert "context_crawler" in list_tasks()

    def test_get_task_returns_function(self):
        fn = get_task("context_crawler")
        assert fn is context_crawler


# ── Basic behaviour ───────────────────────────────────────────


class TestContextCrawlerBasic:
    def test_empty_physics(self):
        result = context_crawler(domain_id="test", domain_physics={})
        assert result.success is True
        assert result.task == "context_crawler"
        assert result.metadata.get("skipped") is True
        assert result.metadata.get("reason") == "no modules in domain"

    def test_no_slm_fn_skips_gracefully(self):
        result = context_crawler(
            domain_id="edu",
            domain_physics=_PHYSICS_BASIC,
        )
        assert result.success is True
        assert len(result.proposals) == 0
        assert result.metadata.get("skipped") is True
        assert result.metadata.get("reason") == "no call_slm_fn provided"


# ── SLM integration ──────────────────────────────────────────


class TestContextCrawlerWithSlm:
    def test_produces_proposals_per_module(self):
        result = context_crawler(
            domain_id="edu",
            domain_physics=_PHYSICS_BASIC,
            call_slm_fn=_mock_slm(hints_per_module=2),
        )
        assert result.success is True
        # 2 modules × 2 hints each = 4 proposals
        assert len(result.proposals) == 4
        assert result.metadata["modules_processed"] == 2
        assert result.metadata["hints_generated"] == 4

    def test_proposal_type_is_context_hint(self):
        result = context_crawler(
            domain_id="edu",
            domain_physics=_PHYSICS_BASIC,
            call_slm_fn=_mock_slm(1),
        )
        for prop in result.proposals:
            assert prop.proposal_type == "context_hint"

    def test_proposal_detail_structure(self):
        result = context_crawler(
            domain_id="edu",
            domain_physics=_PHYSICS_BASIC,
            call_slm_fn=_mock_slm(1),
        )
        prop = result.proposals[0]
        assert "hint_id" in prop.detail
        assert "module_id" in prop.detail
        assert "domain_id" in prop.detail
        assert "content" in prop.detail
        assert prop.detail["domain_id"] == "edu"

    def test_proposal_domain_id(self):
        result = context_crawler(
            domain_id="agri",
            domain_physics=_PHYSICS_BASIC,
            call_slm_fn=_mock_slm(1),
        )
        for prop in result.proposals:
            assert prop.domain_id == "agri"

    def test_summary_contains_module_id(self):
        result = context_crawler(
            domain_id="edu",
            domain_physics=_PHYSICS_BASIC,
            call_slm_fn=_mock_slm(1),
        )
        algebra_prop = next(
            p for p in result.proposals if p.detail["module_id"] == "m_algebra"
        )
        assert "m_algebra" in algebra_prop.summary

    def test_single_hint_per_module(self):
        result = context_crawler(
            domain_id="edu",
            domain_physics=_PHYSICS_BASIC,
            call_slm_fn=_mock_slm(1),
        )
        assert len(result.proposals) == 2
        module_ids = {p.detail["module_id"] for p in result.proposals}
        assert module_ids == {"m_algebra", "m_geometry"}


# ── Error handling ────────────────────────────────────────────


class TestContextCrawlerErrors:
    def test_slm_error_continues_other_modules(self):
        """SLM error on one module shouldn't stop processing others."""
        call_count = {"n": 0}
        def _flaky_slm(system=None, user=None, **_):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("boom")
            return json.dumps([{"hint_id": "h1", "content": "fallback hint"}])

        result = context_crawler(
            domain_id="edu",
            domain_physics=_PHYSICS_BASIC,
            call_slm_fn=_flaky_slm,
        )
        assert result.success is True
        # Second module should still produce results
        assert len(result.proposals) >= 1

    def test_slm_returns_invalid_json(self):
        result = context_crawler(
            domain_id="edu",
            domain_physics=_PHYSICS_BASIC,
            call_slm_fn=_mock_slm_invalid_json,
        )
        assert result.success is True
        assert len(result.proposals) == 0

    def test_slm_returns_empty_list(self):
        result = context_crawler(
            domain_id="edu",
            domain_physics=_PHYSICS_BASIC,
            call_slm_fn=_mock_slm_empty,
        )
        assert result.success is True
        assert len(result.proposals) == 0

    def test_slm_returns_empty_content_filtered(self):
        """Hints with empty content strings should be filtered out."""
        def _slm(**_):
            return json.dumps([{"hint_id": "h1", "content": ""}])

        result = context_crawler(
            domain_id="edu",
            domain_physics=_PHYSICS_BASIC,
            call_slm_fn=_slm,
        )
        assert result.success is True
        assert len(result.proposals) == 0


# ── Edge cases ────────────────────────────────────────────────


class TestContextCrawlerEdgeCases:
    def test_modules_without_artifacts(self):
        physics = {
            "modules": [{"module_id": "bare"}],
            "invariants": [],
            "glossary": [],
        }
        result = context_crawler(
            domain_id="test",
            domain_physics=physics,
            call_slm_fn=_mock_slm(1),
        )
        assert result.success is True
        assert result.metadata["modules_processed"] == 1

    def test_slm_returns_single_object_instead_of_list(self):
        """SLM returning a single hint object (not a list) should be handled."""
        def _slm(**_):
            return json.dumps({"hint_id": "h1", "content": "solo hint"})

        result = context_crawler(
            domain_id="edu",
            domain_physics=_PHYSICS_BASIC,
            call_slm_fn=_slm,
        )
        assert result.success is True
        # Should wrap single object in list — 1 hint per module
        assert len(result.proposals) == 2

    def test_slm_returns_markdown_fenced_json(self):
        """SLM wrapping JSON in markdown fences should still work."""
        def _slm(**_):
            return '```json\n[{"hint_id": "h1", "content": "fenced"}]\n```'

        result = context_crawler(
            domain_id="edu",
            domain_physics=_PHYSICS_BASIC,
            call_slm_fn=_slm,
        )
        assert result.success is True
        assert len(result.proposals) == 2
        assert all("fenced" in p.detail["content"] for p in result.proposals)
