from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Callable

_THIS_DIR = Path(__file__).resolve().parent

_zpd_spec = importlib.util.spec_from_file_location(
    "zpd_monitor_runtime",
    str(_THIS_DIR / "zpd_monitor_v0_2.py"),
)
_zpd_mod = importlib.util.module_from_spec(_zpd_spec)  # type: ignore[arg-type]
sys.modules["zpd_monitor_runtime"] = _zpd_mod
_zpd_spec.loader.exec_module(_zpd_mod)  # type: ignore[union-attr]

AffectState = _zpd_mod.AffectState
RecentWindow = _zpd_mod.RecentWindow
LearningState = _zpd_mod.LearningState
zpd_monitor_step = _zpd_mod.zpd_monitor_step

_fluency_spec = importlib.util.spec_from_file_location(
    "fluency_monitor_runtime",
    str(_THIS_DIR / "fluency_monitor.py"),
)
_fluency_mod = importlib.util.module_from_spec(_fluency_spec)  # type: ignore[arg-type]
sys.modules["fluency_monitor_runtime"] = _fluency_mod
_fluency_spec.loader.exec_module(_fluency_mod)  # type: ignore[union-attr]

FluencyState = _fluency_mod.FluencyState
fluency_monitor_step_fn = _fluency_mod.fluency_monitor_step
build_initial_fluency_state_fn = _fluency_mod.build_initial_fluency_state


def select_world_sim_theme(
    entity_profile: dict[str, Any],
    world_sim_cfg: dict[str, Any] | None,
) -> dict[str, Any]:
    """Select the active world-sim theme for this session based on entity preferences.

    Returns the matched theme config dict, or {} if world_sim is disabled or absent.
    Selection order: first theme whose preference_keywords overlap with profile
    likes, skipping any theme whose keywords overlap with dislikes. Falls back
    to the default_theme when no preference match is found.
    """
    if not world_sim_cfg or not world_sim_cfg.get("enabled", False):
        return {}

    themes: dict[str, Any] = world_sim_cfg.get("themes") or {}
    default_theme_id: str = world_sim_cfg.get("default_theme", "")

    preferences = entity_profile.get("preferences") or {}
    likes: list[str] = [str(v).lower() for v in (preferences.get("likes") or [])]
    dislikes: list[str] = [str(v).lower() for v in (preferences.get("dislikes") or [])]

    # Attempt preference-matched selection
    for theme_id, theme_cfg in themes.items():
        keywords: list[str] = [
            str(kw).lower() for kw in (theme_cfg.get("preference_keywords") or [])
        ]
        if not keywords:
            # Themes with no keywords are fallback-only; skip for active matching
            continue
        keyword_set = set(keywords)
        if keyword_set & set(dislikes):
            # Any overlap with dislikes disqualifies this theme
            continue
        if keyword_set & set(likes):
            return {"theme_id": theme_id, **theme_cfg}

    # Fall back to default_theme
    if default_theme_id and default_theme_id in themes:
        return {"theme_id": default_theme_id, **themes[default_theme_id]}

    return {}


