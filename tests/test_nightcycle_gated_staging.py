"""Tests for the gated_staging night-cycle task."""

from __future__ import annotations

import json

import pytest
from lumina.daemon.report import Proposal, TaskResult
from lumina.daemon.tasks import gated_staging, get_task, list_tasks


# ── Fixtures ──────────────────────────────────────────────────

_GLOSSARY_CLEAN = [
    {"term": "photosynthesis", "definition": "Process of converting light to energy", "related_terms": ["chlorophyll"]},
    {"term": "chlorophyll", "definition": "Green pigment in plants", "related_terms": ["photosynthesis"]},
]

_GLOSSARY_WITH_ISSUES = [
    {"term": "algebra", "definition": "Branch of mathematics"},
    {"term": "equation"},  # no definition=allowed, but no related_terms
    {"term": "algebra"},  # duplicate
    {"term": "geometry", "definition": "Study of shapes", "related_terms": ["angle"]},
]

_MODULES_BASIC = [
    {"module_id": "m_algebra", "name": "Algebra Basics"},
    {"module_id": "m_geometry", "name": "Geometry Foundations"},
]

_PHYSICS_CLEAN = {
    "glossary": _GLOSSARY_CLEAN,
    "modules": _MODULES_BASIC,
}

_PHYSICS_WITH_ISSUES = {
    "glossary": _GLOSSARY_WITH_ISSUES,
    "modules": _MODULES_BASIC,
}


def _mock_slm(drafts: list[dict] | None = None):
    """Return a mock call_slm_fn that produces draft glossary entries."""
    if drafts is None:
        drafts = [
            {"term": "polynomial", "definition": "Expression with multiple terms", "related_terms": ["algebra"]},
        ]

    def _fn(system=None, user=None, **_):
        return json.dumps(drafts)
    return _fn


def _mock_slm_error(**_):
    raise RuntimeError("SLM unavailable")


# ── Registration ──────────────────────────────────────────────


class TestGatedStagingRegistration:
    def test_registered_in_task_registry(self):
        assert "gated_staging" in list_tasks()

    def test_get_task_returns_function(self):
        fn = get_task("gated_staging")
        assert fn is gated_staging


# ── Heuristic pass (no SLM) ──────────────────────────────────


class TestGatedStagingHeuristic:
    def test_empty_glossary(self):
        result = gated_staging(domain_id="test", domain_physics={})
        assert result.success is True
        assert result.task == "gated_staging"
        assert len(result.proposals) == 0

    def test_clean_glossary_no_issues(self):
        result = gated_staging(
            domain_id="test",
            domain_physics={"glossary": _GLOSSARY_CLEAN},
        )
        assert result.success is True
        assert len(result.proposals) == 0

    def test_detects_duplicate_terms(self):
        result = gated_staging(
            domain_id="edu",
            domain_physics=_PHYSICS_WITH_ISSUES,
        )
        duplicates = [p for p in result.proposals if p.proposal_type == "glossary_duplicate"]
        assert len(duplicates) == 1
        assert duplicates[0].detail["term"] == "algebra"

    def test_detects_missing_related_terms(self):
        result = gated_staging(
            domain_id="edu",
            domain_physics=_PHYSICS_WITH_ISSUES,
        )
        enrich = [p for p in result.proposals if p.proposal_type == "glossary_enrich"]
        # "algebra" (first occurrence), "equation", and "algebra" (dup) all lack related_terms
        terms = {p.detail["term"] for p in enrich}
        assert "algebra" in terms
        assert "equation" in terms

    def test_all_proposals_are_pending(self):
        result = gated_staging(
            domain_id="edu",
            domain_physics=_PHYSICS_WITH_ISSUES,
        )
        for prop in result.proposals:
            assert prop.status == "pending"

    def test_all_proposals_have_correct_task(self):
        result = gated_staging(
            domain_id="edu",
            domain_physics=_PHYSICS_WITH_ISSUES,
        )
        for prop in result.proposals:
            assert prop.task == "gated_staging"

    def test_domain_id_propagated(self):
        result = gated_staging(
            domain_id="agri",
            domain_physics=_PHYSICS_WITH_ISSUES,
        )
        for prop in result.proposals:
            assert prop.domain_id == "agri"


# ── SLM-enhanced pass ────────────────────────────────────────


