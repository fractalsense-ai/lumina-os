"""Ingestion operations: list_ingestions, review_ingestion, approve_interpretation, reject_ingestion."""

from __future__ import annotations

from typing import Any

from lumina.api.admin_context import AdminOperationContext
from lumina.api.routes.ingestion import _get_ingest_service


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

    if operation == "list_ingestions":
        domain_id = str(params.get("domain_id", "")) or None
        status_filter = str(params.get("status", "")) or None
        svc = _get_ingest_service()
        records = svc.list_records(domain_id=domain_id, status=status_filter, limit=20)
        if user_data["role"] == "domain_authority":
            governed = set(user_data.get("governed_modules") or [])
            domain_role_keys = set((user_data.get("domain_roles") or {}).keys())
            da_scope = governed | domain_role_keys
            records = [r for r in records if r.get("domain_id") in da_scope]
        return {"operation": operation, "count": len(records), "records": records}

    if operation == "review_ingestion":
        ingestion_id = str(params.get("ingestion_id", target))
        if not ingestion_id:
            raise ctx.HTTPException(status_code=422, detail="ingestion_id required")
        svc = _get_ingest_service()
        record = svc.get_record(ingestion_id)
        if record is None:
            raise ctx.HTTPException(status_code=404, detail="Ingestion not found")
        return {"operation": operation, "record": record}

    if operation == "approve_interpretation":
        ingestion_id = str(params.get("ingestion_id", target))
        interp_id = str(params.get("interpretation_id", ""))
        if not ingestion_id or not interp_id:
            raise ctx.HTTPException(status_code=422, detail="ingestion_id and interpretation_id required")
        if user_data["role"] not in ("root", "domain_authority"):
            raise ctx.HTTPException(status_code=403, detail="Domain authority required")
        svc = _get_ingest_service()
        try:
            updated = svc.review_interpretation(
                ingestion_id, decision="approve", reviewer_id=user_data["sub"],
                selected_interpretation_id=interp_id,
            )
        except ValueError as exc:
            raise ctx.HTTPException(status_code=400, detail=str(exc))
        return {"operation": operation, "status": updated["status"], "ingestion_id": ingestion_id}

    if operation == "reject_ingestion":
        ingestion_id = str(params.get("ingestion_id", target))
        reason = str(params.get("reason", params.get("rationale", "")))
        if not ingestion_id:
            raise ctx.HTTPException(status_code=422, detail="ingestion_id required")
        if user_data["role"] not in ("root", "domain_authority"):
            raise ctx.HTTPException(status_code=403, detail="Domain authority required")
        svc = _get_ingest_service()
        try:
            updated = svc.review_interpretation(
                ingestion_id, decision="reject", reviewer_id=user_data["sub"],
                review_notes=reason,
            )
        except ValueError as exc:
            raise ctx.HTTPException(status_code=400, detail=str(exc))
        return {"operation": operation, "status": updated["status"], "ingestion_id": ingestion_id}

    return None
