"""Template domain — Runtime adapters.

This module provides the three REQUIRED callables that the runtime loader
expects every domain pack to export:

    build_initial_state(profile) → state dict
    domain_step(state, task_spec, evidence, params) → (new_state, decision)
    interpret_turn_input(call_llm, input_text, task_context, prompt_text,
                         default_fields, tool_fns) → evidence dict

All three are referenced in cfg/runtime-config.yaml under the `adapters:`
block.  Module-level overrides in `module_map.*.adapters` can replace any
of them per module.

HOW TO CUSTOMISE:
  1. build_initial_state — seed the session state from the entity profile.
     Return whatever keys your domain_step reads.
  2. domain_step — run one domain tick: read evidence, update state,
     return a decision dict the orchestrator uses for action selection.
  3. interpret_turn_input — call the LLM with your turn interpretation
     prompt, parse the JSON response, merge defaults, and optionally
     call deterministic tool functions to override SLM estimates.
"""

from __future__ import annotations

import json
from typing import Any, Callable


# ── 1. State Builder ─────────────────────────────────────────────────

def build_initial_state(profile: dict[str, Any]) -> dict[str, Any]:
    """Build the initial session state from an entity profile.

    Called once at session start.  The returned dict becomes the `state`
    argument to every subsequent `domain_step` call.

    TODO: Read fields from *profile* that your domain_step needs and
          return them with sensible defaults.
    """
    entity_state = profile.get("entity_state") or {}
    return {
        "score": float(entity_state.get("score", 0.0)),
        "uncertainty": 0.5,
        "turn_count": 0,
    }


# ── 2. Domain Step ───────────────────────────────────────────────────

def domain_step(
    state: dict[str, Any],
    task_spec: dict[str, Any],
    evidence: dict[str, Any],
    params: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run one domain tick: state × evidence → (new_state, decision).

    Called every turn after the turn interpreter produces evidence.

    Args:
        state:     Current session state (mutable copy is fine).
        task_spec: The active task specification from runtime-config.
        evidence:  Structured evidence dict from interpret_turn_input.
        params:    domain_step_params from runtime-config.

    Returns:
        new_state: Updated session state dict.
        decision:  Dict consumed by the orchestrator's actor_resolver.
                   Standard keys the framework reads:
                     - tier: str    — "ok" | "minor" | "major" | "critical"
                     - action: str | None  — standing-order action to invoke
                     - frustration: bool   — entity frustration signal
                     - escalation_eligible: bool — False suppresses metric
                       escalation while baselines are priming (see
                       docs/7-concepts/baseline-before-escalation.md)

    TODO: Replace this stub with your domain's actual state transition logic.
    """
    new_state = dict(state)
    new_state["turn_count"] = new_state.get("turn_count", 0) + 1

    # Example: simple drift detection
    on_track = bool(evidence.get("on_track", True))
    if not on_track:
        new_state["uncertainty"] = min(1.0, new_state["uncertainty"] + 0.1)
    else:
        new_state["uncertainty"] = max(0.0, new_state["uncertainty"] - 0.05)

    # Determine tier based on uncertainty
    uncertainty = new_state["uncertainty"]
    if uncertainty > 0.8:
        tier = "major"
    elif uncertainty > 0.5:
        tier = "minor"
    else:
        tier = "ok"

    return new_state, {
        "tier": tier,
        "action": None if tier == "ok" else "request_more_detail",
        "frustration": False,
    }


# ── 3. Turn Interpreter ─────────────────────────────────────────────

def _strip_markdown_fences(raw: str) -> str:
    """Remove ```json fences the SLM sometimes wraps around output."""
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
    """Call the LLM to parse raw entity text into structured evidence.

    Args:
        call_llm:       Framework-provided callable: (system, user, model) → str
        input_text:     Raw message from the entity.
        task_context:   Current task context dict.
        prompt_text:    The turn interpretation prompt (from runtime-config path).
        default_fields: Fallback values when the SLM omits a field.
        tool_fns:       Dict of deterministic tool callables, keyed by tool name.
                        Use these to override SLM estimates with ground truth.

    Returns:
        Evidence dict matching your turn_input_schema.

    TODO: Customise the user prompt, default fields, and any deterministic
          tool overrides for your domain.
    """
    raw_response = call_llm(
        system=prompt_text,
        user=f"Entity message: {input_text}",
        model=None,
    )

    try:
        evidence = json.loads(_strip_markdown_fences(raw_response))
    except (json.JSONDecodeError, IndexError):
        evidence = {}

    # Merge defaults for any missing fields
    defaults = dict(default_fields or {})
    if not defaults:
        defaults = {
            "on_track": True,
            "response_latency_sec": 5.0,
            "off_task_ratio": 0.0,
        }

    for key, default_val in defaults.items():
        if key not in evidence or evidence[key] is None:
            evidence[key] = default_val

    # ── Deterministic tool overrides ──────────────────────────────
    # Pattern: call a domain-specific tool to replace the SLM's estimate
    # with a deterministic ground-truth value.
    #
    # Example (uncomment and adapt):
    #
    #   _tool_fns = tool_fns or {}
    #   _checker = _tool_fns.get("my_domain_checker")
    #   if _checker is not None:
    #       try:
    #           result = _checker({"input_text": input_text, "evidence": evidence})
    #           if isinstance(result, dict) and "on_track" in result:
    #               evidence["on_track"] = result["on_track"]
    #       except Exception:
    #           pass  # Tool unavailable — keep SLM estimate

    return evidence
