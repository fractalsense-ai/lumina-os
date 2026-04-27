"""Admin endpoints: audit log, manifest, HITL admin command staging.

Escalation REST endpoints and session-unlock have been extracted to the
education domain pack (model-packs/education/controllers/) and are
mounted dynamically at startup via api_routes in runtime-config.yaml.
"""

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
from lumina.api.config import _resolve_user_profile_path
from lumina.api.middleware import _bearer_scheme, get_current_user, require_auth, require_role
from lumina.api.models import (
    AdminCommandRequest,
    CommandResolveRequest,
    ManifestCheckResponse,
    ManifestRegenResponse,
)
from lumina.core import slm as _slm_mod
from lumina.system_log.admin_operations import (
    _canonical_sha256 as admin_canonical_sha256,
    build_commitment_record,
    build_domain_role_assignment,
    build_domain_role_revocation,
    build_trace_event,
    can_govern_domain,
    map_role_to_actor_role,
)
from lumina.core.state_machine import StateTransaction, TransactionState
from lumina.core.yaml_loader import load_yaml
from lumina.middleware.command_schema_registry import get_schema as _get_cmd_schema, validate_command
from lumina.systools.manifest_integrity import check_manifest_report, regen_manifest_report
from lumina.system_log.commit_guard import requires_log_commit
from lumina.api.admin_context import AdminOperationContext
from lumina.api.routes.ops import (
    admin_daemon,
    admin_escalations,
    admin_ingestion,
    admin_invite,
    admin_physics,
    admin_profile,
    admin_queries,
    admin_rbac,
)

log = logging.getLogger("lumina-api")

router = APIRouter()

# System operation executor modules — tried in order; first non-None result wins.
_SYSTEM_EXECUTORS = [
    admin_physics,
    admin_rbac,
    admin_ingestion,
    admin_escalations,
    admin_invite,
    admin_queries,
    admin_profile,
    admin_daemon,
]

_DAEMON_SCHEDULER: Any = None


def _get_daemon_scheduler() -> Any:
    """Lazy-init the daemon task scheduler."""
    global _DAEMON_SCHEDULER
    if _DAEMON_SCHEDULER is None:
        from lumina.daemon.scheduler import DaemonScheduler

        nc_cfg: dict[str, Any] = {}
        try:
            rt = load_yaml(Path("model-packs/system/cfg/runtime-config.yaml"))
            nc_cfg = rt.get("daemon", {})
        except Exception:
            pass
        _DAEMON_SCHEDULER = DaemonScheduler(config=nc_cfg, persistence=_cfg.PERSISTENCE)
    return _DAEMON_SCHEDULER


def _has_escalation_capability(user_data: dict[str, Any], module_id: str) -> bool:
    """Thin wrapper: delegates to ``_has_domain_capability``."""
    return _has_domain_capability(user_data, module_id, "receive_escalations")


def _has_domain_capability(user_data: dict[str, Any], module_id: str, capability: str) -> bool:
    """Check if user has a domain role with a specific scoped capability for *module_id*.

    Reads the module's domain-physics to resolve the capability flag.
    Returns False when the user has no domain role for the module or the
    capability is not set.
    """
    domain_roles_map = user_data.get("domain_roles") or {}
    role_id = domain_roles_map.get(module_id)
    if not role_id:
        return False
    if _cfg.DOMAIN_REGISTRY is None:
        return False
    try:
        for domain_info in _cfg.DOMAIN_REGISTRY.list_domains():
            modules = _cfg.DOMAIN_REGISTRY.list_modules_for_domain(domain_info["domain_id"])
            for mod in modules:
                if mod["module_id"] != module_id:
                    continue
                physics_path = mod.get("domain_physics_path")
                if not physics_path or not Path(physics_path).is_file():
                    return False
                with open(physics_path, encoding="utf-8") as fh:
                    physics = json.load(fh)
                for r in (physics.get("domain_roles") or {}).get("roles", []):
                    if r.get("role_id") == role_id:
                        return bool(
                            (r.get("scoped_capabilities") or {}).get(capability)
                        )
                return False
    except Exception:
        log.debug("Could not check domain capability %s for %s", capability, module_id, exc_info=True)
    return False


