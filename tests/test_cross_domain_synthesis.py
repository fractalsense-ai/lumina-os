"""
Tests for cross-domain synthesis analysis, opt-in filtering,
dual-approval proposals, and the night-cycle task integration.
"""

from __future__ import annotations

import pytest

from lumina.daemon.cross_domain import (
    compare_glossaries,
    compare_invariant_structures,
    filter_mutual_pairs,
    find_synthesis_candidates,
    get_opt_in_config,
    is_mutual_peer,
)
from lumina.daemon.report import Proposal
from lumina.daemon.tasks import (
    cross_domain_synthesis_task,
    get_cross_domain_task,
    list_cross_domain_tasks,
)


# ── Fixtures ────────────────────────────────────────────────────

GLOSSARY_EDUCATION = [
    {"term": "variable", "definition": "A symbol for an unknown", "aliases": ["unknown", "x"], "related_terms": ["coefficient"]},
    {"term": "coefficient", "definition": "The number multiplying a variable", "aliases": ["multiplier"], "related_terms": ["variable"]},
    {"term": "equation", "definition": "A statement of equality", "aliases": [], "related_terms": ["expression"]},
    {"term": "expression", "definition": "A combination of terms", "aliases": [], "related_terms": ["equation"]},
    {"term": "solution", "definition": "The value satisfying an equation", "aliases": ["answer"], "related_terms": []},
]

GLOSSARY_AGRICULTURE = [
    {"term": "yield", "definition": "Crop output per unit area", "aliases": ["harvest output"], "related_terms": ["tolerance"]},
    {"term": "tolerance", "definition": "Acceptable deviation range", "aliases": ["margin"], "related_terms": ["yield"]},
    {"term": "variable", "definition": "A changing measurement", "aliases": ["factor"], "related_terms": ["tolerance"]},
    {"term": "solution", "definition": "A liquid mixture for treatment", "aliases": ["spray mix"], "related_terms": []},
]

GLOSSARY_DISJOINT = [
    {"term": "photosynthesis", "definition": "Light-driven synthesis", "aliases": [], "related_terms": []},
    {"term": "chlorophyll", "definition": "Green pigment", "aliases": [], "related_terms": []},
]

INVARIANTS_EDUCATION = [
    {"id": "equiv_preserved", "severity": "critical", "check": "lhs == rhs", "standing_order_on_violation": "request_correction"},
    {"id": "method_recognized", "severity": "warning", "check": "method_recognized", "standing_order_on_violation": "request_justification", "signal_type": "NOVEL_PATTERN"},
    {"id": "show_work", "severity": "warning", "check": "step_count >= 3", "handled_by": "zpd_monitor"},
]

INVARIANTS_AGRICULTURE = [
    {"id": "within_tolerance", "severity": "critical", "check": "reading <= threshold", "standing_order_on_violation": "flag_out_of_range"},
    {"id": "novel_correlation", "severity": "warning", "check": "correlation_known", "standing_order_on_violation": "request_evidence", "signal_type": "NOVEL_PATTERN"},
    {"id": "soil_health", "severity": "warning", "check": "soil_ok", "handled_by": "soil_health_monitor"},
]


def _make_physics(
    enabled: bool = True,
    peer_domains: list[str] | None = None,
    glossary: list[dict] | None = None,
    invariants: list[dict] | None = None,
    share_glossary: bool = True,
    share_invariant_structure: bool = True,
) -> dict:
    physics: dict = {}
    if enabled:
        physics["cross_domain_synthesis"] = {
            "enabled": True,
            "peer_domains": peer_domains or [],
            "share_glossary": share_glossary,
            "share_invariant_structure": share_invariant_structure,
        }
    if glossary is not None:
        physics["glossary"] = glossary
    if invariants is not None:
        physics["invariants"] = invariants
    return physics


def _make_domain(domain_id: str, physics: dict) -> dict:
    return {"domain_id": domain_id, "physics": physics}


# ── Opt-in filtering tests ──────────────────────────────────────

