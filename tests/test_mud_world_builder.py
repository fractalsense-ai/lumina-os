"""
Tests for the MUD World Builder — generate_mud_world(), the mud_world_state
integration in build_initial_learning_state() and domain_step(), and the
[MUD World Active] hint injection in interpret_turn_input().

Covers:
- generate_mud_world: preference matching (interests), legacy 'likes' alias,
  dislike veto, fallback to general_math, disabled cfg, None cfg,
  second-template match, interests + dislikes merge
- build_initial_learning_state: mud_world_state stored on returned state
- build_initial_learning_state: mud_world_cfg=None → mud_world_state == {}
- domain_step: mud_world_state preserved across ZPD state replacement
- interpret_turn_input: [MUD World Active] block present when mud_world_state set
- interpret_turn_input: [MUD World Active] block absent when mud_world_state None
- interpret_turn_input: all 8 narrative fields appear in the hint
- interpret_turn_input: both [World-Sim Active] and [MUD World Active] present
  simultaneously when both are active
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_runtime_adapters():
    spec = importlib.util.spec_from_file_location(
        "edu_runtime_adapters_mud_test",
        str(REPO_ROOT / "model-packs/education/controllers/runtime_adapters.py"),
    )
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _load_learning_adapters():
    spec = importlib.util.spec_from_file_location(
        "edu_learning_adapters_mud_test",
        str(REPO_ROOT / "model-packs/education/controllers/learning_adapters.py"),
    )
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


_adapters = _load_runtime_adapters()
_learning = _load_learning_adapters()
generate_mud_world = _adapters.generate_mud_world
build_initial_learning_state = _learning.build_initial_learning_state
domain_step = _learning.domain_step
interpret_turn_input = _learning.interpret_turn_input

# ---------------------------------------------------------------------------
# Shared test fixtures
# ---------------------------------------------------------------------------

# A minimal template library that mirrors the real one but is self-contained
# for deterministic testing.
_TEMPLATES = [
    {
        "id": "dark_fantasy_dungeon",
        "preference_keywords": ["fantasy", "dnd", "magic", "dragons", "rpg"],
        "zone": "The Sunken Catacombs of Aethelgard",
        "protagonist": "Novice Spellweaver",
        "antagonist": "Xylar the Undying",
        "guide_npc": "Barnaby (sarcastic enchanted grimoire)",
        "macguffin": "The Crown of Dawn",
        "variable_skin": "Unstable Mana Crystals",
        "obstacle_theme": "Magical Counter-Weight Scales and Runic Doors",
        "failure_state": "Trap triggered! A poison dart strikes you. Lose 10 HP.",
    },
    {
        "id": "zombie_survival",
        "preference_keywords": ["zombies", "zombie", "survival", "horror"],
        "zone": "Sector 4 Quarantine Zone",
        "protagonist": "Rookie Scavenger",
        "antagonist": "The Goliath",
        "guide_npc": "Patch (HAM radio survivor)",
        "macguffin": "The Patient Zero Blood Sample",
        "variable_skin": "Unmarked Supply Crates",
        "obstacle_theme": "Rusted Generator Valves and Barricaded Doors",
        "failure_state": "Too much noise! Horde Proximity +15%.",
    },
    {
        "id": "space_mission",
        "preference_keywords": ["space", "rockets", "astronaut", "nasa", "sci-fi"],
        "zone": "Derelict Research Station Helios-7",
        "protagonist": "Mission Mathematician",
        "antagonist": "MAXIS (rogue AI)",
        "guide_npc": "Glitch (snarky micro-drone)",
        "macguffin": "The Emergency Escape Pod Coordinates",
        "variable_skin": "Energy Cells",
        "obstacle_theme": "Encrypted Airlock Terminals",
        "failure_state": "System error! MAXIS detects the breach. Stealth meter -10.",
    },
    {
        "id": "general_math",
        "preference_keywords": [],
        "zone": "The Math Challenge Arena",
        "protagonist": "Problem Solver",
        "antagonist": "The Equation Master",
        "guide_npc": "Hint",
        "macguffin": "The Final Answer",
        "variable_skin": "unknown quantities",
        "obstacle_theme": "Equations and Mathematical Constraints",
        "failure_state": "Incorrect step! Check your work and try again.",
    },
]

_MUD_CFG_ENABLED = {"enabled": True, "templates": _TEMPLATES}
_MUD_CFG_DISABLED = {"enabled": False, "templates": _TEMPLATES}


def _profile(interests=None, likes=None, dislikes=None) -> dict[str, Any]:
    """Build a minimal entity profile with the given preference lists."""
    prefs: dict[str, Any] = {}
    if interests is not None:
        prefs["interests"] = interests
    if likes is not None:
        prefs["likes"] = likes
    if dislikes is not None:
        prefs["dislikes"] = dislikes
    return {"preferences": prefs}


# ---------------------------------------------------------------------------
# generate_mud_world — template selection
# ---------------------------------------------------------------------------


def test_generate_mud_world_matches_interests():
    """Canonical 'interests' field matches a template keyword."""
    profile = _profile(interests=["fantasy", "reading"])
    world = generate_mud_world(profile, _MUD_CFG_ENABLED)
    assert world["template_id"] == "dark_fantasy_dungeon"
    assert world["protagonist"] == "Novice Spellweaver"


def test_generate_mud_world_matches_legacy_likes():
    """Legacy 'likes' field (alias) also triggers template selection."""
    profile = _profile(likes=["zombies", "gaming"])
    world = generate_mud_world(profile, _MUD_CFG_ENABLED)
    assert world["template_id"] == "zombie_survival"
    assert world["variable_skin"] == "Unmarked Supply Crates"


def test_generate_mud_world_interests_and_likes_merged():
    """interests and likes are merged; either overlap triggers a match."""
    # Only 'likes' overlaps with space_mission keywords
    profile = _profile(interests=["cooking"], likes=["space"])
    world = generate_mud_world(profile, _MUD_CFG_ENABLED)
    assert world["template_id"] == "space_mission"


def test_generate_mud_world_dislike_veto_wins():
    """Dislike veto overrides a matching interest — falls back to general_math."""
    profile = _profile(interests=["fantasy"], dislikes=["fantasy"])
    world = generate_mud_world(profile, _MUD_CFG_ENABLED)
    assert world["template_id"] == "general_math"


def test_generate_mud_world_dislike_partial_keyword_veto():
    """Only needs one dislike keyword to veto an entire template."""
    # "dragons" is in dark_fantasy_dungeon keywords; student dislikes dragons
    profile = _profile(interests=["rpg", "magic"], dislikes=["dragons"])
    world = generate_mud_world(profile, _MUD_CFG_ENABLED)
    # dark_fantasy_dungeon is vetoed; no other match → fallback
    assert world["template_id"] == "general_math"


def test_generate_mud_world_fallback_when_no_match():
    """No matching interests → falls back to general_math (empty keywords)."""
    profile = _profile(interests=["cooking", "chess", "painting"])
    world = generate_mud_world(profile, _MUD_CFG_ENABLED)
    assert world["template_id"] == "general_math"
    assert world["zone"] == "The Math Challenge Arena"


def test_generate_mud_world_empty_interests():
    """Student with no preferences at all → general_math fallback."""
    world = generate_mud_world(_profile(), _MUD_CFG_ENABLED)
    assert world["template_id"] == "general_math"


def test_generate_mud_world_second_template_match():
    """When first template is vetoed, second matching template wins."""
    # Only zombie_survival matches "survival"; dark_fantasy vetoed by dislike
    profile = _profile(interests=["fantasy", "survival"], dislikes=["rpg"])
    world = generate_mud_world(profile, _MUD_CFG_ENABLED)
    assert world["template_id"] == "zombie_survival"


def test_generate_mud_world_disabled_returns_empty():
    """Disabled mud_world_cfg → returns {}."""
    profile = _profile(interests=["fantasy"])
    world = generate_mud_world(profile, _MUD_CFG_DISABLED)
    assert world == {}


def test_generate_mud_world_none_cfg_returns_empty():
    """None cfg → returns {} gracefully."""
    world = generate_mud_world(_profile(interests=["fantasy"]), None)
    assert world == {}


def test_generate_mud_world_no_templates_returns_empty():
    """Empty template list → returns {}."""
    world = generate_mud_world(_profile(interests=["fantasy"]), {"enabled": True, "templates": []})
    assert world == {}


def test_generate_mud_world_excludes_preference_keywords_from_result():
    """Returned dict does NOT contain the 'preference_keywords' field."""
    profile = _profile(interests=["fantasy"])
    world = generate_mud_world(profile, _MUD_CFG_ENABLED)
    assert "preference_keywords" not in world


def test_generate_mud_world_all_eight_fields_present():
    """All 8 narrative fields must be present in every non-empty result."""
    required = {
        "zone", "protagonist", "antagonist", "guide_npc",
        "macguffin", "variable_skin", "obstacle_theme", "failure_state",
    }
    for interests_val in [["fantasy"], ["zombies"], ["space"], ["cooking"]]:
        profile = _profile(interests=interests_val)
        world = generate_mud_world(profile, _MUD_CFG_ENABLED)
        missing = required - set(world.keys())
        assert not missing, (
            f"Template for {interests_val!r} missing fields: {missing}"
        )


# ---------------------------------------------------------------------------
# build_initial_learning_state — mud_world_state on state object
# ---------------------------------------------------------------------------


def test_build_initial_learning_state_stores_mud_world_state():
    """mud_world_state is stored on the returned learning state."""
    profile = {
        "preferences": {"interests": ["fantasy"]},
        "learning_state": {},
    }
    state = build_initial_learning_state(
        profile,
        mud_world_cfg=_MUD_CFG_ENABLED,
    )
    assert hasattr(state, "mud_world_state")
    assert state.mud_world_state["template_id"] == "dark_fantasy_dungeon"


def test_build_initial_learning_state_mud_world_cfg_none():
    """mud_world_cfg=None → mud_world_state is {} (backward compat)."""
    profile = {"preferences": {"interests": ["fantasy"]}, "learning_state": {}}
    state = build_initial_learning_state(profile, mud_world_cfg=None)
    assert hasattr(state, "mud_world_state")
    assert state.mud_world_state == {}


def test_build_initial_learning_state_world_sim_theme_still_set():
    """world_sim_theme is still stored on state even when MUD is also enabled."""
    _ws_cfg = {
        "enabled": True,
        "default_theme": "general_math",
        "themes": {
            "general_math": {
                "setting_description": "Math challenges.",
                "artifact_framing": "certificate",
                "task_framing": "problem",
                "exit_phrase": "exit session",
                "preference_keywords": [],
            }
        },
    }
    profile = {"preferences": {}, "learning_state": {}}
    state = build_initial_learning_state(
        profile,
        world_sim_cfg=_ws_cfg,
        mud_world_cfg=_MUD_CFG_ENABLED,
    )
    assert hasattr(state, "world_sim_theme")
    assert hasattr(state, "mud_world_state")


# ---------------------------------------------------------------------------
# domain_step — mud_world_state preserved across ZPD step
# ---------------------------------------------------------------------------


def _make_state_with_mud(template_id: str = "dark_fantasy_dungeon") -> Any:
    """Build a minimal state object that carries mud_world_state."""
    profile = {
        "preferences": {"interests": ["fantasy"]},
        "learning_state": {},
    }
    state = build_initial_learning_state(
        profile,
        mud_world_cfg=_MUD_CFG_ENABLED,
    )
    return state


def test_domain_step_preserves_mud_world_state():
    """mud_world_state is carried forward through domain_step's ZPD replacement."""
    state = _make_state_with_mud()
    original_template_id = state.mud_world_state.get("template_id")

    task_spec = {
        "task_id": "algebra-test-001",
        "skills_required": ["solve_one_variable"],
        "nominal_difficulty": 0.45,
    }
    evidence = {
        "correctness": "correct",
        "hint_used": False,
        "response_latency_sec": 8.0,
        "frustration_marker_count": 0,
        "repeated_error": False,
        "off_task_ratio": 0.0,
        "step_count": 2,
        "min_steps": 1,
        "problem_solved": True,
        "equivalence_preserved": True,
    }
    params = {
        "min_challenge": 0.3,
        "max_challenge": 0.7,
        "drift_window_turns": 10,
        "minor_drift_threshold": 0.3,
        "major_drift_threshold": 0.5,
        "persistence_required": 3,
        "fluency_monitor": {
            "target_consecutive_successes": 3,
            "time_threshold_seconds": 120,
        },
    }
    new_state, _ = domain_step(state, task_spec, evidence, params)

    assert hasattr(new_state, "mud_world_state"), "mud_world_state missing after domain_step"
    assert new_state.mud_world_state.get("template_id") == original_template_id, (
        "mud_world_state changed across ZPD step"
    )
    assert new_state.mud_world_state.get("zone") == "The Sunken Catacombs of Aethelgard"