# ── Escalation REST endpoints — moved to model-packs/education/controllers/escalation_handlers.py
# Mounted dynamically at startup via api_routes in runtime-config.yaml.


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

    allowed_roles = ("root", "operator", "half_operator")
    if user_data["role"] not in allowed_roles:
        if user_data["role"] == "admin":
            # admin may only view records for domains they govern
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
    if user_data["role"] == "admin":
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
            ledger_path=_cfg.PERSISTENCE.get_system_ledger_path("admin"),
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
    require_role(user_data, "root", "admin", "operator", "half_operator")
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
    require_role(user_data, "root", "admin")
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
            ledger_path=_cfg.PERSISTENCE.get_system_ledger_path("admin"),
        )
    except Exception:
        log.debug("Could not write manifest_regen trace event")

    return ManifestRegenResponse(**report)


# ─────────────────────────────────────────────────────────────
# HITL Admin Command Staging
# ─────────────────────────────────────────────────────────────

# ── Governance config & domain handler registry ──────────────
# Extracted to lumina.api.governance — re-exported here for backward
# compatibility with existing imports.
from lumina.api.governance import (  # noqa: E402
    _load_governance_config,
    _get_known_operations,
    _get_domain_scoped_operations,
    _get_hitl_exempt_ops,
    _get_min_role_policy,
    _get_role_hierarchy,
    _get_domain_role_aliases,
    _get_domain_role_level,
    _load_domain_operation_handlers,
    _get_domain_handler_ops,
)


def _build_admin_context() -> AdminOperationContext:
    """Construct the shared context object for operation handlers."""
    from lumina.api.session import rebuild_user_domain_context

    return AdminOperationContext(
        persistence=_cfg.PERSISTENCE,
        domain_registry=_cfg.DOMAIN_REGISTRY,
        can_govern_domain=can_govern_domain,
        build_commitment_record=build_commitment_record,
        map_role_to_actor_role=map_role_to_actor_role,
        build_trace_event=build_trace_event,
        build_domain_role_assignment=build_domain_role_assignment,
        build_domain_role_revocation=build_domain_role_revocation,
        canonical_sha256=admin_canonical_sha256,
        resolve_user_profile_path=_resolve_user_profile_path,
        has_domain_capability=_has_domain_capability,
        has_escalation_capability=_has_escalation_capability,
        rebuild_domain_context=rebuild_user_domain_context,
    )


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


# ── SLM normalization — extracted to lumina.api.pipeline.slm_normalizer
from lumina.api.pipeline.slm_normalizer import (  # noqa: E402
    _normalize_slm_command,
    _load_domain_slm_normalizers,
)


