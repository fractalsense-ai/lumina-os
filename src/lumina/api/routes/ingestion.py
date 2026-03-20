"""Ingestion endpoints: upload, extract, review, commit, list."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body, Depends, Form, HTTPException, UploadFile
from fastapi.security import HTTPAuthorizationCredentials
from starlette.concurrency import run_in_threadpool

from lumina.api import config as _cfg
from lumina.api.middleware import _bearer_scheme, get_current_user, require_auth
from lumina.core.domain_registry import DomainNotFoundError
from lumina.system_log.admin_operations import can_govern_domain
from lumina.system_log.commit_guard import requires_log_commit

log = logging.getLogger("lumina-api")

router = APIRouter()

# Lazy singleton — created on first use so config is loaded first.
_INGEST_SERVICE: Any = None


def _get_ingest_service() -> Any:
    global _INGEST_SERVICE
    if _INGEST_SERVICE is None:
        from lumina.ingestion.service import IngestService

        _INGEST_SERVICE = IngestService(
            persistence_append=lambda sid, rec: _cfg.PERSISTENCE.append_log_record(
                sid, rec,
                ledger_path=_cfg.PERSISTENCE.get_log_ledger_path(sid, domain_id="_admin"),
            ),
            max_file_size_mb=10,
        )
    return _INGEST_SERVICE


def _detect_content_type(filename: str) -> str | None:
    """Map filename extension to ingestion content type."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return {
        "pdf": "pdf",
        "docx": "docx",
        "doc": "docx",
        "md": "markdown",
        "markdown": "markdown",
        "txt": "markdown",
        "csv": "csv",
        "json": "json",
        "yaml": "yaml",
        "yml": "yaml",
    }.get(ext)


@router.post("/api/ingest/upload")
async def ingest_upload(
    file: UploadFile,
    domain_id: str = Form(...),
    module_id: str | None = Form(None),
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict[str, Any]:
    current = await get_current_user(credentials)
    user_data = require_auth(current)

    try:
        resolved = _cfg.DOMAIN_REGISTRY.resolve_domain_id(domain_id)
    except DomainNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    runtime = _cfg.DOMAIN_REGISTRY.get_runtime_context(resolved)
    domain_physics = await run_in_threadpool(
        _cfg.PERSISTENCE.load_domain_physics, runtime["domain_physics_path"]
    )
    perms = domain_physics.get("permissions", {})
    perms["guest_access"] = domain_physics.get("guest_access")

    if user_data["role"] != "root":
        from lumina.core.permissions import Operation as PermOp, check_permission
        if not check_permission(user_data["sub"], user_data["role"], perms, PermOp.INGEST):
            raise HTTPException(status_code=403, detail="Ingest permission required")

    filename = file.filename or "unknown"
    content_type = _detect_content_type(filename)
    if content_type is None:
        raise HTTPException(status_code=400, detail=f"Unsupported file format: {filename}")

    file_bytes = await file.read()
    svc = _get_ingest_service()

    try:
        doc_id = svc.accept_document(
            file_bytes=file_bytes,
            filename=filename,
            content_type=content_type,
            actor_id=user_data["sub"],
            domain_id=resolved,
            module_id=module_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {"ingestion_id": doc_id, "status": "pending_extraction", "domain_id": resolved}


@router.get("/api/ingest/{ingestion_id}")
async def get_ingestion(
    ingestion_id: str,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict[str, Any]:
    current = await get_current_user(credentials)
    require_auth(current)

    svc = _get_ingest_service()
    record = svc.get_record(ingestion_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Ingestion not found")
    return record


@router.post("/api/ingest/{ingestion_id}/extract")
async def ingest_extract(
    ingestion_id: str,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict[str, Any]:
    current = await get_current_user(credentials)
    require_auth(current)

    svc = _get_ingest_service()
    record = svc.get_record(ingestion_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Ingestion not found")

    domain_id = record.get("domain_id", "")
    try:
        resolved = _cfg.DOMAIN_REGISTRY.resolve_domain_id(domain_id)
    except DomainNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    runtime = _cfg.DOMAIN_REGISTRY.get_runtime_context(resolved)
    domain_physics = await run_in_threadpool(
        _cfg.PERSISTENCE.load_domain_physics, runtime["domain_physics_path"]
    )

    ingestion_config = domain_physics.get("ingestion_config") or {}
    max_interps = ingestion_config.get("max_interpretations", 3)

    interpretations = await run_in_threadpool(
        svc.extract_interpretations,
        ingestion_id,
        domain_physics,
        domain_physics.get("glossary"),
        None,
        max_interps,
    )

    return {
        "ingestion_id": ingestion_id,
        "status": "extraction_complete",
        "interpretation_count": len(interpretations),
        "interpretations": interpretations,
    }


@router.post("/api/ingest/{ingestion_id}/review")
async def ingest_review(
    ingestion_id: str,
    req: dict[str, Any] = Body(...),
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict[str, Any]:
    current = await get_current_user(credentials)
    user_data = require_auth(current)

    if user_data["role"] not in ("root", "domain_authority"):
        raise HTTPException(status_code=403, detail="Domain authority required")

    svc = _get_ingest_service()
    record = svc.get_record(ingestion_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Ingestion not found")

    if user_data["role"] == "domain_authority":
        if not can_govern_domain(user_data, record.get("domain_id", "")):
            raise HTTPException(status_code=403, detail="Not authorized for this domain")

    decision = req.get("decision", "")
    if decision not in ("approve", "reject", "edit"):
        raise HTTPException(status_code=400, detail="decision must be approve, reject, or edit")

    try:
        updated = svc.review_interpretation(
            ingestion_id=ingestion_id,
            decision=decision,
            reviewer_id=user_data["sub"],
            selected_interpretation_id=req.get("selected_interpretation_id"),
            edits=req.get("edits"),
            review_notes=req.get("review_notes"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return updated


@router.post("/api/ingest/{ingestion_id}/commit")
@requires_log_commit
async def ingest_commit(
    ingestion_id: str,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict[str, Any]:
    current = await get_current_user(credentials)
    user_data = require_auth(current)

    if user_data["role"] not in ("root", "domain_authority"):
        raise HTTPException(status_code=403, detail="Domain authority required")

    svc = _get_ingest_service()
    record = svc.get_record(ingestion_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Ingestion not found")

    if user_data["role"] == "domain_authority":
        if not can_govern_domain(user_data, record.get("domain_id", "")):
            raise HTTPException(status_code=403, detail="Not authorized for this domain")

    try:
        result = svc.commit_ingestion(ingestion_id, user_data["sub"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return result


@router.get("/api/ingest")
async def list_ingestions(
    domain_id: str | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> list[dict[str, Any]]:
    current = await get_current_user(credentials)
    user_data = require_auth(current)

    svc = _get_ingest_service()
    records = svc.list_records(domain_id=domain_id, status=status, limit=limit, offset=offset)

    if user_data["role"] == "domain_authority":
        governed = user_data.get("governed_modules") or []
        records = [r for r in records if r.get("domain_id") in governed]

    return records
