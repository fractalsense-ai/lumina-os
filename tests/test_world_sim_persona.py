"""
Tests for the world-sim persona layer — theme selection and LLM context hint injection.

Covers:
- select_world_sim_theme: preference matching, dislike veto, fallback, disabled
- interpret_turn_input: [World-Sim Active] hint present/absent in LLM call
- build_initial_learning_state: world_sim_theme stored on state object
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------------
# Load the domain adapter module under test
# ---------------------------------------------------------------------------

def _load_runtime_adapters():
    spec = importlib.util.spec_from_file_location(
        "edu_runtime_adapters_test",
        str(REPO_ROOT / "model-packs/education/controllers/runtime_adapters.py"),
    )
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _load_learning_adapters():
    spec = importlib.util.spec_from_file_location(
        "edu_learning_adapters_persona_test",
        str(REPO_ROOT / "model-packs/education/controllers/learning_adapters.py"),
    )
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


_adapters = _load_runtime_adapters()
_learning = _load_learning_adapters()
select_world_sim_theme = _adapters.select_world_sim_theme
interpret_turn_input = _learning.interpret_turn_input
build_initial_learning_state = _learning.build_initial_learning_state

# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------

_WORLD_SIM_CFG = {
    "enabled": True,
    "default_theme": "general_math",
    "themes": {
        "space_exploration": {
            "setting_description": "You are the mission mathematician aboard the Helios research vessel.",
            "artifact_framing": "mission_badge",
            "task_framing": "mission_briefing",
            "exit_phrase": "end mission",
            "preference_keywords": ["space", "rockets", "astronaut", "stars"],
        },
        "nature_and_outdoors": {
            "setting_description": "You are a junior field scientist at a nature reserve.",
            "artifact_framing": "field_record",
            "task_framing": "field_observation",
            "exit_phrase": "end fieldwork",
            "preference_keywords": ["nature", "animals", "outdoors", "wildlife"],
        },
        "general_math": {
            "setting_description": "You are working through a set of math challenges.",
            "artifact_framing": "certificate",
            "task_framing": "problem",
            "exit_phrase": "exit session",
            "preference_keywords": [],
        },
    },
}


def _profile(likes: list[str] | None = None, dislikes: list[str] | None = None) -> dict[str, Any]:
    return {"preferences": {"likes": likes or [], "dislikes": dislikes or []}}


# ---------------------------------------------------------------------------
# select_world_sim_theme tests
# ---------------------------------------------------------------------------


def test_select_theme_matches_preference():
    """Entity with 'space' in likes → space_exploration theme selected."""
    profile = _profile(likes=["space", "robots"])
    theme = select_world_sim_theme(profile, _WORLD_SIM_CFG)
    assert theme["theme_id"] == "space_exploration"
    assert theme["task_framing"] == "mission_briefing"
    assert theme["artifact_framing"] == "mission_badge"


def test_select_theme_avoids_dislike():
    """Dislike veto wins even when a preference keyword matches."""
    profile = _profile(likes=["space"], dislikes=["space"])
    theme = select_world_sim_theme(profile, _WORLD_SIM_CFG)
    # space_exploration is disqualified; nature_and_outdoors has no match;
    # should fall back to default (general_math)
    assert theme["theme_id"] == "general_math"


def test_select_theme_falls_back_to_default():
    """Entity with no matching preferences → general_math (default_theme)."""
    profile = _profile(likes=["cooking", "chess"])
    theme = select_world_sim_theme(profile, _WORLD_SIM_CFG)
    assert theme["theme_id"] == "general_math"
    assert theme["task_framing"] == "problem"


def test_select_theme_no_preferences():
    """Entity with empty preferences list → default_theme."""
    profile = _profile()
    theme = select_world_sim_theme(profile, _WORLD_SIM_CFG)
    assert theme["theme_id"] == "general_math"


def test_select_theme_disabled():
    """world_sim.enabled = false → returns empty dict."""
    cfg = {**_WORLD_SIM_CFG, "enabled": False}
    theme = select_world_sim_theme(_profile(likes=["space"]), cfg)
    assert theme == {}


def test_select_theme_none_cfg():
    """world_sim_cfg = None → returns empty dict (graceful no-op)."""
    theme = select_world_sim_theme(_profile(likes=["space"]), None)
    assert theme == {}


def test_select_theme_second_preference_match():
    """Preference in second theme (nature) is correctly matched when space is absent."""
    profile = _profile(likes=["hiking", "wildlife"])
    theme = select_world_sim_theme(profile, _WORLD_SIM_CFG)
    assert theme["theme_id"] == "nature_and_outdoors"
    assert theme["task_framing"] == "field_observation"


# ---------------------------------------------------------------------------
# interpret_turn_input — world_sim_theme hint injection
# ---------------------------------------------------------------------------

_MINIMAL_TASK_CONTEXT: dict[str, Any] = {
    "task_id": "algebra-test-001",
    "skills_required": ["solve_one_variable"],
    "current_task": {
        "equation": "x + 3 = 7",
        "target_variable": "x",
        "expected_answer": "x = 4",
        "min_steps": 1,
    },
}

_SPACE_THEME = {
    "theme_id": "space_exploration",
    "setting_description": "You are the mission mathematician aboard the Helios research vessel.",
    "artifact_framing": "mission_badge",
    "task_framing": "mission_briefing",
    "exit_phrase": "end mission",
    "preference_keywords": ["space"],
}


def test_interpret_turn_input_injects_world_sim_hint():
    """[World-Sim Active] block appears in the LLM system call when theme is active."""
    captured_calls: list[dict] = []

    def mock_call_llm(system: str, user: str, model: str | None) -> str:
        captured_calls.append({"system": system, "user": user})
        return '{"correctness": "correct", "step_count": 1, "substitution_check": true}'

    interpret_turn_input(
        call_llm=mock_call_llm,
        input_text="x = 4",
        task_context=_MINIMAL_TASK_CONTEXT,
        prompt_text="You are a math tutor.",
        world_sim_theme=_SPACE_THEME,
    )

    assert captured_calls, "call_llm was never called"
    user_arg = captured_calls[0]["user"]
    assert "[World-Sim Active]" in user_arg
    assert "mission_briefing" in user_arg
    assert "mission_badge" in user_arg
    assert "Helios" in user_arg


def test_interpret_turn_input_no_world_sim_hint():
    """No [World-Sim Active] block when world_sim_theme is None."""
    captured_calls: list[dict] = []

    def mock_call_llm(system: str, user: str, model: str | None) -> str:
        captured_calls.append({"system": system, "user": user})
        return '{"correctness": "partial", "step_count": 0}'

    interpret_turn_input(
        call_llm=mock_call_llm,
        input_text="I think x is 4",
        task_context=_MINIMAL_TASK_CONTEXT,
        prompt_text="You are a math tutor.",
        world_sim_theme=None,
    )

    assert captured_calls, "call_llm was never called"
    user_arg = captured_calls[0]["user"]
    assert "[World-Sim Active]" not in user_arg


def test_interpret_turn_input_empty_theme_dict():
    """Empty theme dict behaves the same as None — no hint injected."""
    captured_calls: list[dict] = []

    def mock_call_llm(system: str, user: str, model: str | None) -> str:
        captured_calls.append({"system": system, "user": user})
        return '{"correctness": "partial"}'

    interpret_turn_input(
        call_llm=mock_call_llm,
        input_text="x = 4",
        task_context=_MINIMAL_TASK_CONTEXT,
        prompt_text="You are a math tutor.",
        world_sim_theme={},
    )

    assert captured_calls
    assert "[World-Sim Active]" not in captured_calls[0]["user"]


# ---------------------------------------------------------------------------
# build_initial_learning_state — world_sim_theme stored on state
# ---------------------------------------------------------------------------

_MINIMAL_PROFILE: dict[str, Any] = {
    "preferences": {"likes": ["space", "rockets"], "dislikes": []},
    "learning_state": {},
}


def test_build_initial_learning_state_stores_theme():
    """world_sim_theme is attached to the returned state object."""
    state = build_initial_learning_state(_MINIMAL_PROFILE, world_sim_cfg=_WORLD_SIM_CFG)
    assert hasattr(state, "world_sim_theme")
    theme = state.world_sim_theme
    assert isinstance(theme, dict)
    assert theme.get("theme_id") == "space_exploration"


def test_build_initial_learning_state_no_cfg():
    """When world_sim_cfg is None, world_sim_theme is {} on state (no error)."""
    state = build_initial_learning_state(_MINIMAL_PROFILE, world_sim_cfg=None)
    assert hasattr(state, "world_sim_theme")
    assert state.world_sim_theme == {}


def test_build_initial_learning_state_default_kwarg():
    """Calling without world_sim_cfg keyword is backward-compatible."""
    state = build_initial_learning_state(_MINIMAL_PROFILE)
    # Should not raise; world_sim_theme attribute should exist and be {}
    assert hasattr(state, "world_sim_theme")
    assert state.world_sim_theme == {}


# ---------------------------------------------------------------------------
# MUD backward-compat guard: mud_world_cfg=None → mud_world_state == {}
# ---------------------------------------------------------------------------


def test_build_initial_learning_state_mud_world_cfg_none_is_empty():
    """mud_world_cfg=None → mud_world_state is {} on the returned state."""
    state = build_initial_learning_state(_MINIMAL_PROFILE, mud_world_cfg=None)
    assert hasattr(state, "mud_world_state")
    assert state.mud_world_state == {}


def test_build_initial_learning_state_no_mud_kwarg_is_backward_compat():
    """Omitting mud_world_cfg entirely → mud_world_state == {} (no error)."""
    state = build_initial_learning_state(_MINIMAL_PROFILE, world_sim_cfg=_WORLD_SIM_CFG)
    assert hasattr(state, "mud_world_state")
    assert state.mud_world_state == {}


# ---------------------------------------------------------------------------
# select_world_sim_theme — 'interests' canonical field (regression guard)
# ---------------------------------------------------------------------------


def test_select_theme_uses_interests_field():
    """Canonical 'interests' field (not just 'likes') triggers theme selection."""
    profile = {"preferences": {"interests": ["space", "rockets"], "dislikes": []}}
    theme = select_world_sim_theme(profile, _WORLD_SIM_CFG)
    assert theme["theme_id"] == "space_exploration"


def test_select_theme_interests_and_likes_merged():
    """Both interests and likes are checked; either can trigger a match."""
    # Only 'likes' overlaps with nature keywords
    profile = {"preferences": {"interests": ["cooking"], "likes": ["nature", "wildlife"]}}
    theme = select_world_sim_theme(profile, _WORLD_SIM_CFG)
    assert theme["theme_id"] == "nature_and_outdoors"
