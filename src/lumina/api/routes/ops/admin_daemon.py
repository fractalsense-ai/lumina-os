"""Daemon operations: trigger_daemon_task, daemon_status, review_proposals,
resolve_proposal, daemon_report."""

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
        "trigger_daemon_task",
        "daemon_status", "review_proposals",
        "resolve_proposal", "daemon_report",
    ):
        return None

    parsed = parsed or {}
    target = parsed.get("target", "")

    assert get_daemon_scheduler is not None
    scheduler = get_daemon_scheduler()

    if operation == "trigger_daemon_task":
        if user_data["role"] not in ("root", "domain_authority"):
            raise ctx.HTTPException(status_code=403, detail="Insufficient permissions")
        task_names = params.get("tasks")
        domain_ids = params.get("domain_ids")
        run_id = scheduler.trigger_async(
            actor_id=user_data["sub"],
            task_names=task_names,
            domain_ids=domain_ids,
        )
        return {"operation": "trigger_daemon_task", "run_id": run_id, "status": "started"}

    if operation == "daemon_status":
        result = scheduler.get_status()
        result["operation"] = "daemon_status"
        return result

    if operation == "review_proposals":
        resolved_id = str(params.get("domain_id", target))
        proposals = scheduler.get_pending_proposals(domain_id=resolved_id)
        return {"operation": operation, "proposals": proposals, "count": len(proposals)}

    if operation == "resolve_proposal":
        if user_data["role"] not in ("root", "domain_authority"):
            raise ctx.HTTPException(status_code=403, detail="Insufficient permissions")
        proposal_id = params.get("proposal_id") or target
        action = params.get("action")
        if action not in ("approved", "rejected"):
            raise ctx.HTTPException(status_code=400, detail="action must be 'approved' or 'rejected'")
        domain_id = params.get("domain_id")
        found = scheduler.resolve_proposal(proposal_id, action, domain_id=domain_id)
        if not found:
            raise ctx.HTTPException(status_code=404, detail="Proposal not found")
        return {"operation": "resolve_proposal", "proposal_id": proposal_id, "status": action}

    if operation == "daemon_report":
        if user_data["role"] not in ("root", "domain_authority"):
            raise ctx.HTTPException(status_code=403, detail="Insufficient permissions")
        run_id = params.get("run_id") or target
        report = scheduler.get_report(run_id)
        if report is None:
            raise ctx.HTTPException(status_code=404, detail="Report not found")
        report["operation"] = "daemon_report"
        return report

    return None
