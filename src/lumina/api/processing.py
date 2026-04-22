"""Core D.S.A. → LLM pipeline: process_message().

Thin pipeline router that sequences stage calls.  Heavy logic lives in
the ``lumina.api.pipeline`` sub-package — each module handles one layer
of the processing pipeline.

See also:
    docs/7-concepts/dsa-framework.md
    docs/7-concepts/prompt-packet-assembly.md
    docs/7-concepts/slm-compute-distribution.md
    docs/7-concepts/zero-trust-architecture.md
"""

from __future__ import annotations

import inspect
import json
import logging
import time
from typing import Any

from lumina.api import config as _cfg
from lumina.api.config import _canonical_sha256
from lumina.api.llm import call_llm
from lumina.api.pipeline.commands import (
    build_clarification_response,
    build_command_content,
)
from lumina.api.pipeline.enrichment import enrich_turn_data, pre_enrich_rag
from lumina.api.pipeline.gates import (
    check_consent_gate,
    check_session_freeze,
    check_user_freeze,
)
from lumina.api.pipeline.interceptors import (
    check_glossary,
    check_greeting,
    check_turn_0,
    resolve_greeting_eligible,
)
from lumina.api.pipeline.payload import assemble_llm_payload
from lumina.api.pipeline.payload import invoke_llm as _invoke_llm
from lumina.api.pipeline.response import (
    attach_holodeck_data,
    build_escalation_content,
    build_result,
)
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
vlog = logging.getLogger("lumina.verbose")

# Backward-compatible alias — tests import this from processing.
_build_clarification_response = build_clarification_response


def _compute_transcript_seal(
    session_id: str,
    session: dict[str, Any],
    resolved_domain_id: str,
    user: dict[str, Any] | None,
    holodeck: bool,
) -> tuple[str | None, dict[str, Any] | None, list[dict[str, Any]] | None]:
    """Compute the rolling transcript seal for client-side persistence.

    Returns ``(seal, seal_metadata, transcript_snapshot)`` or
    ``(None, None, None)`` when sealing is not applicable.
    """
    if holodeck or user is None:
        return None, None, None
    container = _session_containers.get(session_id)
    if container is None or not hasattr(container, "ring_buffer"):
        return None, None, None
    try:
        from lumina.auth.auth import sign_transcript

        _user_id = user.get("sub", "")
        if not _user_id:
            return None, None, None
        _turns = container.ring_buffer.snapshot()
        _transcript = [
            {
                "turn": t.turn_number,
                "user": t.user_message,
                "assistant": t.llm_response,
                "ts": t.timestamp,
                "domain_id": t.domain_id,
            }
            for t in _turns
        ]
        _seal_meta: dict[str, Any] = {
            "domain_id": resolved_domain_id,
            "turn_count": session.get("turn_count", 0),
            "last_activity_utc": time.time(),
        }
        _seal = sign_transcript(
            _user_id, {"transcript": _transcript, "metadata": _seal_meta}
        )
        return _seal, _seal_meta, _transcript
    except Exception:
        log.warning("Could not compute transcript seal for %s", session_id, exc_info=True)
        return None, None, None


def _sync_session_back(session_id: str, session: dict[str, Any]) -> None:
    """Sync mutations from the local session dict back to the DomainContext.

    Early-return paths (greeting, turn-0 presentation, glossary) skip the
    main end-of-pipeline sync.  Call this before returning so that
    turn_count and other fields are persisted.
    """
    container = _session_containers.get(session_id)
    if container is not None:
        container.active_context.sync_from_dict(session)
        container.last_activity = time.time()
        _persist_session_container(session_id, container)