class TestOptInFiltering:
    def test_disabled_returns_none(self):
        physics = {"cross_domain_synthesis": {"enabled": False}}
        assert get_opt_in_config(physics) is None

    def test_missing_returns_none(self):
        assert get_opt_in_config({}) is None

    def test_enabled_returns_config(self):
        cfg = {"enabled": True, "peer_domains": ["agriculture"]}
        physics = {"cross_domain_synthesis": cfg}
        result = get_opt_in_config(physics)
        assert result is not None
        assert result["peer_domains"] == ["agriculture"]

    def test_mutual_opt_in(self):
        physics_a = _make_physics(enabled=True, peer_domains=["agriculture"])
        physics_b = _make_physics(enabled=True, peer_domains=["education"])
        assert is_mutual_peer("education", physics_a, "agriculture", physics_b)

    def test_one_sided_opt_in_denied(self):
        physics_a = _make_physics(enabled=True, peer_domains=["agriculture"])
        physics_b = _make_physics(enabled=True, peer_domains=[])
        assert not is_mutual_peer("education", physics_a, "agriculture", physics_b)

    def test_one_disabled_denied(self):
        physics_a = _make_physics(enabled=True, peer_domains=["agriculture"])
        physics_b = _make_physics(enabled=False)
        assert not is_mutual_peer("education", physics_a, "agriculture", physics_b)

    def test_filter_mutual_pairs(self):
        domains = [
            _make_domain("education", _make_physics(True, ["agriculture"])),
            _make_domain("agriculture", _make_physics(True, ["education"])),
            _make_domain("healthcare", _make_physics(False)),
        ]
        pairs = filter_mutual_pairs(domains)
        assert len(pairs) == 1
        ids = {pairs[0][0]["domain_id"], pairs[0][1]["domain_id"]}
        assert ids == {"education", "agriculture"}


# ── Glossary comparison tests ───────────────────────────────────

class TestGlossaryComparison:
    def test_overlap_detection(self):
        result = compare_glossaries(GLOSSARY_EDUCATION, GLOSSARY_AGRICULTURE)
        assert "variable" in result["shared_terms"]
        assert "solution" in result["shared_terms"]
        assert result["score"] > 0

    def test_no_overlap(self):
        result = compare_glossaries(GLOSSARY_EDUCATION, GLOSSARY_DISJOINT)
        assert result["shared_terms"] == []
        assert result["score"] == 0.0
        assert not result["passes_threshold"]

    def test_empty_glossary_a(self):
        result = compare_glossaries([], GLOSSARY_AGRICULTURE)
        assert result["score"] == 0.0
        assert not result["passes_threshold"]

    def test_empty_glossary_b(self):
        result = compare_glossaries(GLOSSARY_EDUCATION, [])
        assert result["score"] == 0.0
        assert not result["passes_threshold"]

    def test_alias_matching(self):
        """Aliases from one glossary should match canonical terms in the other."""
        glossary_a = [{"term": "unknown", "definition": "...", "aliases": []}]
        glossary_b = [{"term": "variable", "definition": "...", "aliases": ["unknown"]}]
        result = compare_glossaries(glossary_a, glossary_b, min_overlap=0.0)
        assert "unknown" in result["shared_terms"]

    def test_threshold_respected(self):
        """With a high threshold, moderate overlap should fail."""
        result = compare_glossaries(GLOSSARY_EDUCATION, GLOSSARY_AGRICULTURE, min_overlap=0.9)
        assert not result["passes_threshold"]

    def test_related_terms_overlap(self):
        result = compare_glossaries(GLOSSARY_EDUCATION, GLOSSARY_AGRICULTURE)
        # Both glossaries reference "tolerance" or "coefficient" etc in related_terms
        # The specific overlap depends on data but should be computed
        assert isinstance(result["shared_related"], list)


# ── Invariant structure comparison tests ────────────────────────

