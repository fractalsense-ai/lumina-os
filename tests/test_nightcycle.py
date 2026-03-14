"""Tests for the night cycle subsystem."""

from __future__ import annotations

import pytest
from lumina.nightcycle.report import NightCycleReport, Proposal, TaskResult
from lumina.nightcycle.scheduler import NightCycleScheduler
from lumina.nightcycle.tasks import (
    get_task,
    glossary_expansion,
    glossary_pruning,
    rejection_corpus_alignment,
    cross_module_consistency,
    knowledge_graph_rebuild,
    pacing_heuristic_recompute,
    domain_physics_constraint_refresh,
    slm_hint_generation,
    telemetry_summary_refresh,
    list_tasks,
)


# ── Report dataclass tests ───────────────────────────────────


class TestProposal:
    def test_defaults(self):
        p = Proposal(task="t", domain_id="d", summary="s")
        assert p.status == "pending"
        assert p.proposal_id  # uuid generated
        assert p.to_dict()["task"] == "t"

    def test_to_dict(self):
        p = Proposal(
            task="glossary_expansion",
            domain_id="edu",
            proposal_type="glossary_add",
            summary="New term: foo",
            detail={"term": "foo"},
        )
        d = p.to_dict()
        assert d["proposal_type"] == "glossary_add"
        assert d["detail"] == {"term": "foo"}


class TestTaskResult:
    def test_success(self):
        r = TaskResult(task="t", domain_id="d", success=True, duration_seconds=0.5)
        d = r.to_dict()
        assert d["success"] is True
        assert d["error"] is None

    def test_with_proposals(self):
        p = Proposal(task="t", domain_id="d", summary="s")
        r = TaskResult(task="t", domain_id="d", proposals=[p])
        d = r.to_dict()
        assert len(d["proposals"]) == 1


class TestNightCycleReport:
    def test_finish_success(self):
        report = NightCycleReport()
        report.task_results.append(TaskResult(task="t", success=True))
        report.finish()
        assert report.status == "completed"
        assert report.finished_at is not None

    def test_finish_failure(self):
        report = NightCycleReport()
        report.task_results.append(TaskResult(task="t1", success=True))
        report.task_results.append(TaskResult(task="t2", success=False, error="boom"))
        report.finish()
        assert report.status == "failed"

    def test_total_proposals(self):
        p1 = Proposal(task="t", domain_id="d", summary="a")
        p2 = Proposal(task="t", domain_id="d", summary="b")
        report = NightCycleReport()
        report.task_results.append(TaskResult(task="t", proposals=[p1, p2]))
        report.finish()
        assert report.total_proposals == 2


# ── Task function tests ──────────────────────────────────────


class TestTaskRegistry:
    def test_all_nine_registered(self):
        tasks = list_tasks()
        assert len(tasks) == 9
        assert "glossary_expansion" in tasks
        assert "telemetry_summary_refresh" in tasks

    def test_get_task(self):
        fn = get_task("glossary_expansion")
        assert fn is not None
        assert fn is glossary_expansion

    def test_get_unknown(self):
        assert get_task("nonexistent") is None


class TestGlossaryExpansion:
    def test_empty_physics(self):
        result = glossary_expansion(domain_id="test", domain_physics={})
        assert result.success is True
        assert result.task == "glossary_expansion"

    def test_existing_glossary(self):
        physics = {"glossary": [{"term": "algebra", "definition": "math branch"}]}
        result = glossary_expansion(domain_id="test", domain_physics=physics)
        assert result.success is True


class TestGlossaryPruning:
    def test_no_glossary(self):
        result = glossary_pruning(domain_id="test", domain_physics={})
        assert result.success is True
        assert len(result.proposals) == 0

    def test_missing_definition(self):
        physics = {"glossary": [{"term": "orphan"}]}
        result = glossary_pruning(domain_id="test", domain_physics=physics)
        assert result.success is True
        assert any(p.proposal_type == "glossary_prune" for p in result.proposals)


class TestRejectionCorpusAlignment:
    def test_no_corpus(self):
        result = rejection_corpus_alignment(domain_id="test", domain_physics={})
        assert result.success is True

    def test_stale_module_ref(self):
        physics = {
            "modules": [{"module_id": "m1"}],
            "rejection_corpus": [{"module_id": "m_deleted"}],
        }
        result = rejection_corpus_alignment(domain_id="test", domain_physics=physics)
        assert any(p.proposal_type == "rejection_stale" for p in result.proposals)


class TestCrossModuleConsistency:
    def test_no_cycle(self):
        physics = {
            "modules": [
                {"module_id": "a", "prerequisites": []},
                {"module_id": "b", "prerequisites": ["a"]},
            ]
        }
        result = cross_module_consistency(domain_id="test", domain_physics=physics)
        assert result.success is True
        assert len(result.proposals) == 0

    def test_cycle_detected(self):
        physics = {
            "modules": [
                {"module_id": "a", "prerequisites": ["b"]},
                {"module_id": "b", "prerequisites": ["a"]},
            ]
        }
        result = cross_module_consistency(domain_id="test", domain_physics=physics)
        assert any(p.proposal_type == "prerequisite_cycle" for p in result.proposals)


class TestKnowledgeGraphRebuild:
    def test_with_artifacts(self):
        physics = {
            "modules": [{"module_id": "m1", "artifacts": [{"name": "concept_a"}]}]
        }
        result = knowledge_graph_rebuild(domain_id="test", domain_physics=physics)
        assert result.success is True
        assert result.metadata["concept_count"] == 1


