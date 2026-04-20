"""Assistant domain operation handlers for the admin command pipeline.

Each handler follows the domain-pack handler signature:

    async def handler(operation, params, user_data, ctx) -> dict

This module is loaded dynamically by the admin operation handler registry
via ``runtime-config.yaml → operation_handlers``.

See docs/7-concepts/command-execution-pipeline.md
See docs/7-concepts/domain-adapter-pattern.md
"""

from __future__ import annotations

from typing import Any


# ─────────────────────────────────────────────────────────────
# Task management handlers
# ─────────────────────────────────────────────────────────────


async def list_tasks(
    operation: str,
    params: dict[str, Any],
    user_data: dict[str, Any],
    ctx: Any,
) -> dict[str, Any]:
    """List the user's tracked tasks."""
    profile = _get_profile(ctx)
    task_history = profile.get("task_history", [])
    status_filter = params.get("status")
    limit = int(params.get("limit", 20))

    if status_filter:
        task_history = [t for t in task_history if t.get("status") == status_filter]

    return {
        "ok": True,
        "tasks": task_history[:limit],
        "total": len(task_history),
    }


async def view_task_history(
    operation: str,
    params: dict[str, Any],
    user_data: dict[str, Any],
    ctx: Any,
) -> dict[str, Any]:
    """View turn-by-turn history for a specific task."""
    task_id = params.get("task_id", "").strip()
    if not task_id:
        return {"ok": False, "error": "task_id is required"}

    profile = _get_profile(ctx)
    task_history = profile.get("task_history", [])

    for task in task_history:
        if task.get("task_id") == task_id:
            return {"ok": True, "task": task}

    return {"ok": False, "error": f"Task '{task_id}' not found"}


async def clear_task_history(
    operation: str,
    params: dict[str, Any],
    user_data: dict[str, Any],
    ctx: Any,
) -> dict[str, Any]:
    """Clear completed and abandoned tasks from the user's task list."""
    if not params.get("confirm"):
        return {"ok": False, "error": "confirm=true is required"}

    profile = _get_profile(ctx)
    task_history = profile.get("task_history", [])
    active = [t for t in task_history if t.get("status") in ("open", "deferred")]
    removed = len(task_history) - len(active)

    # In a real implementation this would persist via the profile writer
    return {
        "ok": True,
        "removed": removed,
        "remaining": len(active),
    }


# ─────────────────────────────────────────────────────────────
# Dispatcher
# ─────────────────────────────────────────────────────────────

_HANDLERS: dict[str, Any] = {
    "list_tasks": list_tasks,
    "view_task_history": view_task_history,
    "clear_task_history": clear_task_history,
}


async def handle_operation(
    operation: str,
    params: dict[str, Any],
    user_data: dict[str, Any],
    ctx: Any,
) -> dict[str, Any] | None:
    """Route an assistant-domain admin operation.

    Returns a result dict if the operation is handled, or ``None``
    if *operation* is not an assistant operation.
    """
    handler = _HANDLERS.get(operation)
    if handler is None:
        return None
    return await handler(operation, params, user_data, ctx)


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────


def _get_profile(ctx: Any) -> dict[str, Any]:
    """Extract the profile dict from the orchestrator context."""
    if hasattr(ctx, "_writer"):
        return ctx._writer._profile
    if hasattr(ctx, "profile"):
        return ctx.profile
    return {}