def _stage_command(
    parsed_command: dict[str, Any],
    original_instruction: str,
    actor_id: str,
    actor_role: str,
) -> dict[str, Any]:
    """Create a staged HITL command entry and return it (with structured_content).

    Raises ``ValueError`` when the operation is unknown or fails schema
    validation so callers can decide how to surface the error.
    """
    from lumina.api.structured_content import build_command_proposal_card

    operation = parsed_command.get("operation", "")
    if operation not in _get_known_operations():
        raise ValueError(f"Unknown operation: {operation}")

    # Normalise SLM output before schema validation.
    parsed_command = _normalize_slm_command(parsed_command, original_instruction)

    # ── Early duplicate-username check for invite_user ────────
    # Catch the conflict at staging time so the SLM/chat layer can relay
    # the error immediately instead of deferring to resolve-time.
    if operation == "invite_user":
        _inv_username = str((parsed_command.get("params") or {}).get("username", "")).strip()
        if _inv_username:
            _existing = _cfg.PERSISTENCE.get_user_by_username(_inv_username)
            if _existing is not None:
                raise ValueError(f"Username '{_inv_username}' is already taken")

    cmd_approved, cmd_violations = validate_command(
        operation, parsed_command.get("params", {}), parsed_command.get("target", ""),
    )
    if not cmd_approved:
        raise ValueError(f"Command schema validation failed: {'; '.join(cmd_violations)}")

    staged_id = str(uuid.uuid4())
    expires_at = time.time() + _STAGED_CMD_TTL_SECONDS

    stage_record = build_commitment_record(
        actor_id=actor_id,
        actor_role=map_role_to_actor_role(actor_role),
        commitment_type="hitl_command_staged",
        subject_id=staged_id,
        summary=f"HITL staged: {original_instruction[:200]}",
        subject_version=None,
        subject_hash=None,
        metadata={
            "staged_id": staged_id,
            "parsed_command": parsed_command,
            "original_instruction": original_instruction,
        },
    )
    _cfg.PERSISTENCE.append_log_record(
        "admin", stage_record,
        ledger_path=_cfg.PERSISTENCE.get_system_ledger_path("admin"),
    )

    # Also write an EscalationRecord so the dashboard escalation queue shows
    # the pending HITL command awaiting human resolution.
    esc_record: dict[str, Any] = {
        "record_type": "EscalationRecord",
        "record_id": str(uuid.uuid4()),
        "prev_record_hash": stage_record.get("prev_record_hash", "genesis"),
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "session_id": staged_id,
        "escalating_actor_id": actor_id,
        "target_meta_authority_id": "root",
        "trigger": f"hitl_command_pending: {operation}",
        "trigger_type": "other",
        "domain_pack_id": (
            ((parsed_command.get("params") or {}).get("governed_modules") or [None])[0]
            if isinstance((parsed_command.get("params") or {}).get("governed_modules"), list)
            else (parsed_command.get("params") or {}).get("governed_modules")
        ),
        "evidence_summary": {
            "staged_id": staged_id,
            "operation": operation,
            "original_instruction": original_instruction[:200],
        },
        "status": "pending",
        "metadata": {
            "commitment_record_id": stage_record["record_id"],
        },
    }
    try:
        _cfg.PERSISTENCE.append_log_record(
            "admin", esc_record,
            ledger_path=_cfg.PERSISTENCE.get_system_ledger_path("admin"),
        )
    except Exception:
        log.warning("Failed to write EscalationRecord for staged command %s", staged_id)

    # Build atomic state transaction — PROPOSED then immediately VALIDATED
    # (schema validation already passed above).
    txn = StateTransaction(
        transaction_id=staged_id,
        operation=operation,
        actor_id=actor_id,
        metadata={"parsed_command": parsed_command, "original_instruction": original_instruction},
    )
    txn = txn.advance(TransactionState.VALIDATED, actor_id=actor_id)

    entry: dict[str, Any] = {
        "staged_id": staged_id,
        "actor_id": actor_id,
        "actor_role": actor_role,
        "parsed_command": parsed_command,
        "original_instruction": original_instruction,
        "staged_at": time.time(),
        "expires_at": expires_at,
        "log_stage_record_id": stage_record["record_id"],
        "escalation_record_id": esc_record.get("record_id"),
        "resolved": False,
        "transaction": txn,
    }
    with _STAGED_COMMANDS_LOCK:
        _STAGED_COMMANDS[staged_id] = entry

    entry["structured_content"] = build_command_proposal_card(entry)
    return entry


# ─────────────────────────────────────────────────────────────
# Trace emission helper (shared by system + domain handlers)
# ─────────────────────────────────────────────────────────────

_READ_ONLY_OPS = frozenset({
    "list_domains", "list_modules", "list_commands", "list_ingestions",
    "list_escalations", "module_status", "daemon_status",
    "explain_reasoning", "review_proposals",
    "list_domain_rbac_roles", "get_domain_module_manifest",
    "list_users", "get_domain_physics", "list_daemon_tasks",
    "view_my_profile",
})


