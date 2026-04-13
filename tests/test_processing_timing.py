"""Tests for solve-time inflation fix.

Verifies that:
1. response_latency_sec is set from the pre-SLM request-arrival snapshot
   (i.e. it does NOT grow by however long the inbound SLM call took).
2. problem_presented_at is reset to a time AFTER the outgoing LLM response
   is built, not before.
3. task_presentation turns also reset problem_presented_at.
4. The education domain adapter (runtime_adapters.domain_step) maps
   response_latency_sec → solve_elapsed_sec before passing evidence to the
   fluency monitor so the time-threshold gate works correctly.
5. When solve_elapsed_sec is already present in evidence the adapter does NOT
   overwrite it (explicit domain override wins).
"""
from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
_EDU_CONTROLLERS = REPO_ROOT / "domain-packs" / "education" / "controllers"
if str(_EDU_CONTROLLERS) not in sys.path:
    sys.path.insert(0, str(_EDU_CONTROLLERS))


# ---------------------------------------------------------------------------
# Helpers: load modules under isolation
# ---------------------------------------------------------------------------

def _load_runtime_adapters():
    spec = importlib.util.spec_from_file_location(
        "edu_learning_adapters_timing_test",
        str(_EDU_CONTROLLERS / "learning_adapters.py"),
    )
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _load_post_turn_module():
    spec = importlib.util.spec_from_file_location(
        "edu_post_turn_timing_test",
        str(_EDU_CONTROLLERS / "education_post_turn.py"),
    )
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


_adapters = _load_runtime_adapters()
_post_turn_mod = _load_post_turn_module()
_reset_timer = _post_turn_mod.education_reset_timer
_education_post_turn = _post_turn_mod.education_post_turn
domain_step = _adapters.domain_step
FluencyState = _adapters.FluencyState
LearningState = _adapters.LearningState
AffectState = _adapters.AffectState


# ---------------------------------------------------------------------------
# Minimal state factories
# ---------------------------------------------------------------------------

def _make_learning_state(tier: str = "tier_1", consecutive_correct: int = 0) -> Any:
    from zpd_monitor_runtime import RecentWindow  # type: ignore[import]
    ls = LearningState(
        affect=AffectState(),
        mastery={},
        challenge_band={"min_challenge": 0.3, "max_challenge": 0.7},
        recent_window=RecentWindow(),
        challenge=0.5,
        uncertainty=0.5,
    )
    ls.fluency = FluencyState(current_tier=tier, consecutive_correct=consecutive_correct)  # type: ignore[attr-defined]
    ls.world_sim_theme = {}   # type: ignore[attr-defined]
    ls.mud_world_state = {}   # type: ignore[attr-defined]
    return ls


TASK_SPEC = {"task_id": "test-timing", "nominal_difficulty": 0.2, "skills_required": []}

PARAMS = {
    "fluency_monitor": {
        "target_consecutive_successes": 3,
        "time_threshold_seconds": 45.0,
        "tier_progression": ["tier_1", "tier_2", "tier_3"],
    }
}


# ===========================================================================
# 1-3. processing.py timing tests
# ===========================================================================

