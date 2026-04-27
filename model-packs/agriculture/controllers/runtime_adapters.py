from __future__ import annotations

import json
from typing import Any, Callable


def build_initial_learning_state(profile: dict[str, Any]) -> dict[str, Any]:
    state = profile.get("state") or {}
    return {
        "signal_index": float(state.get("signal_index", 0.5)),
        "uncertainty": float(state.get("uncertainty", 0.3)),
    }


def domain_step(
    state: dict[str, Any],
    task_spec: dict[str, Any],
    evidence: dict[str, Any],
    params: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    new_state = dict(state)
    drift = 0.0 if bool(evidence.get("within_tolerance", True)) else 0.5
    new_state["signal_index"] = max(0.0, min(1.0, float(new_state.get("signal_index", 0.5)) - drift * 0.05))
    return new_state, {
        "tier": "ok" if drift == 0.0 else "minor",
        "action": None,
        "frustration": False,
        "drift_pct": drift,
    }


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
) -> dict[str, Any]:
    raw_response = call_llm(
        system=prompt_text,
        user=f"Operator message: {input_text}",
        model=None,
    )

    try:
        evidence = json.loads(_strip_markdown_fences(raw_response))
    except (json.JSONDecodeError, IndexError):
        evidence = {}

    defaults = dict(default_fields or {})
    if not defaults:
        defaults = {
            "within_tolerance": True,
            "response_latency_sec": 10.0,
            "off_task_ratio": 0.0,
            "step_count": 0,
        }

    for key, default_val in defaults.items():
        if key not in evidence or evidence[key] is None:
            evidence[key] = default_val

    # ── Override SLM fields with deterministic sensor output ───────
    # Same pattern as education domain's algebra parser override: call the
    # collar sensor tool to verify within_tolerance with ground truth,
    # overriding the SLM's estimate.
    _tool_fns = tool_fns or {}
    _sensor_fn = _tool_fns.get("collar_sensor") or _tool_fns.get("check_tolerance")
    if _sensor_fn is not None:
        try:
            _sensor_result = _sensor_fn({"input_text": input_text, "evidence": evidence})
            if isinstance(_sensor_result, dict):
                if "within_tolerance" in _sensor_result:
                    evidence["within_tolerance"] = _sensor_result["within_tolerance"]
                if "sensor_reading_valid" in _sensor_result:
                    evidence["sensor_reading_valid"] = _sensor_result["sensor_reading_valid"]
                if "normalized_value" in _sensor_result:
                    evidence["normalized_value"] = _sensor_result["normalized_value"]
                if "deviation" in _sensor_result:
                    evidence["deviation"] = _sensor_result["deviation"]
        except Exception:
            # Sensor unavailable — keep SLM defaults, flag reading as invalid
            evidence["sensor_reading_valid"] = False
    else:
        # No sensor tool wired — flag for invariant checker
        evidence.setdefault("sensor_reading_valid", True)

    # Populate signal_index for invariant check if domain_step hasn't run yet
    evidence.setdefault("signal_index", 0.5)

    return evidence