# ---------------------------------------------------------------------------
# interpret_turn_input — [MUD World Active] hint injection
# ---------------------------------------------------------------------------

_MINIMAL_TASK_CONTEXT: dict[str, Any] = {
    "task_id": "algebra-test-001",
    "skills_required": ["solve_one_variable"],
    "current_task": {
        "equation": "3x + 5 = 17",
        "target_variable": "x",
        "expected_answer": "x = 4",
        "min_steps": 2,
    },
}

_FANTASY_MUD_STATE = {
    "template_id": "dark_fantasy_dungeon",
    "zone": "The Sunken Catacombs of Aethelgard",
    "protagonist": "Novice Spellweaver",
    "antagonist": "Xylar the Undying",
    "guide_npc": "Barnaby (sarcastic enchanted grimoire)",
    "macguffin": "The Crown of Dawn",
    "variable_skin": "Unstable Mana Crystals",
    "obstacle_theme": "Magical Counter-Weight Scales and Runic Doors",
    "failure_state": "Trap triggered! A poison dart strikes you. Lose 10 HP.",
}

_SPACE_WORLD_SIM_THEME = {
    "theme_id": "space_exploration",
    "setting_description": "You are the mission mathematician aboard Helios.",
    "artifact_framing": "mission_badge",
    "task_framing": "mission_briefing",
    "exit_phrase": "end mission",
    "preference_keywords": ["space"],
}


