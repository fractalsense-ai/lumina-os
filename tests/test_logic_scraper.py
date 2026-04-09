"""
Tests for the logic scraping engine: iterative LLM probing,
feedback accumulation, novel synthesis detection, deduplication,
and result serialisation.
"""

from __future__ import annotations

import pytest

from lumina.tools.logic_scraper import (
    LogicScraper,
    LogicScrapeResult,
    _build_augmented_prompt,
    _detect_novel_synthesis,
    _summarise_response,
    _verify_traces,
)


# ── Fixtures ────────────────────────────────────────────────────

INVARIANTS_WITH_SIGNAL = [
    {
        "id": "method_recognized",
        "severity": "warning",
        "check": "method_recognized",
        "standing_order_on_violation": "request_justification",
        "signal_type": "NOVEL_PATTERN",
    },
    {
        "id": "show_work",
        "severity": "warning",
        "check": "step_count >= 3",
    },
]

INVARIANTS_NO_SIGNAL = [
    {
        "id": "equivalence_preserved",
        "severity": "critical",
        "check": "lhs == rhs",
    },
]


def _mock_llm_counter():
    """Return a callable that returns numbered responses."""
    counter = {"n": 0}

    def _call(system: str, user: str) -> str:
        counter["n"] += 1
        return f"Unique response #{counter['n']}: a novel approach to the problem."

    return _call


def _mock_llm_fixed(response: str = "The same response every time."):
    """Return a callable that always returns the same response."""
    def _call(system: str, user: str) -> str:
        return response
    return _call


def _mock_llm_failing():
    """Return a callable that always raises."""
    def _call(system: str, user: str) -> str:
        raise RuntimeError("LLM error")
    return _call


def _make_physics(invariants=None, logic_config=None):
    physics = {}
    if invariants is not None:
        physics["invariants"] = invariants
    if logic_config is not None:
        physics["logic_scraping"] = logic_config
    return physics


# ── Prompt feedback tests ───────────────────────────────────────

class TestPromptFeedback:
    def test_no_prior_responses(self):
        result = _build_augmented_prompt("test prompt", [], "cumulative", 10)
        assert result == "test prompt"

    def test_cumulative_feedback(self):
        priors = ["response 1", "response 2", "response 3"]
        result = _build_augmented_prompt("test prompt", priors, "cumulative", 10)
        assert "Prior responses" in result
        assert "response 1" in result
        assert "response 2" in result
        assert "response 3" in result

    def test_sliding_window_feedback(self):
        priors = ["r1", "r2", "r3", "r4", "r5"]
        result = _build_augmented_prompt("test prompt", priors, "sliding_window", 2)
        assert "r4" in result
        assert "r5" in result
        assert "r1" not in result

    def test_novel_perspective_instruction(self):
        result = _build_augmented_prompt("q?", ["r1"], "cumulative", 10)
        assert "novel perspective" in result.lower()


class TestSummariseResponse:
    def test_short_response_unchanged(self):
        assert _summarise_response("short") == "short"

    def test_long_response_truncated(self):
        long = "x" * 500
        result = _summarise_response(long, max_chars=100)
        assert len(result) == 103  # 100 + "..."
        assert result.endswith("...")


# ── Novel synthesis detection tests ─────────────────────────────

class TestNovelSynthesisDetection:
    def test_invariants_with_signal_flagged(self):
        result = _detect_novel_synthesis("any response", INVARIANTS_WITH_SIGNAL)
        assert len(result) == 1
        assert result[0]["signal_type"] == "NOVEL_PATTERN"
        assert result[0]["invariant_id"] == "method_recognized"

    def test_invariants_without_signal_not_flagged(self):
        result = _detect_novel_synthesis("any response", INVARIANTS_NO_SIGNAL)
        assert result == []

    def test_custom_check_fn(self):
        def never_novel(response, inv):
            return False

        result = _detect_novel_synthesis(
            "response", INVARIANTS_WITH_SIGNAL, check_fn=never_novel,
        )
        assert result == []

    def test_custom_check_fn_selective(self):
        """Custom check_fn that flags only specific responses."""
        def check_fn(response, inv):
            return "novel" in response.lower()

        result = _detect_novel_synthesis(
            "A novel approach", INVARIANTS_WITH_SIGNAL, check_fn=check_fn,
        )
        assert len(result) == 1

        result = _detect_novel_synthesis(
            "Standard approach", INVARIANTS_WITH_SIGNAL, check_fn=check_fn,
        )
        assert result == []

    def test_empty_invariants(self):
        result = _detect_novel_synthesis("response", [])
        assert result == []