def _emit_trace_if_mutating(
    operation: str,
    params: dict[str, Any],
    user_data: dict[str, Any],
    result: dict[str, Any],
) -> None:
    """Write a TraceEvent for non-read-only admin operations."""
    if operation in _READ_ONLY_OPS:
        return
    try:
        trace = build_trace_event(
            session_id="admin",
            actor_id=user_data["sub"],
            event_type="admin_command_executed",
            decision=f"{operation}: {json.dumps(result.get('record_id', result.get('operation', operation)), default=str)[:200]}",
            evidence_summary={
                "operation": operation,
                "actor_role": user_data["role"],
                "params": {k: str(v)[:100] for k, v in (params or {}).items()},
            },
        )
        _cfg.PERSISTENCE.append_log_record(
            "admin", trace,
            ledger_path=_cfg.PERSISTENCE.get_system_ledger_path("admin"),
        )
    except Exception:
        log.debug("Could not write admin command TraceEvent for %s", operation)


async def _execute_admin_operation(
    user_data: dict[str, Any],
    parsed: dict[str, Any],
    original_instruction: str,
) -> dict[str, Any]:
    operation = parsed["operation"]
    params = parsed.get("params") or {}
    result: dict[str, Any]

    # ── Domain-pack handler dispatch ──────────────────────────
    # Domain packs register operation_handlers in runtime-config.yaml.
    # If a domain handler claims this operation, delegate and skip the
    # system elif chain entirely.
    domain_handlers = _load_domain_operation_handlers()
    handler_entry = domain_handlers.get(operation)
    if handler_entry is not None:
        handler_domain_id = handler_entry.get("domain_id", "")
        ctx = _build_admin_context()
        if handler_domain_id:
            from lumina.persistence.scoped import ScopedPersistenceAdapter
            ctx.persistence = ScopedPersistenceAdapter(
                _cfg.PERSISTENCE, domain_id=handler_domain_id,
            )
            ctx.domain_id = handler_domain_id
        # Inject parsed.target into params so handlers can use it as fallback
        handler_params = dict(params)
        _target = parsed.get("target", "")
        if _target:
            handler_params.setdefault("_target", _target)
        result = await handler_entry["callable"](operation, handler_params, user_data, ctx)
        if result is not None:
            # Domain handler claimed the operation — emit trace and return
            _emit_trace_if_mutating(operation, params, user_data, result)
            return result

    # ── System operation modules ─────────────────────────────
    ctx = _build_admin_context()
    _sys_kw: dict[str, Any] = {
        "parsed": parsed,
        "original_instruction": original_instruction,
        "get_known_operations": _get_known_operations,
        "get_domain_scoped_operations": _get_domain_scoped_operations,
        "get_hitl_exempt_ops": _get_hitl_exempt_ops,
        "get_min_role_policy": _get_min_role_policy,
        "get_role_hierarchy": _get_role_hierarchy,
        "get_cmd_schema": _get_cmd_schema,
        "get_domain_role_level": _get_domain_role_level,
        "get_daemon_scheduler": _get_daemon_scheduler,
    }
    for _executor in _SYSTEM_EXECUTORS:
        result = await _executor.execute(operation, params, user_data, ctx, **_sys_kw)
        if result is not None:
            break
    else:
        raise HTTPException(status_code=422, detail=f"Unknown operation: {operation}")

    _emit_trace_if_mutating(operation, params, user_data, result)
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

    if user_data["role"] not in ("root", "admin", "super_admin"):
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