class TestProcessingTimingCapture:
    """response_latency_sec is captured before SLM calls; presented_at reset after LLM."""

    def _make_session(self, presented_at: float) -> dict[str, Any]:
        """Return a minimal legacy-shaped session dict."""
        mock_orch = MagicMock()
        mock_orch.state = SimpleNamespace(world_sim_theme={}, mud_world_state={})
        mock_orch.last_domain_lib_decision = {}
        mock_orch.process_turn.return_value = (
            {
                "prompt_type": "task_complete",
                "domain_pack_id": "edu",
                "domain_pack_version": "1",
                "task_id": "t1",
                "task_nominal_difficulty": 0.2,
                "skills_targeted": [],
                "theme": None,
                "standing_order_trigger": None,
                "references": [],
                "grounded": True,
            },
            "task_complete",
        )
        mock_orch.log_records = []
        mock_orch.get_standing_order_attempts.return_value = {}
        mock_orch.append_provenance_trace.return_value = None
        return {
            "orchestrator": mock_orch,
            "task_spec": {"task_id": "t1", "nominal_difficulty": 0.2, "skills_required": []},
            "current_problem": {},
            "turn_count": 0,
            "domain_id": "education",
            "problem_presented_at": presented_at,
        }

    def _make_runtime(self) -> dict[str, Any]:
        return {
            "system_prompt": "sys",
            "domain": {"id": "edu", "version": "1", "glossary": []},
            "runtime_provenance": {},
            "turn_input_schema": {},
            "turn_input_defaults": {"correctness": "correct", "problem_solved": True},
            "slm_weight_overrides": {},
            "tool_fns": None,
            "action_prompt_type_map": {},
            "deterministic_templates": {},
            "local_only": False,
            "post_turn_timer_fn": _reset_timer,
        }

    def test_response_latency_sec_sampled_before_slm(self):
        """response_latency_sec must not include time spent in inbound SLM call."""
        # Simulate: problem presented 10 s before request arrived, SLM takes 60 s.
        SLM_LATENCY = 60.0
        STUDENT_ELAPSED = 10.0
        t_presented = 1_000_000.0
        t_arrived = t_presented + STUDENT_ELAPSED

        # clock: presented_at | +10s arrived | +60s after-SLM | +1s after-LLM
        clock_calls = iter([
            t_arrived,             # time.time() captured at request arrival
            t_arrived + SLM_LATENCY,       # time.time() inside SLM (not used for latency)
            t_arrived + SLM_LATENCY + 1.0,  # time.time() for presented_at reset
        ])

        from lumina.api import processing as proc

        session = self._make_session(t_presented)
        runtime = self._make_runtime()

        captured_turn_data: dict[str, Any] = {}

        def fake_interpret(input_text, task_context, rt, **kw):
            return {"correctness": "correct", "problem_solved": True, "off_task_ratio": 0.0}

        def fake_slm_ctx(**kw):
            return {}

        def fake_call_llm(**kw):
            return "good job"

        with (
            patch.object(proc, "get_or_create_session", return_value=session),
            patch.object(proc._cfg.DOMAIN_REGISTRY, "get_runtime_context", return_value=runtime),
            patch.object(proc, "detect_glossary_query", return_value=None),
            patch.object(proc, "interpret_turn_input", side_effect=fake_interpret),
            patch.object(proc, "slm_available", return_value=False),
            patch.object(proc, "call_llm", return_value="good job"),
            patch.object(proc, "normalize_turn_data", side_effect=lambda d, _s: d),
            patch.object(proc, "apply_tool_call_policy", return_value=[]),
            patch.object(proc, "strip_latex_delimiters", side_effect=lambda s: s),
            patch("lumina.api.processing.time") as mock_time,
        ):
            mock_time.time.side_effect = list(clock_calls)
            result = proc.process_message("sess-1", "10/10x = 110/10 so x = 11")

        # turn_data is the second positional arg passed to orch.process_turn
        turn_data_passed = session["orchestrator"].process_turn.call_args[0][1]
        assert "response_latency_sec" in turn_data_passed, (
            f"turn_data keys: {list(turn_data_passed.keys())}"
        )
        # Must equal student elapsed (10 s), NOT student_elapsed + SLM latency (70 s)
        assert abs(turn_data_passed["response_latency_sec"] - STUDENT_ELAPSED) < 0.01, (
            f"Expected {STUDENT_ELAPSED}, got {turn_data_passed['response_latency_sec']}"
        )

    def test_problem_presented_at_updated_after_llm_on_task_presentation(self):
        """problem_presented_at must be set after call_llm completes."""
        T_PRESENTED = 1_000_000.0
        T_ARRIVED = T_PRESENTED + 5.0
        T_AFTER_LLM = T_ARRIVED + 3.0  # after LLM response is built

        call_sequence = iter([T_ARRIVED, T_AFTER_LLM])

        from lumina.api import processing as proc

        session = self._make_session(T_PRESENTED)
        # Make orchestrator return task_presentation action to trigger reset
        session["orchestrator"].process_turn.return_value = (
            {
                "prompt_type": "task_presentation",
                "domain_pack_id": "edu",
                "domain_pack_version": "1",
                "task_id": "t1",
                "task_nominal_difficulty": 0.2,
                "skills_targeted": [],
                "theme": None,
                "standing_order_trigger": None,
                "references": [],
                "grounded": True,
            },
            "task_presentation",
        )
        runtime = self._make_runtime()

        with (
            patch.object(proc, "get_or_create_session", return_value=session),
            patch.object(proc._cfg.DOMAIN_REGISTRY, "get_runtime_context", return_value=runtime),
            patch.object(proc, "detect_glossary_query", return_value=None),
            patch.object(proc, "interpret_turn_input",
                         return_value={"correctness": "correct", "problem_solved": False,
                                       "off_task_ratio": 0.0}),
            patch.object(proc, "slm_available", return_value=False),
            patch.object(proc, "call_llm", return_value="Here is your next problem"),
            patch.object(proc, "normalize_turn_data", side_effect=lambda d, _s: d),
            patch.object(proc, "apply_tool_call_policy", return_value=[]),
            patch.object(proc, "strip_latex_delimiters", side_effect=lambda s: s),
            patch("lumina.api.processing.time") as mock_time,
            patch.object(_post_turn_mod, "time") as mock_hook_time,
        ):
            mock_time.time.side_effect = list(call_sequence)
            mock_hook_time.time.side_effect = [T_AFTER_LLM]
            proc.process_message("sess-2", "let's go")

        # presented_at must be T_AFTER_LLM (after the response was built)
        assert abs(session["problem_presented_at"] - T_AFTER_LLM) < 0.01, (
            f"Expected {T_AFTER_LLM}, got {session['problem_presented_at']}"
        )
        assert session["problem_presented_at"] > T_ARRIVED