class TestInvariantStructureComparison:
    def test_matching_structures_detected(self):
        result = compare_invariant_structures(INVARIANTS_EDUCATION, INVARIANTS_AGRICULTURE)
        assert len(result["matched_pairs"]) > 0
        assert result["score"] > 0

    def test_identical_invariants_full_match(self):
        result = compare_invariant_structures(INVARIANTS_EDUCATION, INVARIANTS_EDUCATION)
        assert result["score"] == 1.0
        assert len(result["matched_pairs"]) == len(INVARIANTS_EDUCATION)

    def test_empty_invariants(self):
        result = compare_invariant_structures([], INVARIANTS_AGRICULTURE)
        assert result["score"] == 0.0
        assert len(result["matched_pairs"]) == 0

    def test_no_structural_match(self):
        """Invariants with completely different structures should not match."""
        inv_a = [{"id": "a", "severity": "critical", "check": "x", "signal_type": "FOO"}]
        inv_b = [{"id": "b", "severity": "warning", "handled_by": "some_monitor"}]
        result = compare_invariant_structures(inv_a, inv_b)
        assert result["score"] == 0.0

    def test_matched_pair_contains_ids(self):
        result = compare_invariant_structures(INVARIANTS_EDUCATION, INVARIANTS_AGRICULTURE)
        for pair in result["matched_pairs"]:
            assert "invariant_a_id" in pair
            assert "invariant_b_id" in pair
            assert "shared_signature" in pair


# ── Dual-approval proposal tests ───────────────────────────────

class TestDualApproval:
    def test_dual_approval_both_approve(self):
        prop = Proposal(
            task="cross_domain_synthesis",
            domain_id="education+agriculture",
            proposal_type="cross_domain_similarity",
            summary="Test",
            required_approvers=["education", "agriculture"],
        )
        prop.resolve_approval("education", "approved")
        assert prop.status == "pending"  # still waiting for agriculture

        prop.resolve_approval("agriculture", "approved")
        assert prop.status == "approved"

    def test_partial_approval_stays_pending(self):
        prop = Proposal(
            task="cross_domain_synthesis",
            domain_id="education+agriculture",
            proposal_type="cross_domain_similarity",
            summary="Test",
            required_approvers=["education", "agriculture"],
        )
        prop.resolve_approval("education", "approved")
        assert prop.status == "pending"

    def test_any_rejection_rejects(self):
        prop = Proposal(
            task="cross_domain_synthesis",
            domain_id="education+agriculture",
            proposal_type="cross_domain_similarity",
            summary="Test",
            required_approvers=["education", "agriculture"],
        )
        prop.resolve_approval("education", "approved")
        prop.resolve_approval("agriculture", "rejected")
        assert prop.status == "rejected"

    def test_rejection_first_rejects_immediately(self):
        prop = Proposal(
            task="cross_domain_synthesis",
            domain_id="education+agriculture",
            proposal_type="cross_domain_similarity",
            summary="Test",
            required_approvers=["education", "agriculture"],
        )
        prop.resolve_approval("agriculture", "rejected")
        assert prop.status == "rejected"

    def test_invalid_decision_raises(self):
        prop = Proposal(
            task="cross_domain_synthesis",
            required_approvers=["education"],
        )
        with pytest.raises(ValueError, match="decision must be"):
            prop.resolve_approval("education", "maybe")

    def test_to_dict_includes_approvals_when_present(self):
        prop = Proposal(
            task="cross_domain_synthesis",
            required_approvers=["education", "agriculture"],
        )
        d = prop.to_dict()
        assert "required_approvers" in d
        assert "approvals" in d

    def test_to_dict_omits_approvals_when_empty(self):
        prop = Proposal(task="glossary_expansion")
        d = prop.to_dict()
        assert "required_approvers" not in d
        assert "approvals" not in d

    def test_legacy_single_approval_still_works(self):
        """Proposals without required_approvers use the legacy path."""
        prop = Proposal(task="glossary_expansion", summary="Test")
        prop.resolve_approval("education", "approved")
        assert prop.status == "approved"


# ── Night cycle task registration tests ─────────────────────────

class TestCrossDomainTaskRegistration:
    def test_task_is_registered(self):
        assert "cross_domain_synthesis" in list_cross_domain_tasks()

    def test_get_cross_domain_task_returns_callable(self):
        fn = get_cross_domain_task("cross_domain_synthesis")
        assert fn is not None
        assert callable(fn)