class TestDomainPhysicsConstraintRefresh:
    def test_orphan_invariant(self):
        physics = {
            "modules": [{"module_id": "m1"}],
            "invariants": [{"id": "inv1", "applies_to": ["m_missing"]}],
        }
        result = domain_physics_constraint_refresh(domain_id="test", domain_physics=physics)
        assert any(p.proposal_type == "invariant_orphan" for p in result.proposals)


# ── Scheduler tests ──────────────────────────────────────────


class TestNightCycleScheduler:
    def _make_scheduler(self, **kwargs):
        domains = [
            {"domain_id": "edu", "physics": {"modules": [], "glossary": []}},
        ]
        return NightCycleScheduler(
            config={"enabled": True, "schedule": "0 2 * * *", "max_duration_minutes": 5},
            domain_loader=lambda: domains,
            **kwargs,
        )

    def test_status_initial(self):
        sched = self._make_scheduler()
        status = sched.get_status()
        assert status["enabled"] is True
        assert status["is_running"] is False
        assert status["run_count"] == 0

    def test_manual_trigger(self):
        sched = self._make_scheduler()
        report = sched.trigger_manual(actor_id="user1")
        assert report.status in ("completed", "failed")
        assert report.triggered_by == "user1"
        # Should have results for each domain × task
        assert len(report.task_results) > 0

    def test_status_after_run(self):
        sched = self._make_scheduler()
        sched.trigger_manual(actor_id="user1")
        status = sched.get_status()
        assert status["run_count"] == 1
        assert status["last_run"] is not None
        assert status["last_run"]["triggered_by"] == "user1"

    def test_get_report(self):
        sched = self._make_scheduler()
        report = sched.trigger_manual(actor_id="user1")
        fetched = sched.get_report(report.run_id)
        assert fetched is not None
        assert fetched["run_id"] == report.run_id

    def test_get_report_missing(self):
        sched = self._make_scheduler()
        assert sched.get_report("nonexistent") is None

    def test_pending_proposals(self):
        # Create a domain with prunable glossary entries
        domains = [
            {"domain_id": "edu", "physics": {"glossary": [{"term": "orphan"}]}},
        ]
        sched = NightCycleScheduler(
            config={"enabled": True, "tasks": ["glossary_pruning"]},
            domain_loader=lambda: domains,
        )
        sched.trigger_manual(actor_id="user1")
        proposals = sched.get_pending_proposals()
        assert len(proposals) > 0
        assert all(p["status"] == "pending" for p in proposals)

    def test_proposals_domain_filter(self):
        domains = [
            {"domain_id": "edu", "physics": {"glossary": [{"term": "x"}]}},
            {"domain_id": "agri", "physics": {"glossary": [{"term": "y"}]}},
        ]
        sched = NightCycleScheduler(
            config={"enabled": True, "tasks": ["glossary_pruning"]},
            domain_loader=lambda: domains,
        )
        sched.trigger_manual(actor_id="user1")
        edu_props = sched.get_pending_proposals(domain_id="edu")
        agri_props = sched.get_pending_proposals(domain_id="agri")
        assert all(p["domain_id"] == "edu" for p in edu_props)
        assert all(p["domain_id"] == "agri" for p in agri_props)

    def test_resolve_proposal(self):
        domains = [{"domain_id": "d", "physics": {"glossary": [{"term": "x"}]}}]
        sched = NightCycleScheduler(
            config={"tasks": ["glossary_pruning"]},
            domain_loader=lambda: domains,
        )
        sched.trigger_manual(actor_id="user1")
        proposals = sched.get_pending_proposals()
        assert len(proposals) > 0
        pid = proposals[0]["proposal_id"]
        assert sched.resolve_proposal(pid, "approved") is True
        # Should no longer be in pending
        remaining = sched.get_pending_proposals()
        assert all(p["proposal_id"] != pid for p in remaining)

    def test_resolve_invalid_action(self):
        sched = self._make_scheduler()
        assert sched.resolve_proposal("xxx", "invalid") is False

    def test_resolve_missing_proposal(self):
        sched = self._make_scheduler()
        assert sched.resolve_proposal("nonexistent", "approved") is False

    def test_trigger_async(self):
        import time
        sched = self._make_scheduler()
        run_id = sched.trigger_async(actor_id="user1")
        assert isinstance(run_id, str)
        # Wait for completion
        for _ in range(50):
            time.sleep(0.05)
            report = sched.get_report(run_id)
            if report and report.get("status") != "running":
                break
        report = sched.get_report(run_id)
        assert report is not None
        assert report["status"] in ("completed", "failed")

    def test_configured_tasks(self):
        sched = NightCycleScheduler(
            config={"tasks": ["glossary_pruning", "knowledge_graph_rebuild"]},
        )
        assert sched.configured_tasks == ["glossary_pruning", "knowledge_graph_rebuild"]

    def test_schedule_property(self):
        sched = NightCycleScheduler(config={"schedule": "0 3 * * 1"})
        assert sched.schedule == "0 3 * * 1"

    def test_domain_id_filter(self):
        domains = [
            {"domain_id": "edu", "physics": {}},
            {"domain_id": "agri", "physics": {}},
        ]
        sched = NightCycleScheduler(
            config={"tasks": ["knowledge_graph_rebuild"]},
            domain_loader=lambda: domains,
        )
        report = sched.trigger_manual(actor_id="user1", domain_ids=["edu"])
        domain_ids = {r.domain_id for r in report.task_results}
        assert domain_ids == {"edu"}