def build_initial_learning_state(
    profile: dict[str, Any],
    world_sim_cfg: dict[str, Any] | None = None,
) -> Any:
    """Build the education domain-lib state from profile learning_state."""
    learning_state = profile.get("learning_state") or {}
    affect = learning_state.get("affect") or {}
    mastery_raw = learning_state.get("mastery") or {}
    challenge_band_raw = learning_state.get("challenge_band") or {}
    recent_window_raw = learning_state.get("recent_window") or {}

    mastery = {str(k): float(v) for k, v in mastery_raw.items()}
    challenge_band = {
        "min_challenge": float(challenge_band_raw.get("min_challenge", 0.3)),
        "max_challenge": float(challenge_band_raw.get("max_challenge", 0.7)),
    }

    recent_window = RecentWindow(
        window_turns=int(recent_window_raw.get("window_turns", 10)),
        attempts=int(recent_window_raw.get("attempts", 0)),
        consecutive_incorrect=int(recent_window_raw.get("consecutive_incorrect", 0)),
        hint_count=int(recent_window_raw.get("hint_count", 0)),
        outside_pct=float(recent_window_raw.get("outside_pct", 0.0)),
        consecutive_outside=int(recent_window_raw.get("consecutive_outside", 0)),
        outside_flags=[bool(v) for v in (recent_window_raw.get("outside_flags") or [])],
        hint_flags=[bool(v) for v in (recent_window_raw.get("hint_flags") or [])],
    )

    ls = LearningState(
        affect=AffectState(
            salience=float(affect.get("salience", 0.7)),
            valence=float(affect.get("valence", 0.0)),
            arousal=float(affect.get("arousal", 0.5)),
        ),
        mastery=mastery,
        challenge_band=challenge_band,
        recent_window=recent_window,
        challenge=float(learning_state.get("challenge", 0.5)),
        uncertainty=float(learning_state.get("uncertainty", 0.5)),
    )

    # Attach fluency state as a dynamic attribute so the composite
    # state object carries both ZPD learning state and fluency tracking.
    ls.fluency = FluencyState()  # type: ignore[attr-defined]

    # Attach world-sim theme: selected once at session start and carried on
    # the state object so the same theme is used consistently every turn.
    ls.world_sim_theme = select_world_sim_theme(profile, world_sim_cfg)  # type: ignore[attr-defined]

    return ls


def domain_step(
    state: Any,
    task_spec: dict[str, Any],
    evidence: dict[str, Any],
    params: dict[str, Any],
) -> tuple[Any, dict[str, Any]]:
    # 1. ZPD monitor (primary)
    state, zpd_decision = zpd_monitor_step(state, task_spec, evidence, params=params)

    # 2. Fluency monitor (secondary)
    fluency_state: FluencyState = getattr(state, "fluency", FluencyState())
    fluency_params = params.get("fluency_monitor") or {}
    fluency_state, fluency_decision = fluency_monitor_step_fn(
        fluency_state, task_spec, evidence, params=fluency_params,
    )
    state.fluency = fluency_state  # type: ignore[attr-defined]

    # 3. Merge: ZPD drift actions take priority over fluency actions
    merged = dict(zpd_decision)
    merged["fluency"] = fluency_decision
    if zpd_decision.get("action") is None and fluency_decision.get("action") is not None:
        merged["action"] = fluency_decision["action"]

    return state, merged


def _strip_markdown_fences(raw: str) -> str:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[: cleaned.rfind("```")]
    return cleaned.strip()


