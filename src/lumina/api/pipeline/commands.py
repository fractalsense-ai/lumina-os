"""Command staging and execution pipeline stage.

Handles system_command, governance_command, and user_command dispatch
including HITL-exempt immediate execution and LLM-assisted physics edits.

See also:
    docs/7-concepts/command-execution-pipeline.md
    docs/7-concepts/domain-adapter-pattern.md
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("lumina-api")


# ---------------------------------------------------------------------------
# Clarification card builder
# ---------------------------------------------------------------------------

def build_clarification_response(
    error_msg: str,
    cmd_dispatch: dict[str, Any],
    user: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build a structured clarification card when auto-stage fails.

    Instead of silently swallowing the error, this produces a user-visible
    card explaining what went wrong and how to fix it.
    """
    from lumina.api import config as _cfg

    operation = cmd_dispatch.get("operation", "")
    _raw_params = cmd_dispatch.get("params") or {}
    params = _raw_params if isinstance(_raw_params, dict) else {}

    hints: list[str] = []

    if "schema validation failed" in error_msg.lower():
        raw_role = params.get("new_role", params.get("role", ""))
        if raw_role:
            from lumina.api.routes.admin import _get_domain_role_aliases

            if raw_role in _get_domain_role_aliases():
                hints.append(
                    f"'{raw_role}' is a domain role, not a system role. "
                    f"The system role should be 'user'. "
                    f"You can then assign the domain role '{raw_role}' separately."
                )

    if "governed_modules" in error_msg.lower() or not params.get("governed_modules"):
        try:
            if _cfg.DOMAIN_REGISTRY is not None:
                domains = _cfg.DOMAIN_REGISTRY.list_domains()
                domain_labels = [
                    f"{d['domain_id']} ({d['label']})" for d in domains
                ]
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


# ---------------------------------------------------------------------------
# Command content builder
# ---------------------------------------------------------------------------

def build_command_content(
    resolved_action: str,
    turn_data: dict[str, Any],
    input_text: str,
    user: dict[str, Any] | None,
    resolved_domain_id: str,
    domain_physics: dict[str, Any],
    runtime: dict[str, Any],
    task_spec: dict[str, Any],
    session_id: str,
    orchestrator: Any,
    *,
    call_llm_fn,
) -> dict[str, Any] | None:
    """Stage or execute a dispatched command.

    Returns a structured_content dict (command_proposal, query_result,
    physics_edit_proposal, or clarification), or *None* when no command
    applies.
    """
    if resolved_action not in (
        "system_command",
        "governance_command",
        "user_command",
    ):
        return None

    cmd_dispatch = turn_data.get("command_dispatch")
    if not isinstance(cmd_dispatch, dict) or not cmd_dispatch.get("operation"):
        return None

    _actor_id = (user or {}).get("sub", "")
    _actor_role = (user or {}).get("role", "user")

    try:
        from lumina.api.routes.admin import (
            _get_hitl_exempt_ops,
            _normalize_slm_command,
            _stage_command,
        )

        operation = cmd_dispatch.get("operation", "")

        # ── HITL-exempt: execute immediately ──────────────────
        if operation in _get_hitl_exempt_ops():
            return _execute_immediate(
                cmd_dispatch, input_text, user, resolved_domain_id,
                _actor_id, _actor_role, operation,
            )

        # ── Staged command (may include physics edit proposal) ─
        return _stage_and_build(
            cmd_dispatch,
            input_text,
            user,
            resolved_domain_id,
            domain_physics,
            runtime,
            task_spec,
            session_id,
            orchestrator,
            _actor_id,
            _actor_role,
            operation,
            resolved_action,
            call_llm_fn=call_llm_fn,
        )

    except ValueError as err:
        log.warning(
            "Auto-stage failed for command_dispatch: %s", err, exc_info=True,
        )
        return build_clarification_response(str(err), cmd_dispatch, user)
    except Exception:
        log.warning("Auto-stage failed for command_dispatch", exc_info=True)
        return None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _execute_immediate(
    cmd_dispatch: dict[str, Any],
    input_text: str,
    user: dict[str, Any] | None,
    resolved_domain_id: str,
    actor_id: str,
    actor_role: str,
    operation: str,
) -> dict[str, Any]:
    """Execute a HITL-exempt operation and return a query_result card."""
    import asyncio

    from lumina.api.routes.admin import (
        _execute_admin_operation,
        _normalize_slm_command,
    )

    normalized = _normalize_slm_command(cmd_dispatch, input_text)
    norm_params = normalized.get("params")
    if isinstance(norm_params, dict) and not norm_params.get("domain_id"):
        norm_params["domain_id"] = resolved_domain_id

    user_data = user or {"sub": actor_id, "role": actor_role}
    coro = _execute_admin_operation(user_data, normalized, input_text)

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None and loop.is_running():
        import concurrent.futures

        future = asyncio.run_coroutine_threadsafe(coro, loop)
        exec_result = future.result(timeout=30)
    else:
        exec_result = asyncio.run(coro)

    return {
        "type": "query_result",
        "operation": operation,
        "result": exec_result,
    }


