"""Daemon operations: trigger_daemon_task, trigger_night_cycle, daemon_status,
night_cycle_status, review_proposals."""

from __future__ import annotations

from typing import Any, Callable

from lumina.api.admin_context import AdminOperationContext


async def execute(
    operation: str,
    params: dict[str, Any],
    user_data: dict[str, Any],
    ctx: AdminOperationContext,
    *,
    parsed: dict[str, Any] | None = None,
    get_daemon_scheduler: Callable[[], Any] | None = None,
    **kw: Any,
) -> dict[str, Any] | None:
    if operation not in (
        "trigger_daemon_task", "trigger_night_cycle",
        "daemon_status", "night_cycle_status", "review_proposals",
    ):
        return None

    parsed = parsed or {}
    target = parsed.get("target", "")

    assert get_daemon_scheduler is not None
    scheduler = get_daemon_scheduler()

    if operation in ("trigger_daemon_task", "trigger_night_cycle"):
        if user_data["role"] not in ("root", "domain_authority"):
            raise ctx.HTTPException(status_code=403, detail="Insufficient permissions")
        run_id = scheduler.trigger_async(actor_id=user_data["sub"])
        return {"operation": "trigger_daemon_task", "run_id": run_id, "status": "started"}

    if operation in ("daemon_status", "night_cycle_status"):
        result = scheduler.get_status()
        result["operation"] = "daemon_status"
        return result

    # review_proposals
    resolved_id = str(params.get("domain_id", target))
    proposals = scheduler.get_pending_proposals(domain_id=resolved_id)
    return {"operation": operation, "proposals": proposals, "count": len(proposals)}
