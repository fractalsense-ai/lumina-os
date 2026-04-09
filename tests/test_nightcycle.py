"""Tests for the night cycle subsystem."""

from __future__ import annotations

import pytest
from lumina.daemon.report import NightCycleReport, Proposal, TaskResult
from lumina.daemon.scheduler import NightCycleScheduler
from lumina.daemon.tasks import (
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
    context_crawler,
    gated_staging,
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
    def test_all_registered(self):
        tasks = list_tasks()
        assert len(tasks) == 13
        assert "glossary_expansion" in tasks
        assert "telemetry_summary_refresh" in tasks
        assert "logic_scrape_review" in tasks
        assert "context_crawler" in tasks
        assert "gated_staging" in tasks
        assert "rebuild_domain_vectors" in tasks

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
        assert result.metadata["concept_count"] >= 1


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
    _LIGHTWEIGHT_TASKS = ["glossary_pruning", "glossary_expansion"]

    def _make_scheduler(self, **kwargs):
        domains = [
            {"domain_id": "edu", "physics": {"modules": [], "glossary": []}},
        ]
        return NightCycleScheduler(
            config={"enabled": True, "schedule": "0 2 * * *", "max_duration_minutes": 5,
                    "tasks": self._LIGHTWEIGHT_TASKS},
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
        report = sched.trigger_manual(actor_id="user1", domain_ids=["edu"])
        assert report.status in ("completed", "failed")
        assert report.triggered_by == "user1"
        # Should have results for each domain × task
        assert len(report.task_results) > 0

    def test_status_after_run(self):
        sched = self._make_scheduler()
        sched.trigger_manual(actor_id="user1", domain_ids=["edu"])
        status = sched.get_status()
        assert status["run_count"] == 1
        assert status["last_run"] is not None
        assert status["last_run"]["triggered_by"] == "user1"

    def test_get_report(self):
        sched = self._make_scheduler()
        report = sched.trigger_manual(actor_id="user1", domain_ids=["edu"])
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
        sched.trigger_manual(actor_id="user1", domain_ids=["edu"])
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
        sched.trigger_manual(actor_id="user1", domain_ids=["edu", "agri"])
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
        sched.trigger_manual(actor_id="user1", domain_ids=["d"])
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
        # Use only lightweight tasks and explicit domain_ids to skip
        # cross-domain tasks (like housekeeper_full_reindex which loads MiniLM)
        sched = NightCycleScheduler(
            config={"enabled": True, "tasks": ["glossary_pruning", "glossary_expansion"]},
            domain_loader=lambda: [
                {"domain_id": "edu", "physics": {"modules": [], "glossary": []}},
            ],
        )
        run_id = sched.trigger_async(actor_id="user1", domain_ids=["edu"])
        assert isinstance(run_id, str)
        # Wait for completion
        for _ in range(200):
            time.sleep(0.1)
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

    def test_call_slm_fn_threaded_to_tasks(self):
        """Scheduler passes call_slm_fn to task functions via kwargs."""
        import json
        slm_calls: list[dict] = []

        def mock_slm(system=None, user=None, **_):
            slm_calls.append({"system": system, "user": user})
            return json.dumps({"hint": "Irrigation triggered due to soil moisture deficit."})

        domains = [{
            "domain_id": "agri",
            "physics": {
                "standing_orders": [{
                    "id": "irrigate", "action": "schedule_irrigation",
                    "description": "Irrigate", "trigger_condition": "moisture < 20",
                    "max_attempts": 3, "escalation_on_exhaust": True,
                }],
                "invariants": [{
                    "id": "moisture_inv", "description": "Soil dry", "severity": "warning",
                    "check": "moisture < 20", "standing_order_on_violation": "irrigate",
                }],
            },
        }]
        sched = NightCycleScheduler(
            config={"tasks": ["slm_hint_generation"]},
            domain_loader=lambda: domains,
            call_slm_fn=mock_slm,
        )
        report = sched.trigger_manual(actor_id="user1", domain_ids=["agri"])
        assert report.status == "completed"
        # SLM was called once for the one standing order
        assert len(slm_calls) == 1
        # A hint proposal was generated
        all_proposals = [p for r in report.task_results for p in r.proposals]
        assert len(all_proposals) == 1
        assert all_proposals[0].proposal_type == "slm_hint"
        assert all_proposals[0].detail["standing_order_id"] == "irrigate"


# ── slm_hint_generation unit tests ──────────────────────────


class TestSlmHintGeneration:
    """Unit tests for the slm_hint_generation night-cycle task."""

    _PHYSICS = {
        "standing_orders": [
            {
                "id": "so_irrigate",
                "action": "schedule_irrigation",
                "description": "Schedule irrigation cycle",
                "trigger_condition": "soil_moisture < 20",
                "max_attempts": 3,
                "escalation_on_exhaust": True,
            },
            {
                "id": "so_drain",
                "action": "open_drain_valve",
                "description": "Open drain valve",
                "trigger_condition": "soil_moisture > 80",
                "max_attempts": 2,
                "escalation_on_exhaust": False,
            },
        ],
        "invariants": [
            {
                "id": "moisture_low",
                "description": "Soil moisture below minimum",
                "severity": "warning",
                "check": "soil_moisture < 20",
                "standing_order_on_violation": "so_irrigate",
            },
            {
                "id": "moisture_high",
                "description": "Soil moisture above maximum",
                "severity": "warning",
                "check": "soil_moisture > 80",
                "standing_order_on_violation": "so_drain",
            },
        ],
    }

    def _mock_slm(self, hint_text: str):
        import json
        return lambda system=None, user=None, **_: json.dumps({"hint": hint_text})

    def test_generates_proposal_per_standing_order(self):
        result = slm_hint_generation(
            domain_id="agri",
            domain_physics=self._PHYSICS,
            call_slm_fn=self._mock_slm("Soil moisture is low, irrigation needed."),
        )
        assert result.success is True
        assert result.task == "slm_hint_generation"
        assert len(result.proposals) == 2
        so_ids = {p.detail["standing_order_id"] for p in result.proposals}
        assert "so_irrigate" in so_ids
        assert "so_drain" in so_ids

    def test_proposal_type_is_slm_hint(self):
        result = slm_hint_generation(
            domain_id="agri",
            domain_physics=self._PHYSICS,
            call_slm_fn=self._mock_slm("A hint."),
        )
        for prop in result.proposals:
            assert prop.proposal_type == "slm_hint"

    def test_linked_invariants_in_proposal_detail(self):
        result = slm_hint_generation(
            domain_id="agri",
            domain_physics=self._PHYSICS,
            call_slm_fn=self._mock_slm("Hint text."),
        )
        irrigate_prop = next(p for p in result.proposals if p.detail["standing_order_id"] == "so_irrigate")
        assert "moisture_low" in irrigate_prop.detail["linked_invariant_ids"]

    def test_hint_text_stored_in_detail(self):
        hint = "When soil moisture drops below 20%, the irrigation cycle activates."
        result = slm_hint_generation(
            domain_id="agri",
            domain_physics=self._PHYSICS,
            call_slm_fn=self._mock_slm(hint),
        )
        assert result.proposals[0].detail["hint"] == hint

    def test_no_call_slm_fn_skips_gracefully(self):
        result = slm_hint_generation(
            domain_id="agri",
            domain_physics=self._PHYSICS,
        )
        assert result.success is True
        assert len(result.proposals) == 0
        assert result.metadata["skipped"] is True

    def test_slm_failure_skips_that_order(self):
        import json

        call_count = [0]

        def flaky_slm(system=None, user=None, **_):
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("SLM timeout")
            return json.dumps({"hint": "Good hint for second order."})

        result = slm_hint_generation(
            domain_id="agri",
            domain_physics=self._PHYSICS,
            call_slm_fn=flaky_slm,
        )
        assert result.success is True
        # First order failed, second succeeded → 1 proposal
        assert len(result.proposals) == 1

    def test_metadata_counts(self):
        result = slm_hint_generation(
            domain_id="agri",
            domain_physics=self._PHYSICS,
            call_slm_fn=self._mock_slm("hint"),
        )
        assert result.metadata["standing_orders_processed"] == 2
        assert result.metadata["hints_generated"] == 2

    def test_empty_standing_orders(self):
        result = slm_hint_generation(
            domain_id="agri",
            domain_physics={"standing_orders": [], "invariants": []},
            call_slm_fn=self._mock_slm("hint"),
        )
        assert result.success is True
        assert len(result.proposals) == 0
        assert result.metadata["standing_orders_processed"] == 0

    def test_handles_markdown_fenced_hint(self):
        import json

        def fenced_slm(system=None, user=None, **_):
            return '```json\n{"hint": "Fenced hint text."}\n```'

        result = slm_hint_generation(
            domain_id="agri",
            domain_physics={
                "standing_orders": [{"id": "so1", "action": "act", "description": ""}],
                "invariants": [],
            },
            call_slm_fn=fenced_slm,
        )
        assert len(result.proposals) == 1
        assert result.proposals[0].detail["hint"] == "Fenced hint text."
