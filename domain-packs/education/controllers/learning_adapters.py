"""Learning-module adapters for the education domain pack.

Contains the ZPD/fluency-backed state builder, domain step, and turn
interpreter used by algebra and pre-algebra modules.  Global helpers
(world-sim theme selection, MUD world generation) are loaded from
``runtime_adapters.py`` at import time.
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any, Callable

# ── Domain-lib: ZPD monitor ──────────────────────────────────
_THIS_DIR = Path(__file__).resolve().parent
_DOMAIN_LIB = _THIS_DIR.parent / "domain-lib"

_zpd_spec = importlib.util.spec_from_file_location(
    "zpd_monitor_runtime",
    str(_DOMAIN_LIB / "zpd_monitor_v0_2.py"),
)
_zpd_mod = importlib.util.module_from_spec(_zpd_spec)  # type: ignore[arg-type]
if "zpd_monitor_runtime" not in sys.modules:
    sys.modules["zpd_monitor_runtime"] = _zpd_mod
    _zpd_spec.loader.exec_module(_zpd_mod)  # type: ignore[union-attr]
else:
    _zpd_mod = sys.modules["zpd_monitor_runtime"]

AffectState = _zpd_mod.AffectState
RecentWindow = _zpd_mod.RecentWindow
LearningState = _zpd_mod.LearningState
zpd_monitor_step = _zpd_mod.zpd_monitor_step

# ── Domain-lib: Fluency monitor ──────────────────────────────
_fluency_spec = importlib.util.spec_from_file_location(
    "fluency_monitor_runtime",
    str(_DOMAIN_LIB / "fluency_monitor.py"),
)
_fluency_mod = importlib.util.module_from_spec(_fluency_spec)  # type: ignore[arg-type]
if "fluency_monitor_runtime" not in sys.modules:
    sys.modules["fluency_monitor_runtime"] = _fluency_mod
    _fluency_spec.loader.exec_module(_fluency_mod)  # type: ignore[union-attr]
else:
    _fluency_mod = sys.modules["fluency_monitor_runtime"]

FluencyState = _fluency_mod.FluencyState
fluency_monitor_step_fn = _fluency_mod.fluency_monitor_step
build_initial_fluency_state_fn = _fluency_mod.build_initial_fluency_state

# ── Global adapter helpers (world-sim) ───────────────────────
_ga_spec = importlib.util.spec_from_file_location(
    "edu_global_adapters",
    str(_THIS_DIR / "runtime_adapters.py"),
)
if "edu_global_adapters" not in sys.modules:
    _ga_mod = importlib.util.module_from_spec(_ga_spec)  # type: ignore[arg-type]
    sys.modules["edu_global_adapters"] = _ga_mod
    _ga_spec.loader.exec_module(_ga_mod)  # type: ignore[union-attr]
_ga_mod = sys.modules["edu_global_adapters"]

select_world_sim_theme = _ga_mod.select_world_sim_theme
generate_mud_world = _ga_mod.generate_mud_world


def _strip_markdown_fences(raw: str) -> str:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[: cleaned.rfind("```")]
    return cleaned.strip()


def build_initial_learning_state(
    profile: dict[str, Any],
    world_sim_cfg: dict[str, Any] | None = None,
    tiers: list[dict[str, Any]] | None = None,
    tier_progression: list[str] | None = None,
    nominal_difficulty: float = 0.5,
    mud_world_cfg: dict[str, Any] | None = None,
    module_state: dict[str, Any] | None = None,
    initial_module_state: dict[str, Any] | None = None,
) -> Any:
    """Build the education domain-lib state from profile learning_state.

    Three-tier state priority:
      1. DB-backed ``module_state`` (returning student)
      2. ``initial_module_state`` from runtime-config (first time in module)
      3. ``profile["learning_state"]`` (backward-compat fallback)
    """
    if module_state:
        learning_state = module_state
    elif initial_module_state:
        learning_state = dict(initial_module_state)
    else:
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
    # If the profile already has persisted fluency (from a previous session),
    # restore it directly so the student resumes at the tier they earned.
    # Otherwise initialise based on nominal_difficulty or default to tier_1.
    fluency_saved = learning_state.get("fluency") if learning_state else None
    if fluency_saved:
        ls.fluency = FluencyState(  # type: ignore[attr-defined]
            current_tier=str(fluency_saved.get("current_tier", "tier_1")),
            consecutive_correct=int(fluency_saved.get("consecutive_correct", 0)),
        )
    elif tiers and tier_progression:
        ls.fluency = build_initial_fluency_state_fn(  # type: ignore[attr-defined]
            nominal_difficulty, tiers, tier_progression
        )
    else:
        ls.fluency = FluencyState()  # type: ignore[attr-defined]

    # Attach world-sim theme: selected once at session start and carried on
    # the state object so the same theme is used consistently every turn.
    ls.world_sim_theme = select_world_sim_theme(profile, world_sim_cfg)  # type: ignore[attr-defined]

    # Attach MUD world state: generated once per session from the student's
    # interest profile and locked in for the session's duration.
    ls.mud_world_state = generate_mud_world(profile, mud_world_cfg)  # type: ignore[attr-defined]

    return ls


def domain_step(
    state: Any,
    task_spec: dict[str, Any],
    evidence: dict[str, Any],
    params: dict[str, Any],
) -> tuple[Any, dict[str, Any]]:
    # Carry forward dynamic attributes that zpd_monitor_step will NOT preserve
    # on the new LearningState it returns (dynamic attrs are not dataclass fields).
    prev_fluency: FluencyState = getattr(state, "fluency", FluencyState())
    prev_world_sim_theme: Any = getattr(state, "world_sim_theme", None)
    prev_mud_world_state: Any = getattr(state, "mud_world_state", None)

    # 1. ZPD monitor (primary) — returns a new LearningState instance
    state, zpd_decision = zpd_monitor_step(state, task_spec, evidence, params=params)

    # Restore dynamic attributes on the new state object.
    if not hasattr(state, "world_sim_theme"):
        state.world_sim_theme = prev_world_sim_theme  # type: ignore[attr-defined]
    if not hasattr(state, "mud_world_state"):
        state.mud_world_state = prev_mud_world_state  # type: ignore[attr-defined]

    # 2. Fluency monitor (secondary)
    # Map the universal base field response_latency_sec to the education-domain
    # evidence field solve_elapsed_sec so the fluency time gate works correctly.
    # The core injects response_latency_sec at request arrival (before any
    # LLM/SLM calls) making it an accurate measure of the student's net pace.
    fluency_evidence = dict(evidence)
    if "solve_elapsed_sec" not in fluency_evidence and "response_latency_sec" in fluency_evidence:
        fluency_evidence["solve_elapsed_sec"] = fluency_evidence["response_latency_sec"]

    fluency_state: FluencyState = getattr(state, "fluency", prev_fluency)
    fluency_params = params.get("fluency_monitor") or {}
    fluency_state, fluency_decision = fluency_monitor_step_fn(
        fluency_state, task_spec, fluency_evidence, params=fluency_params,
    )
    state.fluency = fluency_state  # type: ignore[attr-defined]

    # 3. Merge: ZPD drift actions take priority over fluency actions
    merged = dict(zpd_decision)
    merged["fluency"] = fluency_decision
    if zpd_decision.get("action") is None and fluency_decision.get("action") is not None:
        merged["action"] = fluency_decision["action"]

    return state, merged


def interpret_turn_input(
    call_llm: Callable[[str, str, str | None], str],
    input_text: str,
    task_context: dict[str, Any],
    prompt_text: str,
    default_fields: dict[str, Any] | None = None,
    tool_fns: dict[str, Callable[..., Any]] | None = None,
    nlp_pre_interpreter_fn: Callable[..., Any] | None = None,
    world_sim_theme: dict[str, Any] | None = None,
    mud_world_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context_hint = ""
    if task_context.get("task_id"):
        context_hint = f"\nCurrent task: {task_context.get('task_id', 'unknown')}"
        if task_context.get("skills_required"):
            context_hint += f"\nSkills: {', '.join(task_context['skills_required'])}"
    current_problem = task_context.get("current_task")
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

    # ── MUD World State context hint ───────────────────────────
    if mud_world_state:
        context_hint += (
            f"\n[MUD World Active]"
            f" Zone: {mud_world_state.get('zone', '')}"
            f" | Cast: {mud_world_state.get('protagonist', 'Player')} (student)"
            f" vs {mud_world_state.get('antagonist', 'The Boss')} (antagonist)"
            f" — guided by {mud_world_state.get('guide_npc', 'Guide')}"
            f"\n  Objective (MacGuffin): {mud_world_state.get('macguffin', '')}"
            f"\n  Variable skin: unknowns are '{mud_world_state.get('variable_skin', 'the unknown')}'"
            f" — NEVER use a bare variable letter in narrative language."
            f"\n  Equations represented as: {mud_world_state.get('obstacle_theme', '')}"
            f"\n  Invariant violation consequence (use verbatim): {mud_world_state.get('failure_state', '')}"
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
                _logging.getLogger("edu_learning_adapters").warning(
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

    # ── No-problem grace: skip penalty when no equation is assigned ──
    _has_equation = (
        isinstance(current_problem, dict)
        and bool(current_problem.get("equation"))
    )
    if not _has_equation:
        evidence["off_task_ratio"] = 0.0
        evidence["correctness"] = "n/a"

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

    # If the LLM returned null for equivalence_preserved (e.g. no algebraic
    # transformations were present), remove the key entirely so the orchestrator
    # skips the invariant rather than the schema coercing null → false.
    if evidence.get("equivalence_preserved") is None and "equivalence_preserved" in evidence:
        del evidence["equivalence_preserved"]

    # ── Law 2A: step order (reversibility_order_correct) ──────
    if algebra_parser_fn is not None and isinstance(current_problem, dict) and eq:
        try:
            _so_result = algebra_parser_fn({
                "call_type": "check_step_order",
                "equation": eq,
                "target_variable": tvar,
                "student_work": input_text,
            })
        except Exception:
            _so_result = None
        if _so_result is not None and _so_result.get("ok"):
            if _so_result.get("reversibility_order_correct") is not None:
                evidence["reversibility_order_correct"] = _so_result["reversibility_order_correct"]
    if evidence.get("reversibility_order_correct") is None and "reversibility_order_correct" in evidence:
        del evidence["reversibility_order_correct"]

    # ── Law 2B: inequality direction (inequality_direction_correct) ──
    if algebra_parser_fn is not None and isinstance(current_problem, dict):
        _ineq_eq = current_problem.get("inequality") or eq
        if _ineq_eq:
            try:
                _id_result = algebra_parser_fn({
                    "call_type": "check_inequality_direction",
                    "inequality": _ineq_eq,
                    "target_variable": tvar,
                    "student_work": input_text,
                })
            except Exception:
                _id_result = None
            if _id_result is not None and _id_result.get("ok"):
                if _id_result.get("inequality_direction_correct") is not None:
                    evidence["inequality_direction_correct"] = _id_result["inequality_direction_correct"]
    if evidence.get("inequality_direction_correct") is None and "inequality_direction_correct" in evidence:
        del evidence["inequality_direction_correct"]

    # ── Law 3: system verification (substitution_valid) ───────
    if algebra_parser_fn is not None and isinstance(current_problem, dict):
        _sys_eqs = current_problem.get("system_equations") or []
        if _sys_eqs:
            _x_var = current_problem.get("x_variable", "x")
            _y_var = current_problem.get("y_variable", "y")
            # Extract proposed x and y values from student work
            _xy_match = re.search(
                r"\b" + re.escape(_x_var) + r"\s*=\s*([+-]?\d+\.?\d*)",
                input_text,
            )
            _yy_match = re.search(
                r"\b" + re.escape(_y_var) + r"\s*=\s*([+-]?\d+\.?\d*)",
                input_text,
            )
            if _xy_match and _yy_match:
                try:
                    _sv_result = algebra_parser_fn({
                        "call_type": "check_system_verification",
                        "system_equations": _sys_eqs,
                        "x_variable": _x_var,
                        "y_variable": _y_var,
                        "x_val": float(_xy_match.group(1)),
                        "y_val": float(_yy_match.group(1)),
                    })
                except Exception:
                    _sv_result = None
                if _sv_result is not None and _sv_result.get("ok"):
                    if _sv_result.get("substitution_valid") is not None:
                        evidence["substitution_valid"] = _sv_result["substitution_valid"]
    if evidence.get("substitution_valid") is None and "substitution_valid" in evidence:
        del evidence["substitution_valid"]

    # ── Law 5: slope computation (relationship_correctly_mapped) ─
    if algebra_parser_fn is not None and isinstance(current_problem, dict):
        _correct_slope = current_problem.get("correct_slope")
        _table_data = current_problem.get("table_data")
        if _correct_slope is not None or _table_data is not None:
            try:
                _sc_result = algebra_parser_fn({
                    "call_type": "check_slope_computation",
                    "student_work": input_text,
                    "correct_slope": _correct_slope,
                    "table_data": _table_data,
                })
            except Exception:
                _sc_result = None
            if _sc_result is not None and _sc_result.get("ok"):
                if _sc_result.get("relationship_correctly_mapped") is not None:
                    evidence["relationship_correctly_mapped"] = _sc_result["relationship_correctly_mapped"]
    if evidence.get("relationship_correctly_mapped") is None and "relationship_correctly_mapped" in evidence:
        del evidence["relationship_correctly_mapped"]

    # ── Law 4: polynomial structure (structure_preserved) ─────
    if algebra_parser_fn is not None and isinstance(current_problem, dict):
        _orig_expr = current_problem.get("original_expression", "")
        if _orig_expr:
            # Extract student expression: prefer first equation-like token in input
            _student_expr_match = re.search(r"([^=\n]+(?:\([^)]*\)[^=\n]*)?)", input_text)
            _student_expr = _student_expr_match.group(1).strip() if _student_expr_match else input_text
            try:
                _ps_result = algebra_parser_fn({
                    "call_type": "check_polynomial_structure",
                    "original_expression": _orig_expr,
                    "student_expression": _student_expr,
                    "target_variable": tvar,
                })
            except Exception:
                _ps_result = None
            if _ps_result is not None and _ps_result.get("ok"):
                if _ps_result.get("structure_preserved") is not None:
                    evidence["structure_preserved"] = _ps_result["structure_preserved"]
    if evidence.get("structure_preserved") is None and "structure_preserved" in evidence:
        del evidence["structure_preserved"]

    # ── Law 6: model transcription (model_accurately_transcribed) ─
    if algebra_parser_fn is not None and isinstance(current_problem, dict):
        _model_params = current_problem.get("model_params")
        if _model_params:
            # Extract the student's equation: first line containing '='
            _eq_line_match = re.search(r"[^\n]*=[^\n]*", input_text)
            _student_eq = _eq_line_match.group(0).strip() if _eq_line_match else input_text
            try:
                _mt_result = algebra_parser_fn({
                    "call_type": "check_model_transcription",
                    "model_params": _model_params,
                    "student_equation": _student_eq,
                    "target_variable": tvar,
                })
            except Exception:
                _mt_result = None
            if _mt_result is not None and _mt_result.get("ok"):
                if _mt_result.get("model_accurately_transcribed") is not None:
                    evidence["model_accurately_transcribed"] = _mt_result["model_accurately_transcribed"]
    if evidence.get("model_accurately_transcribed") is None and "model_accurately_transcribed" in evidence:
        del evidence["model_accurately_transcribed"]

    return evidence
