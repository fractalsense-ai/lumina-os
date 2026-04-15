"""Education domain post-turn processor hook.

Extracts education-specific post-orchestrator logic from the system pipeline:
- problem_solved → task_complete action override
- problem_status tracking on current_problem
- Fluency-gated problem advancement (tier lookup + generate_problem)
- problem_presented_at timestamp reset

Called by processing.py via the ``post_turn_processor_fn`` hook point.
"""

from __future__ import annotations

import logging
import time
from typing import Any

log = logging.getLogger("lumina.education.post-turn")


def education_post_turn(
    *,
    turn_data: dict[str, Any],
    prompt_contract: dict[str, Any],
    resolved_action: str,
    session: dict[str, Any],
    task_spec: dict[str, Any],
    current_problem: dict[str, Any],
    runtime: dict[str, Any],
    orchestrator: Any,
) -> dict[str, Any]:
    """Post-turn processor for education learning modules.

    Returns a dict with:
        resolved_action: str — possibly overridden to "task_complete"
        current_problem:  dict — possibly replaced with a new generated problem
        new_problem_presented: bool — True when a new problem was generated
    """
    # ── problem_solved → task_complete override ───────────────
    if turn_data.get("problem_solved") is True:
        resolved_action = "task_complete"
        prompt_contract["prompt_type"] = "task_complete"
        current_problem["solved"] = True

    # ── problem_status tracking ───────────────────────────────
    reported_status = turn_data.get("problem_status")
    if isinstance(reported_status, str) and reported_status.strip():
        current_problem["status"] = reported_status.strip()

    # ── Fluency-gated problem advancement ─────────────────────
    new_problem_presented = False
    fluency_decision = {}
    domain_lib_decision = getattr(orchestrator, "last_domain_lib_decision", None) or {}
    if isinstance(domain_lib_decision.get("fluency"), dict):
        fluency_decision = domain_lib_decision["fluency"]

    should_advance = fluency_decision.get("advanced", False)

    if should_advance or turn_data.get("problem_solved") is True:
        # Use the module-specific domain physics (on the orchestrator),
        # not the default runtime physics which may lack tiers.
        module_physics = getattr(orchestrator, "domain", None) or {}
        subsystem_configs = module_physics.get("subsystem_configs") or {}
        tiers = subsystem_configs.get("equation_difficulty_tiers")
        module_key = session.get("module_key")
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
                    current_problem = gen_fn(diff, subsystem_configs, domain_id=module_key)
                    current_problem["solved"] = False
                    new_problem_presented = True
                else:
                    log.warning("generate_problem tool function not available")
            except Exception:
                log.warning("Problem generation on advance failed", exc_info=True)
        else:
            log.warning("No equation_difficulty_tiers found in module physics")

    return {
        "resolved_action": resolved_action,
        "current_problem": current_problem,
        "new_problem_presented": new_problem_presented,
    }


def education_reset_timer(
    *,
    session: dict[str, Any],
    new_problem_presented: bool,
    resolved_action: str,
    session_containers: dict[str, Any],
    session_id: str,
) -> None:
    """Reset problem_presented_at after response is built.

    Anchors the timestamp to when the outgoing response is fully ready so
    the next turn's response_latency_sec excludes this turn's LLM latency.
    """
    if new_problem_presented or resolved_action == "task_presentation":
        _response_sent_at = time.time()
        session["problem_presented_at"] = _response_sent_at
        _c = session_containers.get(session_id)
        if _c is not None:
            _c.active_context.problem_presented_at = _response_sent_at
