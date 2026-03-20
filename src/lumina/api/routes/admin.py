"""Admin endpoints: escalations, audit log, manifest, HITL admin command staging."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from starlette.concurrency import run_in_threadpool

from lumina.api import config as _cfg
from lumina.api.middleware import _bearer_scheme, get_current_user, require_auth, require_role
from lumina.api.session import _session_containers
from lumina.core.session_unlock import generate_unlock_pin, validate_unlock_pin
from lumina.api.models import (
    AdminCommandRequest,
    CommandResolveRequest,
    EscalationResolveRequest,
    ManifestCheckResponse,
    ManifestRegenResponse,
    SessionUnlockRequest,
)
from lumina.api.routes.ingestion import _get_ingest_service
from lumina.api.routes.nightcycle import _get_night_scheduler
from lumina.auth.auth import VALID_ROLES
from lumina.core.domain_registry import DomainNotFoundError
from lumina.core import slm as _slm_mod
from lumina.core.email_sender import send_invite_email
from lumina.core.invite_store import generate_invite_token
from lumina.system_log.admin_operations import (
    _canonical_sha256 as admin_canonical_sha256,
    build_commitment_record,
    build_domain_role_assignment,
    build_domain_role_revocation,
    build_trace_event,
    can_govern_domain,
    map_role_to_actor_role,
)
from lumina.middleware.command_schema_registry import validate_command
from lumina.systools.manifest_integrity import check_manifest_report, regen_manifest_report
from lumina.system_log.commit_guard import requires_log_commit

log = logging.getLogger("lumina-api")

router = APIRouter()


# ─────────────────────────────────────────────────────────────
# Escalation management
# ─────────────────────────────────────────────────────────────


@router.get("/api/escalations")
async def list_escalations(
    status: str | None = None,
    domain_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> list[dict[str, Any]]:
    current = await get_current_user(credentials)
    user_data = require_auth(current)

    allowed_roles = ("root", "it_support", "qa", "auditor")
    if user_data["role"] not in allowed_roles:
        if user_data["role"] == "domain_authority":
            pass
        else:
            raise HTTPException(status_code=403, detail="Insufficient permissions")

    records = await run_in_threadpool(
        _cfg.PERSISTENCE.query_escalations,
        status=status, domain_id=domain_id, limit=limit, offset=offset,
    )

    if user_data["role"] == "domain_authority":
        governed = user_data.get("governed_modules") or []
        records = [r for r in records if r.get("domain_pack_id") in governed]

    return records


@router.post("/api/escalations/{escalation_id}/resolve")
@requires_log_commit
async def resolve_escalation(
    escalation_id: str,
    req: EscalationResolveRequest,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict[str, Any]:
    current = await get_current_user(credentials)
    user_data = require_auth(current)

    if req.decision not in ("approve", "reject", "defer"):
        raise HTTPException(status_code=400, detail="decision must be approve, reject, or defer")

    if user_data["role"] not in ("root", "domain_authority"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    all_escalations = await run_in_threadpool(_cfg.PERSISTENCE.query_escalations)
    target = None
    for esc in all_escalations:
        if esc.get("record_id") == escalation_id:
            target = esc
            break

    if target is None:
        raise HTTPException(status_code=404, detail="Escalation not found")

    if user_data["role"] == "domain_authority":
        domain = target.get("domain_pack_id", "")
        if not can_govern_domain(user_data, domain):
            raise HTTPException(status_code=403, detail="Not authorized for this domain")

    record = build_commitment_record(
        actor_id=user_data["sub"],
        actor_role=map_role_to_actor_role(user_data["role"]),
        commitment_type="escalation_resolution",
        subject_id=escalation_id,
        summary=f"Escalation {req.decision}: {req.reasoning[:200]}",
        metadata={
            "decision": req.decision,
            "reasoning": req.reasoning,
            "original_trigger": target.get("trigger", ""),
        },
        references=[escalation_id],
    )

    session_id = target.get("session_id", "admin")
    _cfg.PERSISTENCE.append_log_record(
        session_id, record,
        ledger_path=_cfg.PERSISTENCE.get_log_ledger_path(session_id, domain_id="_admin"),
    )

    # ── PIN generation ── freeze session so student must unlock with OTP ──
    response_extra: dict[str, Any] = {}
    if req.generate_pin:
        pin = generate_unlock_pin(session_id, escalation_id)
        response_extra["unlock_pin"] = pin
        container = _session_containers.get(session_id)
        if container is not None:
            container.frozen = True
        log.info("[%s] Session frozen; unlock PIN issued for escalation %s", session_id, escalation_id)

    # ── Intervention notes ── append to student profile if present ────────
    if req.intervention_notes:
        actor_id = target.get("actor_id", "")
        if actor_id:
            profile_path: str | None = None
            container = _session_containers.get(session_id)
            if container is not None:
                try:
                    profile_path = container.active_context.subject_profile_path
                except (KeyError, AttributeError):
                    pass
            if profile_path:
                try:
                    profile = await run_in_threadpool(
                        _cfg.PERSISTENCE.load_subject_profile, profile_path
                    )
                    if isinstance(profile, dict):
                        history = list(profile.get("intervention_history") or [])
                        history.append({
                            "escalation_id": escalation_id,
                            "teacher_id": user_data["sub"],
                            "notes": req.intervention_notes,
                            "recorded_utc": datetime.now(timezone.utc).isoformat(),
                            "generated_proposal": bool(req.generate_proposal),
                        })
                        profile["intervention_history"] = history
                        await run_in_threadpool(
                            _cfg.PERSISTENCE.save_subject_profile, profile_path, profile
                        )
                except Exception:
                    log.debug("Could not update student profile with intervention notes", exc_info=True)

    return {
        "record_id": record["record_id"],
        "escalation_id": escalation_id,
        "decision": req.decision,
        **response_extra,
    }


# ─────────────────────────────────────────────────────────────
# Audit log
# ─────────────────────────────────────────────────────────────


@router.get("/api/audit/log")
async def audit_log(
    session_id: str | None = None,
    domain_id: str | None = None,
    format: str = "json",
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict[str, Any]:
    current = await get_current_user(credentials)
    user_data = require_auth(current)

    allowed_roles = ("root", "qa", "auditor")
    if user_data["role"] not in allowed_roles:
        if user_data["role"] == "domain_authority":
            # DA may only view records for domains they govern
            governed = user_data.get("governed_modules") or []
            if not governed:
                raise HTTPException(status_code=403, detail="No governed modules")
        elif user_data["role"] == "user":
            # Regular users may only view their own records
            pass
        else:
            raise HTTPException(status_code=403, detail="Insufficient permissions")

    records = await run_in_threadpool(
        _cfg.PERSISTENCE.query_log_records, session_id=session_id, domain_id=domain_id,
    )

    # Scope records based on caller role
    if user_data["role"] == "domain_authority":
        governed = user_data.get("governed_modules") or []
        records = [
            r for r in records
            if r.get("actor_id") == user_data["sub"]
            or r.get("domain_id") in governed
            or r.get("to_domain") in governed
        ]
    elif user_data["role"] == "user":
        records = [r for r in records if r.get("actor_id") == user_data["sub"]]

    audit_event = build_trace_event(
        session_id="admin",
        actor_id=user_data["sub"],
        event_type="audit_requested",
        decision=f"Audit log requested: session={session_id}, domain={domain_id}",
    )
    try:
        _cfg.PERSISTENCE.append_log_record(
            "admin", audit_event,
            ledger_path=_cfg.PERSISTENCE.get_log_ledger_path("admin", domain_id="_admin"),
        )
    except Exception:
        log.debug("Could not write audit_requested trace event")

    record_types: dict[str, int] = {}
    for r in records:
        rt = r.get("record_type", "unknown")
        record_types[rt] = record_types.get(rt, 0) + 1

    return {
        "total_records": len(records),
        "record_type_counts": record_types,
        "filters": {"session_id": session_id, "domain_id": domain_id},
        "records": records if format == "json" else [],
        "generated_by": user_data["sub"],
    }


# ─────────────────────────────────────────────────────────────
# Manifest integrity
# ─────────────────────────────────────────────────────────────


@router.get("/api/manifest/check", response_model=ManifestCheckResponse)
async def manifest_check(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> ManifestCheckResponse:
    current = await get_current_user(credentials)
    user_data = require_auth(current)
    require_role(user_data, "root", "domain_authority", "qa", "auditor")
    try:
        report = await run_in_threadpool(check_manifest_report, _cfg._REPO_ROOT)
    except Exception as exc:
        log.exception("Manifest integrity check failed")
        raise HTTPException(status_code=500, detail=str(exc))
    return ManifestCheckResponse(**report)


@router.post("/api/manifest/regen", response_model=ManifestRegenResponse)
@requires_log_commit
async def manifest_regen(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> ManifestRegenResponse:
    current = await get_current_user(credentials)
    user_data = require_auth(current)
    require_role(user_data, "root", "domain_authority")
    try:
        report = await run_in_threadpool(regen_manifest_report, _cfg._REPO_ROOT)
    except Exception as exc:
        log.exception("Manifest regen failed")
        raise HTTPException(status_code=500, detail=str(exc))

    event = build_trace_event(
        session_id="admin",
        actor_id=user_data["sub"],
        event_type="other",
        decision=f"manifest_regen: updated {report['updated_count']} artifact(s)",
        evidence_summary={
            "updated_count": report["updated_count"],
            "missing_paths": report["missing_paths"],
            "actor_role": user_data["role"],
        },
    )
    try:
        _cfg.PERSISTENCE.append_log_record(
            "admin", event,
            ledger_path=_cfg.PERSISTENCE.get_log_ledger_path("admin", domain_id="_admin"),
        )
    except Exception:
        log.debug("Could not write manifest_regen trace event")

    return ManifestRegenResponse(**report)


# ─────────────────────────────────────────────────────────────
# HITL Admin Command Staging
# ─────────────────────────────────────────────────────────────

_KNOWN_OPERATIONS: frozenset[str] = frozenset({
    "update_domain_physics",
    "commit_domain_physics",
    "update_user_role",
    "deactivate_user",
    "assign_domain_role",
    "revoke_domain_role",
    "resolve_escalation",
    "list_ingestions",
    "review_ingestion",
    "approve_interpretation",
    "reject_ingestion",
    "list_escalations",
    "explain_reasoning",
    "module_status",
    "trigger_night_cycle",
    "night_cycle_status",
    "review_proposals",
})

# Staged commands awaiting human resolution (keyed by staged_id).
_STAGED_COMMANDS: dict[str, dict[str, Any]] = {}
_STAGED_COMMANDS_LOCK = threading.Lock()
_STAGED_CMD_TTL_SECONDS: int = int(os.environ.get("LUMINA_STAGED_CMD_TTL_SECONDS", "300"))

_HITL_VALID_ACTIONS: frozenset[str] = frozenset({"accept", "reject", "modify"})


def _purge_expired_staged_commands() -> None:
    now = time.time()
    with _STAGED_COMMANDS_LOCK:
        expired = [sid for sid, entry in _STAGED_COMMANDS.items() if entry["expires_at"] < now]
        for sid in expired:
            del _STAGED_COMMANDS[sid]


def _compute_schema_delta(original: dict[str, Any], modified: dict[str, Any]) -> dict[str, Any]:
    delta: dict[str, Any] = {}
    all_keys = set(original) | set(modified)
    for key in all_keys:
        orig_val = original.get(key)
        mod_val = modified.get(key)
        if orig_val != mod_val:
            delta[key] = {"from": orig_val, "to": mod_val}
    return delta


async def _execute_admin_operation(
    user_data: dict[str, Any],
    parsed: dict[str, Any],
    original_instruction: str,
) -> dict[str, Any]:
    operation = parsed["operation"]
    params = parsed.get("params") or {}
    result: dict[str, Any]

    if operation == "update_domain_physics":
        domain_id = str(params.get("domain_id", parsed.get("target", "")))
        updates = params.get("updates") or {}
        if not domain_id or not updates:
            raise HTTPException(status_code=422, detail="domain_id and updates required")
        if user_data["role"] == "domain_authority" and not can_govern_domain(user_data, domain_id):
            raise HTTPException(status_code=403, detail="Not authorized for this domain")
        try:
            resolved = _cfg.DOMAIN_REGISTRY.resolve_domain_id(domain_id)
        except DomainNotFoundError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        runtime = _cfg.DOMAIN_REGISTRY.get_runtime_context(resolved)
        domain_physics_path = Path(runtime["domain_physics_path"])
        domain = await run_in_threadpool(_cfg.PERSISTENCE.load_domain_physics, str(domain_physics_path))
        for k, v in updates.items():
            domain[k] = v

        def _write() -> None:
            tmp = domain_physics_path.with_suffix(".json.tmp")
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(domain, fh, indent=2, ensure_ascii=False)
            tmp.replace(domain_physics_path)

        await run_in_threadpool(_write)
        subject_hash = admin_canonical_sha256(domain)
        record = build_commitment_record(
            actor_id=user_data["sub"],
            actor_role=map_role_to_actor_role(user_data["role"]),
            commitment_type="domain_pack_activation",
            subject_id=str(domain.get("id", resolved)),
            summary=f"SLM command: {original_instruction}",
            subject_version=str(domain.get("version", "")),
            subject_hash=subject_hash,
            metadata={"slm_command_translation": True, "updated_fields": list(updates.keys())},
        )
        _cfg.PERSISTENCE.append_log_record(
            "admin", record,
            ledger_path=_cfg.PERSISTENCE.get_log_ledger_path("admin", domain_id=resolved),
        )
        result = {"operation": operation, "subject_hash": subject_hash, "record_id": record["record_id"]}

    elif operation == "commit_domain_physics":
        domain_id = str(params.get("domain_id", parsed.get("target", "")))
        if not domain_id:
            raise HTTPException(status_code=422, detail="domain_id required")
        if user_data["role"] == "domain_authority" and not can_govern_domain(user_data, domain_id):
            raise HTTPException(status_code=403, detail="Not authorized for this domain")
        try:
            resolved = _cfg.DOMAIN_REGISTRY.resolve_domain_id(domain_id)
        except DomainNotFoundError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        runtime = _cfg.DOMAIN_REGISTRY.get_runtime_context(resolved)
        domain_physics_path = Path(runtime["domain_physics_path"])
        domain = await run_in_threadpool(_cfg.PERSISTENCE.load_domain_physics, str(domain_physics_path))
        subject_hash = admin_canonical_sha256(domain)
        record = build_commitment_record(
            actor_id=user_data["sub"],
            actor_role=map_role_to_actor_role(user_data["role"]),
            commitment_type="domain_pack_activation",
            subject_id=str(domain.get("id", resolved)),
            summary=f"SLM command: {original_instruction}",
            subject_version=str(domain.get("version", "")),
            subject_hash=subject_hash,
            metadata={"slm_command_translation": True},
        )
        _cfg.PERSISTENCE.append_log_record(
            "admin", record,
            ledger_path=_cfg.PERSISTENCE.get_log_ledger_path("admin", domain_id=resolved),
        )
        result = {"operation": operation, "subject_hash": subject_hash, "record_id": record["record_id"]}

    elif operation == "update_user_role":
        if user_data["role"] != "root":
            raise HTTPException(status_code=403, detail="Only root can update user roles")
        target_user_id = str(params.get("user_id", parsed.get("target", "")))
        new_role = str(params.get("new_role", ""))
        if not target_user_id or new_role not in VALID_ROLES:
            raise HTTPException(status_code=422, detail="user_id and valid new_role required")
        await run_in_threadpool(_cfg.PERSISTENCE.update_user_role, target_user_id, new_role)
        result = {"operation": operation, "user_id": target_user_id, "new_role": new_role}

    elif operation == "deactivate_user":
        if user_data["role"] != "root":
            raise HTTPException(status_code=403, detail="Only root can deactivate users")
        target_user_id = str(params.get("user_id", parsed.get("target", "")))
        if not target_user_id:
            raise HTTPException(status_code=422, detail="user_id required")
        if target_user_id == user_data["sub"]:
            raise HTTPException(status_code=400, detail="Cannot deactivate yourself")
        await run_in_threadpool(_cfg.PERSISTENCE.deactivate_user, target_user_id)
        result = {"operation": operation, "user_id": target_user_id}

    elif operation == "assign_domain_role":
        if user_data["role"] not in ("root", "domain_authority"):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        target_user_id = str(params.get("user_id", parsed.get("target", "")))
        module_id = str(params.get("module_id", ""))
        domain_role = str(params.get("domain_role", ""))
        if not target_user_id or not module_id or not domain_role:
            raise HTTPException(status_code=422, detail="user_id, module_id, and domain_role required")
        if user_data["role"] == "domain_authority" and not can_govern_domain(user_data, module_id):
            raise HTTPException(status_code=403, detail="Not authorized for this domain")
        target = await run_in_threadpool(_cfg.PERSISTENCE.get_user, target_user_id)
        if target is None:
            raise HTTPException(status_code=404, detail="User not found")
        await run_in_threadpool(
            _cfg.PERSISTENCE.update_user_domain_roles, target_user_id, {module_id: domain_role}
        )
        record = build_domain_role_assignment(
            actor_id=user_data["sub"],
            actor_role=map_role_to_actor_role(user_data["role"]),
            target_user_id=target_user_id,
            module_id=module_id,
            domain_role=domain_role,
        )
        _cfg.PERSISTENCE.append_log_record(
            "admin", record,
            ledger_path=_cfg.PERSISTENCE.get_log_ledger_path("admin", domain_id="_admin"),
        )
        result = {
            "operation": operation,
            "user_id": target_user_id,
            "module_id": module_id,
            "domain_role": domain_role,
            "record_id": record["record_id"],
        }

    elif operation == "revoke_domain_role":
        if user_data["role"] not in ("root", "domain_authority"):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        target_user_id = str(params.get("user_id", parsed.get("target", "")))
        module_id = str(params.get("module_id", ""))
        if not target_user_id or not module_id:
            raise HTTPException(status_code=422, detail="user_id and module_id required")
        if user_data["role"] == "domain_authority" and not can_govern_domain(user_data, module_id):
            raise HTTPException(status_code=403, detail="Not authorized for this domain")
        target = await run_in_threadpool(_cfg.PERSISTENCE.get_user, target_user_id)
        if target is None:
            raise HTTPException(status_code=404, detail="User not found")
        prev_role = (target.get("domain_roles") or {}).get(module_id, "")
        # Revoke by removing the key (set empty string signals removal; persistence merges)
        await run_in_threadpool(
            _cfg.PERSISTENCE.update_user_domain_roles, target_user_id, {module_id: ""}
        )
        record = build_domain_role_revocation(
            actor_id=user_data["sub"],
            actor_role=map_role_to_actor_role(user_data["role"]),
            target_user_id=target_user_id,
            module_id=module_id,
            prev_role=prev_role or "unknown",
        )
        _cfg.PERSISTENCE.append_log_record(
            "admin", record,
            ledger_path=_cfg.PERSISTENCE.get_log_ledger_path("admin", domain_id="_admin"),
        )
        result = {
            "operation": operation,
            "user_id": target_user_id,
            "module_id": module_id,
            "prev_role": prev_role,
            "record_id": record["record_id"],
        }

    elif operation == "resolve_escalation":
        esc_id = str(params.get("escalation_id", parsed.get("target", "")))
        resolution = str(params.get("resolution", ""))
        rationale = str(params.get("rationale", ""))
        if not esc_id or resolution not in ("approved", "rejected", "deferred"):
            raise HTTPException(status_code=422, detail="escalation_id and valid resolution required")
        result = {"operation": operation, "escalation_id": esc_id, "resolution": resolution, "rationale": rationale}

    elif operation == "list_ingestions":
        domain_id = str(params.get("domain_id", "")) or None
        status_filter = str(params.get("status", "")) or None
        svc = _get_ingest_service()
        records = svc.list_records(domain_id=domain_id, status=status_filter, limit=20)
        if user_data["role"] == "domain_authority":
            governed = user_data.get("governed_modules") or []
            records = [r for r in records if r.get("domain_id") in governed]
        result = {"operation": operation, "count": len(records), "records": records}

    elif operation == "review_ingestion":
        ingestion_id = str(params.get("ingestion_id", parsed.get("target", "")))
        if not ingestion_id:
            raise HTTPException(status_code=422, detail="ingestion_id required")
        svc = _get_ingest_service()
        record = svc.get_record(ingestion_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Ingestion not found")
        result = {"operation": operation, "record": record}

    elif operation == "approve_interpretation":
        ingestion_id = str(params.get("ingestion_id", parsed.get("target", "")))
        interp_id = str(params.get("interpretation_id", ""))
        if not ingestion_id or not interp_id:
            raise HTTPException(status_code=422, detail="ingestion_id and interpretation_id required")
        if user_data["role"] not in ("root", "domain_authority"):
            raise HTTPException(status_code=403, detail="Domain authority required")
        svc = _get_ingest_service()
        try:
            updated = svc.review_interpretation(
                ingestion_id, decision="approve", reviewer_id=user_data["sub"],
                selected_interpretation_id=interp_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        result = {"operation": operation, "status": updated["status"], "ingestion_id": ingestion_id}

    elif operation == "reject_ingestion":
        ingestion_id = str(params.get("ingestion_id", parsed.get("target", "")))
        reason = str(params.get("reason", params.get("rationale", "")))
        if not ingestion_id:
            raise HTTPException(status_code=422, detail="ingestion_id required")
        if user_data["role"] not in ("root", "domain_authority"):
            raise HTTPException(status_code=403, detail="Domain authority required")
        svc = _get_ingest_service()
        try:
            updated = svc.review_interpretation(
                ingestion_id, decision="reject", reviewer_id=user_data["sub"],
                review_notes=reason,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        result = {"operation": operation, "status": updated["status"], "ingestion_id": ingestion_id}

    elif operation == "list_escalations":
        domain_id = str(params.get("domain_id", "")) or None
        escalations = await run_in_threadpool(
            _cfg.PERSISTENCE.query_escalations, domain_id=domain_id, status="pending",
        )
        if user_data["role"] == "domain_authority":
            governed = user_data.get("governed_modules") or []
            escalations = [e for e in escalations if e.get("domain_pack_id") in governed]
        result = {"operation": operation, "count": len(escalations), "escalations": escalations}

    elif operation == "explain_reasoning":
        event_id = str(params.get("event_id", parsed.get("target", "")))
        if not event_id:
            raise HTTPException(status_code=422, detail="event_id required")
        records = await run_in_threadpool(_cfg.PERSISTENCE.query_log_records)
        target = [r for r in records if r.get("record_id") == event_id]
        if not target:
            raise HTTPException(status_code=404, detail="System Log record not found")
        result = {"operation": operation, "record": target[0]}

    elif operation == "module_status":
        domain_id = str(params.get("domain_id", parsed.get("target", "")))
        if not domain_id:
            raise HTTPException(status_code=422, detail="domain_id required")
        try:
            resolved = _cfg.DOMAIN_REGISTRY.resolve_domain_id(domain_id)
        except DomainNotFoundError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        runtime = _cfg.DOMAIN_REGISTRY.get_runtime_context(resolved)
        domain = await run_in_threadpool(
            _cfg.PERSISTENCE.load_domain_physics, runtime["domain_physics_path"]
        )
        result = {
            "operation": operation,
            "domain_id": resolved,
            "version": domain.get("version"),
            "modules": [m.get("module_id") for m in (domain.get("modules") or [])],
        }

    elif operation in ("trigger_night_cycle", "night_cycle_status", "review_proposals"):
        scheduler = _get_night_scheduler()
        if operation == "trigger_night_cycle":
            if user_data["role"] not in ("root", "domain_authority"):
                raise HTTPException(status_code=403, detail="Insufficient permissions")
            run_id = scheduler.trigger_async(actor_id=user_data["sub"])
            result = {"operation": operation, "run_id": run_id, "status": "started"}
        elif operation == "night_cycle_status":
            result = scheduler.get_status()
            result["operation"] = operation
        else:
            resolved_id = str(params.get("domain_id", parsed.get("target", "")))
            proposals = scheduler.get_pending_proposals(domain_id=resolved_id)
            result = {"operation": operation, "proposals": proposals, "count": len(proposals)}

    elif operation == "invite_user":
        if user_data["role"] not in ("root", "it_support"):
            raise HTTPException(status_code=403, detail="Only root or it_support can invite users")
        username = str(params.get("username", parsed.get("target", "")))
        role = str(params.get("role", "user"))
        governed_modules_raw = params.get("governed_modules", [])
        governed_modules: list[str] = list(governed_modules_raw) if governed_modules_raw else []
        email = str(params.get("email", "")) or None

        if not username:
            raise HTTPException(status_code=422, detail="username required")
        if role not in VALID_ROLES:
            raise HTTPException(status_code=400, detail=f"Invalid role: {role}")
        if role == "domain_authority" and not governed_modules:
            raise HTTPException(
                status_code=400,
                detail="governed_modules is required when role is domain_authority",
            )

        existing = await run_in_threadpool(_cfg.PERSISTENCE.get_user_by_username, username)
        if existing is not None:
            raise HTTPException(status_code=409, detail="Username already taken")

        import uuid as _uuid_mod
        new_user_id = str(_uuid_mod.uuid4())
        await run_in_threadpool(
            _cfg.PERSISTENCE.create_user,
            new_user_id, username, "", role, governed_modules or None, False,
        )

        invite_token = generate_invite_token(new_user_id, username)
        base_url = os.environ.get("LUMINA_BASE_URL", "").rstrip("/")
        setup_url = f"{base_url}/api/auth/setup-password?token={invite_token}"

        email_sent = False
        if email:
            sent, _err = await run_in_threadpool(send_invite_email, email, username, setup_url)
            email_sent = sent

        invite_event = build_trace_event(
            session_id="admin",
            actor_id=user_data["sub"],
            event_type="other",
            decision="user_invited",
            evidence_summary={
                "invited_user_id": new_user_id,
                "invited_username": username,
                "invited_role": role,
                "governed_modules": governed_modules,
                "email_sent": email_sent,
                "via": "hitl_command",
            },
        )
        try:
            _cfg.PERSISTENCE.append_log_record(
                "admin", invite_event,
                ledger_path=_cfg.PERSISTENCE.get_log_ledger_path("admin", domain_id="_admin"),
            )
        except Exception:
            log.debug("Could not write user_invited trace event")

        result = {
            "operation": operation,
            "user_id": new_user_id,
            "username": username,
            "role": role,
            "governed_modules": governed_modules,
            "setup_url": setup_url,
            "email_sent": email_sent,
        }

    else:
        raise HTTPException(status_code=422, detail=f"Unknown operation: {operation}")

    return result


@router.get("/api/admin/command/staged")
async def list_staged_commands(
    limit: int = 20,
    offset: int = 0,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict[str, Any]:
    """List pending staged commands awaiting human resolution."""
    _purge_expired_staged_commands()

    current = await get_current_user(credentials)
    user_data = require_auth(current)

    if user_data["role"] not in ("root", "domain_authority", "it_support"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    with _STAGED_COMMANDS_LOCK:
        all_entries = list(_STAGED_COMMANDS.values())

    # Non-root users only see their own staged commands
    if user_data["role"] != "root":
        all_entries = [e for e in all_entries if e.get("actor_id") == user_data["sub"]]

    all_entries.sort(key=lambda e: e.get("staged_at", 0))
    page = all_entries[offset : offset + limit]

    return {
        "total": len(all_entries),
        "limit": limit,
        "offset": offset,
        "staged_commands": [
            {
                "staged_id": e["staged_id"],
                "operation": e["parsed_command"].get("operation"),
                "original_instruction": e["original_instruction"],
                "actor_id": e["actor_id"],
                "staged_at": e["staged_at"],
                "expires_at": e["expires_at"],
                "resolved": e["resolved"],
            }
            for e in page
        ],
    }


@router.post("/api/admin/command")
@requires_log_commit
async def admin_command(
    req: AdminCommandRequest,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict[str, Any]:
    _purge_expired_staged_commands()

    current = await get_current_user(credentials)
    user_data = require_auth(current)

    if user_data["role"] not in ("root", "domain_authority", "it_support"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    if not _slm_mod.slm_available():
        raise HTTPException(status_code=503, detail="SLM service unavailable")

    parsed = _slm_mod.slm_parse_admin_command(req.instruction)
    if parsed is None:
        raise HTTPException(status_code=422, detail="Could not interpret command")

    operation = parsed.get("operation", "")
    if operation not in _KNOWN_OPERATIONS:
        raise HTTPException(status_code=422, detail=f"Unknown operation: {operation}")

    # Default Deny: validate parsed params against registered command schema
    cmd_approved, cmd_violations = validate_command(
        operation, parsed.get("params", {}), parsed.get("target", ""),
    )
    if not cmd_approved:
        raise HTTPException(
            status_code=422,
            detail=f"Command schema validation failed: {'; '.join(cmd_violations)}",
        )

    staged_id = str(uuid.uuid4())
    expires_at = time.time() + _STAGED_CMD_TTL_SECONDS

    stage_record = build_commitment_record(
        actor_id=user_data["sub"],
        actor_role=map_role_to_actor_role(user_data["role"]),
        commitment_type="hitl_command_staged",
        subject_id=staged_id,
        summary=f"HITL staged: {req.instruction[:200]}",
        subject_version=None,
        subject_hash=None,
        metadata={
            "staged_id": staged_id,
            "parsed_command": parsed,
            "original_instruction": req.instruction,
        },
    )
    _cfg.PERSISTENCE.append_log_record(
        "admin", stage_record,
        ledger_path=_cfg.PERSISTENCE.get_log_ledger_path("admin"),
    )

    entry: dict[str, Any] = {
        "staged_id": staged_id,
        "actor_id": user_data["sub"],
        "actor_role": user_data["role"],
        "parsed_command": parsed,
        "original_instruction": req.instruction,
        "staged_at": time.time(),
        "expires_at": expires_at,
        "log_stage_record_id": stage_record["record_id"],
        "resolved": False,
    }
    with _STAGED_COMMANDS_LOCK:
        _STAGED_COMMANDS[staged_id] = entry

    return {
        "staged_id": staged_id,
        "staged_command": parsed,
        "original_instruction": req.instruction,
        "expires_at": expires_at,
        "log_stage_record_id": stage_record["record_id"],
    }


@router.post("/api/admin/command/{staged_id}/resolve")
@requires_log_commit
async def admin_command_resolve(
    staged_id: str,
    req: CommandResolveRequest,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict[str, Any]:
    current = await get_current_user(credentials)
    user_data = require_auth(current)

    if user_data["role"] not in ("root", "domain_authority", "it_support"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    if req.action not in _HITL_VALID_ACTIONS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid action '{req.action}'. Must be one of: accept, reject, modify",
        )

    with _STAGED_COMMANDS_LOCK:
        entry = _STAGED_COMMANDS.get(staged_id)

    if entry is None:
        raise HTTPException(status_code=404, detail="Staged command not found")

    if entry["expires_at"] < time.time():
        with _STAGED_COMMANDS_LOCK:
            _STAGED_COMMANDS.pop(staged_id, None)
        raise HTTPException(status_code=410, detail="Staged command has expired")

    if entry["resolved"]:
        raise HTTPException(status_code=409, detail="Staged command has already been resolved")

    if user_data["role"] != "root" and entry["actor_id"] != user_data["sub"]:
        raise HTTPException(status_code=403, detail="Not authorized to resolve this staged command")

    with _STAGED_COMMANDS_LOCK:
        if _STAGED_COMMANDS.get(staged_id, {}).get("resolved"):
            raise HTTPException(status_code=409, detail="Staged command has already been resolved")
        _STAGED_COMMANDS[staged_id]["resolved"] = True

    actor_role = map_role_to_actor_role(user_data["role"])
    parsed = entry["parsed_command"]
    original_instruction = entry["original_instruction"]

    if req.action == "reject":
        record = build_commitment_record(
            actor_id=user_data["sub"],
            actor_role=actor_role,
            commitment_type="hitl_command_rejected",
            subject_id=staged_id,
            summary=f"HITL rejected: {original_instruction[:200]}",
            subject_version=None,
            subject_hash=None,
            metadata={
                "staged_id": staged_id,
                "log_stage_record_id": entry["log_stage_record_id"],
                "parsed_command": parsed,
            },
        )
        _cfg.PERSISTENCE.append_log_record(
            "admin", record,
            ledger_path=_cfg.PERSISTENCE.get_log_ledger_path("admin"),
        )
        return {
            "staged_id": staged_id,
            "action": "reject",
            "log_record_id": record["record_id"],
        }

    if req.action == "modify":
        if not req.modified_schema or not isinstance(req.modified_schema, dict):
            raise HTTPException(status_code=422, detail="modified_schema is required for 'modify' action")
        modified_op = req.modified_schema.get("operation", "")
        if modified_op not in _KNOWN_OPERATIONS:
            raise HTTPException(status_code=422, detail=f"Unknown operation in modified_schema: {modified_op}")
        # Default Deny: validate modified params against registered command schema
        mod_approved, mod_violations = validate_command(
            modified_op,
            req.modified_schema.get("params", {}),
            req.modified_schema.get("target", ""),
        )
        if not mod_approved:
            raise HTTPException(
                status_code=422,
                detail=f"Modified command schema validation failed: {'; '.join(mod_violations)}",
            )
        delta = _compute_schema_delta(parsed, req.modified_schema)
        parsed = req.modified_schema
        commitment_type: str = "hitl_command_modified"
        metadata: dict[str, Any] = {
            "staged_id": staged_id,
            "log_stage_record_id": entry["log_stage_record_id"],
            "delta": delta,
            "modified_schema": parsed,
        }
    else:
        commitment_type = "hitl_command_accepted"
        metadata = {
            "staged_id": staged_id,
            "log_stage_record_id": entry["log_stage_record_id"],
            "parsed_command": parsed,
        }

    exec_result = await _execute_admin_operation(user_data, parsed, original_instruction)

    record = build_commitment_record(
        actor_id=user_data["sub"],
        actor_role=actor_role,
        commitment_type=commitment_type,
        subject_id=staged_id,
        summary=f"HITL {req.action}: {original_instruction[:200]}",
        subject_version=None,
        subject_hash=None,
        metadata=metadata,
    )
    _cfg.PERSISTENCE.append_log_record(
        "admin", record,
        ledger_path=_cfg.PERSISTENCE.get_log_ledger_path("admin"),
    )

    return {
        "staged_id": staged_id,
        "action": req.action,
        "parsed_command": parsed,
        "result": exec_result,
        "log_record_id": record["record_id"],
    }


# ─────────────────────────────────────────────────────────────
# Session unlock via OTP PIN
# ─────────────────────────────────────────────────────────────


@router.post("/api/sessions/{session_id}/unlock")
async def unlock_session(
    session_id: str,
    req: SessionUnlockRequest,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict[str, Any]:
    """Allow a student to unlock a frozen session by submitting the OTP issued by their teacher."""
    current = await get_current_user(credentials)
    require_auth(current)   # any authenticated user may attempt; PIN is the secret

    if not validate_unlock_pin(session_id, req.pin):
        raise HTTPException(status_code=403, detail="Invalid or expired unlock PIN")

    container = _session_containers.get(session_id)
    if container is not None:
        container.frozen = False
        log.info("[%s] Session unfrozen via PIN unlock", session_id)

    return {"session_id": session_id, "unlocked": True}
