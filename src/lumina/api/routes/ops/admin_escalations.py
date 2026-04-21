"""Escalation operations: resolve_escalation, list_escalations, explain_reasoning."""

from __future__ import annotations

from typing import Any

from lumina.api.admin_context import AdminOperationContext
from lumina.core.domain_registry import DomainNotFoundError


async def execute(
    operation: str,
    params: dict[str, Any],
    user_data: dict[str, Any],
    ctx: AdminOperationContext,
    *,
    parsed: dict[str, Any] | None = None,
    **kw: Any,
) -> dict[str, Any] | None:
    parsed = parsed or {}
    target = parsed.get("target", "")

    if operation == "resolve_escalation":
        esc_id = str(params.get("escalation_id", target))
        resolution = str(params.get("resolution", ""))
        rationale = str(params.get("rationale", ""))
        if not esc_id or resolution not in ("approved", "rejected", "deferred"):
            raise ctx.HTTPException(status_code=422, detail="escalation_id and valid resolution required")
        return {"operation": operation, "escalation_id": esc_id, "resolution": resolution, "rationale": rationale}

    if operation == "list_escalations":
        domain_id = str(params.get("domain_id", "")) or None
        # DA boundary check: must govern the requested domain
        if domain_id and user_data["role"] == "admin":
            try:
                _resolved_esc = ctx.domain_registry.resolve_domain_id(domain_id)
            except DomainNotFoundError as exc:
                raise ctx.HTTPException(status_code=400, detail=str(exc))
            if not ctx.can_govern_domain(user_data, _resolved_esc, registry=ctx.domain_registry):
                raise ctx.HTTPException(status_code=403, detail="Not authorized for this domain")
        escalations = await ctx.run_in_threadpool(
            ctx.persistence.query_escalations, domain_id=domain_id, status="pending",
        )
        if user_data["role"] == "admin":
            governed = user_data.get("governed_modules") or []
            escalations = [e for e in escalations if e.get("domain_pack_id") in governed]
        return {"operation": operation, "count": len(escalations), "escalations": escalations}

    if operation == "explain_reasoning":
        event_id = str(params.get("event_id", target))
        if not event_id:
            raise ctx.HTTPException(status_code=422, detail="event_id required")
        records = await ctx.run_in_threadpool(ctx.persistence.query_log_records)
        target_rec = [r for r in records if r.get("record_id") == event_id]
        if not target_rec:
            raise ctx.HTTPException(status_code=404, detail="System Log record not found")
        return {"operation": operation, "record": target_rec[0]}

    return None