class TestGatedStagingWithSlm:
    def test_draft_glossary_entries(self):
        result = gated_staging(
            domain_id="edu",
            domain_physics=_PHYSICS_CLEAN,
            call_slm_fn=_mock_slm(),
        )
        drafts = [p for p in result.proposals if p.proposal_type == "glossary_draft"]
        assert len(drafts) == 1
        assert drafts[0].detail["term"] == "polynomial"

    def test_existing_terms_not_duplicated(self):
        """SLM suggests a term already in the glossary — should be filtered."""
        slm = _mock_slm([
            {"term": "photosynthesis", "definition": "duplicate", "related_terms": []},
            {"term": "new_concept", "definition": "fresh", "related_terms": []},
        ])
        result = gated_staging(
            domain_id="edu",
            domain_physics=_PHYSICS_CLEAN,
            call_slm_fn=slm,
        )
        draft_terms = {p.detail["term"] for p in result.proposals if p.proposal_type == "glossary_draft"}
        assert "photosynthesis" not in draft_terms
        assert "new_concept" in draft_terms

    def test_slm_error_falls_back_to_heuristic(self):
        result = gated_staging(
            domain_id="edu",
            domain_physics=_PHYSICS_WITH_ISSUES,
            call_slm_fn=_mock_slm_error,
        )
        assert result.success is True
        # Should still have heuristic proposals (duplicates, missing related_terms)
        assert len(result.proposals) > 0

    def test_slm_returns_single_object(self):
        """SLM returning a single dict instead of list should be handled."""
        def _slm(**_):
            return json.dumps({"term": "scalar", "definition": "single value", "related_terms": []})

        result = gated_staging(
            domain_id="edu",
            domain_physics=_PHYSICS_CLEAN,
            call_slm_fn=_slm,
        )
        drafts = [p for p in result.proposals if p.proposal_type == "glossary_draft"]
        assert len(drafts) == 1

    def test_slm_fenced_json(self):
        """SLM wrapping response in markdown fences should still work."""
        def _slm(**_):
            return '```json\n[{"term": "fenced_term", "definition": "yes", "related_terms": []}]\n```'

        result = gated_staging(
            domain_id="edu",
            domain_physics=_PHYSICS_CLEAN,
            call_slm_fn=_slm,
        )
        drafts = [p for p in result.proposals if p.proposal_type == "glossary_draft"]
        assert len(drafts) == 1
        assert drafts[0].detail["term"] == "fenced_term"

    def test_no_modules_skips_slm(self):
        """Without modules the SLM pass should be skipped."""
        physics = {"glossary": _GLOSSARY_CLEAN, "modules": []}
        result = gated_staging(
            domain_id="edu",
            domain_physics=physics,
            call_slm_fn=_mock_slm(),
        )
        drafts = [p for p in result.proposals if p.proposal_type == "glossary_draft"]
        assert len(drafts) == 0


# ── Metadata ──────────────────────────────────────────────────


class TestGatedStagingMetadata:
    def test_metadata_fields_present(self):
        result = gated_staging(
            domain_id="edu",
            domain_physics=_PHYSICS_WITH_ISSUES,
        )
        assert "glossary_size" in result.metadata
        assert "proposals_generated" in result.metadata
        assert result.metadata["glossary_size"] == len(_GLOSSARY_WITH_ISSUES)

    def test_duration_recorded(self):
        result = gated_staging(
            domain_id="test",
            domain_physics=_PHYSICS_CLEAN,
        )
        assert result.duration_seconds >= 0.0


# ── Never auto-commits ───────────────────────────────────────


class TestGatedStagingNeverAutoCommits:
    """Verify that gated_staging only produces proposals — no side effects."""

    def test_all_outputs_are_proposals(self):
        result = gated_staging(
            domain_id="edu",
            domain_physics=_PHYSICS_WITH_ISSUES,
            call_slm_fn=_mock_slm(),
        )
        assert result.success is True
        # The task should ONLY produce proposals, nothing else
        assert isinstance(result.proposals, list)
        for prop in result.proposals:
            assert isinstance(prop, Proposal)
            assert prop.status == "pending"

    def test_result_contains_no_side_effect_metadata(self):
        """Metadata should not indicate any auto-applied changes."""
        result = gated_staging(
            domain_id="edu",
            domain_physics=_PHYSICS_CLEAN,
            call_slm_fn=_mock_slm(),
        )
        # No "applied", "committed", "written" keys in metadata
        for key in result.metadata:
            assert "applied" not in key.lower()
            assert "committed" not in key.lower()
            assert "written" not in key.lower()
