"""Tests for lumina.core.knowledge_index — Global Knowledge Index."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lumina.core.knowledge_index import ConceptEdge, ConceptNode, KnowledgeIndex


# ── Fixtures ──────────────────────────────────────────────────

def _make_domain_context(
    *,
    glossary: list | None = None,
    modules: list | None = None,
    invariants: list | None = None,
    standing_orders: list | None = None,
) -> dict:
    """Wrap domain-physics sections into the runtime context shape."""
    physics: dict = {}
    if glossary is not None:
        physics["glossary"] = glossary
    if modules is not None:
        physics["modules"] = modules
    if invariants is not None:
        physics["invariants"] = invariants
    if standing_orders is not None:
        physics["standing_orders"] = standing_orders
    return {"domain": physics}


SAMPLE_GLOSSARY = [
    {
        "term": "variable",
        "definition": "A symbol representing an unknown value.",
        "aliases": ["var", "unknown"],
        "related_terms": ["coefficient", "constant"],
    },
    {
        "term": "coefficient",
        "definition": "The numerical factor multiplied by a variable.",
        "aliases": ["coeff"],
        "related_terms": ["variable"],
    },
    {
        "term": "constant",
        "definition": "A fixed value that does not change.",
        "aliases": [],
        "related_terms": [],
    },
]

SAMPLE_MODULES = [
    {
        "module_id": "linear-equations",
        "description": "Solving one-variable linear equations.",
        "prerequisites": [],
        "artifacts": [
            {"name": "solve_linear", "mastery_threshold": 0.8},
            {"name": "graph_linear", "mastery_threshold": 0.7},
        ],
    },
    {
        "module_id": "quadratics",
        "description": "Factoring and solving quadratic equations.",
        "prerequisites": ["linear-equations"],
        "artifacts": [
            {"name": "factor_quadratic", "mastery_threshold": 0.75},
        ],
    },
]

SAMPLE_INVARIANTS = [
    {
        "id": "equivalence_preserved",
        "description": "Both sides remain equal after transformation.",
        "severity": "critical",
        "standing_order_on_violation": "request_more_steps",
    },
]

SAMPLE_STANDING_ORDERS = [
    {
        "id": "request_more_steps",
        "description": "Ask the student to show intermediate steps.",
    },
]


# ═══════════════════════════════════════════════════════════════
#   ConceptNode / ConceptEdge
# ═══════════════════════════════════════════════════════════════


class TestConceptNode:
    @pytest.mark.unit
    def test_round_trip(self):
        node = ConceptNode(
            node_id="glossary:edu:variable",
            label="variable",
            kind="glossary_term",
            domain_id="education",
            detail={"definition": "A symbol"},
        )
        d = node.to_dict()
        restored = ConceptNode.from_dict(d)
        assert restored.node_id == node.node_id
        assert restored.detail == node.detail

    @pytest.mark.unit
    def test_from_dict_missing_detail(self):
        node = ConceptNode.from_dict({
            "node_id": "x", "label": "x", "kind": "module", "domain_id": "d",
        })
        assert node.detail == {}


class TestConceptEdge:
    @pytest.mark.unit
    def test_round_trip(self):
        edge = ConceptEdge(source="a", target="b", relation="related_term")
        restored = ConceptEdge.from_dict(edge.to_dict())
        assert restored.source == "a"
        assert restored.relation == "related_term"


# ═══════════════════════════════════════════════════════════════
#   KnowledgeIndex.build
# ═══════════════════════════════════════════════════════════════


class TestKnowledgeIndexBuild:
    @pytest.mark.unit
    def test_build_glossary_routing(self):
        idx = KnowledgeIndex()
        ctx = _make_domain_context(glossary=SAMPLE_GLOSSARY)
        summary = idx.build({"education": ctx})

        assert summary["glossary_terms"] > 0
        assert idx.lookup_term("variable") == "education"
        assert idx.lookup_term("var") == "education"
        assert idx.lookup_term("coeff") == "education"
        assert idx.lookup_term("nonexistent") is None

    @pytest.mark.unit
    def test_build_modules_and_artifacts(self):
        idx = KnowledgeIndex()
        ctx = _make_domain_context(modules=SAMPLE_MODULES)
        summary = idx.build({"education": ctx})

        assert summary["concept_nodes"] >= 2  # modules
        node = idx.get_node("module:education:quadratics")
        assert node is not None
        assert node.kind == "module"

        art = idx.get_node("artifact:education:solve_linear")
        assert art is not None
        assert art.kind == "artifact"

    @pytest.mark.unit
    def test_build_invariants_and_standing_orders(self):
        idx = KnowledgeIndex()
        ctx = _make_domain_context(
            invariants=SAMPLE_INVARIANTS,
            standing_orders=SAMPLE_STANDING_ORDERS,
        )
        summary = idx.build({"education": ctx})

        inv = idx.get_node("invariant:education:equivalence_preserved")
        assert inv is not None
        assert inv.detail["severity"] == "critical"

        so = idx.get_node("standing_order:education:request_more_steps")
        assert so is not None

        assert summary["concept_edges"] >= 1  # governs edge

    @pytest.mark.unit
    def test_build_multi_domain(self):
        idx = KnowledgeIndex()
        edu_ctx = _make_domain_context(glossary=[
            {"term": "equation", "aliases": ["eq"], "related_terms": []},
        ])
        agri_ctx = _make_domain_context(glossary=[
            {"term": "crop", "aliases": ["harvest"], "related_terms": []},
        ])
        idx.build({"education": edu_ctx, "agriculture": agri_ctx})

        assert idx.lookup_term("equation") == "education"
        assert idx.lookup_term("crop") == "agriculture"
        assert idx.lookup_term("harvest") == "agriculture"

    @pytest.mark.unit
    def test_build_empty_context(self):
        idx = KnowledgeIndex()
        summary = idx.build({})
        assert summary["glossary_terms"] == 0
        assert summary["concept_nodes"] == 0

    @pytest.mark.unit
    def test_rebuild_replaces_old_data(self):
        idx = KnowledgeIndex()
        idx.build({"education": _make_domain_context(glossary=[
            {"term": "old_term", "aliases": [], "related_terms": []},
        ])})
        assert idx.lookup_term("old_term") == "education"

        idx.build({"education": _make_domain_context(glossary=[
            {"term": "new_term", "aliases": [], "related_terms": []},
        ])})
        assert idx.lookup_term("old_term") is None
        assert idx.lookup_term("new_term") == "education"


# ═══════════════════════════════════════════════════════════════
#   KnowledgeIndex.get_related
# ═══════════════════════════════════════════════════════════════


class TestGetRelated:
    @pytest.mark.unit
    def test_related_terms_depth_1(self):
        idx = KnowledgeIndex()
        idx.build({"education": _make_domain_context(glossary=SAMPLE_GLOSSARY)})
        related = idx.get_related("glossary:education:variable", depth=1)
        labels = {n.label for n in related}
        # "variable" has related_terms: coefficient, constant
        assert "coefficient" in labels or len(related) > 0

    @pytest.mark.unit
    def test_prerequisite_traversal(self):
        idx = KnowledgeIndex()
        idx.build({"education": _make_domain_context(modules=SAMPLE_MODULES)})
        related = idx.get_related("module:education:quadratics", depth=1)
        ids = {n.node_id for n in related}
        assert "module:education:linear-equations" in ids


# ═══════════════════════════════════════════════════════════════
#   KnowledgeIndex persistence
# ═══════════════════════════════════════════════════════════════


class TestPersistence:
    @pytest.mark.unit
    def test_save_and_load(self, tmp_path: Path):
        idx = KnowledgeIndex()
        ctx = _make_domain_context(
            glossary=SAMPLE_GLOSSARY,
            modules=SAMPLE_MODULES,
            invariants=SAMPLE_INVARIANTS,
            standing_orders=SAMPLE_STANDING_ORDERS,
        )
        idx.build({"education": ctx})
        idx.save(tmp_path)

        assert (tmp_path / "glossary_table.json").exists()
        assert (tmp_path / "concept_graph.json").exists()

        idx2 = KnowledgeIndex()
        assert idx2.load(tmp_path) is True
        assert idx2.lookup_term("variable") == "education"
        assert idx2.get_node("module:education:quadratics") is not None
        assert idx2.stats["glossary_terms"] == idx.stats["glossary_terms"]

    @pytest.mark.unit
    def test_load_missing_dir(self, tmp_path: Path):
        idx = KnowledgeIndex()
        assert idx.load(tmp_path / "nonexistent") is False

    @pytest.mark.unit
    def test_persisted_json_structure(self, tmp_path: Path):
        idx = KnowledgeIndex()
        idx.build({"edu": _make_domain_context(glossary=[
            {"term": "x", "aliases": ["y"], "related_terms": []},
        ])})
        idx.save(tmp_path)
        gt = json.loads((tmp_path / "glossary_table.json").read_text())
        assert gt["x"] == "edu"
        assert gt["y"] == "edu"

        cg = json.loads((tmp_path / "concept_graph.json").read_text())
        assert "nodes" in cg
        assert "edges" in cg


# ═══════════════════════════════════════════════════════════════
#   NLP Pass 0 integration
# ═══════════════════════════════════════════════════════════════


class TestNlpGlossaryRouting:
    @pytest.mark.unit
    def test_classify_domain_glossary_pass0(self):
        """classify_domain returns glossary method when index is set."""
        import lumina.core.nlp as nlp_mod
        from lumina.core.nlp import classify_domain, set_knowledge_index

        idx = KnowledgeIndex()
        idx.build({
            "education": _make_domain_context(glossary=[
                {"term": "variable", "aliases": ["var", "unknown"], "related_terms": []},
                {"term": "coefficient", "aliases": ["coeff"], "related_terms": []},
            ]),
        })

        old_idx = nlp_mod._knowledge_index
        try:
            set_knowledge_index(idx)
            domain_map = {
                "education": {"label": "Education", "description": "Math", "keywords": []},
                "agriculture": {"label": "Agriculture", "description": "Farming", "keywords": []},
            }
            # Message with enough glossary hits for confidence >= 0.6
            result = classify_domain(
                "I need help with a variable and a coefficient",
                domain_map,
            )
            assert result is not None
            assert result["domain_id"] == "education"
            assert result["method"] == "glossary"
        finally:
            nlp_mod._knowledge_index = old_idx

    @pytest.mark.unit
    def test_classify_domain_no_index_falls_through(self):
        """When no index is set, Pass 0 is skipped and keyword/similarity used."""
        import lumina.core.nlp as nlp_mod
        from lumina.core.nlp import classify_domain

        old_idx = nlp_mod._knowledge_index
        try:
            nlp_mod._knowledge_index = None
            domain_map = {
                "education": {
                    "label": "Education",
                    "description": "Math tutoring",
                    "keywords": ["algebra", "equation"],
                },
            }
            result = classify_domain("solve this algebra equation", domain_map)
            assert result is not None
            assert result["method"] in ("keyword", "similarity", "description")
        finally:
            nlp_mod._knowledge_index = old_idx


# ═══════════════════════════════════════════════════════════════
#   knowledge_graph_rebuild task
# ═══════════════════════════════════════════════════════════════


class TestKnowledgeGraphRebuildTask:
    @pytest.mark.unit
    def test_single_domain_rebuild(self, tmp_path: Path):
        from lumina.daemon.tasks import knowledge_graph_rebuild

        physics = {
            "glossary": [{"term": "photosynthesis", "aliases": [], "related_terms": []}],
            "modules": [{"module_id": "bio-1", "artifacts": [{"name": "cell_diagram"}]}],
        }
        result = knowledge_graph_rebuild(
            domain_id="biology",
            domain_physics=physics,
            index_dir=tmp_path,
        )
        assert result.success is True
        assert result.metadata["glossary_terms"] >= 1
        assert (tmp_path / "glossary_table.json").exists()

    @pytest.mark.unit
    def test_multi_domain_rebuild(self, tmp_path: Path):
        from lumina.daemon.tasks import knowledge_graph_rebuild

        all_contexts = {
            "education": _make_domain_context(glossary=[
                {"term": "equation", "aliases": [], "related_terms": []},
            ]),
            "agriculture": _make_domain_context(glossary=[
                {"term": "crop", "aliases": [], "related_terms": []},
            ]),
        }
        result = knowledge_graph_rebuild(
            domain_id="education",
            domain_physics={},
            all_domain_contexts=all_contexts,
            index_dir=tmp_path,
        )
        assert result.success is True
        assert result.metadata["domains_indexed"] == 2

        gt = json.loads((tmp_path / "glossary_table.json").read_text())
        assert gt["equation"] == "education"
        assert gt["crop"] == "agriculture"