def _stage_and_build(
    cmd_dispatch: dict[str, Any],
    input_text: str,
    user: dict[str, Any] | None,
    resolved_domain_id: str,
    domain_physics: dict[str, Any],
    runtime: dict[str, Any],
    task_spec: dict[str, Any],
    session_id: str,
    orchestrator: Any,
    actor_id: str,
    actor_role: str,
    operation: str,
    resolved_action: str,
    *,
    call_llm_fn,
) -> dict[str, Any] | None:
    """Stage a command and build the appropriate structured card."""
    from lumina.api.routes.admin import _stage_command

    # ── LLM-assisted physics edit proposal ────────────────────
    _is_physics_edit = (
        operation == "update_domain_physics"
        and resolved_action == "governance_command"
    )
    _physics_proposal: dict[str, Any] | None = None

    if _is_physics_edit and domain_physics:
        try:
            extract_fn = (runtime.get("tool_fns") or {}).get(
                "extract_physics_patch",
            )
            if extract_fn is not None:
                _physics_proposal = extract_fn(
                    call_llm_fn, input_text, domain_physics,
                )
            if _physics_proposal and _physics_proposal.get("proposed_patch"):
                cmd_dispatch.setdefault("params", {})
                cmd_dispatch["params"]["domain_id"] = (
                    cmd_dispatch["params"].get("domain_id") or resolved_domain_id
                )
                cmd_dispatch["params"]["updates"] = _physics_proposal[
                    "proposed_patch"
                ]
        except Exception:
            log.warning(
                "LLM physics patch extraction failed, "
                "falling back to standard staging",
                exc_info=True,
            )

    # ── Escalation for non-DA physics edits ───────────────────
    _requires_escalation = (
        _is_physics_edit and actor_role not in ("root", "admin")
    )

    staged = _stage_command(
        parsed_command=cmd_dispatch,
        original_instruction=input_text,
        actor_id=actor_id,
        actor_role=actor_role,
    )

    if _is_physics_edit and _physics_proposal is not None:
        from lumina.api.structured_content import build_physics_edit_card

        content = build_physics_edit_card(
            staged,
            _physics_proposal,
            domain_physics,
            requires_escalation=_requires_escalation,
            escalation_record_id=staged.get("escalation_record_id"),
        )

        # ── Novel synthesis detection ─────────────────────────
        try:
            detect_fn = (runtime.get("tool_fns") or {}).get(
                "detect_novel_synthesis",
            )
            novel_ids = detect_fn(_physics_proposal, domain_physics) if detect_fn else []
            if novel_ids:
                content["context"]["novel_synthesis_ids"] = novel_ids
                orchestrator.append_provenance_trace(
                    task_id=str(task_spec.get("task_id", "")),
                    action="novel_synthesis_flagged",
                    prompt_type="governance_command",
                    metadata={
                        "novel_synthesis_signal": "NOVEL_PATTERN",
                        "novel_ids": novel_ids,
                        "domain_id": resolved_domain_id,
                        "staged_id": staged.get("staged_id", ""),
                        "actor_id": actor_id,
                    },
                )
                log.info(
                    "[%s] Novel synthesis detected in physics edit: %s",
                    session_id,
                    novel_ids,
                )
        except Exception:
            log.debug("Novel synthesis detection skipped", exc_info=True)

        return content

    return staged.get("structured_content")
