"""Core D.S.A. → LLM pipeline: process_message().

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


def _build_clarification_response(
    error_msg: str,
    cmd_dispatch: dict[str, Any],
    user: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build a structured clarification card when auto-stage fails.

    Instead of silently swallowing the error, this produces a user-visible
    card explaining what went wrong and how to fix it.
    """
    operation = cmd_dispatch.get("operation", "")
    _raw_params = cmd_dispatch.get("params") or {}
    params = _raw_params if isinstance(_raw_params, dict) else {}

    hints: list[str] = []

    # Detect common failure patterns and provide actionable guidance
    if "schema validation failed" in error_msg.lower():
        raw_role = params.get("new_role", params.get("role", ""))
        if raw_role:
            from lumina.api.routes.admin import _DOMAIN_ROLE_ALIASES
            if raw_role in _DOMAIN_ROLE_ALIASES:
                hints.append(
                    f"'{raw_role}' is a domain role, not a system role. "
                    f"The system role should be 'user'. "
                    f"You can then assign the domain role '{raw_role}' separately."
                )

    if "governed_modules" in error_msg.lower() or not params.get("governed_modules"):
        # Try to list available modules
        try:
            if _cfg.DOMAIN_REGISTRY is not None:
                domains = _cfg.DOMAIN_REGISTRY.list_domains()
                domain_labels = [f"{d['domain_id']} ({d['label']})" for d in domains]
                hints.append(f"Available domains: {', '.join(domain_labels)}")
        except Exception:
            pass

    if not hints:
        hints.append(f"The command could not be processed: {error_msg}")
        hints.append("Please rephrase with the required fields.")

    return {
        "type": "clarification",
        "operation": operation,
        "error": error_msg,
        "hints": hints,
        "original_params": {k: v for k, v in params.items() if k != "password"},
    }


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

    # ── Frozen-session gate: block input until teacher issues unlock PIN ──
    container = _session_containers.get(session_id)
    if container is not None and container.frozen:
        import re as _re
        from lumina.core.session_unlock import validate_unlock_pin
        _pin_candidate = input_text.strip()
        if _re.fullmatch(r"\d{6}", _pin_candidate) and validate_unlock_pin(session_id, _pin_candidate):
            container.frozen = False
            log.info("[%s] Session unlocked via PIN in chat turn", session_id)
            return {
                "response": "Session unlocked. You may continue.",
                "action": "session_unlocked",
                "prompt_type": "session_unlocked",
                "escalated": False,
                "tool_results": {},
                "domain_id": domain_id or session.get("domain_id", ""),
            }
        return {
            "response": "This session is temporarily locked pending teacher review.",
            "action": "session_frozen",
            "prompt_type": "session_frozen",
            "escalated": True,
            "tool_results": {},
            "domain_id": domain_id or session.get("domain_id", ""),
        }

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
    # Capture the problem the student is currently working on.
    # This snapshot is used for LLM feedback context regardless of whether
    # a new problem is generated later in the same turn (see _answered_problem
    # usage below). Copying avoids aliasing issues if gen_fn mutates the dict.
    _answered_problem: dict[str, Any] = dict(current_problem)

    # Resolve per-session runtime context
    resolved_domain_id = session["domain_id"]
    runtime = _cfg.DOMAIN_REGISTRY.get_runtime_context(resolved_domain_id)

    # ── Sandbox physics override ──────────────────────────────
    # When physics_sandbox is provided (holodeck simulation), deep-copy the
    # runtime so the cached live context is never mutated, then swap in the
    # sandbox physics.  The orchestrator's domain reference is also updated
    # so that standing-order evaluation uses the proposed physics.
    if physics_sandbox is not None:
        import copy as _copy
        runtime = _copy.deepcopy(runtime)
        runtime["domain"] = physics_sandbox
        orch.domain = physics_sandbox

    runtime_provenance = dict(runtime.get("runtime_provenance") or {})
    system_prompt = runtime["system_prompt"]

    # ── Per-module prompt overrides (governance persona) ──────
    # Governance modules pre-compile a module-specific system_prompt and
    # turn_interpretation_prompt in runtime_loader.  When present, these
    # replace the domain-wide (learning) prompts so governance roles are
    # never addressed with algebra/curriculum context.
    _module_map = runtime.get("module_map") or {}
    _module_key = session.get("module_key") or resolved_domain_id
    _active_mod = _module_map.get(_module_key) or {}
    if _active_mod.get("system_prompt"):
        system_prompt = _active_mod["system_prompt"]
    if _active_mod.get("turn_interpretation_prompt") or _active_mod.get("turn_interpreter_fn"):
        # Shallow-copy runtime so interpret_turn_input reads the override
        # without mutating the cached domain-wide context.
        runtime = dict(runtime)
        if _active_mod.get("turn_interpretation_prompt"):
            runtime["turn_interpretation_prompt"] = _active_mod["turn_interpretation_prompt"]
        if _active_mod.get("turn_interpreter_fn"):
            runtime["turn_interpreter_fn"] = _active_mod["turn_interpreter_fn"]
    # Per-module turn_input_defaults / turn_input_schema override so
    # governance modules produce governance-shaped evidence instead of
    # inheriting algebra-shaped defaults.
    # See: docs/7-concepts/llm-assisted-governance-adapters.md
    if _active_mod.get("turn_input_defaults"):
        runtime = dict(runtime)
        runtime["turn_input_defaults"] = _active_mod["turn_input_defaults"]
    if _active_mod.get("turn_input_schema"):
        runtime = dict(runtime)
        runtime["turn_input_schema"] = _active_mod["turn_input_schema"]

    # ── Magic-circle consent gate ─────────────────────────────
    # Only "user" role needs consent; governance roles and unauthenticated
    # sessions bypass entirely.
    # Domain must declare consent_boundary in pre_turn_checks with enabled: true.
    _GOVERNANCE_ROLES = frozenset({"root", "domain_authority", "it_support", "qa", "auditor"})
    _user_role = (user or {}).get("role", "")
    if user is not None and _user_role not in _GOVERNANCE_ROLES:
        pre_turn_checks = runtime.get("pre_turn_checks") or []
        consent_check = next(
            (c for c in pre_turn_checks if c.get("id") == "consent_boundary" and c.get("enabled")),
            None,
        )
        if consent_check is not None:
            container = _session_containers.get(session_id)
            if container is not None and not container.consent_accepted:
                return {
                    "response": "Please accept the magic-circle consent agreement before continuing.",
                    "action": "consent_required",
                    "prompt_type": "consent_required",
                    "escalated": False,
                    "tool_results": None,
                    "domain_id": domain_id or session.get("domain_id", ""),
                }

    # ── Glossary interception (neutral turn — no mastery/affect change) ──
    # Prefer the session's module-specific domain physics (orch.domain) which
    # carries the per-module glossary.  Fall back to the domain-wide runtime
    # physics only when the orchestrator's domain has no glossary.
    domain_physics = getattr(orch, "domain", None) or runtime.get("domain") or {}
    glossary = domain_physics.get("glossary") or (runtime.get("domain") or {}).get("glossary") or []
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

    # ── Extract world-sim state for ALL code paths ────────────
    world_sim_theme = getattr(orch.state, "world_sim_theme", {}) or {}
    mud_world_state = getattr(orch.state, "mud_world_state", {}) or {}

    if turn_data_override is not None:
        turn_data = turn_data_override
    elif deterministic_response:
        turn_data = dict(runtime.get("turn_input_defaults") or {})
    elif runtime.get("local_only") or _active_mod.get("local_only"):
        if slm_available():
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
        turn_data = interpret_turn_input(input_text, task_context, runtime, world_sim_theme=world_sim_theme, mud_world_state=mud_world_state)
    turn_data = normalize_turn_data(turn_data, runtime.get("turn_input_schema") or {})

    # ── SLM physics interpretation (context compression) ─────
    # All domains (including local-only) benefit from physics context
    # enrichment.  The SLM matches incoming signals against domain
    # invariants, standing orders, and glossary so the orchestrator has
    # structured context before making action decisions.
    # Skip for deterministic responses — the response is pre-computed so
    # physics context enrichment is unnecessary overhead.
    if not deterministic_response and slm_available():
        slm_context = slm_interpret_physics_context(
            incoming_signals=turn_data,
            domain_physics=domain_physics,
            glossary=glossary,
            actor_input=input_text,
        )
        turn_data["_slm_context"] = slm_context

    # ── Per-domain vector retrieval (RAG grounding) ───────────
    # Query the pre-built per-domain vector store so the LLM receives
    # pre-digested document chunks alongside physics context.
    try:
        from lumina.core.nlp import search_domain as _search_domain

        _rag_hits = _search_domain(input_text, resolved_domain_id, k=3)
        if _rag_hits:
            turn_data["_rag_context"] = [
                {
                    "text": hit.chunk.text[:500],
                    "source": hit.chunk.source_path,
                    "heading": hit.chunk.heading,
                    "score": round(hit.score, 4),
                }
                for hit in _rag_hits
            ]
    except Exception:
        pass  # Vector retrieval is optional — never blocks the pipeline

    # Inject the universal base field response_latency_sec (sampled at request
    # arrival, before any LLM/SLM calls — excludes server-side inference latency).
    # Domain adapters are responsible for mapping this to any domain-specific
    # timing fields (e.g. solve_elapsed_sec in the education domain).
    if _student_elapsed is not None:
        turn_data["response_latency_sec"] = _student_elapsed

    log.info("[%s] Turn Data: %s", session_id, json.dumps(turn_data, default=str))

    # ── Inspection Middleware Gate ─────────────────────────────
    # Run the three-stage inspection pipeline (NLP → schema → invariants)
    # before allowing the orchestrator to process the turn.
    from lumina.middleware import InspectionPipeline

    _turn_schema = runtime.get("turn_input_schema") or {}
    _domain_invariants = (runtime.get("domain") or {}).get("invariants", [])
    _inspection = InspectionPipeline(
        turn_input_schema=_turn_schema,
        invariants=_domain_invariants,
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
    # Use sanitized payload (defaults filled, NLP anchors merged)
    turn_data = _inspection_result.sanitized_payload or turn_data

    turn_provenance: dict[str, Any] = dict(runtime_provenance)
    turn_provenance["turn_data_hash"] = _canonical_sha256(turn_data)
    if model_id is not None:
        turn_provenance["model_id"] = model_id
    if model_version is not None:
        turn_provenance["model_version"] = model_version

    slm_weight_overrides = runtime.get("slm_weight_overrides") or {}

    # ── Inject sliding-window telemetry into turn evidence ────
    try:
        from lumina.daemon import resource_monitor as _rm
        _daemon_status = _rm.get_status()
        if _daemon_status.get("enabled") and _daemon_status.get("telemetry_window"):
            turn_data["_system_telemetry"] = _daemon_status["telemetry_window"]
    except Exception:
        pass  # Graceful fallback — telemetry is optional

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
        for r in orch.log_records[-2:]
    )

    # Build structured escalation card when an escalation was raised this turn.
    structured_content: dict[str, Any] | None = None
    if escalated:
        from lumina.api.structured_content import build_escalation_card

        esc_records = [
            r for r in orch.log_records[-2:]
            if r.get("record_type") == "EscalationRecord"
            and r.get("session_id") == session_id
        ]
        if esc_records:
            session_ctx = {
                "domain_id": resolved_domain_id,
                "turn_count": session.get("turn_count"),
                "student_pseudonym": orch._writer._profile.get(
                    "subject_id",
                    orch._writer._profile.get("student_id", ""),
                ) if hasattr(orch, "_writer") else "",
            }
            structured_content = build_escalation_card(
                esc_records[-1], session_context=session_ctx,
            )

    # Build structured command-proposal card when a command was dispatched
    # (system_command for system domain, governance_command for education governance).
    if (
        structured_content is None
        and resolved_action in ("system_command", "governance_command")
        and isinstance(turn_data.get("command_dispatch"), dict)
    ):
        cmd_dispatch = turn_data["command_dispatch"]
        if cmd_dispatch.get("operation"):
            _actor_id = (user or {}).get("sub", "")
            _actor_role = (user or {}).get("role", "user")
            try:
                from lumina.api.routes.admin import _stage_command, _HITL_EXEMPT_OPS, _normalize_slm_command

                operation = cmd_dispatch.get("operation", "")

                # HITL-exempt operations execute immediately without staging
                if operation in _HITL_EXEMPT_OPS:
                    from lumina.api.routes.admin import _execute_admin_operation
                    import asyncio

                    _normalized = _normalize_slm_command(cmd_dispatch, input_text)
                    _user_data = user or {"sub": _actor_id, "role": _actor_role}
                    # _execute_admin_operation is async; we are in a sync function.
                    _coro = _execute_admin_operation(
                        _user_data, _normalized, input_text,
                    )
                    try:
                        _loop = asyncio.get_running_loop()
                    except RuntimeError:
                        _loop = None

                    if _loop is not None and _loop.is_running():
                        # Already in an async context (e.g. FastAPI) — create a
                        # task via run_coroutine_threadsafe from a thread.
                        import concurrent.futures
                        _future = asyncio.run_coroutine_threadsafe(_coro, _loop)
                        _exec_result = _future.result(timeout=30)
                    else:
                        _exec_result = asyncio.run(_coro)

                    structured_content = {
                        "type": "query_result",
                        "operation": operation,
                        "result": _exec_result,
                    }
                else:
                    # ── LLM-assisted physics edit proposal ────────
                    # When the operation is update_domain_physics and we are
                    # in a governance context, call the LLM to interpret the
                    # NL instruction into a structured patch and build a
                    # form-like physics_edit_proposal card instead of the
                    # generic command_proposal card.
                    _is_physics_edit = (
                        operation == "update_domain_physics"
                        and resolved_action == "governance_command"
                    )
                    _physics_proposal: dict[str, Any] | None = None
                    if _is_physics_edit and domain_physics:
                        try:
                            from domain_packs.education.controllers.governance_adapters import (
                                extract_physics_patch,
                            )
                            _physics_proposal = extract_physics_patch(
                                call_llm, input_text, domain_physics,
                            )
                            # Enrich the command dispatch params with the
                            # LLM-generated updates so _stage_command gets
                            # a fully-populated command.
                            if _physics_proposal.get("proposed_patch"):
                                cmd_dispatch.setdefault("params", {})
                                cmd_dispatch["params"]["domain_id"] = (
                                    cmd_dispatch["params"].get("domain_id")
                                    or resolved_domain_id
                                )
                                cmd_dispatch["params"]["updates"] = (
                                    _physics_proposal["proposed_patch"]
                                )
                        except Exception:
                            log.warning(
                                "LLM physics patch extraction failed, "
                                "falling back to standard staging",
                                exc_info=True,
                            )

                    # ── Teacher / TA escalation for physics edits ─
                    # Non-DA governance roles proposing physics changes
                    # get an auto-escalation so a DA must approve.
                    _requires_escalation = (
                        _is_physics_edit
                        and _actor_role not in ("root", "domain_authority")
                    )

                    _staged = _stage_command(
                        parsed_command=cmd_dispatch,
                        original_instruction=input_text,
                        actor_id=_actor_id,
                        actor_role=_actor_role,
                    )

                    if _is_physics_edit and _physics_proposal is not None:
                        from lumina.api.structured_content import build_physics_edit_card

                        structured_content = build_physics_edit_card(
                            _staged,
                            _physics_proposal,
                            domain_physics,
                            requires_escalation=_requires_escalation,
                            escalation_record_id=_staged.get("escalation_record_id"),
                        )

                        # ── Novel synthesis detection ─────────
                        # If the proposal adds genuinely new entries,
                        # flag it and log a TraceEvent so the escalation
                        # pipeline can present it for two-key verification.
                        try:
                            from domain_packs.education.controllers.governance_adapters import (
                                detect_novel_synthesis,
                            )
                            _novel_ids = detect_novel_synthesis(
                                _physics_proposal, domain_physics,
                            )
                            if _novel_ids:
                                structured_content["context"]["novel_synthesis_ids"] = _novel_ids
                                orch.append_provenance_trace(
                                    task_id=str(task_spec.get("task_id", "")),
                                    action="novel_synthesis_flagged",
                                    prompt_type="governance_command",
                                    metadata={
                                        "novel_synthesis_signal": "NOVEL_PATTERN",
                                        "novel_ids": _novel_ids,
                                        "domain_id": resolved_domain_id,
                                        "staged_id": _staged.get("staged_id", ""),
                                        "actor_id": _actor_id,
                                    },
                                )
                                log.info(
                                    "[%s] Novel synthesis detected in physics edit: %s",
                                    session_id,
                                    _novel_ids,
                                )
                        except Exception:
                            log.debug("Novel synthesis detection skipped", exc_info=True)
                    else:
                        structured_content = _staged.get("structured_content")
            except ValueError as _val_err:
                log.warning("Auto-stage failed for command_dispatch: %s", _val_err, exc_info=True)
                # Build a clarification response instead of silently swallowing
                structured_content = _build_clarification_response(
                    str(_val_err), cmd_dispatch, user,
                )
            except Exception:
                log.warning("Auto-stage failed for command_dispatch", exc_info=True)

    tool_results = apply_tool_call_policy(
        resolved_action=resolved_action,
        prompt_contract=prompt_contract,
        turn_data=turn_data,
        task_spec=task_spec,
        runtime=runtime,
    )

    llm_payload = dict(prompt_contract)
    # Governance prompt types don't have learning problems — skip
    # current_problem injection to avoid leaking algebra context.
    _prompt_type = str(prompt_contract.get("prompt_type", ""))
    _is_governance = _prompt_type.startswith("governance_")
    if not _is_governance:
        # Always use the problem the student was working on for feedback context,
        # not the new problem generated by the advancement block.  When a new
        # problem has been generated, pass it separately as "next_problem" so the
        # LLM can introduce it without mis-evaluating the student's work.
        llm_payload["current_problem"] = _answered_problem
        if _new_problem_presented:
            llm_payload["next_problem"] = current_problem
    llm_payload["student_message"] = input_text
    if tool_results:
        llm_payload["tool_results"] = tool_results
    if turn_data.get("_system_telemetry"):
        llm_payload["system_telemetry"] = turn_data["_system_telemetry"]

    # ── Inject RAG grounding into LLM payload ────────────────
    _rag = turn_data.get("_rag_context")
    if _rag:
        llm_payload["grounding_context"] = _rag

    # ── Strip internal-only metadata from LLM payload ────────
    # Keys prefixed with '_' are machine metadata for the orchestrator;
    # they waste LLM reasoning tokens and may leak internal state.
    _internal_keys = [k for k in llm_payload if k.startswith("_")]
    for k in _internal_keys:
        del llm_payload[k]

    _payload_json = json.dumps(llm_payload, indent=2, ensure_ascii=False)
    log.debug("[%s] LLM payload: ~%d tokens (%d chars)", session_id, len(_payload_json) // 4, len(_payload_json))

    # When a query_result structured_content is present, the UI renders the
    # data directly — skip LLM summarisation to avoid redundant narration.
    # See: docs/7-concepts/command-execution-pipeline.md
    # See: docs/7-concepts/domain-adapter-pattern.md
    if structured_content and isinstance(structured_content, dict) and structured_content.get("type") == "query_result":
        _op_name = structured_content.get("operation", "command")
        llm_response = f"Executed {_op_name} successfully."
    elif deterministic_response:
        llm_response = render_contract_response(
            prompt_contract, runtime,
            mud_world_state=mud_world_state,
            world_sim_theme=world_sim_theme,
        )
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

    # ── Push turn into conversation ring buffer ──────────────
    _container = _session_containers.get(session_id)
    if _container is not None and hasattr(_container, "ring_buffer"):
        _container.ring_buffer.push(
            user_message=input_text,
            llm_response=llm_response,
            turn_number=session.get("turn_count", 0),
            domain_id=resolved_domain_id,
        )

    # ── Compute rolling transcript seal for client persistence ──
    _rolling_seal: str | None = None
    if not holodeck and _container is not None and user:
        try:
            from lumina.auth.auth import sign_transcript

            _user_id = user.get("sub", "")
            if _user_id:
                _turns = _container.ring_buffer.snapshot()
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
                _seal_meta = {
                    "domain_id": resolved_domain_id,
                    "turn_count": session.get("turn_count", 0),
                    "last_activity_utc": time.time(),
                }
                _rolling_seal = sign_transcript(
                    _user_id, {"transcript": _transcript, "metadata": _seal_meta}
                )
        except Exception:
            log.warning("Could not compute transcript seal for %s", session_id, exc_info=True)

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

    result: dict[str, Any] = {
        "response": llm_response,
        "action": resolved_action,
        "prompt_type": prompt_contract.get("prompt_type", "task_presentation"),
        "escalated": escalated,
        "tool_results": tool_results,
        "domain_id": resolved_domain_id,
    }
    if _rolling_seal is not None:
        result["transcript_seal"] = _rolling_seal
        result["transcript_seal_metadata"] = _seal_meta
        # Include the server-authoritative transcript snapshot so the client
        # stores exactly what was sealed — eliminates timestamp drift between
        # client Date.now() and server time.time().
        # See: docs/7-concepts/zero-trust-architecture.md
        result["transcript_snapshot"] = _transcript
    if structured_content is not None:
        result["structured_content"] = structured_content

    # ── Holodeck: attach raw structured evidence for builders ─
    if holodeck:
        import dataclasses as _dc

        _state_obj = orch.state
        if _dc.is_dataclass(_state_obj) and not isinstance(_state_obj, type):
            _state_snap = _dc.asdict(_state_obj)
        elif isinstance(_state_obj, dict):
            _state_snap = dict(_state_obj)
        else:
            _state_snap = {}

        holodeck_data: dict[str, Any] = {
            "state_snapshot": _state_snap,
            "inspection_result": _inspection_result.to_dict(),
            "invariant_checks": _inspection_result.invariant_results,
            "evidence": turn_data,
            "world_sim_active": bool(mud_world_state.get("zone")),
            "mud_world_state": mud_world_state or None,
        }
        if result.get("structured_content") is None:
            result["structured_content"] = {}
        result["structured_content"]["holodeck"] = holodeck_data

    return result
