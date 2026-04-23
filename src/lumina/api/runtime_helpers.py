"""Runtime-driven helpers: contract rendering, turn interpretation, tool invocation.

See also:
    docs/7-concepts/domain-adapter-pattern.md
    docs/7-concepts/slm-compute-distribution.md
"""

from __future__ import annotations

import inspect
from typing import Any

from lumina.api.llm import call_llm
from lumina.api.utils.templates import render_template_value
from lumina.core.slm import TaskWeight, call_slm, classify_task_weight, slm_available


def render_contract_response(
    prompt_contract: dict[str, Any],
    runtime: dict[str, Any],
    mud_world_state: dict[str, Any] | None = None,
    world_sim_theme: dict[str, Any] | None = None,
) -> str:
    """Deterministic fallback driven by domain runtime config templates.

    When MUD world state is present, uses narrative-aware templates from
    ``deterministic_templates_mud`` that inject guide_npc, zone, protagonist,
    and other world-sim narrative constants into the response.
    """
    prompt_type = str(prompt_contract.get("prompt_type", "default"))
    task_id = str(prompt_contract.get("task_id", "task"))

    # Try MUD-aware templates first when world-sim is active
    if mud_world_state and mud_world_state.get("zone"):
        mud_templates = runtime.get("deterministic_templates_mud") or {}
        mud_template = mud_templates.get(prompt_type) or mud_templates.get("default")
        if mud_template:
            fmt_vars = {"task_id": task_id, "prompt_type": prompt_type}
            fmt_vars.update(mud_world_state)
            if world_sim_theme:
                fmt_vars["theme_label"] = world_sim_theme.get("label", "")
            try:
                return mud_template.format(**fmt_vars)
            except KeyError:
                pass  # Fall through to plain templates

    templates = runtime["deterministic_templates"]
    template = templates.get(prompt_type) or templates.get("default") or "Continue with {task_id}."
    try:
        return template.format(task_id=task_id, prompt_type=prompt_type)
    except KeyError:
        return template


def interpret_turn_input(
    input_text: str,
    task_context: dict[str, Any],
    runtime: dict[str, Any],
    world_sim_theme: dict[str, Any] | None = None,
    mud_world_state: dict[str, Any] | None = None,
    slm_weight_overrides: dict[str, str] | None = None,
) -> dict[str, Any]:
    interpreter = runtime["turn_interpreter_fn"]
    _overrides = slm_weight_overrides or {}
    _call_fn = (
        call_slm
        if (
            _overrides
            and slm_available()
            and classify_task_weight("turn_interpretation", _overrides) == TaskWeight.LOW
        )
        else call_llm
    )
    kwargs: dict[str, Any] = {
        "call_llm": _call_fn,
        "input_text": input_text,
        "task_context": task_context,
        "prompt_text": runtime["turn_interpretation_prompt"],
        "default_fields": runtime["turn_input_defaults"],
        "tool_fns": runtime.get("tool_fns"),
    }
    _interp_sig = inspect.signature(interpreter)
    if "call_slm" in _interp_sig.parameters:
        kwargs["call_slm"] = call_slm
    nlp_fn = runtime.get("nlp_pre_interpreter_fn")
    if nlp_fn is not None and "nlp_pre_interpreter_fn" in _interp_sig.parameters:
        kwargs["nlp_pre_interpreter_fn"] = nlp_fn
    if world_sim_theme:
        kwargs["world_sim_theme"] = world_sim_theme
    if mud_world_state and "mud_world_state" in _interp_sig.parameters:
        kwargs["mud_world_state"] = mud_world_state
    return interpreter(**kwargs)


def invoke_runtime_tool(tool_id: str, payload: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    tool_fns: dict[str, Any] = runtime.get("tool_fns") or {}
    tool_fn = tool_fns.get(tool_id)
    if tool_fn is None:
        raise RuntimeError(f"Unknown tool adapter: {tool_id}")
    result = tool_fn(payload)
    if not isinstance(result, dict):
        raise RuntimeError(f"Tool adapter '{tool_id}' must return a dict result")
    return result


def apply_tool_call_policy(
    resolved_action: str,
    prompt_contract: dict[str, Any],
    turn_data: dict[str, Any],
    task_spec: dict[str, Any],
    runtime: dict[str, Any],
) -> list[dict[str, Any]]:
    policies: dict[str, Any] = runtime.get("tool_call_policies") or {}
    entries = policies.get(resolved_action) or []
    if not isinstance(entries, list):
        return []

    context = {
        "action": resolved_action,
        "prompt_contract": prompt_contract,
        "turn_data": turn_data,
        "task_spec": task_spec,
    }

    results: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        tool_id = entry.get("tool_id")
        if not isinstance(tool_id, str) or not tool_id:
            continue
        payload = render_template_value(entry.get("payload") or {}, context)
        if not isinstance(payload, dict):
            payload = {}
        tool_result = invoke_runtime_tool(tool_id, payload, runtime)
        results.append({"tool_id": tool_id, "payload": payload, "result": tool_result})
    return results
