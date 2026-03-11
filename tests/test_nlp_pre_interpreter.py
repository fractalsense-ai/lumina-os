"""Tests for the NLP pre-interpreter extractors."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

# ── Load the hyphenated module via importlib ────────────────
_NLP_PATH = (
    Path(__file__).resolve().parent.parent
    / "domain-packs"
    / "education"
    / "systools"
    / "nlp_pre_interpreter.py"
)
_spec = importlib.util.spec_from_file_location("nlp_pre_interpreter", str(_NLP_PATH))
_mod = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
sys.modules["nlp_pre_interpreter"] = _mod
_spec.loader.exec_module(_mod)  # type: ignore[union-attr]

extract_answer_match = _mod.extract_answer_match
extract_frustration_markers = _mod.extract_frustration_markers
extract_hint_request = _mod.extract_hint_request
extract_off_task_ratio = _mod.extract_off_task_ratio
nlp_preprocess = _mod.nlp_preprocess


# ── extract_answer_match ────────────────────────────────────

class TestExtractAnswerMatch:
    def test_x_equals_correct(self):
        result = extract_answer_match("x = 4", "4")
        assert result["correctness"] == "correct"
        assert result["confidence"] == 0.95
        assert result["extracted_answer"] == 4.0

    def test_x_equals_incorrect(self):
        result = extract_answer_match("x = 5", "4")
        assert result["correctness"] == "incorrect"
        assert result["confidence"] == 0.90
        assert result["extracted_answer"] == 5.0

    def test_bare_number_correct(self):
        result = extract_answer_match("4", "4")
        assert result["correctness"] == "correct"

    def test_answer_is_pattern(self):
        result = extract_answer_match("the answer is 7", "7")
        assert result["correctness"] == "correct"
        assert result["extracted_answer"] == 7.0

    def test_no_answer_found(self):
        result = extract_answer_match("I don't know what to do", "4")
        assert result["correctness"] is None
        assert result["confidence"] == 0.0

    def test_no_expected_answer(self):
        result = extract_answer_match("x = 4", None)
        assert result["correctness"] is None
        assert result["extracted_answer"] == 4.0

    def test_multiline_last_answer(self):
        text = "subtract 3 from both sides\n2x = 8\ndivide by 2\nx = 4"
        result = extract_answer_match(text, "4")
        assert result["correctness"] == "correct"

    def test_negative_answer(self):
        result = extract_answer_match("x = -3", "-3")
        assert result["correctness"] == "correct"

    def test_decimal_answer(self):
        result = extract_answer_match("x = 2.5", "2.5")
        assert result["correctness"] == "correct"


# ── extract_frustration_markers ─────────────────────────────

class TestExtractFrustrationMarkers:
    def test_keyword_detection(self):
        result = extract_frustration_markers("I don't get it")
        assert result["frustration_marker_count"] >= 1
        assert any("don" in m.lower() for m in result["markers"])

    def test_all_caps(self):
        result = extract_frustration_markers("I HATE THIS PROBLEM")
        assert "ALL_CAPS" in result["markers"]

    def test_excessive_punctuation(self):
        result = extract_frustration_markers("what is this???")
        assert "excessive_punctuation" in result["markers"]

    def test_short_frustrated(self):
        result = extract_frustration_markers("ugh!")
        assert result["frustration_marker_count"] >= 1

    def test_clean_message(self):
        result = extract_frustration_markers("x = 4 after subtracting 3")
        assert result["frustration_marker_count"] == 0
        assert result["markers"] == []

    def test_multiple_markers(self):
        result = extract_frustration_markers("I DON'T GET IT!!!")
        # Should detect keyword + ALL_CAPS + excessive punctuation
        assert result["frustration_marker_count"] >= 2

    def test_ugh_keyword(self):
        result = extract_frustration_markers("ugh this is hard")
        assert result["frustration_marker_count"] >= 1

    def test_give_up(self):
        result = extract_frustration_markers("I give up")
        assert result["frustration_marker_count"] >= 1


# ── extract_hint_request ────────────────────────────────────

class TestExtractHintRequest:
    def test_give_me_a_hint(self):
        assert extract_hint_request("give me a hint")["hint_used"] is True

    def test_help(self):
        assert extract_hint_request("help")["hint_used"] is True

    def test_im_stuck(self):
        assert extract_hint_request("I'm stuck")["hint_used"] is True

    def test_what_do_i_do(self):
        assert extract_hint_request("what do I do")["hint_used"] is True

    def test_how_do_i(self):
        assert extract_hint_request("how do I solve this")["hint_used"] is True

    def test_not_a_hint_request(self):
        assert extract_hint_request("x = 4")["hint_used"] is False

    def test_normal_math_message(self):
        assert extract_hint_request("subtract 3 from both sides")["hint_used"] is False


# ── extract_off_task_ratio ──────────────────────────────────

class TestExtractOffTaskRatio:
    def test_pure_math(self):
        result = extract_off_task_ratio("x + 3 = 7 subtract 3")
        assert result["off_task_ratio"] < 0.3

    def test_pure_off_topic(self):
        result = extract_off_task_ratio("what is your favorite color purple green blue")
        assert result["off_task_ratio"] > 0.7

    def test_mixed_message(self):
        result = extract_off_task_ratio("I think x equals 4 but also dogs are cool")
        ratio = result["off_task_ratio"]
        assert 0.2 < ratio < 0.8

    def test_empty_message(self):
        result = extract_off_task_ratio("")
        assert result["off_task_ratio"] == 0.0

    def test_single_number(self):
        result = extract_off_task_ratio("4")
        assert result["off_task_ratio"] == 0.0


# ── nlp_preprocess (integration) ────────────────────────────

class TestNlpPreprocess:
    def test_correct_answer_full_pipeline(self):
        task_context = {
            "current_problem": {
                "equation": "2x + 3 = 11",
                "expected_answer": "4",
            }
        }
        result = nlp_preprocess("x = 4", task_context)
        assert result.get("correctness") == "correct"
        assert result["frustration_marker_count"] == 0
        assert result["hint_used"] is False
        assert "_nlp_anchors" in result
        assert any(a["field"] == "correctness" for a in result["_nlp_anchors"])

    def test_frustrated_message(self):
        task_context = {"current_problem": {"equation": "x + 5 = 12", "expected_answer": "7"}}
        result = nlp_preprocess("UGH I DON'T GET IT!!!", task_context)
        assert result["frustration_marker_count"] >= 2
        assert any(a["field"] == "frustration_marker_count" for a in result["_nlp_anchors"])

    def test_hint_request(self):
        task_context = {"current_problem": {"equation": "x + 1 = 5", "expected_answer": "4"}}
        result = nlp_preprocess("can I get a hint please", task_context)
        assert result["hint_used"] is True

    def test_no_current_problem(self):
        result = nlp_preprocess("hello there", {})
        assert result.get("correctness") is None or "correctness" not in result
        assert "off_task_ratio" in result

    def test_off_task_message(self):
        task_context = {"current_problem": {"equation": "x + 1 = 3", "expected_answer": "2"}}
        result = nlp_preprocess("I like pizza and video games", task_context)
        assert result["off_task_ratio"] > 0.5