def interpret_turn_input(
    call_llm: Callable[[str, str, str | None], str],
    input_text: str,
    task_context: dict[str, Any],
    prompt_text: str,
    default_fields: dict[str, Any] | None = None,
    tool_fns: dict[str, Callable[..., Any]] | None = None,
    nlp_pre_interpreter_fn: Callable[..., Any] | None = None,
    world_sim_theme: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context_hint = ""
    if task_context.get("task_id"):
        context_hint = f"\nCurrent task: {task_context.get('task_id', 'unknown')}"
        if task_context.get("skills_required"):
            context_hint += f"\nSkills: {', '.join(task_context['skills_required'])}"
    current_problem = task_context.get("current_problem")
    if isinstance(current_problem, dict):
        equation = current_problem.get("equation")
        target_variable = current_problem.get("target_variable")
        expected_answer = current_problem.get("expected_answer")
        status = current_problem.get("status")
        if equation:
            context_hint += f"\nCurrent problem equation: {equation}"
        if target_variable:
            context_hint += f"\nTarget variable: {target_variable}"
        if expected_answer:
            context_hint += f"\nExpected solved form: {expected_answer}"
        if status:
            context_hint += f"\nProblem status: {status}"
        min_steps = current_problem.get("min_steps")
        if min_steps is not None:
            context_hint += f"\nMinimum steps required: {min_steps}"

    # ── NLP pre-interpreter (deterministic anchors) ────────────
    nlp_evidence: dict[str, Any] | None = None
    if nlp_pre_interpreter_fn is not None:
        try:
            nlp_evidence = nlp_pre_interpreter_fn(input_text, task_context)
        except Exception:
            nlp_evidence = None

    if nlp_evidence is not None:
        anchors = nlp_evidence.get("_nlp_anchors") or []
        if anchors:
            lines = ["\nNLP pre-analysis (deterministic):"]
            for a in anchors:
                line = f"- {a['field']}: {a['value']}"
                if "confidence" in a:
                    line += f" (confidence: {a['confidence']})"
                if "detail" in a:
                    line += f" — {a['detail']}"
                lines.append(line)
            lines.append("Use these as starting values. Override if your analysis disagrees.")
            context_hint += "\n" + "\n".join(lines)

    # ── World-sim persona context hint ─────────────────────────
    if world_sim_theme:
        setting = world_sim_theme.get("setting_description", "")
        task_framing = world_sim_theme.get("task_framing", "problem")
        artifact_framing = world_sim_theme.get("artifact_framing", "certificate")
        context_hint += (
            f"\n[World-Sim Active] Setting: {setting}"
            f" Use in-world framing ('{task_framing}') for task labels."
            f" Artifact framing: '{artifact_framing}'."
        )

    # ── Deterministic algebra parser (primary source) ──────────
    parser_result: dict[str, Any] | None = None
    all_tools = tool_fns or {}
    algebra_parser_fn = all_tools.get("algebra_parser")
    if algebra_parser_fn is not None and isinstance(current_problem, dict):
        eq = current_problem.get("equation", "")
        tvar = current_problem.get("target_variable", "x")
        exp_ans = current_problem.get("expected_answer", "")
        if eq:
            try:
                parser_result = algebra_parser_fn({
                    "call_type": "parse_steps",
                    "equation": eq,
                    "target_variable": tvar,
                    "expected_answer": exp_ans,
                    "student_work": input_text,
                })
            except Exception as exc:
                import logging as _logging
                import traceback as _tb
                _logging.getLogger("edu_runtime_adapters").warning(
                    "Algebra parser failed: %s\n%s", exc, _tb.format_exc(),
                )
                parser_result = None

    # ── LLM extraction (fallback / supplementary) ─────────────
    raw_response = call_llm(
        system=prompt_text,
        user=f"Student message: {input_text}{context_hint}",
        model=None,
    )

    try:
        evidence = json.loads(_strip_markdown_fences(raw_response))
    except (json.JSONDecodeError, IndexError):
        evidence = {}

    defaults = dict(default_fields or {})
    if not defaults:
        _min_steps = int(current_problem.get("min_steps", 1)) if isinstance(current_problem, dict) else 1
        defaults = {
            "correctness": "partial",
            "hint_used": False,
            "response_latency_sec": 10.0,
            "frustration_marker_count": 0,
            "repeated_error": False,
            "off_task_ratio": 0.0,
            "step_count": 0,
            "min_steps": _min_steps,
        }

    for key, default_val in defaults.items():
        if key not in evidence or evidence[key] is None:
            evidence[key] = default_val

    # ── Override LLM fields with deterministic parser output ──
    if parser_result is not None and parser_result.get("ok"):
        if parser_result.get("step_count") is not None:
            evidence["step_count"] = parser_result["step_count"]
        if parser_result.get("equivalence_preserved") is not None:
            evidence["equivalence_preserved"] = parser_result["equivalence_preserved"]
        if parser_result.get("substitution_check") is not None:
            evidence["substitution_check"] = parser_result["substitution_check"]
        if parser_result.get("method_recognized") is not None:
            evidence["method_recognized"] = True

        # Override correctness when parser confirms substitution and the
        # student's text contains the expected answer value.
        exp_answer = current_problem.get("expected_answer", "") if isinstance(current_problem, dict) else ""
        if parser_result.get("substitution_check") is True and exp_answer:
            ans_match = re.search(r"=\s*([+-]?\d+\.?\d*)", exp_answer)
            if ans_match:
                expected_num = ans_match.group(1)
                if re.search(r"(?:^|\s|=)" + re.escape(expected_num) + r"(?:\s|$|[.,;])", input_text):
                    evidence["correctness"] = "correct"

    # A problem is fully solved when correctness is confirmed by substitution
    # and the step-count minimum has been met. This flag is consumed by the
    # core engine's problem-advancement gate and must not reference domain
    # field names outside this adapter.
    evidence["problem_solved"] = (
        evidence.get("correctness") == "correct"
        and evidence.get("substitution_check") is True
        and evidence.get("step_count", 0) >= evidence.get("min_steps", 1)
    )

    return evidence
