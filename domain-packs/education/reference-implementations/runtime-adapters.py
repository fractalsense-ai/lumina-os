from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable

_THIS_DIR = Path(__file__).resolve().parent

_zpd_spec = importlib.util.spec_from_file_location(
    "zpd_monitor_runtime",
    str(_THIS_DIR / "zpd-monitor-v0.2.py"),
)
_zpd_mod = importlib.util.module_from_spec(_zpd_spec)  # type: ignore[arg-type]
sys.modules["zpd_monitor_runtime"] = _zpd_mod
_zpd_spec.loader.exec_module(_zpd_mod)  # type: ignore[union-attr]

AffectState = _zpd_mod.AffectState
RecentWindow = _zpd_mod.RecentWindow
LearningState = _zpd_mod.LearningState
zpd_monitor_step = _zpd_mod.zpd_monitor_step


def build_initial_learning_state(profile: dict[str, Any]) -> Any:
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

    return LearningState(
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


def domain_step(
    state: Any,
    task_spec: dict[str, Any],
    evidence: dict[str, Any],
    params: dict[str, Any],
) -> tuple[Any, dict[str, Any]]:
    return zpd_monitor_step(state, task_spec, evidence, params=params)


def _strip_markdown_fences(raw: str) -> str:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[: cleaned.rfind("```")]
    return cleaned.strip()


def extract_evidence(
    call_llm: Callable[[str, str, str | None], str],
    input_text: str,
    task_context: dict[str, Any],
    prompt_text: str,
    default_fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context_hint = ""
    if task_context.get("task_id"):
        context_hint = f"\nCurrent task: {task_context.get('task_id', 'unknown')}"
        if task_context.get("skills_required"):
            context_hint += f"\nSkills: {', '.join(task_context['skills_required'])}"

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
        defaults = {
            "correctness": "partial",
            "hint_used": False,
            "response_latency_sec": 10.0,
            "frustration_marker_count": 0,
            "repeated_error": False,
            "off_task_ratio": 0.0,
            "step_count": 0,
        }

    for key, default_val in defaults.items():
        if key not in evidence or evidence[key] is None:
            evidence[key] = default_val

    return evidence
