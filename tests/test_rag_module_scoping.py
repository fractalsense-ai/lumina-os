"""Tests for per-module RAG scoping and standing-order counter reset on task transition.

Bug: RAG retrieval returned chunks from sibling modules (e.g. algebra-level-1
while the student was in pre-algebra), contaminating the LLM context.

Bug: Standing-order counters persisted across task transitions, causing
unfair escalation on a fresh problem.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

_REPO_ROOT = Path(__file__).resolve().parent.parent
_EDU_CONTROLLERS = _REPO_ROOT / "domain-packs" / "education" / "controllers"


def _load_post_turn():
    spec = importlib.util.spec_from_file_location(
        "edu_post_turn_rag_test",
        str(_EDU_CONTROLLERS / "education_post_turn.py"),
    )
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


_pt_mod = _load_post_turn()
_education_post_turn = _pt_mod.education_post_turn


# ── RAG module-scoping tests ─────────────────────────────────


@dataclass(frozen=True)
class _FakeChunk:
    source_path: str
    heading: str = ""
    text: str = "stub"
    content_hash: str = ""


class _FakeHit:
    def __init__(self, source_path: str, score: float = 0.9):
        self.chunk = _FakeChunk(source_path=source_path)
        self.score = score


class TestRagModuleScoping:
    """enrich_turn_data must filter RAG hits to the active module."""

    def _call_enrich(self, hits: list[_FakeHit], module_key: str | None = None):
        from lumina.api.pipeline.enrichment import enrich_turn_data

        with patch("lumina.core.nlp.search_domain", return_value=hits):
            td: dict = {}
            result = enrich_turn_data(
                td,
                input_text="solve for x",
                domain_physics={},
                glossary=[],
                resolved_domain_id="education",
                actor_elapsed=None,
                deterministic_response=True,
                module_key=module_key,
                slm_available_fn=lambda: False,
                slm_interpret_physics_context_fn=lambda **_kw: {},
            )
        return result

    def test_without_module_key_all_hits_returned(self):
        """When module_key is None, no filtering should be applied."""
        hits = [
            _FakeHit("domain-packs/education/modules/algebra-level-1/domain-physics.json"),
            _FakeHit("domain-packs/education/modules/pre-algebra/domain-physics.json"),
        ]
        td = self._call_enrich(hits, module_key=None)
        assert len(td.get("_rag_context", [])) == 2

    def test_sibling_module_chunks_filtered(self):
        """Chunks from /modules/<other>/ must not appear in results."""
        hits = [
            _FakeHit("domain-packs/education/modules/algebra-level-1/domain-physics.json"),
            _FakeHit("domain-packs/education/modules/pre-algebra/domain-physics.json"),
            _FakeHit("domain-packs/education/docs/README.md"),
        ]
        td = self._call_enrich(hits, module_key="pre-algebra")
        sources = [r["source"] for r in td["_rag_context"]]
        assert "domain-packs/education/modules/algebra-level-1/domain-physics.json" not in sources
        assert "domain-packs/education/modules/pre-algebra/domain-physics.json" in sources
        assert "domain-packs/education/docs/README.md" in sources

    def test_domain_level_docs_always_pass_through(self):
        """Chunks NOT under /modules/ are domain-level and always included."""
        hits = [
            _FakeHit("domain-packs/education/cfg/runtime-config.yaml"),
            _FakeHit("domain-packs/education/docs/7-concepts/student-commons.md"),
        ]
        td = self._call_enrich(hits, module_key="pre-algebra")
        assert len(td["_rag_context"]) == 2

    def test_only_active_module_chunks_survive(self):
        """All chunks from sibling modules are removed; active module kept."""
        hits = [
            _FakeHit("domain-packs/education/modules/algebra-1/domain-physics.yaml"),
            _FakeHit("domain-packs/education/modules/algebra-intro/domain-physics.yaml"),
            _FakeHit("domain-packs/education/modules/pre-algebra/domain-physics.yaml"),
        ]
        td = self._call_enrich(hits, module_key="pre-algebra")
        sources = [r["source"] for r in td["_rag_context"]]
        assert sources == ["domain-packs/education/modules/pre-algebra/domain-physics.yaml"]

    def test_processing_passes_module_key(self):
        """processing.py must pass session module_key to enrich_turn_data."""
        import ast, inspect
        from lumina.api import processing

        src = inspect.getsource(processing)
        tree = ast.parse(src)
        found = False
        for node in ast.walk(tree):
            if isinstance(node, ast.keyword) and node.arg == "module_key":
                found = True
                break
        assert found, "processing.py must pass module_key= to enrich_turn_data"


# ── Standing-order counter reset on task transition ──────────


class TestStandingOrderCounterResetOnTaskTransition:
    """education_post_turn must clear standing-order counters on new task."""

    def _make_orch(self, attempts: dict | None = None):
        orch = MagicMock()
        orch.last_domain_lib_decision = {
            "fluency": {"advanced": True, "next_tier": "tier-2"},
        }
        orch.domain = {
            "subsystem_configs": {
                "equation_difficulty_tiers": [
                    {"tier_id": "tier-1", "min_difficulty": 0.0, "max_difficulty": 0.5},
                    {"tier_id": "tier-2", "min_difficulty": 0.5, "max_difficulty": 1.0},
                ]
            }
        }
        # Track the calls to set_standing_order_attempts
        orch.set_standing_order_attempts = MagicMock()
        return orch

    def test_counters_cleared_on_task_advance(self):
        """When a new problem is generated, all counters must be reset."""
        orch = self._make_orch()
        gen_fn = MagicMock(return_value={"task_id": "new-task", "equation": "x+1=3"})
        runtime = {"tool_fns": {"generate_problem": gen_fn}}

        result = _education_post_turn(
            turn_data={"problem_solved": True},
            prompt_contract={"prompt_type": "continue"},
            resolved_action="continue",
            session={"module_key": "pre-algebra"},
            task_spec={"nominal_difficulty": 0.5},
            current_task={"task_id": "old-task", "solved": False},
            runtime=runtime,
            orchestrator=orch,
        )
        assert result["new_task_presented"] is True
        orch.set_standing_order_attempts.assert_called_once_with({})

    def test_counters_not_cleared_when_no_advance(self):
        """When no new task is presented, counters must be preserved."""
        orch = self._make_orch()
        # Override fluency to NOT advance
        orch.last_domain_lib_decision = {"fluency": {"advanced": False}}

        result = _education_post_turn(
            turn_data={},
            prompt_contract={"prompt_type": "continue"},
            resolved_action="continue",
            session={"module_key": "pre-algebra"},
            task_spec={"nominal_difficulty": 0.5},
            current_task={"task_id": "old-task", "solved": False},
            runtime={},
            orchestrator=orch,
        )
        assert result["new_task_presented"] is False
        orch.set_standing_order_attempts.assert_not_called()

    def test_source_code_resets_on_new_task(self):
        """Verify set_standing_order_attempts({}) appears after new_task_presented."""
        import inspect

        src = inspect.getsource(_education_post_turn)
        assert "set_standing_order_attempts" in src, (
            "education_post_turn must call set_standing_order_attempts"
        )
