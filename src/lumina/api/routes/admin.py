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
from lumina.auth.auth import VALID_ROLES
from lumina.core.domain_registry import DomainNotFoundError
from lumina.core import slm as _slm_mod
from lumina.core.email_sender import send_invite_email
from lumina.core.invite_store import (
    generate_invite_token,
    _INVITE_TOKEN_TTL_SECONDS as _INVITE_TOKEN_TTL,
)
from lumina.system_log.admin_operations import (
    _canonical_sha256 as admin_canonical_sha256,
    build_commitment_record,
    build_domain_role_assignment,
    build_domain_role_revocation,
    build_trace_event,
    can_govern_domain,
    map_role_to_actor_role,
)
from lumina.core.state_machine import StateTransaction, TransactionState, IllegalTransitionError
from lumina.core.yaml_loader import load_yaml
from lumina.middleware.command_schema_registry import get_schema as _get_cmd_schema, validate_command
from lumina.systools.manifest_integrity import check_manifest_report, regen_manifest_report
from lumina.system_log.commit_guard import requires_log_commit

log = logging.getLogger("lumina-api")

router = APIRouter()

_DAEMON_SCHEDULER: Any = None


def _get_daemon_scheduler() -> Any:
    """Lazy-init the daemon task scheduler (replaces nightcycle scheduler)."""
    global _DAEMON_SCHEDULER
    if _DAEMON_SCHEDULER is None:
        from lumina.daemon.scheduler import NightCycleScheduler

        nc_cfg: dict[str, Any] = {}
        try:
            rt = load_yaml(Path("domain-packs/system/cfg/runtime-config.yaml"))
            nc_cfg = rt.get("daemon", {})
        except Exception:
            pass
        _DAEMON_SCHEDULER = NightCycleScheduler(config=nc_cfg, persistence=_cfg.PERSISTENCE)
    return _DAEMON_SCHEDULER


def _has_escalation_capability(user_data: dict[str, Any], module_id: str) -> bool:
    """Check if user has a domain role with ``receive_escalations: true`` for *module_id*."""
    domain_roles_map = user_data.get("domain_roles") or {}
    role_id = domain_roles_map.get(module_id)
    if not role_id:
        return False
    # Load the module's domain-physics to inspect scoped_capabilities
    if _cfg.DOMAIN_REGISTRY is None:
        return False
    try:
        # Resolve the domain from the module_id prefix
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
                            (r.get("scoped_capabilities") or {}).get("receive_escalations")
                        )
                return False
    except Exception:
        log.debug("Could not check escalation capability for %s", module_id, exc_info=True)
    return False


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

    # System roles that can always view escalations
    allowed_roles = ("root", "it_support", "qa", "auditor")
    is_domain_authority = user_data["role"] == "domain_authority"

    # Teachers (system role "user") with receive_escalations capability
    # can also access escalations scoped to their modules.
    has_esc_capability = False
    if user_data["role"] not in allowed_roles and not is_domain_authority:
        domain_roles_map = user_data.get("domain_roles") or {}
        for mod_id in domain_roles_map:
            if _has_escalation_capability(user_data, mod_id):
                has_esc_capability = True
                break
        if not has_esc_capability:
            raise HTTPException(status_code=403, detail="Insufficient permissions")

    records = await run_in_threadpool(
        _cfg.PERSISTENCE.query_escalations,
        status=status, domain_id=domain_id, limit=limit, offset=offset,
    )

    if is_domain_authority:
        governed = user_data.get("governed_modules") or []
        records = [r for r in records if r.get("domain_pack_id") in governed]
    elif has_esc_capability:
        # Scope to modules where the user has escalation capability
        allowed_modules = {
            mod_id for mod_id in (user_data.get("domain_roles") or {})
            if _has_escalation_capability(user_data, mod_id)
        }
        records = [r for r in records if r.get("domain_pack_id") in allowed_modules]

    return records


