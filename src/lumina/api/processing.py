"""Core D.S.A. → LLM pipeline: process_message()."""

from __future__ import annotations

import inspect
import json
import logging
import time
from typing import Any

from lumina.api import config as _cfg
from lumina.api.config import _canonical_sha256
from lumina.api.llm import call_llm
from lumina.api.runtime_helpers import (
    apply_tool_call_policy,
    interpret_turn_input,
    render_contract_response,
)
from lumina.api.session import (
    _persist_session_container,
    _session_containers,
    get_or_create_session,
)
from lumina.api.utils.coercion import normalize_turn_data
from lumina.api.utils.glossary import detect_glossary_query
from lumina.api.utils.text import strip_latex_delimiters
from lumina.core.slm import (
    TaskWeight,
    call_slm,
    classify_task_weight,
    slm_available,
    slm_interpret_physics_context,
    slm_render_glossary,
)
from lumina.orchestrator.ppa_orchestrator import PPAOrchestrator

log = logging.getLogger("lumina-api")


def process_message(
    session_id: str,
    input_text: str,
    turn_data_override: dict[str, Any] | None = None,
    deterministic_response: bool = False,
    domain_id: str | None = None,
    user: dict[str, Any] | None = None,
    model_id: str | None = None,
    model_version: str | None = None,
) -> dict[str, Any]:
    session = get_or_create_session(session_id, domain_id=domain_id, user=user)

    # ── Capture student solve time at request arrival ─────────
    # Must be read before any LLM/SLM calls so server-side inference
    # latency is not counted against the student's response time.
    _presented_at = session.get("problem_presented_at")
    _student_elapsed: float | None = (
        time.time() - _presented_at if _presented_at is not None else None
    )

    orch: PPAOrchestrator = session["orchestrator"]
    task_spec: dict[str, Any] = session["task_spec"]
    current_problem: dict[str, Any] = session["current_problem"]

    # Resolve per-session runtime context
    resolved_domain_id = session["domain_id"]
    runtime = _cfg.DOMAIN_REGISTRY.get_runtime_context(resolved_domain_id)
    runtime_provenance = dict(runtime.get("runtime_provenance") or {})
    system_prompt = runtime["system_prompt"]

    # ── Glossary interception (neutral turn — no mastery/affect change) ──
    domain_physics = runtime.get("domain") or {}
    glossary = domain_physics.get("glossary") or []
    glossary_match = detect_glossary_query(input_text, glossary, domain_id=resolved_domain_id)
    if glossary_match is not None:
        prompt_contract = {
            "prompt_type": "definition_lookup",
            "domain_pack_id": str(domain_physics.get("id", "")),
            "domain_pack_version": str(domain_physics.get("version", "")),
            "task_id": str(task_spec.get("task_id", "")),
            "glossary_entry": {
                "term": glossary_match.get("term", ""),
                "definition": glossary_match.get("definition", ""),
                "example_in_context": glossary_match.get("example_in_context", ""),
                "related_terms": glossary_match.get("related_terms") or [],
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
        elif slm_available():
            llm_response = slm_render_glossary(prompt_contract["glossary_entry"])
        else:
            entry = prompt_contract["glossary_entry"]
            llm_response = (
                f"{entry['term'].title()}: {entry['definition']} "
                f"Example: {entry['example_in_context']}"
            )

        llm_response = strip_latex_delimiters(llm_response)
        session["turn_count"] += 1
        return {
            "response": llm_response,
            "action": "definition_lookup",
            "prompt_type": "definition_lookup",
            "escalated": False,
            "tool_results": None,
            "domain_id": resolved_domain_id,
        }

    task_context = dict(task_spec)
    task_context["current_problem"] = current_problem
    if turn_data_override is not None:
        turn_data = turn_data_override
    elif deterministic_response:
        turn_data = dict(runtime.get("turn_input_defaults") or {})
    elif runtime.get("local_only"):
        if slm_available():
            _li_interpreter = runtime["turn_interpreter_fn"]
            _li_sig = inspect.signature(_li_interpreter)
            _li_kwargs: dict[str, Any] = {
                "call_llm": call_slm,
                "input_text": input_text,
                "task_context": task_context,
                "prompt_text": runtime["turn_interpretation_prompt"],
                "default_fields": runtime["turn_input_defaults"],
                "tool_fns": runtime.get("tool_fns"),
            }
            if "call_slm" in _li_sig.parameters:
                _li_kwargs["call_slm"] = call_slm
            turn_data = _li_interpreter(**_li_kwargs)
        else:
            turn_data = dict(runtime.get("turn_input_defaults") or {})
    else:
        world_sim_theme = getattr(orch.state, "world_sim_theme", {})
        mud_world_state = getattr(orch.state, "mud_world_state", {})
        turn_data = interpret_turn_input(input_text, task_context, runtime, world_sim_theme=world_sim_theme, mud_world_state=mud_world_state)
    turn_data = normalize_turn_data(turn_data, runtime.get("turn_input_schema") or {})

    # ── SLM physics interpretation (context compression) ─────
    if not runtime.get("local_only") and slm_available():
        slm_context = slm_interpret_physics_context(
            incoming_signals=turn_data,
            domain_physics=domain_physics,
            glossary=glossary,
        )
        turn_data["_slm_context"] = slm_context

    # Inject the universal base field response_latency_sec (sampled at request
    # arrival, before any LLM/SLM calls — excludes server-side inference latency).
    # Domain adapters are responsible for mapping this to any domain-specific
    # timing fields (e.g. solve_elapsed_sec in the education domain).
    if _student_elapsed is not None:
        turn_data["response_latency_sec"] = _student_elapsed

    log.info("[%s] Turn Data: %s", session_id, json.dumps(turn_data, default=str))

    turn_provenance: dict[str, Any] = dict(runtime_provenance)
    turn_provenance["turn_data_hash"] = _canonical_sha256(turn_data)
    if model_id is not None:
        turn_provenance["model_id"] = model_id
    if model_version is not None:
        turn_provenance["model_version"] = model_version

    slm_weight_overrides = runtime.get("slm_weight_overrides") or {}

    prompt_contract, resolved_action = orch.process_turn(
        task_spec,
        turn_data,
        provenance_metadata=turn_provenance,
    )

    if turn_data.get("problem_solved") is True:
        resolved_action = "task_complete"
        prompt_contract["prompt_type"] = "task_complete"

    reported_status = turn_data.get("problem_status")
    if isinstance(reported_status, str) and reported_status.strip():
        current_problem["status"] = reported_status.strip()

    # ── Fluency-gated problem advancement ─────────────────────
    _new_problem_presented = False
    fluency_decision = {}
    domain_lib_decision = getattr(orch, "last_domain_lib_decision", None) or {}
    if isinstance(domain_lib_decision.get("fluency"), dict):
        fluency_decision = domain_lib_decision["fluency"]

    should_advance = fluency_decision.get("advanced", False)

    if should_advance or turn_data.get("problem_solved") is True:
        domain = (runtime.get("domain") or {}).get("subsystem_configs") or {}
        tiers = domain.get("equation_difficulty_tiers")
        if isinstance(tiers, list) and tiers:
            try:
                gen_fn = (runtime.get("tool_fns") or {}).get("generate_problem")
                if gen_fn is not None:
                    if should_advance:
                        next_tier = fluency_decision.get("next_tier", "")
                        tier_objs = {str(t.get("tier_id")): t for t in tiers}
                        target_tier = tier_objs.get(next_tier, tiers[-1])
                        diff = (float(target_tier.get("min_difficulty", 0)) +
                                float(target_tier.get("max_difficulty", 1))) / 2
                        task_spec["nominal_difficulty"] = diff
                    else:
                        diff = float(task_spec.get("nominal_difficulty", 0.5))
                    current_problem = gen_fn(diff, domain)
            except Exception:
                log.warning("Problem generation on advance failed", exc_info=True)
        _new_problem_presented = True

    session["current_problem"] = current_problem
    session["turn_count"] += 1

    # Sync mutations back to the DomainContext in the session container
    container = _session_containers.get(session_id)
    if container is not None:
        container.active_context.sync_from_dict(session)
        container.last_activity = time.time()
        _persist_session_container(session_id, container)

        # ── Auto-save per-user profile after each turn ────────
        if container.user is not None and orch.state is not None:
            profile_path = container.active_context.subject_profile_path
            if profile_path:
                try:
                    import dataclasses
                    profile_data = _cfg.PERSISTENCE.load_subject_profile(profile_path)
                    if dataclasses.is_dataclass(orch.state):
                        _ls_dict = dataclasses.asdict(orch.state)
                        if hasattr(orch.state, "fluency"):
                            _ls_dict["fluency"] = {
                                "current_tier": orch.state.fluency.current_tier,
                                "consecutive_correct": orch.state.fluency.consecutive_correct,
                            }
                        profile_data["learning_state"] = _ls_dict
                    else:
                        _sd = orch.state if isinstance(orch.state, dict) else {}
                        profile_data["session_state"] = {
                            "turn_count": int(_sd.get("turn_count", 0)),
                            "operator_id": str(_sd.get("operator_id", "")),
                        }
                    _cfg.PERSISTENCE.save_subject_profile(profile_path, profile_data)
                except Exception:
                    log.warning("Profile auto-save failed for session %s", session_id)
    else:
        _cfg.PERSISTENCE.save_session_state(
            session_id,
            {
                "task_spec": task_spec,
                "current_problem": current_problem,
                "turn_count": session["turn_count"],
                "last_action": resolved_action,
                "standing_order_attempts": orch.get_standing_order_attempts(),
                "domain_id": resolved_domain_id,
            },
        )

    log.info(
        "[%s] Turn %s: action=%s, prompt_type=%s",
        session_id,
        session["turn_count"],
        resolved_action,
        prompt_contract.get("prompt_type"),
    )

    escalated = any(
        r.get("record_type") == "EscalationRecord" and r.get("session_id") == session_id
        for r in orch.ctl_records[-2:]
    )

    tool_results = apply_tool_call_policy(
        resolved_action=resolved_action,
        prompt_contract=prompt_contract,
        turn_data=turn_data,
        task_spec=task_spec,
        runtime=runtime,
    )

    llm_payload = dict(prompt_contract)
    llm_payload["current_problem"] = current_problem
    llm_payload["student_message"] = input_text
    if tool_results:
        llm_payload["tool_results"] = tool_results

    if deterministic_response:
        llm_response = render_contract_response(prompt_contract, runtime)
    else:
        prompt_type = str(prompt_contract.get("prompt_type", "task_presentation"))
        weight = classify_task_weight(prompt_type, overrides=slm_weight_overrides)
        if weight is TaskWeight.LOW and slm_available():
            llm_response = call_slm(
                system=system_prompt,
                user=json.dumps(llm_payload, indent=2, ensure_ascii=False),
            )
            from lumina.core.slm import SLM_MODEL as _slm_model_name
            turn_provenance["slm_model_id"] = _slm_model_name
        elif runtime.get("local_only"):
            if slm_available():
                llm_response = call_slm(
                    system=system_prompt,
                    user=json.dumps(llm_payload, indent=2, ensure_ascii=False),
                )
                from lumina.core.slm import SLM_MODEL as _slm_model_name
                turn_provenance["slm_model_id"] = _slm_model_name
            else:
                llm_response = render_contract_response(prompt_contract, runtime)
        else:
            llm_response = call_llm(
                system=system_prompt,
                user=json.dumps(llm_payload, indent=2, ensure_ascii=False),
            )

    llm_response = strip_latex_delimiters(llm_response)

    # ── Reset problem_presented_at after response is ready ───
    # Timestamp is anchored to when the outgoing response is fully built so
    # the next turn's solve_elapsed_sec excludes this turn's LLM latency.
    # Also reset on task_presentation turns (new problem being introduced).
    if _new_problem_presented or resolved_action == "task_presentation":
        _response_sent_at = time.time()
        session["problem_presented_at"] = _response_sent_at
        _c = _session_containers.get(session_id)
        if _c is not None:
            _c.active_context.problem_presented_at = _response_sent_at

    log.info("[%s] Response length: %s chars", session_id, len(llm_response))

    post_payload_provenance = dict(turn_provenance)
    post_payload_provenance["prompt_contract_hash"] = _canonical_sha256(prompt_contract)
    post_payload_provenance["tool_results_hash"] = _canonical_sha256(tool_results)
    post_payload_provenance["llm_payload_hash"] = _canonical_sha256(llm_payload)
    post_payload_provenance["response_hash"] = _canonical_sha256(llm_response)
    orch.append_provenance_trace(
        task_id=str(task_spec.get("task_id", "")),
        action=resolved_action,
        prompt_type=str(prompt_contract.get("prompt_type", "task_presentation")),
        metadata=post_payload_provenance,
    )

    return {
        "response": llm_response,
        "action": resolved_action,
        "prompt_type": prompt_contract.get("prompt_type", "task_presentation"),
        "escalated": escalated,
        "tool_results": tool_results,
        "domain_id": resolved_domain_id,
    }