def _capture_llm():
    """Return a (mock_fn, captures_list) pair."""
    captures: list[dict] = []

    def _mock(system: str, user: str, model: str | None) -> str:
        captures.append({"system": system, "user": user})
        return '{"correctness": "partial", "step_count": 1}'

    return _mock, captures


def test_interpret_turn_input_injects_mud_world_hint():
    """[MUD World Active] block appears in user arg when mud_world_state is set."""
    mock_llm, caps = _capture_llm()
    interpret_turn_input(
        call_llm=mock_llm,
        input_text="I subtract 5 from both sides",
        task_context=_MINIMAL_TASK_CONTEXT,
        prompt_text="You are a tutor.",
        mud_world_state=_FANTASY_MUD_STATE,
    )
    assert caps, "call_llm was never called"
    user_arg = caps[0]["user"]
    assert "[MUD World Active]" in user_arg


def test_interpret_turn_input_mud_hint_contains_all_eight_fields():
    """All 8 narrative field values appear in the MUD hint block."""
    mock_llm, caps = _capture_llm()
    interpret_turn_input(
        call_llm=mock_llm,
        input_text="I subtract 5 from both sides",
        task_context=_MINIMAL_TASK_CONTEXT,
        prompt_text="You are a tutor.",
        mud_world_state=_FANTASY_MUD_STATE,
    )
    user_arg = caps[0]["user"]
    for field in (
        "The Sunken Catacombs of Aethelgard",  # zone
        "Novice Spellweaver",                  # protagonist
        "Xylar the Undying",                   # antagonist
        "Barnaby",                             # guide_npc
        "The Crown of Dawn",                   # macguffin
        "Unstable Mana Crystals",              # variable_skin
        "Magical Counter-Weight Scales",       # obstacle_theme (partial)
        "Trap triggered!",                     # failure_state (partial)
    ):
        assert field in user_arg, f"Expected field value {field!r} missing from MUD hint"