async def _dispatch_command(
    req: AdminCommandRequest,
    user_data: dict[str, Any],
) -> dict[str, Any]:
    """Shared command dispatch logic used by all command tier endpoints.

    Handles direct-dispatch (operation + params) and SLM-parsed commands,
    domain_id injection, HITL staging, and immediate execution for exempt ops.
    """
    _purge_expired_staged_commands()

    # ── Direct dispatch: skip SLM when operation + params supplied ──
    if req.operation:
        operation = req.operation
        if operation not in _get_known_operations():
            raise HTTPException(status_code=422, detail=f"Unknown operation: {operation}")
        parsed = {
            "operation": operation,
            "params": req.params or {},
        }
        instruction = req.instruction or f"/{operation}"
    else:
        if not _slm_mod.slm_available():
            raise HTTPException(status_code=503, detail="SLM service unavailable")

        parsed = _slm_mod.slm_parse_admin_command(req.instruction)
        if parsed is None:
            raise HTTPException(status_code=422, detail="Could not interpret command")

    # Inject domain_id from the request into params so query operations
    # (e.g. list_commands) can scope to the session's active domain.
    # The frontend sends the session's active module path (e.g.
    # "domain/edu/domain-authority/v1") which must be resolved to the
    # registry domain ID ("education") before injection.
    _parsed_params = parsed.get("params")
    if isinstance(_parsed_params, dict) and not _parsed_params.get("domain_id") and req.domain_id:
        _injected_domain = req.domain_id
        if _cfg.DOMAIN_REGISTRY is not None:
            try:
                _injected_domain = _cfg.DOMAIN_REGISTRY.resolve_domain_id(req.domain_id)
            except Exception:
                pass  # fall back to raw value
        _parsed_params["domain_id"] = _injected_domain

    # For SLM-parsed commands, extract operation/instruction from parse result.
    if not req.operation:
        operation = parsed.get("operation", "")
        if operation not in _get_known_operations():
            raise HTTPException(status_code=422, detail=f"Unknown operation: {operation}")
        instruction = req.instruction or ""

    # HITL-exempt operations execute immediately without staging.
    if operation in _get_hitl_exempt_ops():
        parsed = _normalize_slm_command(parsed, instruction)
        try:
            exec_result = await _execute_admin_operation(user_data, parsed, instruction)
        except HTTPException:
            raise
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        except RuntimeError as exc:
            msg = str(exc).lower()
            if "policy commitment" in msg:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "Domain physics have been modified but not yet committed. "
                        "Run 'commit domain physics' before this operation."
                    ),
                )
            raise HTTPException(status_code=500, detail=str(exc))
        # Read-only queries don't write a log record; satisfy the commit guard.
        from lumina.system_log.commit_guard import notify_log_commit
        notify_log_commit()
        response: dict[str, Any] = {
            "staged_id": None,
            "staged_command": parsed,
            "original_instruction": instruction,
            "result": exec_result,
            "hitl_exempt": True,
        }
        # Return list/query results as structured_content so the UI can
        # render them directly without LLM summarization.
        if operation.startswith("list_") or operation in ("review_ingestion", "review_proposals"):
            response["structured_content"] = {
                "type": "query_result",
                "operation": operation,
                "result": exec_result,
            }
        return response

    try:
        entry = _stage_command(
            parsed_command=parsed,
            original_instruction=instruction,
            actor_id=user_data["sub"],
            actor_role=user_data["role"],
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return {
        "staged_id": entry["staged_id"],
        "staged_command": parsed,
        "original_instruction": instruction,
        "expires_at": entry["expires_at"],
        "log_stage_record_id": entry["log_stage_record_id"],
        "structured_content": entry["structured_content"],
    }


# ── Tiered Command Endpoints ─────────────────────────────────
#
# Commands are split into three tiers by access level:
#   /api/command        — any authenticated user
#   /api/domain/command — domain authority + root
#   /api/admin/command  — root / super_admin only
#
# All three share _dispatch_command(); per-operation min_role checks
# still enforce fine-grained RBAC within each tier.


@router.post("/api/command")
@requires_log_commit
async def user_command(
    req: AdminCommandRequest,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict[str, Any]:
    """User-tier command endpoint — any authenticated user."""
    current = await get_current_user(credentials)
    user_data = require_auth(current)
    return await _dispatch_command(req, user_data)


@router.post("/api/domain/command")
@requires_log_commit
async def domain_command(
    req: AdminCommandRequest,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict[str, Any]:
    """Domain-tier command endpoint — domain authority and above."""
    current = await get_current_user(credentials)
    user_data = require_auth(current)
    require_role(user_data, "admin", "root", "super_admin")
    return await _dispatch_command(req, user_data)


@router.post("/api/admin/command")
@requires_log_commit
async def admin_command(
    req: AdminCommandRequest,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict[str, Any]:
    """Admin-tier command endpoint — root / IT support only."""
    current = await get_current_user(credentials)
    user_data = require_auth(current)
    require_role(user_data, "root", "super_admin")
    return await _dispatch_command(req, user_data)


@router.post("/api/admin/command/{staged_id}/resolve")
@requires_log_commit
async def admin_command_resolve(
    staged_id: str,
    req: CommandResolveRequest,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict[str, Any]:
    current = await get_current_user(credentials)
    user_data = require_auth(current)

    if user_data["role"] not in ("root", "admin", "super_admin"):
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

    actor_role = map_role_to_actor_role(user_data["role"])
    parsed = entry["parsed_command"]
    original_instruction = entry["original_instruction"]

    if req.action == "reject":
        # Advance state transaction → ROLLED_BACK
        txn = entry.get("transaction")
        if txn is not None:
            txn = txn.advance(TransactionState.ROLLED_BACK, actor_id=user_data["sub"])
            entry["transaction"] = txn

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
        with _STAGED_COMMANDS_LOCK:
            _STAGED_COMMANDS[staged_id]["resolved"] = True
        _cfg.PERSISTENCE.append_log_record(
            "admin", record,
            ledger_path=_cfg.PERSISTENCE.get_system_ledger_path("admin"),
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
        if modified_op not in _get_known_operations():
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
        parsed = _normalize_slm_command(req.modified_schema, original_instruction)
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

    # All validation passed — mark resolved before executing side-effects
    with _STAGED_COMMANDS_LOCK:
        _STAGED_COMMANDS[staged_id]["resolved"] = True

    # Advance state transaction → COMMITTED before executing side-effects
    txn = entry.get("transaction")
    if txn is not None:
        txn = txn.advance(TransactionState.COMMITTED, actor_id=user_data["sub"])
        entry["transaction"] = txn

    exec_result = await _execute_admin_operation(user_data, parsed, original_instruction)

    # Advance state transaction → FINALIZED after side-effects succeed
    txn = entry.get("transaction")
    if txn is not None:
        txn = txn.advance(TransactionState.FINALIZED, actor_id=user_data["sub"])
        entry["transaction"] = txn

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
        ledger_path=_cfg.PERSISTENCE.get_system_ledger_path("admin"),
    )

    # ── Mark the corresponding EscalationRecord as resolved ──
    _esc_rid = entry.get("escalation_record_id")
    if _esc_rid:
        try:
            _all_esc = _cfg.PERSISTENCE.query_escalations()
            _esc_target = None
            for _esc in _all_esc:
                if _esc.get("record_id") == _esc_rid:
                    _esc_target = _esc
                    break
            if _esc_target is None:
                # Fallback: match by session_id == staged_id
                for _esc in _all_esc:
                    if _esc.get("session_id") == staged_id and _esc.get("status") == "pending":
                        _esc_target = _esc
                        break
            if _esc_target is not None:
                _resolved_esc = dict(_esc_target)
                _resolved_esc["status"] = "resolved"
                _resolved_esc["resolution_commitment_id"] = record["record_id"]
                _cfg.PERSISTENCE.append_log_record(
                    "admin", _resolved_esc,
                    ledger_path=_cfg.PERSISTENCE.get_system_ledger_path("admin"),
                )
        except Exception:
            log.warning("Failed to mark EscalationRecord resolved for staged command %s", staged_id)

    response: dict[str, Any] = {
        "staged_id": staged_id,
        "action": req.action,
        "parsed_command": parsed,
        "result": exec_result,
        "log_record_id": record["record_id"],
    }
    txn = entry.get("transaction")
    if txn is not None:
        response["transaction_state"] = txn.state.value
    return response