# ===========================================================================
# 4-5. domain_step response_latency_sec → solve_elapsed_sec mapping
# ===========================================================================

class TestDomainStepLatencyMapping:
    """runtime_adapters.domain_step maps response_latency_sec → solve_elapsed_sec."""

    def test_response_latency_mapped_to_solve_elapsed(self):
        """When only response_latency_sec is present, fluency receives it as solve_elapsed_sec."""
        state = _make_learning_state(tier="tier_1", consecutive_correct=2)
        # 10 s is well within the 45 s threshold → should count as a fast solve
        evidence = {"correctness": "correct", "response_latency_sec": 10.0}
        new_state, decision = domain_step(state, TASK_SPEC, evidence, PARAMS)
        # Third consecutive correct within time threshold → advance tier
        assert decision["fluency"]["advanced"] is True, (
            "Expected tier advancement after 3 fast correct solves; "
            f"got fluency decision: {decision['fluency']}"
        )

    def test_slow_latency_triggers_bottleneck(self):
        """A response_latency_sec above threshold produces fluency_bottleneck via mapping."""
        state = _make_learning_state(tier="tier_1", consecutive_correct=2)
        evidence = {"correctness": "correct", "response_latency_sec": 120.0}
        new_state, decision = domain_step(state, TASK_SPEC, evidence, PARAMS)
        assert decision["fluency"]["fluency_bottleneck"] is True
        assert decision["fluency"]["advanced"] is False

    def test_explicit_solve_elapsed_not_overwritten(self):
        """If solve_elapsed_sec already exists in evidence the adapter must not overwrite it."""
        state = _make_learning_state(tier="tier_1", consecutive_correct=2)
        # solve_elapsed_sec = 10 (fast), response_latency_sec = 200 (slow)
        # domain should use the explicit 10, not the latency 200
        evidence = {
            "correctness": "correct",
            "solve_elapsed_sec": 10.0,
            "response_latency_sec": 200.0,
        }
        new_state, decision = domain_step(state, TASK_SPEC, evidence, PARAMS)
        assert decision["fluency"]["advanced"] is True, (
            "Explicit solve_elapsed_sec=10 should have been used, not overwritten by latency=200"
        )

    def test_missing_latency_defaults_to_zero_elapsed(self):
        """When neither solve_elapsed_sec nor response_latency_sec is present, no crash."""
        state = _make_learning_state(tier="tier_1")
        evidence = {"correctness": "correct"}  # neither timing field present
        # solve_elapsed_sec defaults to 0.0 in fluency_monitor_step → counts as fast
        new_state, decision = domain_step(state, TASK_SPEC, evidence, PARAMS)
        assert decision["fluency"]["fluency_bottleneck"] is False


# ===========================================================================
# 6. task_complete LLM payload — answered-problem / next-problem separation
# ===========================================================================