# ── Full integration: cross_domain_synthesis_task ────────────────

class TestCrossDomainSynthesisTask:
    def test_no_opt_in_domains_produces_no_proposals(self):
        domains = [
            _make_domain("education", _make_physics(False)),
            _make_domain("agriculture", _make_physics(False)),
        ]
        result = cross_domain_synthesis_task(domains=domains)
        assert result.success
        assert len(result.proposals) == 0

    def test_mutual_opt_in_with_similar_physics_produces_proposals(self):
        domains = [
            _make_domain(
                "education",
                _make_physics(True, ["agriculture"],
                              glossary=GLOSSARY_EDUCATION,
                              invariants=INVARIANTS_EDUCATION),
            ),
            _make_domain(
                "agriculture",
                _make_physics(True, ["education"],
                              glossary=GLOSSARY_AGRICULTURE,
                              invariants=INVARIANTS_AGRICULTURE),
            ),
        ]
        result = cross_domain_synthesis_task(domains=domains)
        assert result.success
        assert len(result.proposals) > 0
        # Each proposal should be dual-approval
        for prop in result.proposals:
            assert prop.proposal_type == "cross_domain_similarity"
            assert len(prop.required_approvers) == 2

    def test_one_sided_opt_in_produces_no_proposals(self):
        domains = [
            _make_domain("education", _make_physics(True, ["agriculture"],
                          glossary=GLOSSARY_EDUCATION, invariants=INVARIANTS_EDUCATION)),
            _make_domain("agriculture", _make_physics(True, [],
                          glossary=GLOSSARY_AGRICULTURE, invariants=INVARIANTS_AGRICULTURE)),
        ]
        result = cross_domain_synthesis_task(domains=domains)
        assert result.success
        assert len(result.proposals) == 0

    def test_metadata_includes_pair_counts(self):
        domains = [
            _make_domain("education", _make_physics(True, ["agriculture"],
                          glossary=GLOSSARY_EDUCATION, invariants=INVARIANTS_EDUCATION)),
            _make_domain("agriculture", _make_physics(True, ["education"],
                          glossary=GLOSSARY_AGRICULTURE, invariants=INVARIANTS_AGRICULTURE)),
        ]
        result = cross_domain_synthesis_task(domains=domains)
        assert "pairs_analysed" in result.metadata
        assert "candidates_found" in result.metadata

    def test_task_result_domain_id_is_cross_domain(self):
        domains = [_make_domain("a", _make_physics(False))]
        result = cross_domain_synthesis_task(domains=domains)
        assert result.domain_id == "cross_domain"


# ── find_synthesis_candidates tests ─────────────────────────────

class TestFindSynthesisCandidates:
    def test_empty_domains_returns_empty(self):
        assert find_synthesis_candidates([]) == []

    def test_single_domain_returns_empty(self):
        domains = [_make_domain("education", _make_physics(True, []))]
        assert find_synthesis_candidates(domains) == []

    def test_glossary_only_candidate(self):
        """Pair with glossary overlap but no invariants should be a candidate."""
        domains = [
            _make_domain("education", _make_physics(True, ["agriculture"],
                          glossary=GLOSSARY_EDUCATION)),
            _make_domain("agriculture", _make_physics(True, ["education"],
                          glossary=GLOSSARY_AGRICULTURE)),
        ]
        results = find_synthesis_candidates(domains)
        assert len(results) == 1
        assert results[0]["is_candidate"]
        assert results[0]["glossary_result"]["passes_threshold"]

    def test_invariant_only_candidate(self):
        """Pair with no glossary but matching invariant structures should be a candidate."""
        domains = [
            _make_domain("education", _make_physics(True, ["agriculture"],
                          invariants=INVARIANTS_EDUCATION)),
            _make_domain("agriculture", _make_physics(True, ["education"],
                          invariants=INVARIANTS_AGRICULTURE)),
        ]
        results = find_synthesis_candidates(domains)
        assert len(results) == 1
        assert results[0]["is_candidate"]
