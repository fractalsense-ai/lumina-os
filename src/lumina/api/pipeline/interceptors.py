"""Early-return interceptors: glossary, turn-0 presentation, greeting.

Each function returns an early response dict when interception applies,
or *None* to let the pipeline continue.

See also:
    docs/7-concepts/dsa-framework.md
    docs/7-concepts/prompt-packet-assembly.md
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from lumina.api.utils.text import strip_latex_delimiters

log = logging.getLogger("lumina-api")


# ---------------------------------------------------------------------------
# Glossary interception
# ---------------------------------------------------------------------------

def check_glossary(
    session_id: str,
    session: dict[str, Any],
    input_text: str,
    current_problem: dict[str, Any],
    task_spec: dict[str, Any],
    domain_physics: dict[str, Any],
    runtime: dict[str, Any],
    resolved_domain_id: str,
    deterministic_response: bool,
    system_prompt: str,
    *,
    detect_glossary_query_fn,
    slm_available_fn,
    slm_render_glossary_fn,
    call_llm_fn,
    sync_session_fn,
) -> dict[str, Any] | None:
    """Intercept glossary lookup requests as neutral turns.

    Returns the glossary definition response or *None* to continue.
    """
    glossary = (
        domain_physics.get("glossary")
        or (runtime.get("domain") or {}).get("glossary")
        or []
    )
    match = detect_glossary_query_fn(
        input_text, glossary, domain_id=resolved_domain_id,
    )
    if match is None:
        return None

    prompt_contract = {
        "prompt_type": "definition_lookup",
        "domain_pack_id": str(domain_physics.get("id", "")),
        "domain_pack_version": str(domain_physics.get("version", "")),
        "task_id": str(task_spec.get("task_id", "")),
        "glossary_entry": {
            "term": match.get("term", ""),
            "definition": match.get("definition", ""),
            "example_in_context": match.get("example_in_context", ""),
            "related_terms": match.get("related_terms") or [],
        },
    }
    llm_payload = dict(prompt_contract)
    llm_payload["current_problem"] = current_problem

    if deterministic_response:
        template = runtime.get("deterministic_templates", {}).get("definition_lookup")
        if template:
            llm_response = template.format(**prompt_contract.get("glossary_entry", {}))
        else:
            entry = prompt_contract["glossary_entry"]
            llm_response = (
                f"{entry['term'].title()}: {entry['definition']} "
                f"Example: {entry['example_in_context']}"
            )
    elif slm_available_fn():
        llm_response = slm_render_glossary_fn(prompt_contract["glossary_entry"])
    else:
        entry = prompt_contract["glossary_entry"]
        llm_response = (
            f"{entry['term'].title()}: {entry['definition']} "
            f"Example: {entry['example_in_context']}"
        )

    llm_response = strip_latex_delimiters(llm_response)
    session["turn_count"] += 1
    sync_session_fn(session_id, session)
    return {
        "response": llm_response,
        "action": "definition_lookup",
        "prompt_type": "definition_lookup",
        "escalated": False,
        "tool_results": None,
        "domain_id": resolved_domain_id,
    }


# ---------------------------------------------------------------------------
# Turn-0 presentation gate (domain-hook driven)
# ---------------------------------------------------------------------------

def check_turn_0(
    session_id: str,
    session: dict[str, Any],
    input_text: str,
    current_problem: dict[str, Any],
    task_spec: dict[str, Any],
    domain_physics: dict[str, Any],
    runtime: dict[str, Any],
    resolved_domain_id: str,
    system_prompt: str,
    holodeck: bool,
    deterministic_response: bool,
    active_mod: dict[str, Any],
    session_containers: dict,
    user: dict[str, Any] | None,
    *,
    slm_available_fn,
    call_llm_fn,
    compute_seal_fn,
    sync_session_fn,
) -> dict[str, Any] | None:
    """Intercept turn 0 for task presentation when a domain hook fires.

    Returns the task presentation response or *None* to continue.
    """
    t0_fn = active_mod.get("turn_0_presenter_fn") or runtime.get("turn_0_presenter_fn")
    if t0_fn is None:
        return None

    has_equation = t0_fn(
        session=session,
        current_problem=current_problem,
        holodeck=holodeck,
        deterministic_response=deterministic_response,
    )
    if not has_equation:
        return None

    contract = {
        "prompt_type": "task_presentation",
        "domain_pack_id": str(domain_physics.get("id", "")),
        "domain_pack_version": str(domain_physics.get("version", "")),
        "task_id": str(task_spec.get("task_id", "")),
        "current_problem": current_problem,
        "actor_message": input_text,
    }
    payload_json = json.dumps(contract, indent=2, ensure_ascii=False)

    if slm_available_fn():
        from lumina.core.slm import call_slm as _t0_call_slm

        response = _t0_call_slm(system=system_prompt, user=payload_json)
    else:
        response = call_llm_fn(system=system_prompt, user=payload_json)

    response = strip_latex_delimiters(response)
    session["turn_count"] += 1
    session["problem_presented_at"] = time.time()

    container = session_containers.get(session_id)
    if container is not None and hasattr(container, "ring_buffer"):
        container.ring_buffer.push(
            user_message=input_text,
            llm_response=response,
            turn_number=0,
            domain_id=resolved_domain_id,
        )

    seal, seal_meta, transcript = compute_seal_fn(
        session_id, session, resolved_domain_id, user, holodeck,
    )

    result: dict[str, Any] = {
        "response": response,
        "action": "task_presentation",
        "prompt_type": "task_presentation",
        "escalated": False,
        "tool_results": {},
        "domain_id": resolved_domain_id,
    }
    if seal is not None:
        result["transcript_seal"] = seal
        result["transcript_seal_metadata"] = seal_meta
        result["transcript_snapshot"] = transcript

    sync_session_fn(session_id, session)
    return result


# ---------------------------------------------------------------------------
# Greeting (deferred — runs AFTER turn interpretation)
# ---------------------------------------------------------------------------

def resolve_greeting_eligible(
    session: dict[str, Any],
    domain_physics: dict[str, Any],
    holodeck: bool,
    deterministic_response: bool,
    has_equation: bool,
) -> bool:
    """Return True when the current turn qualifies for a warm greeting."""
    greeting_cfg = domain_physics.get("greeting") or {}
    return (
        session.get("turn_count", 0) == 0
        and not has_equation
        and not holodeck
        and not deterministic_response
        and isinstance(greeting_cfg, dict)
        and greeting_cfg.get("enabled") is True
    )


def check_greeting(
    session_id: str,
    session: dict[str, Any],
    input_text: str,
    turn_data: dict[str, Any],
    domain_physics: dict[str, Any],
    runtime: dict[str, Any],
    resolved_domain_id: str,
    system_prompt: str,
    session_containers: dict,
    user: dict[str, Any] | None,
    holodeck: bool,
    *,
    slm_available_fn,
    compute_seal_fn,
    sync_session_fn,
) -> dict[str, Any] | None:
    """Produce a warm greeting on turn 0 for eligible modules.

    Only called when :func:`resolve_greeting_eligible` returned True.
    Returns the greeting response or *None* if a command was dispatched
    (commands take priority even on turn 0).
    """
    if isinstance(turn_data.get("command_dispatch"), dict):
        return None  # command takes priority

    greeting_cfg = domain_physics.get("greeting") or {}
    greeting = greeting_cfg.get(
        "fallback_message",
        "Welcome! What's on your mind today?",
    )

    if slm_available_fn():
        from lumina.core.slm import call_slm as _g_call_slm

        contract = {
            "prompt_type": "greeting",
            "actor_message": input_text,
            "instructions": (
                "Warmly greet the user and invite them to share what is "
                "on their mind. Keep it brief and encouraging."
            ),
        }
        try:
            greeting = _g_call_slm(
                system=system_prompt,
                user=json.dumps(contract, ensure_ascii=False),
            )
            greeting = strip_latex_delimiters(greeting)
        except Exception:
            pass  # fall back to static greeting from physics

    session["turn_count"] += 1
    container = session_containers.get(session_id)
    if container is not None and hasattr(container, "ring_buffer"):
        container.ring_buffer.push(
            user_message=input_text,
            llm_response=greeting,
            turn_number=0,
            domain_id=resolved_domain_id,
        )

    seal, seal_meta, transcript = compute_seal_fn(
        session_id, session, resolved_domain_id, user, holodeck,
    )

    result: dict[str, Any] = {
        "response": greeting,
        "action": "greeting",
        "prompt_type": "greeting",
        "escalated": False,
        "tool_results": {},
        "domain_id": resolved_domain_id,
    }
    if seal is not None:
        result["transcript_seal"] = seal
        result["transcript_seal_metadata"] = seal_meta
        result["transcript_snapshot"] = transcript

    sync_session_fn(session_id, session)
    return result