# ── Trace verification tests ────────────────────────────────────

class TestTraceVerification:
    def test_deduplication(self):
        items = [
            {"summary": "exactly the same text", "signals": []},
            {"summary": "exactly the same text", "signals": []},
            {"summary": "different text", "signals": []},
        ]
        result = _verify_traces(items)
        assert result["duplicates_removed"] == 1
        assert result["unique_count"] == 2

    def test_no_items(self):
        result = _verify_traces([])
        assert result["unique_count"] == 0
        assert result["consistency_check"] == "no_items"

    def test_all_unique(self):
        items = [
            {"summary": f"unique response {i}", "signals": []}
            for i in range(5)
        ]
        result = _verify_traces(items)
        assert result["duplicates_removed"] == 0
        assert result["unique_count"] == 5
        assert result["consistency_check"] == "pass"


# ── LogicScraper integration tests ─────────────────────────────

class TestLogicScraper:
    def test_basic_scrape_loop(self):
        physics = _make_physics(INVARIANTS_WITH_SIGNAL)
        scraper = LogicScraper(
            call_llm_fn=_mock_llm_counter(),
            domain_physics=physics,
            config={"max_iterations": 5},
        )
        result = scraper.scrape("test prompt", iterations=5, domain_id="test")
        assert result.iterations_run == 5
        assert result.total_flagged == 5  # default check_fn flags all
        assert result.yield_rate == 1.0

    def test_max_iterations_respected(self):
        physics = _make_physics(INVARIANTS_WITH_SIGNAL)
        scraper = LogicScraper(
            call_llm_fn=_mock_llm_counter(),
            domain_physics=physics,
            config={"max_iterations": 3},
        )
        # Request more than max
        result = scraper.scrape("test", iterations=10)
        assert result.iterations_run == 3

    def test_feedback_accumulation(self):
        """Verify that prior responses are fed back in the prompt."""
        calls = []

        def recording_llm(system: str, user: str) -> str:
            calls.append(user)
            return f"Response {len(calls)}"

        physics = _make_physics(INVARIANTS_NO_SIGNAL)
        scraper = LogicScraper(
            call_llm_fn=recording_llm,
            domain_physics=physics,
            config={"max_iterations": 3, "feedback_mode": "cumulative"},
        )
        scraper.scrape("original question")

        assert len(calls) == 3
        # First call should be the original prompt only
        assert "Prior responses" not in calls[0]
        # Second call should include first response
        assert "Prior responses" in calls[1]
        assert "Response 1" in calls[1]
        # Third call should include both prior responses
        assert "Response 1" in calls[2]
        assert "Response 2" in calls[2]

    def test_sliding_window_mode(self):
        calls = []

        def recording_llm(system: str, user: str) -> str:
            calls.append(user)
            # Use a unique prefix so content is distinguishable from labels
            return f"UniqueReply-{len(calls)}"

        physics = _make_physics(INVARIANTS_NO_SIGNAL)
        scraper = LogicScraper(
            call_llm_fn=recording_llm,
            domain_physics=physics,
            config={
                "max_iterations": 5,
                "feedback_mode": "sliding_window",
                "sliding_window_size": 2,
            },
        )
        scraper.scrape("question")

        # Last call should only contain last 2 responses, not all 4
        last_call = calls[-1]
        assert "UniqueReply-4" in last_call
        assert "UniqueReply-3" in last_call
        # Early responses should NOT be in the sliding window
        assert "UniqueReply-1" not in last_call

    def test_yield_rate_calculation(self):
        """Custom check_fn that approves ~50% of responses."""
        counter = {"n": 0}

        def half_novel(response, inv):
            counter["n"] += 1
            return counter["n"] % 2 == 0  # every other is novel

        physics = _make_physics(INVARIANTS_WITH_SIGNAL)
        scraper = LogicScraper(
            call_llm_fn=_mock_llm_counter(),
            domain_physics=physics,
            config={"max_iterations": 10},
            check_fn=half_novel,
        )
        result = scraper.scrape("test")
        # 5 out of 10 should be flagged
        assert result.total_flagged == 5
        assert result.yield_rate == pytest.approx(0.5)

    def test_proposals_generated(self):
        physics = _make_physics(INVARIANTS_WITH_SIGNAL)
        scraper = LogicScraper(
            call_llm_fn=_mock_llm_counter(),
            domain_physics=physics,
            config={"max_iterations": 3},
        )
        result = scraper.scrape("test", domain_id="education")
        # Each unique flagged item should have a proposal
        assert len(result.proposals) == result.trace_verification["unique_count"]
        for p in result.proposals:
            assert p.domain_id == "education"
            assert p.proposal_type == "novel_synthesis_candidate"

    def test_no_signal_invariants_no_flags(self):
        physics = _make_physics(INVARIANTS_NO_SIGNAL)
        scraper = LogicScraper(
            call_llm_fn=_mock_llm_counter(),
            domain_physics=physics,
            config={"max_iterations": 5},
        )
        result = scraper.scrape("test")
        assert result.total_flagged == 0
        assert result.yield_rate == 0.0
        assert len(result.proposals) == 0

    def test_llm_failure_continues(self):
        """LLM failures on individual iterations should not abort the scrape."""
        physics = _make_physics(INVARIANTS_WITH_SIGNAL)
        scraper = LogicScraper(
            call_llm_fn=_mock_llm_failing(),
            domain_physics=physics,
            config={"max_iterations": 3},
        )
        result = scraper.scrape("test")
        assert result.iterations_run == 3
        assert result.total_flagged == 0  # no successful responses to flag

    def test_prompt_hash_computed(self):
        physics = _make_physics(INVARIANTS_NO_SIGNAL)
        scraper = LogicScraper(
            call_llm_fn=_mock_llm_counter(),
            domain_physics=physics,
            config={"max_iterations": 1},
        )
        result = scraper.scrape("hello world")
        assert len(result.prompt_hash) == 64  # SHA-256 hex

    def test_config_from_physics(self):
        physics = _make_physics(
            INVARIANTS_NO_SIGNAL,
            logic_config={"max_iterations": 42, "feedback_mode": "sliding_window"},
        )
        scraper = LogicScraper(
            call_llm_fn=_mock_llm_counter(),
            domain_physics=physics,
        )
        assert scraper.max_iterations == 42
        assert scraper.feedback_mode == "sliding_window"


# ── Result serialisation tests ──────────────────────────────────

class TestLogicScrapeResultSerialisation:
    def test_to_dict_keys(self):
        result = LogicScrapeResult(
            prompt="test",
            prompt_hash="abc123",
            iterations_run=10,
            total_flagged=2,
            yield_rate=0.2,
        )
        d = result.to_dict()
        assert d["scrape_id"]  # auto-generated UUID
        assert d["prompt"] == "test"
        assert d["iterations_run"] == 10
        assert d["total_flagged"] == 2
        assert d["yield_rate"] == 0.2
        assert isinstance(d["flagged_items"], list)
        assert isinstance(d["proposals"], list)

    def test_to_dict_with_proposals(self):
        from lumina.daemon.report import Proposal
        result = LogicScrapeResult(
            prompt="test",
            proposals=[Proposal(task="logic_scraping", summary="item 1")],
        )
        d = result.to_dict()
        assert len(d["proposals"]) == 1
        assert d["proposals"][0]["task"] == "logic_scraping"
