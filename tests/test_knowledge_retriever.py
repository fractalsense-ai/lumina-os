"""Tests for lumina.orchestrator.knowledge_retriever — PPA grounding retrieval."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from lumina.core.knowledge_index import ConceptNode, KnowledgeIndex
from lumina.orchestrator.knowledge_retriever import retrieve_grounding


# ── Fixtures ──────────────────────────────────────────────────

GLOSSARY = [
    {
        "term": "variable",
        "definition": "A symbol representing an unknown value.",
        "aliases": ["var"],
        "related_terms": ["coefficient"],
    },
    {
        "term": "coefficient",
        "definition": "Numerical factor.",
        "aliases": [],
        "related_terms": [],
    },
]


def _build_index() -> KnowledgeIndex:
    """Build a small KnowledgeIndex with glossary + concept graph."""
    ki = KnowledgeIndex()
    ki.build({
        "edu/algebra/v1": {
            "domain": {
                "glossary": GLOSSARY,
                "invariants": [],
                "standing_orders": [],
            },
        },
    })
    return ki


# ── Tests ─────────────────────────────────────────────────────

class TestRetrieveGroundingNoIndex:
    """When no KnowledgeIndex is set, retriever returns empty list."""

    @pytest.mark.unit
    def test_returns_empty_when_no_index(self):
        with patch(
            "lumina.orchestrator.knowledge_retriever._get_knowledge_index",
            return_value=None,
        ):
            refs = retrieve_grounding(
                task_spec={"task_id": "q1", "skills_required": ["variable"]},
                evidence={},
                domain_id="edu/algebra/v1",
            )
        assert refs == []


class TestRetrieveGroundingWithIndex:
    """When a KnowledgeIndex is available, retriever returns references."""

    @pytest.fixture()
    def ki(self):
        return _build_index()

    @pytest.mark.unit
    def test_glossary_hit(self, ki):
        with patch(
            "lumina.orchestrator.knowledge_retriever._get_knowledge_index",
            return_value=ki,
        ):
            refs = retrieve_grounding(
                task_spec={"task_id": "q1", "skills_required": ["variable"]},
                evidence={},
                domain_id="edu/algebra/v1",
            )
        # Should find at least the glossary:... entry for "variable"
        ids = {r["artifact_id"] for r in refs}
        assert "glossary:edu/algebra/v1:variable" in ids

    @pytest.mark.unit
    def test_concept_graph_expansion(self, ki):
        """Glossary hit for 'variable' should also pull 'coefficient' via related_terms edge."""
        with patch(
            "lumina.orchestrator.knowledge_retriever._get_knowledge_index",
            return_value=ki,
        ):
            refs = retrieve_grounding(
                task_spec={"task_id": "q1", "skills_required": ["variable"]},
                evidence={},
                domain_id="edu/algebra/v1",
            )
        ids = {r["artifact_id"] for r in refs}
        assert "glossary:edu/algebra/v1:coefficient" in ids, \
            "1-hop expansion should include 'coefficient'"

    @pytest.mark.unit
    def test_no_duplicates(self, ki):
        """References should not contain duplicate artifact_ids."""
        with patch(
            "lumina.orchestrator.knowledge_retriever._get_knowledge_index",
            return_value=ki,
        ):
            refs = retrieve_grounding(
                task_spec={
                    "task_id": "q1",
                    "skills_required": ["variable", "coefficient"],
                },
                evidence={},
                domain_id="edu/algebra/v1",
            )
        ids = [r["artifact_id"] for r in refs]
        assert len(ids) == len(set(ids)), "No duplicate artifact_ids"

    @pytest.mark.unit
    def test_hash_verified_flag(self, ki):
        with patch(
            "lumina.orchestrator.knowledge_retriever._get_knowledge_index",
            return_value=ki,
        ):
            refs = retrieve_grounding(
                task_spec={"task_id": "q1", "skills_required": ["variable"]},
                evidence={},
                domain_id="edu/algebra/v1",
            )
        assert all(r["hash_verified"] is True for r in refs)

    @pytest.mark.unit
    def test_no_match_returns_empty(self, ki):
        """Terms that are not in the glossary yield no references."""
        with patch(
            "lumina.orchestrator.knowledge_retriever._get_knowledge_index",
            return_value=ki,
        ):
            refs = retrieve_grounding(
                task_spec={"task_id": "q1", "skills_required": ["topology"]},
                evidence={},
                domain_id="edu/algebra/v1",
            )
        assert refs == []

    @pytest.mark.unit
    def test_task_id_included_in_lookup(self, ki):
        """The task_id itself is sent to lookup_terms as well."""
        with patch(
            "lumina.orchestrator.knowledge_retriever._get_knowledge_index",
            return_value=ki,
        ):
            # task_id == "variable" matches the glossary
            refs = retrieve_grounding(
                task_spec={"task_id": "variable", "skills_required": []},
                evidence={},
                domain_id="edu/algebra/v1",
            )
        ids = {r["artifact_id"] for r in refs}
        assert "glossary:edu/algebra/v1:variable" in ids


class TestContractDrafterGrounding:
    """ContractDrafter sets grounded=True when references are supplied."""

    @pytest.mark.unit
    def test_grounded_true_with_references(self):
        from lumina.orchestrator.contract_drafter import ContractDrafter

        drafter = ContractDrafter(
            {"id": "test/v1", "version": "1.0.0"},
            {"id": "subj-1", "preferences": {}},
        )
        contract = drafter.build(
            task_spec={"task_id": "q1", "skills_required": []},
            action=None,
            domain_lib_decision={},
            standing_order_trigger=None,
            references=[{"artifact_id": "x", "artifact_version": "index", "hash_verified": True}],
        )
        assert contract["grounded"] is True
        assert len(contract["references"]) == 1

    @pytest.mark.unit
    def test_grounded_false_without_references(self):
        from lumina.orchestrator.contract_drafter import ContractDrafter

        drafter = ContractDrafter(
            {"id": "test/v1", "version": "1.0.0"},
            {"id": "subj-1", "preferences": {}},
        )
        contract = drafter.build(
            task_spec={"task_id": "q1", "skills_required": []},
            action=None,
            domain_lib_decision={},
            standing_order_trigger=None,
        )
        assert contract["grounded"] is False
        assert contract["references"] == []


class TestActorResolverImportCompat:
    """Backward-compatibility: ActionResolver still importable."""

    @pytest.mark.unit
    def test_action_resolver_shim(self):
        from lumina.orchestrator.action_resolver import ActionResolver
        from lumina.orchestrator.actor_resolver import ActorResolver
        assert ActionResolver is ActorResolver

    @pytest.mark.unit
    def test_init_export(self):
        from lumina.orchestrator import ActionResolver, ActorResolver
        assert ActionResolver is ActorResolver