def process_message(
    session_id: str,
    input_text: str,
    turn_data_override: dict[str, Any] | None = None,
    deterministic_response: bool = False,
    domain_id: str | None = None,
    user: dict[str, Any] | None = None,
    model_id: str | None = None,
    model_version: str | None = None,
    holodeck: bool = False,
    physics_sandbox: dict[str, Any] | None = None,
) -> dict[str, Any]:
    # physics_sandbox implies holodeck
    if physics_sandbox is not None:
        holodeck = True

    session = get_or_create_session(session_id, domain_id=domain_id, user=user)

    vlog.debug("[GATE] session=%s domain=%s user=%s", session_id, domain_id, user.get("username") if user else None)

    # ── Layer 1: Pre-turn gates ───────────────────────────────
    _gate = check_user_freeze(
        session_id, input_text, user, domain_id, session, _session_containers,
    )
    if _gate is not None:
        return _gate

    _gate = check_session_freeze(
        session_id, input_text, user, domain_id, session, _session_containers,
    )
    if _gate is not None:
        return _gate

    # ── Capture actor response latency at request arrival ─────
    _presented_at = session.get("task_presented_at")
    _actor_elapsed: float | None = (
        time.time() - _presented_at if _presented_at is not None else None
    )

    # ── Resolve domain + runtime context ──────────────────────
    orch: PPAOrchestrator = session["orchestrator"]
    task_spec: dict[str, Any] = session["task_spec"]
    current_task: dict[str, Any] = session["current_task"]
    # Snapshot the task the actor is currently working on so LLM
    # feedback references the correct task even after advancement.
    _answered_task: dict[str, Any] = dict(current_task)

    resolved_domain_id = session["domain_id"]
    runtime = _cfg.DOMAIN_REGISTRY.get_runtime_context(resolved_domain_id)

    # ── Sandbox physics override ──────────────────────────────
    if physics_sandbox is not None:
        import copy as _copy
        runtime = _copy.deepcopy(runtime)
        runtime["domain"] = physics_sandbox
        orch.domain = physics_sandbox

    runtime_provenance = dict(runtime.get("runtime_provenance") or {})
    system_prompt = runtime["system_prompt"]

    # ── Per-module prompt overrides (governance persona) ──────
    _module_map = runtime.get("module_map") or {}
    _module_key = session.get("module_key") or resolved_domain_id
    _active_mod = _module_map.get(_module_key) or {}
    if _active_mod.get("system_prompt"):
        system_prompt = _active_mod["system_prompt"]
    if _active_mod.get("turn_interpretation_prompt") or _active_mod.get("turn_interpreter_fn"):
        runtime = dict(runtime)
        if _active_mod.get("turn_interpretation_prompt"):
            runtime["turn_interpretation_prompt"] = _active_mod["turn_interpretation_prompt"]
        if _active_mod.get("turn_interpreter_fn"):
            runtime["turn_interpreter_fn"] = _active_mod["turn_interpreter_fn"]
    if _active_mod.get("turn_input_defaults"):
        runtime = dict(runtime)
        runtime["turn_input_defaults"] = _active_mod["turn_input_defaults"]
    if _active_mod.get("turn_input_schema"):
        runtime = dict(runtime)
        runtime["turn_input_schema"] = _active_mod["turn_input_schema"]
    if _active_mod.get("tool_fns"):
        runtime = dict(runtime)
        _merged_tools = dict(runtime.get("tool_fns") or {})
        _merged_tools.update(_active_mod["tool_fns"])
        runtime["tool_fns"] = _merged_tools
    if _active_mod.get("nlp_pre_interpreter_fn"):
        runtime = dict(runtime)
        runtime["nlp_pre_interpreter_fn"] = _active_mod["nlp_pre_interpreter_fn"]

    # ── Pre-turn resume hook (domain-driven) ────────────────────
    # When a domain marks current_task as completed and the user returns,
    # the domain's pre_turn_resume_fn decides whether/how to replace it.
    _new_task_on_resume = False
    _ptr_fn = _active_mod.get("pre_turn_resume_fn") or runtime.get("pre_turn_resume_fn")
    if current_task.get("completed") is True:
        if _ptr_fn is not None:
            _ptr_result = _ptr_fn(
                session=session,
                task_spec=task_spec,
                current_task=current_task,
                runtime=runtime,
                orchestrator=orch,
            )
            if _ptr_result.get("replaced"):
                current_task = _ptr_result["current_task"]
                session["current_task"] = current_task
                _new_task_on_resume = True
                vlog.debug("[RESUME] Domain hook replaced completed task")
        else:
            log.warning(
                "Task marked completed but no pre_turn_resume_fn registered for domain %s",
                resolved_domain_id,
            )

    # ── Consent gate ──────────────────────────────────────────
    _gate = check_consent_gate(
        session_id, user, domain_id, session, runtime,
        _session_containers, _cfg.PERSISTENCE,
    )
    if _gate is not None:
        return _gate

    # ── Layer 2: Interceptors (early-return paths) ────────────
    domain_physics = getattr(orch, "domain", None) or runtime.get("domain") or {}

    _glossary_result = check_glossary(
        session_id, session, input_text, current_task, task_spec,
        domain_physics, runtime, resolved_domain_id,
        deterministic_response, system_prompt,
        detect_glossary_query_fn=detect_glossary_query,
        slm_available_fn=slm_available,
        slm_render_glossary_fn=slm_render_glossary,
        call_llm_fn=call_llm,
        sync_session_fn=_sync_session_back,
    )
    if _glossary_result is not None:
        return _glossary_result

    task_context = dict(task_spec)
    task_context["current_task"] = current_task

    _t0_result = check_turn_0(
        session_id, session, input_text, current_task, task_spec,
        domain_physics, runtime, resolved_domain_id, system_prompt,
        holodeck, deterministic_response, _active_mod,
        _session_containers, user,
        slm_available_fn=slm_available,
        call_llm_fn=call_llm,
        compute_seal_fn=_compute_transcript_seal,
        sync_session_fn=_sync_session_back,
    )
    if _t0_result is not None:
        return _t0_result

    # If check_turn_0 did not intercept, _has_equation is False.
    _greeting_eligible = resolve_greeting_eligible(
        session, domain_physics, holodeck, deterministic_response,
        has_equation=False,
    )

    # ── World-sim state ───────────────────────────────────────
    world_sim_theme = getattr(orch.state, "world_sim_theme", {}) or {}
    mud_world_state = getattr(orch.state, "mud_world_state", {}) or {}

    # ── Layer 2½a: Pre-enrichment RAG retrieval ───────────────
    # RAG only needs input_text + domain_id — no turn_data dependency.
    # Runs before turn interpretation so the interpreter (and downstream
    # SLM context compression) have domain context available.
    _pre_rag_context = pre_enrich_rag(
        input_text, resolved_domain_id,
        module_key=session.get("module_key"),
    )

    # ── NLP pre-scan for multi-intent detection ───────────────
    # Run the domain's NLP pre-interpreter deterministically before any
    # LLM call. If multiple intent signals are detected AND the domain has
    # registered a multi_task_turn_interpreter_fn, the multi-task path fires.
    _nlp_pre_result: dict[str, Any] = {}
    _multi_intent_detected = False
    if not deterministic_response and turn_data_override is None:
        _nlp_fn_pre = runtime.get("nlp_pre_interpreter_fn")
        if _nlp_fn_pre is not None:
            try:
                _nlp_pre_result = _nlp_fn_pre(input_text, task_context) or {}
                _nlp_intent_scores = _nlp_pre_result.get("intent_scores") or {}
                _multi_intent_detected = (
                    len([s for s in _nlp_intent_scores.values() if s > 0]) >= 2
                    and bool(runtime.get("multi_task_turn_interpreter_fn"))
                )
                if _multi_intent_detected:
                    vlog.debug("[TURN] Multi-intent detected: %s", _nlp_intent_scores)
            except Exception:
                _nlp_pre_result = {}
                _multi_intent_detected = False

    # Task graph state — populated when multi-task interpretation fires.
    _task_graph: list[dict[str, Any]] | None = None
    _primary_task_id: int | None = None
    _secondary_results: list[tuple[dict[str, Any], str, dict[str, Any]]] = []

    # ── Turn interpretation ───────────────────────────────────
    vlog.debug("[TURN] Interpreting turn input (override=%s, deterministic=%s)", turn_data_override is not None, deterministic_response)
    if turn_data_override is not None:
        turn_data = turn_data_override
    elif deterministic_response:
        turn_data = dict(runtime.get("turn_input_defaults") or {})
    elif runtime.get("local_only") or _active_mod.get("local_only"):
        if slm_available():
            if _multi_intent_detected:
                _mti_fn = runtime["multi_task_turn_interpreter_fn"]
                _mti_prompt = (
                    runtime.get("multi_task_interpretation_prompt")
                    or runtime["turn_interpretation_prompt"]
                )
                turn_data = _mti_fn(
                    call_llm=call_slm,
                    input_text=input_text,
                    task_context=task_context,
                    prompt_text=_mti_prompt,
                    default_fields=runtime["turn_input_defaults"],
                    tool_fns=runtime.get("tool_fns"),
                )
            else:
                _li_interpreter = _active_mod.get("turn_interpreter_fn") or runtime["turn_interpreter_fn"]
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
                _nlp_fn = runtime.get("nlp_pre_interpreter_fn")
                if _nlp_fn is not None and "nlp_pre_interpreter_fn" in _li_sig.parameters:
                    _li_kwargs["nlp_pre_interpreter_fn"] = _nlp_fn
                turn_data = _li_interpreter(**_li_kwargs)
        else:
            turn_data = dict(runtime.get("turn_input_defaults") or {})
    else:
        if _multi_intent_detected:
            _mti_fn = runtime["multi_task_turn_interpreter_fn"]
            _mti_prompt = (
                runtime.get("multi_task_interpretation_prompt")
                or runtime["turn_interpretation_prompt"]
            )
            turn_data = _mti_fn(
                call_llm=call_llm,
                input_text=input_text,
                task_context=task_context,
                prompt_text=_mti_prompt,
                default_fields=runtime["turn_input_defaults"],
                tool_fns=runtime.get("tool_fns"),
            )
        else:
            turn_data = interpret_turn_input(
                input_text, task_context, runtime,
                world_sim_theme=world_sim_theme, mud_world_state=mud_world_state,
            )
    turn_data = normalize_turn_data(turn_data, runtime.get("turn_input_schema") or {})

    # ── Multi-task graph extraction ───────────────────────────
    # If the multi-task interpreter emitted a {tasks: [...]} graph shape,
    # extract the primary (first unblocked) task's turn_data for the rest
    # of the single-task pipeline (carry-forward, enrichment, inspection).
    # Secondary tasks are dispatched in the graph walk after orch.process_turn().
    if isinstance(turn_data.get("tasks"), list) and turn_data["tasks"]:
        _task_graph = turn_data["tasks"]
        _turn_schema = runtime.get("turn_input_schema") or {}
        for _gt in _task_graph:
            if isinstance(_gt.get("turn_data"), dict):
                _gt["turn_data"] = normalize_turn_data(_gt["turn_data"], _turn_schema)
        _primary_node = next(
            (t for t in _task_graph if not t.get("blocked_by")), _task_graph[0]
        )
        _primary_task_id = _primary_node.get("task_id")
        turn_data = dict(_primary_node.get("turn_data") or {})
        vlog.debug(
            "[TURN] Multi-task graph: %d tasks, primary=%s intent=%s",
            len(_task_graph), _primary_task_id, turn_data.get("intent_type"),
        )

    vlog.debug("[TURN] turn_data keys: %s", list(turn_data.keys()))

    # ── Carry-forward: pending tool call from prior turn ─────────────
    # If the previous turn set tool_call_requested=True and the task has not
    # been resolved, carry the flag forward even when the SLM classified the
    # current turn as "general" (e.g. a location follow-up after a weather
    # query). orch.state here is the state from the *previous* turn because
    # domain_step (inside process_turn) has not yet run for this turn.
    _orch_prior_state = orch.state if isinstance(orch.state, dict) else {}
    if (
        not turn_data.get("tool_call_requested")
        and _orch_prior_state.get("pending_tool_call")
        and turn_data.get("task_status") not in ("completed", "abandoned", "deferred")
    ):
        turn_data["tool_call_requested"] = True
        vlog.debug("[TURN] Carried forward tool_call_requested=True from prior turn")
        if turn_data.get("intent_type") == "general":
            _prior_intent = _orch_prior_state.get("pending_tool_intent")
            if _prior_intent:
                turn_data["intent_type"] = _prior_intent
                vlog.debug("[TURN] Carried forward intent_type=%s from prior turn", _prior_intent)

    # ── Deferred greeting (after turn interpretation) ─────────
    if _greeting_eligible:
        _g_result = check_greeting(
            session_id, session, input_text, turn_data,
            domain_physics, runtime, resolved_domain_id, system_prompt,
            _session_containers, user, holodeck,
            slm_available_fn=slm_available,
            compute_seal_fn=_compute_transcript_seal,
            sync_session_fn=_sync_session_back,
        )
        if _g_result is not None:
            return _g_result

    # ── Layer 2½b: Post-interpretation enrichment (SLM context + telemetry) ──
    vlog.debug("[ENRICH] Enriching turn data (domain=%s)", resolved_domain_id)
    # Prefer the active module's physics glossary so per-module terms (e.g.
    # weather/forecast, search/query) reach the SLM context compression.
    # Fall back to the top-level domain physics glossary if the module has none.
    _active_mod_physics = _active_mod.get("domain_physics") or {}
    glossary = (
        _active_mod_physics.get("glossary")
        or domain_physics.get("glossary")
        or []
    )
    turn_data = enrich_turn_data(
        turn_data, input_text, domain_physics, glossary,
        resolved_domain_id, _actor_elapsed, deterministic_response,
        module_key=session.get("module_key"),
        slm_available_fn=slm_available,
        slm_interpret_physics_context_fn=slm_interpret_physics_context,
        rag_context=_pre_rag_context,
    )

    log.info("[%s] Turn Data: %s", session_id, json.dumps(turn_data, default=str))

    # ── Inspection middleware gate ─────────────────────────────
    from lumina.middleware import InspectionPipeline

    _turn_schema = runtime.get("turn_input_schema") or {}
    # Invariants with standing_order_on_violation are orchestrator-grade:
    # they fire standing orders and track attempt counters inside
    # ActorResolver.check_invariants() → resolve().  The inspection
    # gate must NOT evaluate them — a critical failure here would deny
    # the input before the orchestrator can respond pedagogically.
    _all_invariants = domain_physics.get("invariants", [])
    _inspection_invariants = [
        inv for inv in _all_invariants
        if not inv.get("standing_order_on_violation")
    ]
    vlog.debug(
        "[INSPECT] Running inspection pipeline (invariants=%d of %d, %d orchestrator-only)",
        len(_inspection_invariants), len(_all_invariants),
        len(_all_invariants) - len(_inspection_invariants),
    )
    _inspection = InspectionPipeline(
        turn_input_schema=_turn_schema,
        invariants=_inspection_invariants,
        strict=True,
    )
    _inspection_result = _inspection.run(
        turn_data, input_text=input_text, task_context=task_context,
    )
    if not _inspection_result.approved and not holodeck:
        log.warning(
            "[%s] Inspection denied: %s",
            session_id,
            _inspection_result.violations,
        )
        return {
            "response": "I cannot process this input \u2014 it does not satisfy the domain constraints.",
            "action": "inspection_denied",
            "prompt_type": "inspection_denied",
            "escalated": True,
            "tool_results": {},
            "domain_id": resolved_domain_id,
            "_inspection": _inspection_result.to_dict(),
        }
    turn_data = _inspection_result.sanitized_payload or turn_data

    # ── Layer 4: Orchestration ────────────────────────────────
    vlog.debug("[ORCH] Orchestrating turn (domain=%s)", resolved_domain_id)
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
    vlog.debug("[ORCH] action=%s prompt_type=%s", resolved_action, prompt_contract.get("prompt_type"))

    # ── Multi-task graph walk ─────────────────────────────────
    # Dispatch all non-primary, non-blocked subtasks through the orchestrator.
    # Each secondary call advances orch.state (affect, task history) for all
    # subtasks before the session sync. Blocked tasks are deferred to
    # pending_tasks in orch.state for carry-forward on the next user turn.
    if _task_graph is not None:
        for _gt in _task_graph:
            if _gt.get("task_id") == _primary_task_id:
                continue  # Already processed as primary
            if _gt.get("blocked_by"):
                continue  # Blocked — deferred to pending_tasks
            _sub_td = dict(_gt.get("turn_data") or {})
            _sub_contract, _sub_action = orch.process_turn(
                task_spec, _sub_td, provenance_metadata=turn_provenance,
            )
            _secondary_results.append((_sub_contract, _sub_action, _sub_td))
            vlog.debug(
                "[ORCH] Graph walk: task_id=%s action=%s",
                _gt.get("task_id"), _sub_action,
            )
        # Persist blocked tasks so the next turn can resume them
        _pending = [
            {
                "task_id": t["task_id"],
                "intent": t.get("intent", "general"),
                "turn_data": t.get("turn_data"),
            }
            for t in _task_graph if t.get("blocked_by")
        ]
        if _pending and isinstance(orch.state, dict):
            orch.state = dict(orch.state)
            orch.state["pending_tasks"] = _pending
            vlog.debug(
                "[ORCH] %d blocked task(s) deferred to pending_tasks queue",
                len(_pending),
            )

    # ── Post-turn processing (domain-hook driven) ──────────────
    _new_task_presented = _new_task_on_resume
    _ptp_fn = _active_mod.get("post_turn_processor_fn") or runtime.get("post_turn_processor_fn")
    vlog.debug("[POST] Post-turn processing (hook=%s)", _ptp_fn is not None)
    if _ptp_fn is not None:
        _ptp_result = _ptp_fn(
            turn_data=turn_data,
            prompt_contract=prompt_contract,
            resolved_action=resolved_action,
            session=session,
            task_spec=task_spec,
            current_task=current_task,
            runtime=runtime,
            orchestrator=orch,
        )
        resolved_action = _ptp_result.get("resolved_action", resolved_action)
        current_task = _ptp_result.get("current_task", current_task)
        _new_task_presented = _ptp_result.get("new_task_presented", False) or _new_task_presented

    session["current_task"] = current_task
    session["turn_count"] += 1

    # ── Sync session + auto-save profile ──────────────────────
    vlog.debug("[SYNC] Syncing session state (turn=%d)", session["turn_count"])
    container = _session_containers.get(session_id)
    if container is not None:
        container.active_context.sync_from_dict(session)
        container.last_activity = time.time()
        _persist_session_container(session_id, container)

        if container.user is not None and orch.state is not None:
            profile_path = container.active_context.subject_profile_path
            _mod_key = container.active_context.module_key
            _user_id = str(container.user["sub"]) if container.user else None
            _ac_domain_id = container.active_context.domain_id or ""
            _domain_key = _ac_domain_id.split("/")[0] if "/" in _ac_domain_id else _ac_domain_id
            if profile_path:
                try:
                    # Try key-based store first, fall back to path-based
                    profile_data = None
                    if _user_id and _domain_key:
                        profile_data = _cfg.PERSISTENCE.load_profile(_user_id, _domain_key)
                    if profile_data is None:
                        profile_data = _cfg.PERSISTENCE.load_subject_profile(profile_path)
                    _ps_fn = (
                        _active_mod.get("profile_serializer_fn")
                        or runtime.get("profile_serializer_fn")
                    )
                    if _ps_fn is not None:
                        _ps_sig = inspect.signature(_ps_fn)
                        _ps_kwargs: dict[str, Any] = {
                            "orch_state": orch.state,
                            "profile_data": profile_data,
                            "module_key": _mod_key,
                        }
                        if "persistence" in _ps_sig.parameters:
                            _ps_kwargs["persistence"] = _cfg.PERSISTENCE
                        if "user_id" in _ps_sig.parameters:
                            _ps_kwargs["user_id"] = _user_id
                        profile_data = _ps_fn(**_ps_kwargs)
                    else:
                        import dataclasses
                        if dataclasses.is_dataclass(orch.state):
                            profile_data["session_state"] = dataclasses.asdict(orch.state)
                        elif isinstance(orch.state, dict):
                            profile_data["session_state"] = dict(orch.state)
                    # Save to both key-based and legacy path-based stores
                    if _user_id and _domain_key:
                        _cfg.PERSISTENCE.save_profile(_user_id, _domain_key, profile_data)
                    _cfg.PERSISTENCE.save_subject_profile(profile_path, profile_data)
                except Exception:
                    log.warning("Profile auto-save failed for session %s", session_id)
    else:
        _cfg.PERSISTENCE.save_session_state(
            session_id,
            {
                "task_spec": task_spec,
                "current_task": current_task,
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

    # ── Layer 5: Response assembly ────────────────────────────
    vlog.debug("[RESPONSE] Assembling response (turn=%d)", session["turn_count"])
    escalated, structured_content = build_escalation_content(
        session_id, orch, resolved_domain_id, runtime, _active_mod,
    )

    if structured_content is None:
        structured_content = build_command_content(
            resolved_action, turn_data, input_text, user,
            resolved_domain_id, domain_physics, runtime, task_spec,
            session_id, orch,
            call_llm_fn=call_llm,
        )

    tool_results = apply_tool_call_policy(
        resolved_action=resolved_action,
        prompt_contract=prompt_contract,
        turn_data=turn_data,
        task_spec=task_spec,
        runtime=runtime,
    )

    # Aggregate tool results from secondary tasks in the multi-task graph walk
    if _secondary_results:
        _extra_tools: list[dict[str, Any]] = []
        for _sec_contract, _sec_action, _sec_td in _secondary_results:
            _extra_tools.extend(apply_tool_call_policy(
                resolved_action=_sec_action,
                prompt_contract=_sec_contract,
                turn_data=_sec_td,
                task_spec=task_spec,
                runtime=runtime,
            ))
        if _extra_tools:
            tool_results = list(tool_results) + _extra_tools
            vlog.debug("[LLM] Aggregated %d secondary tool result(s)", len(_extra_tools))

    # ── Layer 6: LLM payload + invocation ─────────────────────
    vlog.debug("[LLM] Assembling LLM payload (tool_results=%d)", len(tool_results))
    llm_payload = assemble_llm_payload(
        prompt_contract, input_text, _answered_task, current_task,
        _new_task_presented, turn_data, tool_results,
        session_id, _session_containers,
    )

    llm_response = _invoke_llm(
        llm_payload, prompt_contract, system_prompt, runtime,
        structured_content, deterministic_response, session_id,
        slm_weight_overrides, turn_provenance,
        world_sim_theme, mud_world_state,
        call_llm_fn=call_llm,
        call_slm_fn=call_slm,
        slm_available_fn=slm_available,
        render_contract_response_fn=render_contract_response,
        classify_task_weight_fn=classify_task_weight,
        TaskWeight=TaskWeight,
    )

    vlog.debug("[LLM] Response received (%d chars)", len(llm_response))

    # ── Ring buffer push ──────────────────────────────────────
    _rb_container = _session_containers.get(session_id)
    if _rb_container is not None and hasattr(_rb_container, "ring_buffer"):
        _rb_container.ring_buffer.push(
            user_message=input_text,
            llm_response=llm_response,
            turn_number=session.get("turn_count", 0),
            domain_id=resolved_domain_id,
        )

    # ── Transcript seal ───────────────────────────────────────
    vlog.debug("[SEAL] Computing transcript seal")
    _seal, _seal_meta, _transcript = _compute_transcript_seal(
        session_id, session, resolved_domain_id, user, holodeck,
    )

    # ── Timer hook ────────────────────────────────────────────
    _post_turn_timer_fn = (
        _active_mod.get("post_turn_timer_fn")
        or runtime.get("post_turn_timer_fn")
    )
    if _post_turn_timer_fn:
        _post_turn_timer_fn(
            session=session,
            session_id=session_id,
            resolved_action=resolved_action,
            new_task_presented=_new_task_presented,
            session_containers=_session_containers,
        )

    log.info("[%s] Response length: %s chars", session_id, len(llm_response))

    # ── Provenance trace ──────────────────────────────────────
    vlog.debug("[PROV] Recording provenance trace")
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

    # ── Build final result ────────────────────────────────────
    vlog.debug("[RESULT] Building final result (action=%s, escalated=%s)", resolved_action, escalated)
    result = build_result(
        llm_response, resolved_action, prompt_contract, escalated,
        tool_results, resolved_domain_id, structured_content,
        session_id, _session_containers,
        _seal, _seal_meta, _transcript,
    )

    # ── Holodeck: attach raw structured evidence ──────────────
    if holodeck:
        result = attach_holodeck_data(
            result, orch, turn_data, _inspection_result,
            world_sim_theme, mud_world_state,
        )

    return result
