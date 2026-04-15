"""Education domain pre-turn resume hook.

When a user returns to a session whose last problem was already solved,
generate a fresh problem so the LLM presents a new equation instead of
re-showing the completed one.

Called by processing.py via the ``pre_turn_resume_fn`` hook point.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("lumina.education.pre-turn-resume")


def education_pre_turn_resume(
    *,
    session: dict[str, Any],
    task_spec: dict[str, Any],
    current_task: dict[str, Any],
    runtime: dict[str, Any],
    orchestrator: Any,
) -> dict[str, Any]:
    """Replace a solved problem with a freshly generated one on resume.

    Returns a dict with:
        replaced: bool — True when a new problem was generated
        current_task: dict — the (possibly new) current task
    """
    module_physics = getattr(orchestrator, "domain", None) or {}
    subsystem_configs = module_physics.get("subsystem_configs") or {}
    tiers = subsystem_configs.get("equation_difficulty_tiers")
    gen_fn = (runtime.get("tool_fns") or {}).get("generate_problem")

    if not (isinstance(tiers, list) and tiers and gen_fn is not None):
        log.warning("Cannot replace solved problem on resume: missing tiers or generate_problem")
        return {"replaced": False, "current_task": current_task}

    try:
        diff = float(task_spec.get("nominal_difficulty", 0.5))
        module_key = session.get("module_key")
        new_problem = gen_fn(diff, subsystem_configs, domain_id=module_key)
        new_problem["solved"] = False
        new_problem["completed"] = False
        return {"replaced": True, "current_task": new_problem}
    except Exception:
        log.warning("Problem generation on resume failed", exc_info=True)
        return {"replaced": False, "current_task": current_task}