@router.get("/api/escalations/{escalation_id}")
async def get_escalation_detail(
    escalation_id: str,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict[str, Any]:
    """Return a single escalation record by ID."""
    current = await get_current_user(credentials)
    user_data = require_auth(current)

    allowed_roles = ("root", "it_support", "qa", "auditor", "domain_authority")
    quick_pass = user_data["role"] in allowed_roles

    # Users without a privileged system role must have at least one module
    # with receive_escalations capability; reject early if not.
    if not quick_pass:
        domain_roles_map = user_data.get("domain_roles") or {}
        if not any(_has_escalation_capability(user_data, m) for m in domain_roles_map):
            raise HTTPException(status_code=403, detail="Insufficient permissions")

    all_escalations = await run_in_threadpool(_cfg.PERSISTENCE.query_escalations)
    target = None
    for esc in all_escalations:
        if esc.get("record_id") == escalation_id:
            target = esc
            break

    if target is None:
        raise HTTPException(status_code=404, detail="Escalation not found")

    module_id = target.get("domain_pack_id", "")

    if user_data["role"] == "domain_authority":
        if not can_govern_domain(user_data, module_id, registry=_cfg.DOMAIN_REGISTRY):
            raise HTTPException(status_code=403, detail="Not authorized for this domain")
    elif not quick_pass:
        if not _has_escalation_capability(user_data, module_id):
            raise HTTPException(status_code=403, detail="Insufficient permissions")

    return target


@router.delete("/api/escalations/stale")
async def clear_stale_escalations(
    max_age_hours: int = 24,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict[str, Any]:
    """Purge escalation records older than *max_age_hours*. Root only."""
    current = await get_current_user(credentials)
    user_data = require_auth(current)
    if user_data["role"] != "root":
        raise HTTPException(status_code=403, detail="Root only")

    all_esc = await run_in_threadpool(
        _cfg.PERSISTENCE.query_escalations, limit=10000,
    )
    cutoff = datetime.now(timezone.utc).timestamp() - (max_age_hours * 3600)
    stale_ids: list[str] = []
    for esc in all_esc:
        ts_str = esc.get("timestamp_utc", "")
        try:
            ts = datetime.fromisoformat(ts_str).timestamp()
        except (ValueError, TypeError):
            ts = 0.0
        if ts < cutoff and esc.get("status", "open") == "open":
            stale_ids.append(esc["record_id"])

    # Mark each stale escalation as expired in the log
    for rid in stale_ids:
        expired = {
            "record_type": "EscalationRecord",
            "record_id": rid,
            "status": "expired",
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        }
        _cfg.PERSISTENCE.append_log_record(
            "admin", expired,
            ledger_path=_cfg.PERSISTENCE.get_log_ledger_path("admin", domain_id="_admin"),
        )

    return {"purged": len(stale_ids), "max_age_hours": max_age_hours}


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

    # Defer full RBAC check until we know the escalation's module —
    # domain-role users with receive_escalations capability are also allowed.
    _role = user_data["role"]
    _quick_pass = _role in ("root", "domain_authority")

    all_escalations = await run_in_threadpool(_cfg.PERSISTENCE.query_escalations)
    target = None
    for esc in all_escalations:
        if esc.get("record_id") == escalation_id:
            target = esc
            break

    if target is None:
        raise HTTPException(status_code=404, detail="Escalation not found")

    module_id = target.get("domain_pack_id", "")

    if _role == "domain_authority":
        if not can_govern_domain(user_data, module_id, registry=_cfg.DOMAIN_REGISTRY):
            raise HTTPException(status_code=403, detail="Not authorized for this domain")
    elif not _quick_pass:
        # Not root/DA — check for domain-role escalation capability
        if not _has_escalation_capability(user_data, module_id):
            raise HTTPException(status_code=403, detail="Insufficient permissions")

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

    # ── Mark original EscalationRecord as resolved ──
    resolved_esc = dict(target)
    resolved_esc["status"] = "resolved"
    resolved_esc["resolution_commitment_id"] = record["record_id"]
    _cfg.PERSISTENCE.append_log_record(
        session_id, resolved_esc,
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

# ── Governance Config Loader ──────────────────────────────────
#
# Canonical source: domain-packs/system/modules/system-core/domain-physics.json
# → subsystem_configs.admin_operations  (operation_ids, hitl_policy)
# → subsystem_configs.governance        (role_hierarchy, min_role_policy, domain_role_aliases)
#
# The loader reads the JSON once and caches.  If the file is missing or
# the subsystem_configs blocks are absent, hardcoded fallbacks are used.

_governance_cache: dict[str, Any] | None = None

# See: docs/7-concepts/domain-role-hierarchy.md
# See: docs/7-concepts/command-execution-pipeline.md
_FALLBACK_KNOWN_OPERATIONS: frozenset[str] = frozenset({
    "update_domain_physics", "commit_domain_physics", "update_user_role",
    "deactivate_user", "assign_domain_role", "revoke_domain_role",
    "resolve_escalation", "list_ingestions", "review_ingestion",
    "approve_interpretation", "reject_ingestion", "list_escalations",
    "explain_reasoning", "module_status", "trigger_daemon_task",
    "daemon_status", "review_proposals", "invite_user",
    "list_domains", "list_modules", "list_commands",
    "list_domain_rbac_roles", "get_domain_module_manifest",
    "list_users", "get_domain_physics", "list_daemon_tasks",
    "request_module_assignment",
})

_FALLBACK_HITL_EXEMPT: frozenset[str] = frozenset({
    "list_domains", "list_modules", "list_ingestions", "list_escalations",
    "module_status", "daemon_status", "explain_reasoning",
    "list_commands", "review_ingestion", "review_proposals",
    "list_domain_rbac_roles", "get_domain_module_manifest",
    "list_users", "get_domain_physics", "list_daemon_tasks",
    "assign_student", "remove_student", "assign_module", "remove_module",
})

_FALLBACK_ROLE_HIERARCHY: dict[str, int] = {
    "root": 100, "it_support": 80, "domain_authority": 60,
    "qa": 40, "auditor": 40, "user": 20, "guest": 10,
}

_FALLBACK_MIN_ROLE: dict[str, str] = {
    "update_domain_physics": "domain_authority",
    "commit_domain_physics": "domain_authority",
    "update_user_role": "root",
    "deactivate_user": "root",
    "assign_domain_role": "domain_authority",
    "revoke_domain_role": "domain_authority",
    "resolve_escalation": "domain_authority",
    "approve_interpretation": "domain_authority",
    "reject_ingestion": "domain_authority",
    "trigger_daemon_task": "domain_authority",
    "trigger_night_cycle": "domain_authority",
    "invite_user": "domain_authority",
    "list_users": "domain_authority",
    "get_domain_physics": "domain_authority",
    "list_daemon_tasks": "domain_authority",
    "request_module_assignment": "user",
    "assign_student": "user",
    "remove_student": "user",
    "assign_module": "user",
    "remove_module": "user",
}

_FALLBACK_DOMAIN_ROLE_ALIASES: dict[str, str] = {
    "student": "user", "teacher": "user", "teaching_assistant": "user",
    "parent": "user", "observer": "user", "field_operator": "user",
    "site_manager": "user", "ta": "user",
}


def _load_governance_config() -> dict[str, Any]:
    """Load governance policies from system domain physics with fallback."""
    global _governance_cache
    if _governance_cache is not None:
        return _governance_cache

    repo_root = Path(os.environ.get(
        "LUMINA_REPO_ROOT", Path(__file__).resolve().parents[4],
    ))
    physics_path = repo_root / "domain-packs" / "system" / "modules" / "system-core" / "domain-physics.json"

    result: dict[str, Any] = {
        "known_operations": _FALLBACK_KNOWN_OPERATIONS,
        "hitl_exempt": _FALLBACK_HITL_EXEMPT,
        "role_hierarchy": _FALLBACK_ROLE_HIERARCHY,
        "min_role_policy": _FALLBACK_MIN_ROLE,
        "domain_role_aliases": _FALLBACK_DOMAIN_ROLE_ALIASES,
    }

    if physics_path.is_file():
        try:
            import json as _json
            data = _json.loads(physics_path.read_text(encoding="utf-8"))
            sub = data.get("subsystem_configs") or {}

            # Admin operations block
            admin_ops = sub.get("admin_operations") or {}
            op_ids = admin_ops.get("operation_ids")
            if isinstance(op_ids, list) and op_ids:
                result["known_operations"] = frozenset(op_ids)

            hitl = admin_ops.get("hitl_policy") or {}
            exempt = hitl.get("system_exempt")
            if isinstance(exempt, list):
                result["hitl_exempt"] = frozenset(exempt)

            # Governance block
            gov = sub.get("governance") or {}
            rh = gov.get("role_hierarchy")
            if isinstance(rh, dict) and rh:
                result["role_hierarchy"] = rh

            mrp = gov.get("min_role_policy")
            if isinstance(mrp, dict) and mrp:
                result["min_role_policy"] = mrp

            dra = gov.get("domain_role_aliases")
            if isinstance(dra, dict) and dra:
                result["domain_role_aliases"] = dra

            log.info("Loaded governance config from %s", physics_path)
        except Exception as exc:
            log.warning("Failed to load governance config (%s); using fallback", exc)

    _governance_cache = result
    return result


def _get_known_operations() -> frozenset[str]:
    return _load_governance_config()["known_operations"]


def _get_hitl_exempt_ops() -> frozenset[str]:
    return _load_governance_config()["hitl_exempt"]


def _get_role_hierarchy() -> dict[str, int]:
    return _load_governance_config()["role_hierarchy"]


def _get_min_role_policy() -> dict[str, str]:
    return _load_governance_config()["min_role_policy"]


def _get_domain_role_aliases() -> dict[str, str]:
    """Dynamically aggregate domain role → system role mappings.

    Scans all modules across all domains, reading the ``domain_roles.roles``
    block for ``maps_to_system_role``.  Falls back to the static governance
    config ``domain_role_aliases`` if no dynamic roles are found.
    """
    aliases: dict[str, str] = {}
    try:
        for dom in _cfg.DOMAIN_REGISTRY.list_domains():
            dom_id = dom.get("domain_id", "")
            if not dom_id:
                continue
            modules = _cfg.DOMAIN_REGISTRY.list_modules_for_domain(dom_id)
            for mod in modules:
                dp_path = mod.get("domain_physics_path", "")
                if not dp_path:
                    continue
                try:
                    dp_full = Path(_cfg.DOMAIN_REGISTRY._repo_root) / dp_path
                    dp_data = json.loads(dp_full.read_text(encoding="utf-8"))
                    for role in dp_data.get("domain_roles", {}).get("roles", []):
                        if isinstance(role, dict) and role.get("role_id"):
                            aliases[role["role_id"]] = role.get(
                                "maps_to_system_role", "user"
                            )
                except Exception:
                    continue
    except Exception:
        pass
    # Fall back to static governance config if nothing found dynamically
    if not aliases:
        try:
            aliases = _load_governance_config().get("domain_role_aliases", {})
        except Exception:
            pass
    return aliases


# Legacy aliases for backwards compatibility (used in tests and elsewhere).
_KNOWN_OPERATIONS = _FALLBACK_KNOWN_OPERATIONS
_HITL_EXEMPT_OPS = _FALLBACK_HITL_EXEMPT

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


# Domain-specific roles the SLM may output that map to the "user" system role.
# The intended domain role is preserved in params["intended_domain_role"] so
# downstream logic (e.g. assign_domain_role chaining) can use it.
# Loaded from domain-physics.json subsystem_configs.governance.domain_role_aliases.
_DOMAIN_ROLE_ALIASES: dict[str, str] = _FALLBACK_DOMAIN_ROLE_ALIASES


def _normalize_slm_command(parsed_command: dict[str, Any], original_instruction: str = "") -> dict[str, Any]:
    """Normalise SLM-produced command dicts so they match admin-command-schemas.

    The SLM is probabilistic --- it may return ``"Domain Authority"`` instead of
    ``"domain_authority"``, put the user name in ``target`` instead of
    ``params.user_id``, or include extra keys like ``governed_modules`` at the
    top level rather than inside ``params``.  This function applies best-effort
    mapping **before** schema validation so the pipeline doesn't silently fail.
    """
    import re

    cmd = {k: v for k, v in parsed_command.items()}  # shallow copy
    _raw_params = cmd.get("params")
    if isinstance(_raw_params, list):
        # SLM sometimes returns params as a list of strings; coerce to dict
        params: dict[str, Any] = {str(p): True for p in _raw_params}
    else:
        params = dict(_raw_params or {})
    target = cmd.get("target", "")
    operation = cmd.get("operation", "")

    if operation in ("update_user_role", "invite_user"):
        # ── user_id / username fallback: SLM often puts the name in 'target' ──
        if operation == "update_user_role":
            if not params.get("user_id") and target:
                params["user_id"] = target
        elif operation == "invite_user":
            if not params.get("username") and target:
                params["username"] = target

        # ── new_role / role normalisation: "Domain Authority" → "domain_authority" ──
        role_key = "new_role" if operation == "update_user_role" else "role"
        raw_role = params.get(role_key, "")
        if raw_role and not re.fullmatch(r"[a-z_]+", raw_role):
            params[role_key] = re.sub(r"[\s-]+", "_", raw_role.strip()).lower()

        # ── Domain-role alias table: map domain-specific roles to system role ──
        # SLM often outputs domain roles like "student", "teacher", "field_operator"
        # which are NOT system roles.  Map them to the system role "user" and
        # preserve the intended domain role for downstream chaining.
        normalised_role = params.get(role_key, "")
        if normalised_role and normalised_role not in VALID_ROLES:
            # Strip common domain prefixes the SLM invents
            # e.g. "education_user" → "user", "education_domain_user" → "user"
            _stripped = re.sub(
                r"^(education|agriculture|system)_?(domain_?)?", "", normalised_role,
            )
            if _stripped and _stripped in VALID_ROLES:
                params["intended_domain_role"] = normalised_role
                params[role_key] = _stripped
            elif normalised_role in _get_domain_role_aliases():
                params["intended_domain_role"] = normalised_role
                params[role_key] = _get_domain_role_aliases()[normalised_role]
            else:
                # Fuzzy substring match against known system roles
                matched = [vr for vr in VALID_ROLES if vr in normalised_role]
                if matched:
                    params["intended_domain_role"] = normalised_role
                    params[role_key] = max(matched, key=len)

        # ── invite_user: infer missing role from intended_domain_role ──
        if operation == "invite_user":
            # ── Reject system roles leaked into intended_domain_role ──
            # The SLM sometimes puts system roles ("user", "domain_authority")
            # into intended_domain_role.  That field is exclusively for
            # domain-specific roles like "student", "teacher", etc.
            _idr_raw = params.get("intended_domain_role", "")
            if _idr_raw and _idr_raw in VALID_ROLES:
                params["intended_domain_role"] = None

            if not params.get(role_key):
                _idr = params.get("intended_domain_role", "")
                if _idr and _idr in _get_domain_role_aliases():
                    params[role_key] = _get_domain_role_aliases()[_idr]
                elif _idr:
                    params[role_key] = "user"
                else:
                    params[role_key] = "user"

            # ── Infer intended_domain_role when SLM pre-mapped to system role ──
            # If the SLM already mapped e.g. "student" → role="user" and set
            # intended_domain_role to null, try to recover from the original
            # instruction text stored in target or from known domain role aliases.
            if not params.get("intended_domain_role"):
                _search_text = f"{target or ''} {original_instruction}".lower()
                _aliases = _get_domain_role_aliases()
                for _alias in _aliases:
                    if _alias in _search_text:
                        params["intended_domain_role"] = _alias
                        break

            # ── Infer domain_id from target or instruction context ──
            # If the SLM didn't set domain_id, check whether any registered
            # domain ID appears in the target field.
            if not params.get("domain_id") and _cfg.DOMAIN_REGISTRY is not None:
                _search_text = f"{target or ''} {original_instruction}".lower()
                try:
                    for _dom in _cfg.DOMAIN_REGISTRY.list_domains():
                        _did = _dom.get("domain_id", "")
                        if _did and _did.lower() in _search_text:
                            params["domain_id"] = _did
                            break
                except Exception:
                    pass

            # ── Strip governed_modules for non-DA roles unconditionally ──
            # The SLM frequently hallucinates governed_modules for student/user
            # invites.  Only domain_authority should ever have governed_modules.
            if params.get(role_key) != "domain_authority":
                params.pop("governed_modules", None)

        # ── governed_modules: may appear at top level or inside params ──
        if "governed_modules" not in params and cmd.get("governed_modules"):
            params["governed_modules"] = cmd.pop("governed_modules")

        # Normalise governed_modules to a list when a single string is provided
        gm = params.get("governed_modules")
        if isinstance(gm, str):
            params["governed_modules"] = [gm]

        # ── Expand "all": SLM may output governed_modules: "all" or ["all"] ──
        gm_list = params.get("governed_modules")
        if isinstance(gm_list, list) and any(
            isinstance(m, str) and m.lower() == "all" for m in gm_list
        ):
            # Determine domain from context — use target field or the first
            # module_prefix hint in existing governed_modules
            _domain_hint = cmd.get("target", "") or params.get("domain_id", "")
            try:
                if _domain_hint and _cfg.DOMAIN_REGISTRY is not None:
                    # Resolve prefixes (e.g. "edu" → "education") before lookup
                    _domain_hint = _cfg.DOMAIN_REGISTRY._prefix_to_domain.get(_domain_hint, _domain_hint)
                    _resolved_domain = _cfg.DOMAIN_REGISTRY.resolve_domain_id(_domain_hint)
                    _mod_list = _cfg.DOMAIN_REGISTRY.list_modules_for_domain(_resolved_domain)
                    if _mod_list:
                        params["governed_modules"] = [m["module_id"] for m in _mod_list]
            except Exception:
                # If we can't resolve, leave as-is — graceful degradation
                # will catch it downstream
                pass

        # ── Expand wildcard patterns: "domain/edu/*" → actual module IDs ──
        gm_list = params.get("governed_modules")
        if isinstance(gm_list, list) and _cfg.DOMAIN_REGISTRY is not None:
            expanded: list[str] = []
            changed = False
            for mod_id in gm_list:
                if isinstance(mod_id, str) and ("*" in mod_id or mod_id.endswith("/")):
                    _parts = mod_id.replace("*", "").rstrip("/").split("/")
                    _hint = _parts[-1] if _parts else ""
                    if not _hint:
                        _hint = _parts[-2] if len(_parts) > 1 else ""
                    try:
                        # Resolve prefixes (e.g. "edu" → "education") before lookup
                        _hint = _cfg.DOMAIN_REGISTRY._prefix_to_domain.get(_hint, _hint)
                        _resolved = _cfg.DOMAIN_REGISTRY.resolve_domain_id(_hint)
                        _mods = _cfg.DOMAIN_REGISTRY.list_modules_for_domain(_resolved)
                        if _mods:
                            expanded.extend(m["module_id"] for m in _mods)
                            changed = True
                            continue
                    except Exception:
                        pass
                expanded.append(mod_id)
            if changed:
                params["governed_modules"] = expanded

    elif operation in ("assign_domain_role", "revoke_domain_role"):
        # Similar user_id fallback for role assignment operations
        if not params.get("user_id") and target:
            params["user_id"] = target

    elif operation in ("list_users", "list_escalations", "list_modules"):
        # ── Infer domain_id from target or instruction context ──
        # Follow the same pattern as invite_user: when the SLM didn't
        # set domain_id, check whether any registered domain ID appears
        # in the target field or the original instruction.
        if not params.get("domain_id") and _cfg.DOMAIN_REGISTRY is not None:
            _search_text = f"{target or ''} {original_instruction}".lower()
            try:
                for _dom in _cfg.DOMAIN_REGISTRY.list_domains():
                    _did = _dom.get("domain_id", "")
                    if _did and _did.lower() in _search_text:
                        params["domain_id"] = _did
                        break
            except Exception:
                pass

    cmd["params"] = params
    return cmd


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
        ledger_path=_cfg.PERSISTENCE.get_log_ledger_path("admin"),
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
            ledger_path=_cfg.PERSISTENCE.get_log_ledger_path("admin"),
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
        if user_data["role"] == "domain_authority" and not can_govern_domain(user_data, domain_id, registry=_cfg.DOMAIN_REGISTRY):
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
        if user_data["role"] == "domain_authority" and not can_govern_domain(user_data, domain_id, registry=_cfg.DOMAIN_REGISTRY):
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
        if user_data["role"] == "domain_authority" and not can_govern_domain(user_data, module_id, registry=_cfg.DOMAIN_REGISTRY):
            raise HTTPException(status_code=403, detail="Not authorized for this domain")
        # Validate role_id against the module's actual domain_roles block
        try:
            _mod_domain = _cfg.DOMAIN_REGISTRY.resolve_domain_id(module_id)
            _mod_runtime = _cfg.DOMAIN_REGISTRY.get_runtime_context(_mod_domain)
            _module_map = _mod_runtime.get("module_map") or {}
            if module_id in _module_map:
                _dp_path = Path(_cfg.DOMAIN_REGISTRY._repo_root) / _module_map[module_id]["domain_physics_path"]
            else:
                _dp_path = Path(_cfg.DOMAIN_REGISTRY._repo_root) / _mod_runtime["domain_physics_path"]
            _dp_data = json.loads(_dp_path.read_text(encoding="utf-8"))
            _valid_roles = [
                r.get("role_id") for r in (_dp_data.get("domain_roles", {}).get("roles") or [])
                if isinstance(r, dict) and r.get("role_id")
            ]
            if _valid_roles and domain_role not in _valid_roles:
                raise HTTPException(
                    status_code=422,
                    detail=f"Unknown domain role {domain_role!r} for module {module_id!r}. "
                    f"Valid roles: {_valid_roles}. Use list_domain_rbac_roles to discover.",
                )
        except (DomainNotFoundError, FileNotFoundError, KeyError):
            pass  # Module not in registry or no physics file — allow assignment
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
        if user_data["role"] == "domain_authority" and not can_govern_domain(user_data, module_id, registry=_cfg.DOMAIN_REGISTRY):
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
        # DA boundary check: must govern the requested domain
        if domain_id and user_data["role"] == "domain_authority":
            try:
                _resolved_esc = _cfg.DOMAIN_REGISTRY.resolve_domain_id(domain_id)
            except DomainNotFoundError as exc:
                raise HTTPException(status_code=400, detail=str(exc))
            if not can_govern_domain(user_data, _resolved_esc, registry=_cfg.DOMAIN_REGISTRY):
                raise HTTPException(status_code=403, detail="Not authorized for this domain")
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

    elif operation in ("trigger_daemon_task", "trigger_night_cycle", "daemon_status", "night_cycle_status", "review_proposals"):
        scheduler = _get_daemon_scheduler()
        if operation in ("trigger_daemon_task", "trigger_night_cycle"):
            if user_data["role"] not in ("root", "domain_authority"):
                raise HTTPException(status_code=403, detail="Insufficient permissions")
            run_id = scheduler.trigger_async(actor_id=user_data["sub"])
            result = {"operation": "trigger_daemon_task", "run_id": run_id, "status": "started"}
        elif operation in ("daemon_status", "night_cycle_status"):
            result = scheduler.get_status()
            result["operation"] = "daemon_status"
        else:
            resolved_id = str(params.get("domain_id", parsed.get("target", "")))
            proposals = scheduler.get_pending_proposals(domain_id=resolved_id)
            result = {"operation": operation, "proposals": proposals, "count": len(proposals)}

    elif operation == "invite_user":
        # See: docs/7-concepts/domain-role-hierarchy.md
        # See: docs/7-concepts/domain-adapter-pattern.md
        if user_data["role"] not in ("root", "it_support", "domain_authority"):
            raise HTTPException(status_code=403, detail="Only root, it_support, or domain_authority can invite users")
        username = str(params.get("username", parsed.get("target", "")))
        role = str(params.get("role", "user"))
        governed_modules_raw = params.get("governed_modules")
        # None / absent means "all modules" for DA; [] means explicitly empty; present list → validate
        if governed_modules_raw is None:
            governed_modules = None  # explicit null or absent = all modules for DA
        else:
            governed_modules: list[str] = list(governed_modules_raw) if governed_modules_raw else []
        email = str(params.get("email", "")) or None

        # Validate governed_modules against real module IDs (only when
        # the registry is populated — skip in minimal/test environments).
        if governed_modules and _cfg.DOMAIN_REGISTRY is not None:
            _known_modules: set[str] = set()
            for _dom in (_cfg.DOMAIN_REGISTRY.list_domains() or []):
                for _m in (_cfg.DOMAIN_REGISTRY.list_modules_for_domain(_dom.get("domain_id", "")) or []):
                    _known_modules.add(_m["module_id"])
            if _known_modules:  # only enforce when registry is populated
                _invalid = [m for m in governed_modules if m not in _known_modules]
                if _invalid:
                    raise HTTPException(
                        status_code=422,
                        detail=f"Unknown governed_modules: {_invalid}. Use list_modules to see valid IDs.",
                    )

        if not username:
            raise HTTPException(status_code=422, detail="username required")
        if role not in VALID_ROLES:
            raise HTTPException(status_code=400, detail=f"Invalid role: {role}")
        # domain_authority with governed_modules=None means access to ALL
        # modules in their domain. This is intentional — DAs are the
        # subject-matter experts / domain administrators.
        # An explicit empty list [] is rejected — use None for "all".
        if role == "domain_authority" and governed_modules is not None and len(governed_modules) == 0:
            raise HTTPException(
                status_code=400,
                detail="governed_modules is required when role is domain_authority (use null for all modules)",
            )

        # DA-scoped invite: domain_authority can only invite "user" role within their governed modules
        if user_data["role"] == "domain_authority":
            if role not in ("user", "guest"):
                raise HTTPException(
                    status_code=403,
                    detail="Domain authority can only invite users with 'user' or 'guest' role",
                )
            da_governed = set(user_data.get("governed_modules") or [])
            if governed_modules and not set(governed_modules).issubset(da_governed):
                raise HTTPException(
                    status_code=403,
                    detail="Cannot invite user to modules outside your governed scope",
                )

        existing = await run_in_threadpool(_cfg.PERSISTENCE.get_user_by_username, username)
        if existing is not None:
            raise HTTPException(status_code=409, detail="Username already taken")

        # ── Auto-assign default module for non-DA users without modules ──
        # When a user is invited without governed_modules and there is a
        # domain context (from intended_domain_role or the current session),
        # assign the domain's default staging module so the user has at least
        # one module to land in.
        if role != "domain_authority" and not governed_modules and _cfg.DOMAIN_REGISTRY is not None:
            _idr = params.get("intended_domain_role", "")
            _domain_hint = params.get("domain_id", "")
            # Try to resolve domain from intended_domain_role context
            if not _domain_hint and _idr:
                # intended_domain_role might be "student", "teacher" etc.
                # — not a domain ID.  But domain context may come from
                # the SLM's target or domain_id param.
                pass
            if _domain_hint:
                try:
                    _resolved_dom = _cfg.DOMAIN_REGISTRY.resolve_domain_id(_domain_hint)
                    _default_mod = _cfg.DOMAIN_REGISTRY.get_default_module_id(
                        _resolved_dom, domain_role=_idr,
                    )
                    if _default_mod:
                        governed_modules = [_default_mod]
                except Exception:
                    pass

        import uuid as _uuid_mod
        new_user_id = str(_uuid_mod.uuid4())
        await run_in_threadpool(
            _cfg.PERSISTENCE.create_user,
            new_user_id, username, "", role, governed_modules or None, False,
        )

        # ── Pre-assign domain role so it's ready when the user activates ──
        _intended_dr = params.get("intended_domain_role", "")
        if _intended_dr and governed_modules:
            _dr_map = {mod: _intended_dr for mod in governed_modules}
            try:
                await run_in_threadpool(
                    _cfg.PERSISTENCE.update_user_domain_roles, new_user_id, _dr_map,
                )
            except Exception:
                log.debug("Could not pre-assign domain role for %s", new_user_id)

        invite_token = generate_invite_token(new_user_id, username)
        _cfg.PERSISTENCE.set_user_invite_token(new_user_id, invite_token, time.time() + _INVITE_TOKEN_TTL)
        base_url = os.environ.get("LUMINA_BASE_URL", "").rstrip("/")
        setup_url = f"{base_url}/?token={invite_token}"

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

    elif operation == "list_domains":
        domains = _cfg.DOMAIN_REGISTRY.list_domains()
        result = {"operation": operation, "domains": domains, "count": len(domains)}

    elif operation == "list_commands":
        include_details = bool(params.get("include_details", True))
        _min_role = _get_min_role_policy()
        _role_rank = _get_role_hierarchy()
        _hitl_exempt = _get_hitl_exempt_ops()
        actor_rank = _role_rank.get(user_data["role"], 0)
        commands: list[dict[str, Any]] = []
        for op_name in sorted(_get_known_operations()):
            min_role = _min_role.get(op_name, "user")
            if actor_rank < _role_rank.get(min_role, 0):
                continue
            entry: dict[str, Any] = {"name": op_name}
            if include_details:
                schema = _get_cmd_schema(op_name)
                entry["description"] = (schema or {}).get("description", "")
                entry["hitl_exempt"] = op_name in _hitl_exempt
                entry["min_role"] = min_role
            commands.append(entry)
        result = {"operation": operation, "commands": commands, "count": len(commands)}

    elif operation == "list_modules":
        domain_id = str(params.get("domain_id", parsed.get("target", "")))
        if not domain_id:
            raise HTTPException(status_code=422, detail="domain_id required")
        try:
            resolved = _cfg.DOMAIN_REGISTRY.resolve_domain_id(domain_id)
        except DomainNotFoundError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        # DA scoping: domain_authority sees only governed domain modules
        if user_data["role"] == "domain_authority" and not can_govern_domain(user_data, resolved, registry=_cfg.DOMAIN_REGISTRY):
            raise HTTPException(status_code=403, detail="Not authorized for this domain")
        modules = _cfg.DOMAIN_REGISTRY.list_modules_for_domain(resolved)
        result = {"operation": operation, "domain_id": resolved, "modules": modules, "count": len(modules)}

    elif operation == "list_domain_rbac_roles":
        domain_id = str(params.get("domain_id", parsed.get("target", "")))
        if not domain_id:
            raise HTTPException(status_code=422, detail="domain_id required")
        try:
            resolved = _cfg.DOMAIN_REGISTRY.resolve_domain_id(domain_id)
        except DomainNotFoundError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        # Collect domain_roles from the actual domain_roles.roles block
        modules = _cfg.DOMAIN_REGISTRY.list_modules_for_domain(resolved)
        domain_roles: dict[str, Any] = {}
        for mod in modules:
            dp_path = mod.get("domain_physics_path", "")
            if not dp_path:
                continue
            try:
                dp_full = Path(_cfg.DOMAIN_REGISTRY._repo_root) / dp_path
                dp_data = json.loads(dp_full.read_text(encoding="utf-8"))
                dr_block = dp_data.get("domain_roles", {})
                roles_list = dr_block.get("roles", [])
                if roles_list:
                    domain_roles[mod["module_id"]] = {
                        "roles": [
                            {
                                "role_id": r.get("role_id"),
                                "role_name": r.get("role_name"),
                                "hierarchy_level": r.get("hierarchy_level"),
                                "maps_to_system_role": r.get("maps_to_system_role"),
                                "default_access": r.get("default_access"),
                                "scoped_capabilities": r.get("scoped_capabilities", {}),
                            }
                            for r in roles_list
                            if isinstance(r, dict)
                        ],
                    }
            except Exception:
                log.debug("Could not read domain physics for %s", mod.get("module_id"))
        result = {"operation": operation, "domain_id": resolved, "domain_roles": domain_roles}

    elif operation == "get_domain_module_manifest":
        domain_id = str(params.get("domain_id", parsed.get("target", "")))
        if not domain_id:
            raise HTTPException(status_code=422, detail="domain_id required")
        try:
            resolved = _cfg.DOMAIN_REGISTRY.resolve_domain_id(domain_id)
        except DomainNotFoundError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        modules = _cfg.DOMAIN_REGISTRY.list_modules_for_domain(resolved)
        manifest_entries: list[dict[str, Any]] = []
        for mod in modules:
            dp_path = mod.get("domain_physics_path", "")
            entry: dict[str, Any] = {"module_id": mod["module_id"]}
            if dp_path:
                try:
                    dp_full = Path(_cfg.DOMAIN_REGISTRY._repo_root) / dp_path
                    dp_data = json.loads(dp_full.read_text(encoding="utf-8"))
                    entry["label"] = dp_data.get("label", "")
                    entry["version"] = dp_data.get("version", "")
                    entry["description"] = dp_data.get("description", "")
                    entry["domain"] = dp_data.get("domain", resolved)
                except Exception:
                    pass
            manifest_entries.append(entry)
        result = {"operation": operation, "domain_id": resolved, "modules": manifest_entries, "count": len(manifest_entries)}

    elif operation == "list_users":
        role_filter = params.get("role")
        domain_id_filter = params.get("domain_id", "")
        module_id_filter = params.get("module_id", "")
        domain_role_filter = params.get("domain_role", "")

        # Resolve domain_id to canonical name and get its module IDs
        domain_module_ids: set[str] | None = None
        if domain_id_filter:
            try:
                resolved_domain = _cfg.DOMAIN_REGISTRY.resolve_domain_id(domain_id_filter)
            except DomainNotFoundError as exc:
                raise HTTPException(status_code=400, detail=str(exc))
            # DA boundary check: must govern the requested domain
            if user_data["role"] == "domain_authority" and not can_govern_domain(
                user_data, resolved_domain, registry=_cfg.DOMAIN_REGISTRY
            ):
                raise HTTPException(status_code=403, detail="Not authorized for this domain")
            domain_modules = _cfg.DOMAIN_REGISTRY.list_modules_for_domain(resolved_domain)
            domain_module_ids = {m["module_id"] for m in domain_modules}
        elif user_data["role"] == "domain_authority":
            # No domain_id given — scope to DA's own governed modules
            pass  # handled below in DA scoping block

        # Specific module filter — also enforce DA boundary
        if module_id_filter and user_data["role"] == "domain_authority":
            if not can_govern_domain(user_data, module_id_filter, registry=_cfg.DOMAIN_REGISTRY):
                raise HTTPException(status_code=403, detail="Not authorized for this module")

        users = _cfg.PERSISTENCE.list_users()
        if role_filter:
            users = [u for u in users if u.get("role") == role_filter]

        # Domain-scoped filtering: DAs only see users in their governed modules.
        # See: docs/7-concepts/domain-role-hierarchy.md
        # See: docs/7-concepts/zero-trust-architecture.md
        if user_data["role"] == "domain_authority":
            da_modules = set(user_data.get("governed_modules") or [])
            if da_modules:
                scoped: list[dict[str, Any]] = []
                for u in users:
                    u_modules = set(u.get("governed_modules") or [])
                    u_domain_roles = u.get("domain_roles") or {}
                    # Include if user shares any governed module OR has a
                    # domain role in any of the DA's modules.
                    if u_modules & da_modules or set(u_domain_roles) & da_modules:
                        scoped.append(u)
                users = scoped

        # Apply domain_id filter (narrow to users in domain's modules)
        if domain_module_ids is not None:
            filtered: list[dict[str, Any]] = []
            for u in users:
                u_modules = set(u.get("governed_modules") or [])
                u_domain_roles = u.get("domain_roles") or {}
                if u_modules & domain_module_ids or set(u_domain_roles) & domain_module_ids:
                    filtered.append(u)
            users = filtered

        # Apply module_id filter (narrow to users in a specific module)
        if module_id_filter:
            users = [
                u for u in users
                if module_id_filter in (u.get("governed_modules") or [])
                or module_id_filter in (u.get("domain_roles") or {})
            ]

        # Apply domain_role filter (narrow to users with a specific domain role)
        if domain_role_filter:
            users = [
                u for u in users
                if domain_role_filter in (u.get("domain_roles") or {}).values()
            ]

        # Strip sensitive fields
        safe_users = []
        for u in users:
            safe_users.append({
                k: v for k, v in u.items()
                if k not in ("password_hash", "invite_token", "invite_expires_at", "invite_token_expires_at")
            })
        result = {"operation": operation, "users": safe_users, "count": len(safe_users)}

    elif operation == "get_domain_physics":
        domain_id = str(params.get("domain_id", parsed.get("target", "")))
        if not domain_id:
            raise HTTPException(status_code=422, detail="domain_id required")
        try:
            resolved = _cfg.DOMAIN_REGISTRY.resolve_domain_id(domain_id)
        except DomainNotFoundError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        module_id_filter = params.get("module_id")
        modules = _cfg.DOMAIN_REGISTRY.list_modules_for_domain(resolved)
        physics_entries: list[dict[str, Any]] = []
        for mod in modules:
            if module_id_filter and mod["module_id"] != module_id_filter:
                continue
            dp_path = mod.get("domain_physics_path", "")
            if not dp_path:
                continue
            try:
                dp_full = Path(_cfg.DOMAIN_REGISTRY._repo_root) / dp_path
                dp_data = json.loads(dp_full.read_text(encoding="utf-8"))
                # Remove internal file paths, keep governance-relevant fields
                entry: dict[str, Any] = {
                    "module_id": mod["module_id"],
                    "label": dp_data.get("label", ""),
                    "version": dp_data.get("version", ""),
                    "domain": dp_data.get("domain", resolved),
                }
                subsys = dp_data.get("subsystem_configs", {})
                if subsys.get("governance"):
                    entry["governance"] = subsys["governance"]
                if subsys.get("admin_operations"):
                    entry["admin_operations"] = subsys["admin_operations"]
                if dp_data.get("topics"):
                    entry["topics"] = dp_data["topics"]
                if dp_data.get("standing_orders"):
                    entry["standing_order_count"] = len(dp_data["standing_orders"])
                physics_entries.append(entry)
            except Exception:
                log.debug("Could not read domain physics for %s", mod.get("module_id"))
        result = {"operation": operation, "domain_id": resolved, "physics": physics_entries, "count": len(physics_entries)}

    elif operation == "list_daemon_tasks":
        from lumina.daemon import resource_monitor as _daemon_mod
        status = _daemon_mod.get_status()
        # Get task list from the daemon singleton or fall back to runtime config
        task_list: list[str] = []
        if _daemon_mod._daemon is not None and _daemon_mod._daemon._task_priority:
            task_list = list(_daemon_mod._daemon._task_priority)
        else:
            try:
                rt = load_yaml(Path("domain-packs/system/cfg/runtime-config.yaml"))
                task_list = rt.get("daemon", {}).get("task_priority", [])
            except Exception:
                pass
        result = {
            "operation": operation,
            "tasks": task_list,
            "count": len(task_list),
            "daemon_state": status.get("state", "UNKNOWN"),
            "daemon_enabled": status.get("enabled", False),
        }

    elif operation == "request_module_assignment":
        # Creates an escalation record for a domain authority / teacher to approve.
        domain_id = str(params.get("domain_id", ""))
        module_id = str(params.get("module_id", ""))
        reason = str(params.get("reason", "")) or "User requested module assignment"

        if not domain_id:
            raise HTTPException(status_code=422, detail="domain_id is required")
        if not module_id:
            raise HTTPException(status_code=422, detail="module_id is required")

        # Resolve and validate domain + module
        try:
            resolved_domain = _cfg.DOMAIN_REGISTRY.resolve_domain_id(domain_id)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        _mods = _cfg.DOMAIN_REGISTRY.list_modules_for_domain(resolved_domain)
        _valid_mod_ids = {m["module_id"] for m in _mods}
        if module_id not in _valid_mod_ids:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown module_id: {module_id}. Valid modules: {sorted(_valid_mod_ids)}",
            )

        # Build an escalation record for the DA / teacher to resolve
        import uuid as _uuid_mod
        escalation_id = str(_uuid_mod.uuid4())
        escalation_record = {
            "record_type": "EscalationRecord",
            "escalation_id": escalation_id,
            "session_id": user_data.get("session_id", "admin"),
            "actor_id": user_data["sub"],
            "domain_id": resolved_domain,
            "module_id": module_id,
            "escalation_type": "module_assignment_request",
            "summary": f"User {user_data.get('username', user_data['sub'])} requests assignment to {module_id}",
            "reason": reason,
            "status": "open",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        try:
            _cfg.PERSISTENCE.append_log_record(
                "admin", escalation_record,
                ledger_path=_cfg.PERSISTENCE.get_log_ledger_path("admin", domain_id="_admin"),
            )
        except Exception:
            log.debug("Could not write module_assignment_request escalation")

        result = {
            "operation": operation,
            "escalation_id": escalation_id,
            "domain_id": resolved_domain,
            "module_id": module_id,
            "status": "pending_approval",
            "message": f"Module assignment request submitted. A domain authority for '{resolved_domain}' will review this request.",
        }

    # ── Student ↔ teacher assignment ──────────────────────────
    elif operation == "assign_student":
        student_id = str(params.get("student_id", "")).strip()
        teacher_id = str(params.get("teacher_id", "")).strip()
        if not student_id:
            raise HTTPException(status_code=422, detail="student_id required")

        caller_role = user_data["role"]
        # Teachers can only assign to themselves
        if caller_role == "user":
            _has_cap = False
            for _mid, _rid in (user_data.get("domain_roles") or {}).items():
                if _rid in ("teacher",) and _has_domain_capability(user_data, _mid, "receive_escalations"):
                    _has_cap = True
                    break
            if not _has_cap:
                raise HTTPException(status_code=403, detail="Requires teacher domain role with receive_escalations capability")
            teacher_id = user_data["sub"]  # force self
        elif caller_role in ("root", "domain_authority"):
            if not teacher_id:
                raise HTTPException(status_code=422, detail="teacher_id required for domain authorities")
        else:
            raise HTTPException(status_code=403, detail="Insufficient permissions")

        # Validate both users exist
        student = await run_in_threadpool(_cfg.PERSISTENCE.get_user, student_id)
        if student is None:
            raise HTTPException(status_code=404, detail=f"Student not found: {student_id}")
        teacher = await run_in_threadpool(_cfg.PERSISTENCE.get_user, teacher_id)
        if teacher is None:
            raise HTTPException(status_code=404, detail=f"Teacher not found: {teacher_id}")

        # DA scope check — must govern a module the teacher is assigned to
        if caller_role == "domain_authority":
            _teacher_modules = list((teacher.get("domain_roles") or {}).keys())
            if not any(can_govern_domain(user_data, m, registry=_cfg.DOMAIN_REGISTRY) for m in _teacher_modules):
                raise HTTPException(status_code=403, detail="Not authorised — teacher is outside your governed modules")

        # Update student profile: set assigned_teacher_id
        _profile_dir = Path("data/profiles")
        _student_profile_path = str(_profile_dir / f"{student_id}.yaml")
        try:
            _sprofile = await run_in_threadpool(_cfg.PERSISTENCE.load_subject_profile, _student_profile_path)
        except Exception:
            _sprofile = {}
        _sprofile["assigned_teacher_id"] = teacher_id
        await run_in_threadpool(_cfg.PERSISTENCE.save_subject_profile, _student_profile_path, _sprofile)

        # Update teacher profile: add to assigned_students
        _teacher_profile_path = str(_profile_dir / f"{teacher_id}.yaml")
        try:
            _tprofile = await run_in_threadpool(_cfg.PERSISTENCE.load_subject_profile, _teacher_profile_path)
        except Exception:
            _tprofile = {}
        _edu_state = _tprofile.setdefault("educator_state", {})
        _assigned = list(_edu_state.get("assigned_students") or [])
        if student_id not in _assigned:
            _assigned.append(student_id)
        _edu_state["assigned_students"] = _assigned
        await run_in_threadpool(_cfg.PERSISTENCE.save_subject_profile, _teacher_profile_path, _tprofile)

        # Audit trail
        record = build_commitment_record(
            actor_id=user_data["sub"],
            actor_role=map_role_to_actor_role(caller_role),
            commitment_type="student_assignment",
            subject_id=student_id,
            summary=f"Assigned student {student_id} to teacher {teacher_id}",
            metadata={"teacher_id": teacher_id, "assigned_by": user_data["sub"]},
            references=[student_id, teacher_id],
        )
        _cfg.PERSISTENCE.append_log_record(
            "admin", record,
            ledger_path=_cfg.PERSISTENCE.get_log_ledger_path("admin", domain_id="_admin"),
        )
        result = {
            "operation": operation,
            "student_id": student_id,
            "teacher_id": teacher_id,
            "status": "assigned",
            "record_id": record["record_id"],
        }

    elif operation == "remove_student":
        student_id = str(params.get("student_id", "")).strip()
        teacher_id = str(params.get("teacher_id", "")).strip()
        if not student_id:
            raise HTTPException(status_code=422, detail="student_id required")

        caller_role = user_data["role"]
        if caller_role == "user":
            _has_cap = False
            for _mid, _rid in (user_data.get("domain_roles") or {}).items():
                if _rid in ("teacher",) and _has_domain_capability(user_data, _mid, "receive_escalations"):
                    _has_cap = True
                    break
            if not _has_cap:
                raise HTTPException(status_code=403, detail="Requires teacher domain role with receive_escalations capability")
            teacher_id = user_data["sub"]
        elif caller_role in ("root", "domain_authority"):
            if not teacher_id:
                raise HTTPException(status_code=422, detail="teacher_id required for domain authorities")
        else:
            raise HTTPException(status_code=403, detail="Insufficient permissions")

        student = await run_in_threadpool(_cfg.PERSISTENCE.get_user, student_id)
        if student is None:
            raise HTTPException(status_code=404, detail=f"Student not found: {student_id}")

        # Update student profile: clear assigned_teacher_id
        _profile_dir = Path("data/profiles")
        _student_profile_path = str(_profile_dir / f"{student_id}.yaml")
        try:
            _sprofile = await run_in_threadpool(_cfg.PERSISTENCE.load_subject_profile, _student_profile_path)
        except Exception:
            _sprofile = {}
        _sprofile.pop("assigned_teacher_id", None)
        await run_in_threadpool(_cfg.PERSISTENCE.save_subject_profile, _student_profile_path, _sprofile)

        # Update teacher profile: remove from assigned_students
        _teacher_profile_path = str(_profile_dir / f"{teacher_id}.yaml")
        try:
            _tprofile = await run_in_threadpool(_cfg.PERSISTENCE.load_subject_profile, _teacher_profile_path)
        except Exception:
            _tprofile = {}
        _edu_state = _tprofile.get("educator_state") or {}
        _assigned = list(_edu_state.get("assigned_students") or [])
        if student_id in _assigned:
            _assigned.remove(student_id)
            _edu_state["assigned_students"] = _assigned
            _tprofile["educator_state"] = _edu_state
            await run_in_threadpool(_cfg.PERSISTENCE.save_subject_profile, _teacher_profile_path, _tprofile)

        record = build_commitment_record(
            actor_id=user_data["sub"],
            actor_role=map_role_to_actor_role(caller_role),
            commitment_type="student_removal",
            subject_id=student_id,
            summary=f"Removed student {student_id} from teacher {teacher_id}",
            metadata={"teacher_id": teacher_id, "removed_by": user_data["sub"]},
            references=[student_id, teacher_id],
        )
        _cfg.PERSISTENCE.append_log_record(
            "admin", record,
            ledger_path=_cfg.PERSISTENCE.get_log_ledger_path("admin", domain_id="_admin"),
        )
        result = {
            "operation": operation,
            "student_id": student_id,
            "teacher_id": teacher_id,
            "status": "removed",
            "record_id": record["record_id"],
        }

    # ── Module assignment / removal ───────────────────────────
    elif operation == "assign_module":
        target_user_id = str(params.get("user_id", parsed.get("target", ""))).strip()
        module_id = str(params.get("module_id", "")).strip()
        if not target_user_id or not module_id:
            raise HTTPException(status_code=422, detail="user_id and module_id required")

        caller_role = user_data["role"]
        if caller_role in ("root", "domain_authority"):
            if caller_role == "domain_authority" and not can_govern_domain(user_data, module_id, registry=_cfg.DOMAIN_REGISTRY):
                raise HTTPException(status_code=403, detail="Not authorised for this domain/module")
        elif caller_role == "user":
            # Teacher with assign_modules_to_students capability
            _can_assign = False
            for _mid, _rid in (user_data.get("domain_roles") or {}).items():
                if _has_domain_capability(user_data, _mid, "assign_modules_to_students"):
                    _can_assign = True
                    break
            if not _can_assign:
                raise HTTPException(status_code=403, detail="Requires assign_modules_to_students capability")
        else:
            raise HTTPException(status_code=403, detail="Insufficient permissions")

        target = await run_in_threadpool(_cfg.PERSISTENCE.get_user, target_user_id)
        if target is None:
            raise HTTPException(status_code=404, detail=f"User not found: {target_user_id}")

        updated = await run_in_threadpool(
            _cfg.PERSISTENCE.update_user_governed_modules, target_user_id, add=[module_id],
        )
        record = build_commitment_record(
            actor_id=user_data["sub"],
            actor_role=map_role_to_actor_role(caller_role),
            commitment_type="module_assignment",
            subject_id=target_user_id,
            summary=f"Assigned module {module_id} to user {target_user_id}",
            metadata={"module_id": module_id, "assigned_by": user_data["sub"]},
            references=[target_user_id, module_id],
        )
        _cfg.PERSISTENCE.append_log_record(
            "admin", record,
            ledger_path=_cfg.PERSISTENCE.get_log_ledger_path("admin", domain_id="_admin"),
        )
        result = {
            "operation": operation,
            "user_id": target_user_id,
            "module_id": module_id,
            "status": "assigned",
            "record_id": record["record_id"],
        }

    elif operation == "remove_module":
        target_user_id = str(params.get("user_id", parsed.get("target", ""))).strip()
        module_id = str(params.get("module_id", "")).strip()
        if not target_user_id or not module_id:
            raise HTTPException(status_code=422, detail="user_id and module_id required")

        caller_role = user_data["role"]
        if caller_role in ("root", "domain_authority"):
            if caller_role == "domain_authority" and not can_govern_domain(user_data, module_id, registry=_cfg.DOMAIN_REGISTRY):
                raise HTTPException(status_code=403, detail="Not authorised for this domain/module")
        elif caller_role == "user":
            _can_assign = False
            for _mid, _rid in (user_data.get("domain_roles") or {}).items():
                if _has_domain_capability(user_data, _mid, "assign_modules_to_students"):
                    _can_assign = True
                    break
            if not _can_assign:
                raise HTTPException(status_code=403, detail="Requires assign_modules_to_students capability")
        else:
            raise HTTPException(status_code=403, detail="Insufficient permissions")

        target = await run_in_threadpool(_cfg.PERSISTENCE.get_user, target_user_id)
        if target is None:
            raise HTTPException(status_code=404, detail=f"User not found: {target_user_id}")

        updated = await run_in_threadpool(
            _cfg.PERSISTENCE.update_user_governed_modules, target_user_id, remove=[module_id],
        )
        record = build_commitment_record(
            actor_id=user_data["sub"],
            actor_role=map_role_to_actor_role(caller_role),
            commitment_type="module_removal",
            subject_id=target_user_id,
            summary=f"Removed module {module_id} from user {target_user_id}",
            metadata={"module_id": module_id, "removed_by": user_data["sub"]},
            references=[target_user_id, module_id],
        )
        _cfg.PERSISTENCE.append_log_record(
            "admin", record,
            ledger_path=_cfg.PERSISTENCE.get_log_ledger_path("admin", domain_id="_admin"),
        )
        result = {
            "operation": operation,
            "user_id": target_user_id,
            "module_id": module_id,
            "status": "removed",
            "record_id": record["record_id"],
        }

    else:
        raise HTTPException(status_code=422, detail=f"Unknown operation: {operation}")

    # ── Emit TraceEvent for mutating operations (causal trace ledger) ──
    _READ_ONLY_OPS = frozenset({
        "list_domains", "list_modules", "list_commands", "list_ingestions",
        "list_escalations", "module_status", "daemon_status",
        "explain_reasoning", "review_proposals",
        "list_domain_rbac_roles", "get_domain_module_manifest",
        "list_users", "get_domain_physics", "list_daemon_tasks",
    })
    if operation not in _READ_ONLY_OPS:
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
                ledger_path=_cfg.PERSISTENCE.get_log_ledger_path("admin", domain_id="_admin"),
            )
        except Exception:
            log.debug("Could not write admin command TraceEvent for %s", operation)

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
    if operation not in _get_known_operations():
        raise HTTPException(status_code=422, detail=f"Unknown operation: {operation}")

    # HITL-exempt operations execute immediately without staging.
    if operation in _get_hitl_exempt_ops():
        parsed = _normalize_slm_command(parsed, req.instruction)
        try:
            exec_result = await _execute_admin_operation(user_data, parsed, req.instruction)
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
            "original_instruction": req.instruction,
            "result": exec_result,
            "hitl_exempt": True,
        }
        # Return list/query results as structured_content so the UI can
        # render them directly without LLM summarization.
        if operation.startswith("list_") or operation in ("review_ingestion", "review_proposals"):
            response["structured_content"] = {
                "type": "query_result",
                "operation": operation,
                "data": exec_result,
            }
        return response

    try:
        entry = _stage_command(
            parsed_command=parsed,
            original_instruction=req.instruction,
            actor_id=user_data["sub"],
            actor_role=user_data["role"],
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return {
        "staged_id": entry["staged_id"],
        "staged_command": parsed,
        "original_instruction": req.instruction,
        "expires_at": entry["expires_at"],
        "log_stage_record_id": entry["log_stage_record_id"],
        "structured_content": entry["structured_content"],
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
        ledger_path=_cfg.PERSISTENCE.get_log_ledger_path("admin"),
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
                    ledger_path=_cfg.PERSISTENCE.get_log_ledger_path("admin"),
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