class TestTaskCompletePayloadSeparation:
    """process_message must pass the answered problem (not the new one) in
    llm_payload['current_problem'] when a new problem is generated on
    task_complete.  The newly generated problem is passed separately as
    llm_payload['next_problem']."""

    _OLD_PROBLEM = {"equation": "6x = 90", "target_variable": "x", "expected_answer": "x = 15"}
    _NEW_PROBLEM = {"equation": "7x = 98", "target_variable": "x", "expected_answer": "x = 14"}

    def _make_session(self) -> dict[str, Any]:
        mock_orch = MagicMock()
        mock_orch.state = SimpleNamespace(world_sim_theme={}, mud_world_state={})
        mock_orch.last_domain_lib_decision = {}
        mock_orch.process_turn.return_value = (
            {
                "prompt_type": "task_complete",
                "domain_pack_id": "edu",
                "domain_pack_version": "1",
                "task_id": "t1",
                "task_nominal_difficulty": 0.5,
                "skills_targeted": [],
                "theme": None,
                "standing_order_trigger": None,
                "references": [],
                "grounded": True,
            },
            "task_complete",
        )
        mock_orch.log_records = []
        mock_orch.get_standing_order_attempts.return_value = {}
        mock_orch.append_provenance_trace.return_value = None
        return {
            "orchestrator": mock_orch,
            "task_spec": {"task_id": "t1", "nominal_difficulty": 0.5, "skills_required": []},
            "current_problem": dict(self._OLD_PROBLEM),
            "turn_count": 1,
            "domain_id": "education",
            "problem_presented_at": 1_000_000.0,
        }

    def _make_runtime_with_generator(self, new_problem: dict[str, Any]) -> dict[str, Any]:
        """Runtime that includes a problem generator returning new_problem."""
        def _generate_problem(difficulty, domain):
            return new_problem

        return {
            "system_prompt": "sys",
            "domain": {
                "id": "edu",
                "version": "1",
                "glossary": [],
                "subsystem_configs": {
                    "equation_difficulty_tiers": [
                        {"tier_id": "tier_2", "min_difficulty": 0.35, "max_difficulty": 0.65},
                    ],
                },
            },
            "runtime_provenance": {},
            "turn_input_schema": {},
            "turn_input_defaults": {},
            "slm_weight_overrides": {},
            "tool_fns": {"generate_problem": _generate_problem},
            "action_prompt_type_map": {},
            "deterministic_templates": {},
            "local_only": False,
            "post_turn_processor_fn": _education_post_turn,
            "post_turn_timer_fn": _reset_timer,
        }

    def _make_runtime_no_generator(self) -> dict[str, Any]:
        """Runtime without a problem generator (no advancement possible)."""
        return {
            "system_prompt": "sys",
            "domain": {"id": "edu", "version": "1", "glossary": []},
            "runtime_provenance": {},
            "turn_input_schema": {},
            "turn_input_defaults": {},
            "slm_weight_overrides": {},
            "tool_fns": None,
            "action_prompt_type_map": {},
            "deterministic_templates": {},
            "local_only": False,
        }

    def _call_process_message(
        self, session: dict[str, Any], runtime: dict[str, Any], problem_solved: bool
    ) -> dict[str, Any]:
        """Run process_message and return the kwargs passed to call_llm."""
        from lumina.api import processing as proc

        captured: dict[str, Any] = {}

        def fake_llm(system: str, user: str, **kw) -> str:
            import json as _json
            captured["payload"] = _json.loads(user)
            return "Great work!"

        with (
            patch.object(proc, "get_or_create_session", return_value=session),
            patch.object(proc._cfg.DOMAIN_REGISTRY, "get_runtime_context", return_value=runtime),
            patch.object(proc, "detect_glossary_query", return_value=None),
            patch.object(
                proc,
                "interpret_turn_input",
                return_value={
                    "correctness": "correct",
                    "problem_solved": problem_solved,
                    "off_task_ratio": 0.0,
                },
            ),
            patch.object(proc, "slm_available", return_value=False),
            patch.object(proc, "call_llm", side_effect=fake_llm),
            patch.object(proc, "normalize_turn_data", side_effect=lambda d, _s: d),
            patch.object(proc, "apply_tool_call_policy", return_value=[]),
            patch.object(proc, "strip_latex_delimiters", side_effect=lambda s: s),
            patch("lumina.api.processing.time") as mock_time,
        ):
            mock_time.time.side_effect = [1_000_010.0, 1_000_012.0]
            proc.process_message("sess-payload", "6/6x = 90/6 so x = 15")

        return captured.get("payload", {})

    @pytest.mark.unit
    def test_answered_problem_used_for_current_problem_in_payload(self):
        """When problem is solved and a new problem generated, current_problem in the
        LLM payload must be the answered problem — not the new generated problem."""
        session = self._make_session()
        runtime = self._make_runtime_with_generator(self._NEW_PROBLEM)

        payload = self._call_process_message(session, runtime, problem_solved=True)

        assert payload.get("current_problem") == self._OLD_PROBLEM, (
            f"LLM payload current_problem should be the answered problem ({self._OLD_PROBLEM}), "
            f"but got: {payload.get('current_problem')}"
        )

    @pytest.mark.unit
    def test_next_problem_present_when_new_problem_generated(self):
        """When a new problem is generated, llm_payload must contain a next_problem key
        holding the new problem so the LLM can introduce it."""
        session = self._make_session()
        runtime = self._make_runtime_with_generator(self._NEW_PROBLEM)

        payload = self._call_process_message(session, runtime, problem_solved=True)

        assert "next_problem" in payload, (
            "next_problem must be present in LLM payload when a new problem was generated"
        )
        assert payload["next_problem"] == self._NEW_PROBLEM, (
            f"next_problem should be the newly generated problem ({self._NEW_PROBLEM}), "
            f"but got: {payload.get('next_problem')}"
        )

    @pytest.mark.unit
    def test_no_next_problem_when_no_advancement(self):
        """When the problem is NOT solved (no advancement), next_problem must not appear
        in the LLM payload."""
        session = self._make_session()
        runtime = self._make_runtime_no_generator()

        payload = self._call_process_message(session, runtime, problem_solved=False)

        assert "next_problem" not in payload, (
            f"next_problem should not be present when there was no problem advancement, "
            f"but payload keys are: {list(payload.keys())}"
        )