def test_interpret_turn_input_no_mud_hint_when_state_none():
    """No [MUD World Active] block when mud_world_state is None."""
    mock_llm, caps = _capture_llm()
    interpret_turn_input(
        call_llm=mock_llm,
        input_text="x = 4",
        task_context=_MINIMAL_TASK_CONTEXT,
        prompt_text="You are a tutor.",
        mud_world_state=None,
    )
    user_arg = caps[0]["user"]
    assert "[MUD World Active]" not in user_arg


def test_interpret_turn_input_no_mud_hint_when_state_empty():
    """No [MUD World Active] block when mud_world_state is {} (disabled/fallback)."""
    mock_llm, caps = _capture_llm()
    interpret_turn_input(
        call_llm=mock_llm,
        input_text="x = 4",
        task_context=_MINIMAL_TASK_CONTEXT,
        prompt_text="You are a tutor.",
        mud_world_state={},
    )
    user_arg = caps[0]["user"]
    assert "[MUD World Active]" not in user_arg


def test_interpret_turn_input_both_world_sim_and_mud_active():
    """When both world_sim_theme and mud_world_state are set, both hint blocks appear."""
    mock_llm, caps = _capture_llm()
    interpret_turn_input(
        call_llm=mock_llm,
        input_text="I subtract 5 first",
        task_context=_MINIMAL_TASK_CONTEXT,
        prompt_text="You are a tutor.",
        world_sim_theme=_SPACE_WORLD_SIM_THEME,
        mud_world_state=_FANTASY_MUD_STATE,
    )
    user_arg = caps[0]["user"]
    assert "[World-Sim Active]" in user_arg
    assert "[MUD World Active]" in user_arg
    # Spot-check each hint contributes its specific content
    assert "mission_briefing" in user_arg       # from world_sim_theme
    assert "Sunken Catacombs" in user_arg       # from mud_world_state


def test_interpret_turn_input_variable_skin_never_instruction_present():
    """The NEVER use bare variable letter instruction appears in the hint."""
    mock_llm, caps = _capture_llm()
    interpret_turn_input(
        call_llm=mock_llm,
        input_text="x = 4",
        task_context=_MINIMAL_TASK_CONTEXT,
        prompt_text="You are a tutor.",
        mud_world_state=_FANTASY_MUD_STATE,
    )
    user_arg = caps[0]["user"]
    assert "NEVER" in user_arg


def test_interpret_turn_input_failure_state_verbatim_instruction_present():
    """The 'use verbatim' instruction for failure_state appears in the hint."""
    mock_llm, caps = _capture_llm()
    interpret_turn_input(
        call_llm=mock_llm,
        input_text="subtract only one side",
        task_context=_MINIMAL_TASK_CONTEXT,
        prompt_text="You are a tutor.",
        mud_world_state=_FANTASY_MUD_STATE,
    )
    user_arg = caps[0]["user"]
    assert "verbatim" in user_arg.lower()
