"""LLM payload assembly and invocation.

Assembles the final JSON payload sent to the LLM / SLM and dispatches
the call based on task weight, domain locality, and SLM availability.

See also:
    docs/7-concepts/prompt-packet-assembly.md
    docs/7-concepts/slm-compute-distribution.md
"""

from __future__ import annotations

import json
import logging
from typing import Any

from lumina.api.utils.text import strip_latex_delimiters

log = logging.getLogger("lumina-api")


def assemble_llm_payload(
    prompt_contract: dict[str, Any],
    input_text: str,
    answered_task: dict[str, Any],
    current_task: dict[str, Any],
    new_task_presented: bool,
    turn_data: dict[str, Any],
    tool_results: dict[str, Any] | None,
    session_id: str,
    session_containers: dict,
) -> dict[str, Any]:
    """Build the LLM payload from the prompt contract + enriched context.

    Handles governance vs. learning prompt types, conversation history
    injection, RAG grounding, and internal-key stripping.
    """
    llm_payload = dict(prompt_contract)

    _prompt_type = str(prompt_contract.get("prompt_type", ""))
    _is_governance = _prompt_type.startswith("governance_")

    if not _is_governance:
        llm_payload["current_problem"] = answered_task
        if new_task_presented:
            llm_payload["next_problem"] = current_task

    llm_payload["actor_message"] = input_text

    # ── Conversation history from ring buffer ─────────────────
    container = session_containers.get(session_id)
    if container is not None and hasattr(container, "ring_buffer"):
        recent = container.ring_buffer.snapshot()
        if recent:
            llm_payload["conversation_history"] = [
                {
                    "turn": t.turn_number,
                    "user": t.user_message,
                    "assistant": t.llm_response,
                }
                for t in recent
            ]

    if tool_results:
        llm_payload["tool_results"] = tool_results
    if turn_data.get("_system_telemetry"):
        llm_payload["system_telemetry"] = turn_data["_system_telemetry"]

    # ── RAG grounding ─────────────────────────────────────────
    rag = turn_data.get("_rag_context")
    if rag:
        llm_payload["grounding_context"] = rag

    # ── Strip internal-only metadata ──────────────────────────
    for k in [k for k in llm_payload if k.startswith("_")]:
        del llm_payload[k]

    return llm_payload


def invoke_llm(
    llm_payload: dict[str, Any],
    prompt_contract: dict[str, Any],
    system_prompt: str,
    runtime: dict[str, Any],
    structured_content: dict[str, Any] | None,
    deterministic_response: bool,
    session_id: str,
    slm_weight_overrides: dict[str, Any],
    turn_provenance: dict[str, Any],
    world_sim_theme: dict[str, Any],
    mud_world_state: dict[str, Any],
    *,
    call_llm_fn,
    call_slm_fn,
    slm_available_fn,
    render_contract_response_fn,
    classify_task_weight_fn,
    TaskWeight,
) -> str:
    """Invoke the LLM or SLM and return the plain-text response.

    Skips the LLM call entirely when a ``query_result`` structured
    content card is already present.
    """
    # Skip LLM when a query_result is present — the UI renders it directly
    if (
        structured_content
        and isinstance(structured_content, dict)
        and structured_content.get("type") == "query_result"
    ):
        op = structured_content.get("operation", "command")
        return f"Executed {op} successfully."

    if deterministic_response:
        return render_contract_response_fn(
            prompt_contract,
            runtime,
            mud_world_state=mud_world_state,
            world_sim_theme=world_sim_theme,
        )

    payload_json = json.dumps(llm_payload, indent=2, ensure_ascii=False)
    log.debug(
        "[%s] LLM payload: ~%d tokens (%d chars)",
        session_id,
        len(payload_json) // 4,
        len(payload_json),
    )

    prompt_type = str(prompt_contract.get("prompt_type", "task_presentation"))
    weight = classify_task_weight_fn(prompt_type, overrides=slm_weight_overrides)

    if weight is TaskWeight.LOW and slm_available_fn():
        response = call_slm_fn(system=system_prompt, user=payload_json)
        from lumina.core.slm import SLM_MODEL as _slm_name

        turn_provenance["slm_model_id"] = _slm_name
    elif runtime.get("local_only"):
        if slm_available_fn():
            response = call_slm_fn(system=system_prompt, user=payload_json)
            from lumina.core.slm import SLM_MODEL as _slm_name

            turn_provenance["slm_model_id"] = _slm_name
        else:
            response = render_contract_response_fn(prompt_contract, runtime)
    else:
        response = call_llm_fn(system=system_prompt, user=payload_json)

    return strip_latex_delimiters(response)
